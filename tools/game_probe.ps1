<#
game_probe.ps1 — фоновый анализ сетевых соединений процесса игры.

Использование:
  game_probe.bat                          (процесс по умолчанию: WardogsClient)
  powershell -ExecutionPolicy Bypass -File game_probe.ps1 -Process dayz

Параметры:
  -Process      часть имени процесса игры (по умолчанию WardogsClient)
  -IntervalSec  период обновления лога в секундах (по умолчанию 2)
  -DurationSec  длительность наблюдения, 0 = до Ctrl+C (по умолчанию 0)
  -CheckTcp     дополнительно проверить TCP-доступность найденных IP
  -NoCapture    отключить UDP-захват (pktmon; иначе — при правах админа)

Что делает: пока вы играете, скрипт в фоне опрашивает сетевые соединения
процесса игры и пишет ЖИВОЙ лог game_probe.log рядом со скриптом —
файл обновляется каждые пару секунд, копировать из консоли ничего не надо.
По окончании (Ctrl+C или выход из игры) лог помечается ЗАВЕРШЕНО.

UDP-серверы видны только через захват трафика (Windows не хранит remote
для UDP) — для этого используется встроенный pktmon. Запуск game_probe.bat
сам запросит права администратора.

На что смотреть в логе:
  - TCP state "SynSent" — SYN не получает ответа (вероятен блок IP/подсети);
  - IPv6-соединения — если игра ходит по IPv6, обход (IPv4) её не видит;
  - UDP-серверы (из захвата) — если игра блокируется по ним.

Лог game_probe.log можно отправить разработчику — по нему видно, куда
ходит игра и что именно блокируется.
#>
param(
    [string]$Process = "WardogsClient",
    [int]$IntervalSec = 2,
    [int]$DurationSec = 0,
    [switch]$CheckTcp,
    [switch]$NoCapture
)

$ErrorActionPreference = 'SilentlyContinue'

$outDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $outDir) { $outDir = "." }
$logFile = Join-Path $outDir "game_probe.log"
$etlFile = Join-Path $outDir "game_probe.etl"
$txtFile = Join-Path $outDir "game_probe_pkt.txt"

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

function Get-GameProcs([string]$mask) {
    Get-Process | Where-Object { $_.ProcessName -like "*$mask*" }
}

function Get-LocalUdpPorts($cpids) {
    $ports = New-Object System.Collections.Generic.List[int]
    foreach ($e in (Get-NetUDPEndpoint -ErrorAction SilentlyContinue)) {
        if ($cpids -contains $e.OwningProcess) {
            if ($ports -notcontains $e.LocalPort) { $ports.Add([int]$e.LocalPort) }
        }
    }
    return ,$ports
}

function Write-Log([string[]]$lines) {
    $lines | Set-Content -Path $logFile -Encoding UTF8
}

