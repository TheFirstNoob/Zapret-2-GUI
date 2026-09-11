<#
game_probe.ps1 - background network analyzer for a game process.

Usage:
  game_probe.bat                          (default process: WardogsClient)
  powershell -ExecutionPolicy Bypass -File game_probe.ps1 -Process dayz

Parameters:
  -Process      part of the game process name (default WardogsClient)
  -IntervalSec  log refresh period in seconds (default 2)
  -DurationSec  observation time, 0 = until Ctrl+C (default 0)
  -CheckTcp     additionally test TCP reachability of found IPs
  -NoCapture    disable UDP capture (pktmon; otherwise used when admin)

What it does: while you play, the script polls the game process network
connections and writes a LIVE log game_probe.log next to the script -
the file refreshes every couple of seconds, nothing to copy from console.
On finish (Ctrl+C or game exit) the log is marked FINISHED.

UDP servers are visible only via packet capture (Windows does not store
UDP remote addresses) - the built-in pktmon is used for that.
game_probe.bat requests administrator rights automatically.

What to look for in the log:
  - TCP state "SynSent" - SYN got no answer (possible IP/subnet block);
  - IPv6 connections - if the game uses IPv6, the bypass (IPv4) misses it;
  - UDP servers (from capture) - if the game is blocked by them;
  - Domains (DNS cache) - which domains map to the found IPs.

Send game_probe.log to the developer - it shows where the game connects
and what exactly is blocked.
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
    param($status, $elapsed, $procName, $pids, $ipv6, $tcp, $udp, $udpCapture, $tcpCheck, $captureNote, $dnsMap, $sysTcp)
    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add("=== game_probe: $Process ===")
    $now = Get-Date -Format 'HH:mm:ss'
    $lines.Add("Status: $status (updated $now, elapsed ${elapsed}s)")
    $lines.Add("Process: $procName (PID $pids)")
    if ($ipv6) {
        $lines.Add("IPv6 connections: YES (bypass is IPv4-only - may be the cause!)")
    } else {
        $lines.Add("IPv6 connections: no")
    }
    if ($captureNote) { $lines.Add("UDP capture: $captureNote") }
    $lines.Add("")

    $lines.Add("--- TCP endpoints (unique, by frequency) ---")
    if ($tcp.Count -eq 0) { $lines.Add("(none)") }
    foreach ($k in ($tcp.Keys | Sort-Object { $tcp[$_].n } -Descending)) {
        $v = $tcp[$k]
        $mark = ""
        if ($v.state -eq 'SynSent') { $mark = "  <-- SYN not answered (possible IP block)" }
        $lines.Add(("{0,-42} {1,-12} seen {2,3}{3}" -f $k, $v.state, $v.n, $mark))
    }
    $lines.Add("")
    $lines.Add("--- UDP endpoints (connected, from system) ---")
    if ($udp.Count -eq 0) { $lines.Add("(none - see capture below)") }
    foreach ($k in ($udp.Keys | Sort-Object { $udp[$_] } -Descending)) {
        $lines.Add(("{0,-42} seen {1,3}" -f $k, $udp[$k]))
    }
    if ($udpCapture -and $udpCapture.Count -gt 0) {
        $lines.Add("")
        $lines.Add("--- UDP servers (from pktmon capture, by frequency) ---")
        foreach ($k in ($udpCapture.Keys | Sort-Object { $udpCapture[$_] } -Descending)) {
            $lines.Add(("{0,-42} packets {1,4}" -f $k, $udpCapture[$k]))
        }
    }
    if ($tcpCheck -and $tcpCheck.Count -gt 0) {
        $lines.Add("")
        $lines.Add("--- TCP reachability check (Test-NetConnection) ---")
        foreach ($k in $tcpCheck.Keys) {
            $res = $tcpCheck[$k]
            if ($res) {
                $lines.Add(("{0,-42} reachable" -f $k))
            } else {
                $lines.Add(("{0,-42} NOT RESPONDING" -f $k))
            }
        }
    }
    if ($dnsMap -and $dnsMap.Count -gt 0) {
        $lines.Add("")
        $lines.Add("--- Domains (DNS cache) for found IPs ---")
        foreach ($ip in $dnsMap.Keys) {
            $lines.Add(("{0,-20} -> {1}" -f $ip, ($dnsMap[$ip] -join ", ")))
        }
    }
    $lines.Add("")
    $lines.Add("--- Summary ---")
    $lines.Add("TCP: $($tcp.Count), UDP (system): $($udp.Count), UDP (capture): $(if ($udpCapture) { $udpCapture.Count } else { 0 })")
    if ($null -ne $sysTcp) { $lines.Add("System TCP connections (all processes): $sysTcp") }
    if ($tcp.Count -eq 0 -and $udp.Count -eq 0 -and (-not $udpCapture -or $udpCapture.Count -eq 0)) {
        $lines.Add("")
        $lines.Add("NOTE: no game connections were seen. Make sure the game is actually")
        $lines.Add("trying to connect (reproduce the problem) while the probe is running.")
    }
    return ,$lines
}

