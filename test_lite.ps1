# Zapret 2 lite — проверка связи (PowerShell 5.1)
# Finds CDN problems and offers to fix them. No reports, no preset comparison.
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

$UA = @("-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
$timeoutSec = 6
$CON = 8   # concurrency

# ── host sets (same as the GUI tester) ──────────────────────────────────
$RATED = @(
    "discord.com", "gateway.discord.gg", "cdn.discordapp.com", "updates.discord.com",
    "www.youtube.com", "youtu.be", "i.ytimg.com", "redirector.googlevideo.com",
    "github.com", "raw.githubusercontent.com", "storage.googleapis.com"
)
$CONTROL = @(
    "www.google.com", "www.gstatic.com", "www.cloudflare.com", "cdnjs.cloudflare.com",
    "web.telegram.org", "api.telegram.org", "x.com", "www.facebook.com",
    "www.instagram.com", "www.linkedin.com", "web.whatsapp.com",
    "fcm.googleapis.com", "api.push.apple.com", "vk.ru", "ya.ru", "www.gosuslugi.ru"
)
# CDN candidates for the hostlist-vs-ipset A/B (GUI CDN_HOSTS)
$CDN = @(
    "hyperion-cs.github.io", "www.mobil.com.se", "cdn.apple-mapkit.com",
    "amplifon.com", "optout.aboutads.info", "cdn.eso.org",
    "go.coveo.com", "justice.gov", "img.wzstats.gg", "esm.sh",
    "antoniotartaglia.it", "status.moow.info", "ui-arts.com",
    "app.thecuriositylibrary.com", "admin.survey54.com", "ssl.p.jwpcdn.com",
    "www.jetblue.com", "buyvm.net", "dmvideo.download",
    "gcore.com", "api.usercentrics.eu", "widgets.reputation.com",
    "king.hr", "mail.server.apaone.com", "nioges.com",
    "5fd8bdae.nip.io", "net4u.de", "elecane.com",
    "store.takeda.com", "sh00065.hostgator.com", "ged.com.sg",
    "www.adwin.fr", "www.emca.be", "www.velivole.fr",
    "askit-app.de", "us.rudder.qntmnet.com"
)

function Kill-Winws {
    try { taskkill /F /IM winws2.exe 2>$null | Out-Null } catch { }
    Start-Sleep -Seconds 2
}

function Start-Preset([string]$name) {
    $bat = Join-Path $root "start-$name.bat"
    if (-not (Test-Path $bat)) { return $false }
    Start-Process cmd -ArgumentList "/c", "`"$bat`"" -WindowStyle Hidden | Out-Null
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 250
        $r = tasklist /FI "IMAGENAME eq winws2.exe" /NH 2>$null
        if ($r -match "winws2") { return $true }
    }
    Start-Sleep -Seconds 3
    return $false
}

# ── parallel probe via runspaces ────────────────────────────────────────
$probeScript = {
    param($url, $ua, $timeoutSec)
    $out = (& curl.exe -4 -s -m $timeoutSec --connect-timeout 3 $ua -o NUL -w "%{http_code}" $url 2>$null) -join ""
    if ($out -match "^\d{3}$") { return [string]$out } else { return [string]"000" }
}
function Test-Set([string[]]$hosts) {
    $pool = [runspacefactory]::CreateRunspacePool(1, $CON)
    $pool.Open()
    $jobs = @()
    foreach ($h in $hosts) {
        $ps = [powershell]::Create()
        $ps.AddScript($probeScript) | Out-Null
        $ps.AddArgument("https://$h/") | Out-Null
        $ps.AddArgument($UA) | Out-Null
        $ps.AddArgument($timeoutSec) | Out-Null
        $ps.RunspacePool = $pool
        $jobs += @{ Ps = $ps; Handle = $ps.BeginInvoke(); Host = $h }
    }
    $res = @{}
    foreach ($j in $jobs) {
        $code = [string](($j.Ps.EndInvoke($j.Handle)) -join "")
        $res[$j.Host] = ($code -match "^\d{3}$" -and $code -ne "000")
        $j.Ps.Dispose()
    }
    $pool.Close(); $pool.Dispose()
    return $res
}

function Resolve-Ips([string]$domain) {
    try {
        $ips = @()
        foreach ($a in [System.Net.Dns]::GetHostAddresses($domain)) {
            if ($a.AddressFamily -eq 'InterNetwork') { $ips += $a.IPAddressToString }
        }
        return $ips
    } catch { return @() }
}

# Zapret 1 conflict guard
$z1Proc = (tasklist /FI "IMAGENAME eq winws.exe" /NH 2>$null) -match "winws"
$z1Svc = (sc query zapret 2>$null) -match "RUNNING"
if ($z1Proc -or $z1Svc) {
    Write-Host "`nОбнаружен Zapret 1 (winws.exe) — остановите его сначала (два WinDivert-фильтра конфликтуют)." -ForegroundColor Red
    Read-Host "Enter"
    exit 1
}

Write-Host "Zapret 2 lite — проверка связи" -ForegroundColor White

try {
    # ── 1. naked baseline on CDN candidates ──
    Write-Host "`n[1/4] Шаг 1/4: проверка без защиты..." -ForegroundColor Cyan
    Kill-Winws
    $nakedCdn = Test-Set $CDN

    # ── 2. hostlist mode (default preset) ──
    Write-Host "[2/4] Шаг 2/4: обычный обход (default)..." -ForegroundColor Cyan
    Kill-Winws
    if (-not (Start-Preset "default")) { throw "winws2 did not start (default preset)" }
    Start-Sleep -Seconds 2
    $ratedDefault = Test-Set $RATED
    $hlCdn = Test-Set $CDN

    # ── 3. ipset mode ──
    Write-Host "[3/4] Шаг 3/4: обход для всех сайтов (ipset)..." -ForegroundColor Cyan
    Kill-Winws
    if (-not (Start-Preset "ipset")) { throw "winws2 did not start (ipset preset)" }
    Start-Sleep -Seconds 2
    $ipCdn = Test-Set $CDN
    Kill-Winws

    # ── 4. verdicts + fixes ──
    Write-Host "[4/4] Шаг 4/4: анализ..." -ForegroundColor Cyan
    $fixInc = @()   # "чинит ipset" -> ipset-include-user (needs IPs)
    $fixExc = @()   # "ломает ipset" -> list-exclude
    $hard = @()
    $dead = @()
    foreach ($h in $CDN) {
        $naked = $nakedCdn[$h]; $hl = $hlCdn[$h]; $ip = $ipCdn[$h]
        if (-not $naked) { $dead += $h; continue }
        if ($hl -and $ip) { continue }                        # ok
        elseif (-not $hl -and $ip) { $fixInc += $h }          # fixed by ipset
        elseif ($hl -and -not $ip) { $fixExc += $h }          # broken by ipset
        else { $hard += $h }                                  # not curable
    }
    $ratedOk = ($ratedDefault.Values | Where-Object { $_ }).Count

    Write-Host ("  Рабочих сайтов под защитой: {0}/{1}" -f $ratedOk, $RATED.Count)
    if ($dead.Count)  { Write-Host ("  мёртвые (не блок): {0}" -f ($dead -join ", ")) -ForegroundColor DarkGray }
    if ($hard.Count)  { Write-Host ("  не лечится: {0}" -f ($hard -join ", ")) -ForegroundColor Yellow }
    if ($fixInc.Count){ Write-Host ("  чинит ipset (добавить IP в обход): {0}" -f ($fixInc -join ", ")) -ForegroundColor Green }
    if ($fixExc.Count){ Write-Host ("  ломает ipset (добавить в исключения): {0}" -f ($fixExc -join ", ")) -ForegroundColor Green }

    $apply = $fixInc.Count + $fixExc.Count
    if ($apply -eq 0) {
        Write-Host "`nПроблем не найдено. Ничего не нужно." -ForegroundColor Green
        Read-Host "Enter"
        exit 0
    }
    Write-Host ""
    $ans = Read-Host "Применить фиксы (добавить $apply сайт(ов) в списки)? [Y/N]"
    if ($ans -notmatch "^[YyДд]") {
        Write-Host "Пропущено. Списки не изменены." -ForegroundColor Yellow
        Read-Host "Enter"
        exit 0
    }

    # write fixes
    foreach ($h in $fixExc) {
        $f = Join-Path $root "lists\list-exclude.txt"
        $exists = (Test-Path $f) -and ((Get-Content $f -Raw) -match [regex]::Escape($h))
        if (-not $exists) { Add-Content -Path $f -Value $h -Encoding UTF8 }
    }
    foreach ($h in $fixInc) {
        $ips = Resolve-Ips $h
        if ($ips.Count -eq 0) { Write-Host "  $h - нет резолвнутых IP, пропущено" -ForegroundColor Yellow; continue }
        $f = Join-Path $root "lists\ipset-include-user.txt"
        $existing = if (Test-Path $f) { (Get-Content $f -Raw) } else { "" }
        foreach ($ip in $ips) {
            if ($existing -notmatch [regex]::Escape($ip)) { Add-Content -Path $f -Value $ip -Encoding UTF8 }
        }
    }

    # restart protection and re-verify RATED
    Write-Host "`nПерезапуск обхода..." -ForegroundColor Cyan
    Kill-Winws
    if (Start-Preset "default") {
        Start-Sleep -Seconds 2
        $after = Test-Set $RATED
        $afterOk = ($after.Values | Where-Object { $_ }).Count
        Write-Host ("  После фикса рабочих сайтов: {0}/{1} (было {2}/{1})" -f $afterOk, $RATED.Count, $ratedOk)
    } else {
        Write-Host "  winws2 не перезапустился. Запустите вручную: service.bat или start-default.bat" -ForegroundColor Yellow
    }
} catch {
    Write-Host "`nОшибка: $($_.Exception.Message)" -ForegroundColor Red
    try { Kill-Winws } catch { }
    Write-Host "Обход остановлен. Восстановите: service.bat или start-default.bat" -ForegroundColor DarkGray
}
Read-Host "Enter"