function Format-Report {
    param($status, $elapsed, $procName, $pids, $ipv6, $tcp, $udp, $udpCapture, $tcpCheck, $captureNote, $dnsMap)
    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add("=== game_probe: $Process ===")
    $now = Get-Date -Format 'HH:mm:ss'
    $lines.Add("Статус: $status (обновлено $now, прошло $elapsed сек)")
    $lines.Add("Процесс: $procName (PID $pids)")
    if ($ipv6) {
        $lines.Add("IPv6-соединения: ДА (обход работает только по IPv4 — это может быть причиной!)")
    } else {
        $lines.Add("IPv6-соединения: нет")
    }
    if ($captureNote) { $lines.Add("UDP-захват: $captureNote") }
    $lines.Add("")

    $lines.Add("--- TCP endpoints (уникальные, по частоте) ---")
    if ($tcp.Count -eq 0) { $lines.Add("(нет)") }
    foreach ($k in ($tcp.Keys | Sort-Object { $tcp[$_].n } -Descending)) {
        $v = $tcp[$k]
        $mark = ""
        if ($v.state -eq 'SynSent') { $mark = "  <-- SYN не отвечает (возможен блок IP)" }
        $lines.Add(("{0,-42} {1,-12} видели {2,3}{3}" -f $k, $v.state, $v.n, $mark))
    }
    $lines.Add("")
    $lines.Add("--- UDP endpoints (connected, из системы) ---")
    if ($udp.Count -eq 0) { $lines.Add("(нет — смотрите захват ниже)") }
    foreach ($k in ($udp.Keys | Sort-Object { $udp[$_] } -Descending)) {
        $lines.Add(("{0,-42} видели {1,3}" -f $k, $udp[$k]))
    }
    if ($udpCapture -and $udpCapture.Count -gt 0) {
        $lines.Add("")
        $lines.Add("--- UDP-серверы (из захвата pktmon, по частоте) ---")
        foreach ($k in ($udpCapture.Keys | Sort-Object { $udpCapture[$_] } -Descending)) {
            $lines.Add(("{0,-42} пакетов {1,4}" -f $k, $udpCapture[$k]))
        }
    }
    if ($tcpCheck -and $tcpCheck.Count -gt 0) {
        $lines.Add("")
        $lines.Add("--- Проверка TCP-доступности (Test-NetConnection) ---")
        foreach ($k in $tcpCheck.Keys) {
            $res = $tcpCheck[$k]
            if ($res) {
                $lines.Add(("{0,-42} доступен" -f $k))
            } else {
                $lines.Add(("{0,-42} НЕ ОТВЕЧАЕТ" -f $k))
            }
        }
    }
    if ($dnsMap -and $dnsMap.Count -gt 0) {
        $lines.Add("")
        $lines.Add("--- Домены (DNS-кэш) для найденных IP ---")
        foreach ($ip in $dnsMap.Keys) {
            $lines.Add(("{0,-20} -> {1}" -f $ip, ($dnsMap[$ip] -join ", ")))
        }
    }
    $lines.Add("")
    $lines.Add("--- Итог ---")
    $lines.Add("Всего TCP: $($tcp.Count), UDP (system): $($udp.Count), UDP (capture): $(if ($udpCapture) { $udpCapture.Count } else { 0 })")
    return ,$lines
}

function Parse-UdpCapture([string]$file, $knownPorts) {
    $remote = @{}
    if (-not (Test-Path $file)) { return $remote }
    foreach ($line in (Get-Content -Path $file -ErrorAction SilentlyContinue)) {
        if ($line -match '(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\.(\d+) > (\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\.(\d+)') {
            $a = $matches[1]; $ap = [int]$matches[2]; $b = $matches[3]; $bp = [int]$matches[4]
            # интересуют только пакеты, связанные с портами игры
            if (($knownPorts -contains $ap) -or ($knownPorts -contains $bp)) {
                foreach ($p in @(@($a, $ap), @($b, $bp))) {
                    $ip = $p[0]; $port = [int]$p[1]
                    if ($ip -notmatch '^(192\.168\.|10\.|172\.(1[6-9]|2[0-9]|3[01])\.|127\.|0\.|169\.254\.|224\.|239\.|255\.)') {
                        $k = "$ip`:$port"
                        if (-not $remote.ContainsKey($k)) { $remote[$k] = 0 }
                        $remote[$k] = $remote[$k] + 1
                    }
                }
            }
        }
    }
    return $remote
}

function Get-DnsMap($remoteIps) {
    # IP -> домены (из DNS-кэша): связывает найденные адреса игры с доменными именами
    $map = @{}
    $dns = Get-DnsClientCache -ErrorAction SilentlyContinue
    foreach ($d in $dns) {
        $data = [string]$d.Data
        if ($data -match '^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$' -and $remoteIps.Contains($data)) {
            if (-not $map.ContainsKey($data)) { $map[$data] = @() }
            if ($map[$data] -notcontains $d.Entry) { $map[$data] += $d.Entry }
        }
    }
    return $map
}