function Parse-UdpCapture([string]$file, $knownPorts) {
    $remote = @{}
    if (-not (Test-Path $file)) { return $remote }
    foreach ($line in (Get-Content -Path $file -ErrorAction SilentlyContinue)) {
        if ($line -match '(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\.(\d+) > (\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\.(\d+)') {
            $a = $matches[1]; $ap = [int]$matches[2]; $b = $matches[3]; $bp = [int]$matches[4]
            # only packets related to the game ports (empty list = accept all)
            $portMatch = ($knownPorts.Count -eq 0) -or ($knownPorts -contains $ap) -or ($knownPorts -contains $bp)
            if ($portMatch) {
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
    # IP -> domains (from DNS cache): maps found game addresses to domain names
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
    Write-Host "Process '*$Process*' not found - waiting up to 2 minutes." -ForegroundColor Yellow
    Write-Host "Start the game now (in lobby)..." -ForegroundColor Yellow
    $waitStart = Get-Date
    while (-not $procs -and ((Get-Date) - $waitStart).TotalSeconds -lt 120) {
        Start-Sleep -Seconds 3
        $procs = Get-GameProcs $Process
    }
    if (-not $procs) {
        Write-Host "Process '*$Process*' did not appear. Check the name:" -ForegroundColor Red
        Write-Host "  game_probe.bat other_process_name" -ForegroundColor Yellow
        exit 1
    }
}

$procName = ($procs | ForEach-Object { $_.ProcessName }) -join ", "
$pidList = ($procs | ForEach-Object { $_.Id }) -join ", "

# --- UDP capture (pktmon) ---
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
        $captureNote = "running (pktmon, UDP, ports: $($knownPorts.Count))"
    } else {
        $captureNote = "failed to start (pktmon)"
    }
} elseif (-not $isAdmin -and -not $NoCapture) {
    $captureNote = "not available without admin rights (TCP only)"
}

Write-Host ""
Write-Host "=== game_probe ===" -ForegroundColor Cyan
Write-Host "Observing: $procName (PID $pidList)"
Write-Host "Live log: $logFile"
if ($captureNote) { Write-Host "UDP capture: $captureNote" }
if ($DurationSec -gt 0) {
    Write-Host "Play! The log updates itself. Stop in $DurationSec sec."
} else {
    Write-Host "Play! The log updates itself. Stop: Ctrl+C"
}
Write-Host ""

$tcp = @{}
$udp = @{}
$ipv6 = $false
$sysTcp = $null
$start = Get-Date
$lastPortRefresh = Get-Date

try {
    while ($true) {
        if ($DurationSec -gt 0 -and ((Get-Date) - $start).TotalSeconds -ge $DurationSec) { break }
        $current = Get-GameProcs $Process
        if (-not $current) { break }
        $cpids = @($current | Select-Object -ExpandProperty Id)

        $allTcp = @(Get-NetTCPConnection -ErrorAction SilentlyContinue)
        $sysTcp = $allTcp.Count
        foreach ($e in $allTcp) {
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
        # periodically refresh capture ports (new ones may appear)
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
        $live = Format-Report "RUNNING" $elapsed $procName $pidList $ipv6 $tcp $udp $null $null $captureNote $null $sysTcp
        Write-Log $live
        Start-Sleep -Seconds $IntervalSec
    }
} finally {
    $elapsed = [int]((Get-Date) - $start).TotalSeconds

    # stop capture and parse
    $udpCapture = $null
    if ($captureActive) {
        pktmon stop 2>&1 | Out-Null
        pktmon etl2txt $etlFile -o $txtFile 2>&1 | Out-Null
        $udpCapture = Parse-UdpCapture $txtFile $knownPorts
        Remove-Item $etlFile -ErrorAction SilentlyContinue
        Remove-Item $txtFile -ErrorAction SilentlyContinue
        pktmon filter remove 2>&1 | Out-Null
        $captureNote = "finished, servers found: $(if ($udpCapture) { $udpCapture.Count } else { 0 })"
    }

    # optional final TCP reachability check (once, for found IPs)
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

    # DNS cache: map found IPs to game domain names
    $remoteIps = New-Object System.Collections.Generic.HashSet[string]
    foreach ($k in $tcp.Keys) { [void]$remoteIps.Add($k.Substring(0, $k.LastIndexOf(':'))) }
    foreach ($k in $udp.Keys) { [void]$remoteIps.Add($k.Substring(0, $k.LastIndexOf(':'))) }
    if ($udpCapture) { foreach ($k in $udpCapture.Keys) { [void]$remoteIps.Add($k.Substring(0, $k.LastIndexOf(':'))) } }
    $dnsMap = Get-DnsMap $remoteIps

    $final = Format-Report "FINISHED" $elapsed $procName $pidList $ipv6 $tcp $udp $udpCapture $tcpCheck $captureNote $dnsMap $sysTcp
    Write-Log $final

    Write-Host ""
    Write-Host "Done. Log saved: $logFile" -ForegroundColor Green
    Write-Host "Send this file for analysis." -ForegroundColor Green
}
