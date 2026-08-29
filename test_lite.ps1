# Zapret 2 lite — tester (PowerShell 5.1, same host set as the GUI tester)
$ErrorActionPreference = "Continue"

# ── Admin self-elevation (one UAC prompt, no loops) ──────────────────────
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    try {
        Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"") -Verb RunAs -Wait
    } catch {
        Write-Host "`nНет прав администратора и не удалось запросить UAC." -ForegroundColor Red
        Read-Host "Enter"
    }
    exit
}

$root = Split-Path -Parent $PSCommandPath
Set-Location $root

$UA = @("-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0")
$timeoutSec = 6

# Same TEST_HOSTS as the GUI tester (CDN hosts excluded)
$hosts = @(
    "discord.com", "gateway.discord.gg", "cdn.discordapp.com", "updates.discord.com",
    "www.youtube.com", "youtu.be", "i.ytimg.com", "redirector.googlevideo.com",
    "www.google.com", "www.gstatic.com", "www.cloudflare.com", "cdnjs.cloudflare.com"
)

function Kill-Winws {
    try { taskkill /F /IM winws2.exe 2>$null | Out-Null } catch { }
    Start-Sleep -Seconds 2
}

function Start-Preset([string]$name) {
    $bat = Join-Path $root "start-$name.bat"
    if (-not (Test-Path $bat)) { return $false }
    for ($attempt = 1; $attempt -le 2; $attempt++) {
        Start-Process cmd -ArgumentList "/c", "`"$bat`"" -WindowStyle Hidden | Out-Null
        for ($i = 0; $i -lt 40; $i++) {
            Start-Sleep -Milliseconds 250
            $r = tasklist /FI "IMAGENAME eq winws2.exe" /NH 2>$null
            if ($r -match "winws2") { return $true }
        }
        # WinDivert handle may still be releasing from the killed instance
        if ($attempt -eq 1) { Start-Sleep -Seconds 3 }
    }
    return $false
}

# ── parallel curl via runspaces (same pattern as Zapret 1's tester) ──────
$runspaceScript = {
    param($url, $ua, $timeoutSec)
    $out = (& curl.exe -4 -I -s -m $timeoutSec --connect-timeout 3 $ua -o NUL -w "%{http_code}" $url 2>$null) -join ""
    if ($out -match "^\d{3}$") { return [string]$out } else { return [string]"000" }
}

function Test-Hosts([string]$label) {
    $pool = [runspacefactory]::CreateRunspacePool(1, 8)
    $pool.Open()
    $jobs = @()
    foreach ($h in $hosts) {
        $ps = [powershell]::Create()
        $ps.AddScript($runspaceScript) | Out-Null
        $ps.AddArgument("https://$h/") | Out-Null
        $ps.AddArgument($UA) | Out-Null
        $ps.AddArgument($timeoutSec) | Out-Null
        $ps.RunspacePool = $pool
        $jobs += @{ Ps = $ps; Handle = $ps.BeginInvoke(); Host = $h }
    }
    $results = @{}
    foreach ($j in $jobs) {
        $code = $j.Ps.EndInvoke($j.Handle)
        $code = [string]($code -join "")
        $results[$j.Host] = $code
        $j.Ps.Dispose()
    }
    $pool.Close(); $pool.Dispose()
    Write-Host ""
    Write-Host "=== $label ===" -ForegroundColor Cyan
    foreach ($h in $hosts) {
        $code = $results[$h]
        $color = "Green"
        if ($code -eq "000") { $color = "Red" }
        elseif ([int]$code -ge 400) { $color = "Yellow" }
        Write-Host ("  {0,-42} {1}" -f $h, $code) -ForegroundColor $color
    }
    # ANY http code >= 100 means the site answered — the DPI did not block.
    # 404/403/303 are normal "anonymous request" replies, NOT blockages.
    $ok = ($results.Values | Where-Object { $_ -match "^\d{3}$" -and $_ -ne "000" }).Count
    Write-Host ("  ПРОБИТО: {0}/{1} (ответ получен; 4xx/5xx — не блокировка)" -f $ok, $hosts.Count) -ForegroundColor White
    return $ok
}

# ── run ──────────────────────────────────────────────────────────────────
Write-Host "Zapret 2 lite — тестер" -ForegroundColor White
Write-Host "Проверяемые хосты: $($hosts.Count) (те же, что в GUI-тестере, без CDN)" -ForegroundColor DarkGray

# Zapret 1 conflict guard: winws.exe + winws2.exe both hold WinDivert filters.
$z1Proc = (tasklist /FI "IMAGENAME eq winws.exe" /NH 2>$null) -match "winws"
$z1Svc = (sc query zapret 2>$null) -match "RUNNING"
if ($z1Proc -or $z1Svc) {
    Write-Host ""
    Write-Host "Zapret 1 (winws.exe) обнаружен — тест невозможен: два WinDivert-фильтра конфликтуют." -ForegroundColor Red
    Write-Host "Остановите Zapret 1 (или удалите его службу) и повторите тест." -ForegroundColor Yellow
    Read-Host "Enter"
    exit 1
}

try {
    $runningBefore = (tasklist /FI "IMAGENAME eq winws2.exe" /NH 2>$null) -match "winws2"

    # Phase 0: naked baseline
    Kill-Winws
    $nakedOk = Test-Hosts "ГОЛЫЙ ТЕСТ (без защиты)"

    # pings (network sanity, once)
    $pingOk = 0
    foreach ($ip in @("1.1.1.1", "8.8.8.8", "9.9.9.9")) {
        $p = Test-Connection -ComputerName $ip -Count 1 -Quiet -ErrorAction SilentlyContinue
        if ($p) { $pingOk++ }
    }
    Write-Host ("  Ping публичных DNS: {0}/3" -f $pingOk) -ForegroundColor DarkGray

    # presets
    $results = @()
    foreach ($pf in Get-ChildItem (Join-Path $root "presets") -Filter "*.txt") {
        $name = $pf.BaseName
        Kill-Winws
        if (-not (Start-Preset $name)) {
            Write-Host "[$name] не удалось запустить winws2" -ForegroundColor Red
            continue
        }
        Start-Sleep -Seconds 2
        $ok = Test-Hosts $name
        $results += New-Object PSObject -Property @{ Name = $name; OK = $ok }
        Kill-Winws
    }

    # summary
    Write-Host ""
    Write-Host "===== ИТОГ =====" -ForegroundColor Cyan
    Write-Host ("  {0,-24} {1,4}" -f "Пресет", "OK")
    $sorted = $results | Sort-Object -Property OK -Descending
    foreach ($r in $sorted) {
        $best = ""
        if ($r.OK -eq $sorted[0].OK) { $best = "  <-- лучший" }
        Write-Host ("  {0,-24} {1}/{2}{3}" -f $r.Name, $r.OK, $hosts.Count, $best)
    }
    $bestPreset = $sorted | Select-Object -First 1
    if ($bestPreset) {
        Write-Host ""
        Write-Host "Рекомендуемая стратегия: $($bestPreset.Name)" -ForegroundColor Green
    }
    if ($nakedOk -eq 0 -and $bestPreset -and $bestPreset.OK -eq 0) {
        Write-Host "`nНичего не пробивается даже с обходом. Проверьте права/службу или DPI." -ForegroundColor Yellow
    }
    Write-Host "`nЗащита остановлена. Для восстановления: service.bat (меню) или start-default.bat" -ForegroundColor DarkGray
} catch {
    Write-Host ""
    Write-Host "Ошибка тестера: $($_.Exception.Message)" -ForegroundColor Red
    try { Kill-Winws } catch { }
}
Read-Host "Enter"