$procs = Get-GameProcs $Process
if (-not $procs) {
    Write-Host "Процесс '*$Process*' не найден — жду появления (до 2 минут)." -ForegroundColor Yellow
    Write-Host "Запустите игру сейчас (в лобби)..." -ForegroundColor Yellow
    $waitStart = Get-Date
    while (-not $procs -and ((Get-Date) - $waitStart).TotalSeconds -lt 120) {
        Start-Sleep -Seconds 3
        $procs = Get-GameProcs $Process
    }
    if (-not $procs) {
        Write-Host "Процесс '*$Process*' так и не появился. Проверьте имя:" -ForegroundColor Red
        Write-Host "  game_probe.bat другое_имя_процесса" -ForegroundColor Yellow
        exit 1
    }
}

$procName = ($procs | ForEach-Object { $_.ProcessName }) -join ", "
$pidList = ($procs | ForEach-Object { $_.Id }) -join ", "

# --- UDP-захват (pktmon) ---
$captureNote = ""
$captureActive = $false
$knownPorts = New-Object System.Collections.Generic.List[int]
if (-not $NoCapture -and $isAdmin) {
    $knownPorts = Get-LocalUdpPorts @($procs | Select-Object -ExpandProperty Id)
    pktmon filter remove 2>&1 | Out-Null
    if ($knownPorts.Count -gt 0) {
        $portArgs = ($knownPorts | ForEach-Object { "$_" }) -join " "
        pktmon filter add game -t UDP -p $portArgs 2>&1 | Out-Null
    } else {
        pktmon filter add game -t UDP 2>&1 | Out-Null
    }
    pktmon start --capture --pkt-size 0 --file-name $etlFile 2>&1 | Out-Null
    if (Test-Path $etlFile) {
        $captureActive = $true
        $captureNote = "идёт (pktmon, UDP, портов: $($knownPorts.Count))"
    } else {
        $captureNote = "не запустился (pktmon)"
    }
} elseif (-not $isAdmin -and -not $NoCapture) {
    $captureNote = "недоступен без прав администратора (только TCP)"
}

Write-Host ""
Write-Host "=== game_probe ===" -ForegroundColor Cyan
Write-Host "Наблюдаю: $procName (PID $pidList)"
Write-Host "Живой лог: $logFile"
if ($captureNote) { Write-Host "UDP-захват: $captureNote" }
if ($DurationSec -gt 0) {
    Write-Host "Играйте! Лог обновляется сам. Остановка через $DurationSec сек."
} else {
    Write-Host "Играйте! Лог обновляется сам. Остановка: Ctrl+C"
}
Write-Host ""

$tcp = @{}
$udp = @{}
$ipv6 = $false
$start = Get-Date
$lastPortRefresh = Get-Date

try {
    while ($true) {
        if ($DurationSec -gt 0 -and ((Get-Date) - $start).TotalSeconds -ge $DurationSec) { break }
        $current = Get-GameProcs $Process
        if (-not $current) { break }
        $cpids = @($current | Select-Object -ExpandProperty Id)

        foreach ($e in (Get-NetTCPConnection -ErrorAction SilentlyContinue)) {
            if ($cpids -contains $e.OwningProcess) {
                $ra = [string]$e.RemoteAddress
                if ($ra -and $ra -ne '0.0.0.0' -and $ra -ne '::' -and $ra -ne '::1' -and $ra -ne '127.0.0.1') {
                    if ($ra.Contains(':')) { $ipv6 = $true }
                    $k = "$ra`:$($e.RemotePort)"
                    if (-not $tcp.ContainsKey($k)) { $tcp[$k] = @{ n = 0; state = [string]$e.State } }
                    $tcp[$k].n = $tcp[$k].n + 1
                    $tcp[$k].state = [string]$e.State
                }
            }
        }
        foreach ($e in (Get-NetUDPEndpoint -ErrorAction SilentlyContinue)) {
            if ($cpids -contains $e.OwningProcess) {
                $ra = [string]$e.RemoteAddress
                if ($ra -and $ra -ne '0.0.0.0' -and $ra -ne '::' -and $ra -ne '::1' -and $ra -ne '127.0.0.1') {
                    if ($ra.Contains(':')) { $ipv6 = $true }
                    $k = "$ra`:$($e.RemotePort)"
                    if (-not $udp.ContainsKey($k)) { $udp[$k] = 0 }
                    $udp[$k] = $udp[$k] + 1
                }
            }
        }
        # периодически обновляем порты для захвата (появились новые)
        if ($captureActive -and ((Get-Date) - $lastPortRefresh).TotalSeconds -ge 20) {
            $lastPortRefresh = Get-Date
            $newPorts = Get-LocalUdpPorts $cpids
            foreach ($p in $newPorts) {
                if ($knownPorts -notcontains $p) {
                    $knownPorts.Add($p)
                    pktmon filter add "game$p" -t UDP -p $p 2>&1 | Out-Null
                }
            }
        }
        $elapsed = [int]((Get-Date) - $start).TotalSeconds
        $live = Format-Report "НАБЛЮДЕНИЕ" $elapsed $procName $pidList $ipv6 $tcp $udp $null $null $captureNote $null
        Write-Log $live
        Start-Sleep -Seconds $IntervalSec
    }
} finally {
    $elapsed = [int]((Get-Date) - $start).TotalSeconds

    # остановка захвата и разбор
    $udpCapture = $null
    if ($captureActive) {
        pktmon stop 2>&1 | Out-Null
        pktmon etl2txt $etlFile -o $txtFile 2>&1 | Out-Null
        $udpCapture = Parse-UdpCapture $txtFile $knownPorts
        Remove-Item $etlFile -ErrorAction SilentlyContinue
        Remove-Item $txtFile -ErrorAction SilentlyContinue
        pktmon filter remove 2>&1 | Out-Null
        $captureNote = "завершён, найдено серверов: $(if ($udpCapture) { $udpCapture.Count } else { 0 })"
    }

    # финальная TCP-проверка по запросу (один раз, для найденных IP)
    $tcpCheck = $null
    if ($CheckTcp -and $tcp.Count -gt 0) {
        $tcpCheck = @{}
        foreach ($k in $tcp.Keys) {
            $ip = $k.Substring(0, $k.LastIndexOf(':'))
            if ($ip.Contains(':')) { continue }
            $port = [int]$k.Substring($k.LastIndexOf(':') + 1)
            $ok = Test-NetConnection -ComputerName $ip -Port $port -InformationLevel Quiet -WarningAction SilentlyContinue
            $tcpCheck[$k] = [bool]$ok
        }
    }

    # DNS-кэш: связываем найденные IP с доменными именами игры
    $remoteIps = New-Object System.Collections.Generic.HashSet[string]
    foreach ($k in $tcp.Keys) { [void]$remoteIps.Add($k.Substring(0, $k.LastIndexOf(':'))) }
    foreach ($k in $udp.Keys) { [void]$remoteIps.Add($k.Substring(0, $k.LastIndexOf(':'))) }
    if ($udpCapture) { foreach ($k in $udpCapture.Keys) { [void]$remoteIps.Add($k.Substring(0, $k.LastIndexOf(':'))) } }
    $dnsMap = Get-DnsMap $remoteIps

    $final = Format-Report "ЗАВЕРШЕНО" $elapsed $procName $pidList $ipv6 $tcp $udp $udpCapture $tcpCheck $captureNote $dnsMap
    Write-Log $final

    Write-Host ""
    Write-Host "Готово. Лог сохранён: $logFile" -ForegroundColor Green
    Write-Host "Отправьте этот файл — по нему видно, куда ходит игра и что блокируется." -ForegroundColor Green
}
