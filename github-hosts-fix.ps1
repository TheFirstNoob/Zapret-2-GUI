# GitHub hosts fix — для сетей, где githubusercontent (185.199.108.0/22)
# режется на уровне IP (Ростелеком, Т2 и др., с 2026-08).
#
# Fastly отдаёт контент GitHub с ЛЮБОГО своего edge-IP (конфиг общий), а
# DPI фильтрует только выделенный GitHub-диапазон. Скрипт:
#   1) тянет публичные IP-сети Fastly (api.fastly.com/public-ip-list),
#   2) проверяет, какие из них реально отдают raw.githubusercontent.com
#      (curl --resolve + реальный файл из репо),
#   3) выбирает самый быстрый, дописывает hosts-записи для всех
#      githubusercontent-доменов, сбрасывает DNS-кэш.
#
# Запуск: двойной клик или powershell -ExecutionPolicy Bypass -File github-hosts-fix.ps1
$ErrorActionPreference = "Continue"

# ── admin self-elevation (one UAC prompt) ────────────────────────────────
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    try {
        Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"") -Verb RunAs -Wait
    } catch {
        Write-Host "Нет прав администратора (UAC отменён)." -ForegroundColor Red
        Read-Host "Enter"
    }
    exit
}

$hostsPath = "$env:SystemRoot\System32\drivers\etc\hosts"
$marker = "# --- Zapret2 GitHub fix (auto) ---"
$testUrl = "https://raw.githubusercontent.com/TheFirstNoob/Zapret-2-GUI/main/VERSION"
$testHost = "raw.githubusercontent.com"
$domains = @(
    "raw.githubusercontent.com", "objects.githubusercontent.com",
    "release-assets.githubusercontent.com", "private-user-images.githubusercontent.com",
    "gist.githubusercontent.com", "avatars.githubusercontent.com",
    "avatars0.githubusercontent.com", "avatars1.githubusercontent.com",
    "avatars2.githubusercontent.com", "avatars3.githubusercontent.com",
    "avatars4.githubusercontent.com", "avatars5.githubusercontent.com"
)

Write-Host "GitHub hosts fix" -ForegroundColor White

# 1) Fastly public IP ranges
Write-Host "Скачиваю публичные IP-сети Fastly..." -ForegroundColor DarkGray
try {
    $ranges = (Invoke-RestMethod -Uri "https://api.fastly.com/public-ip-list" -TimeoutSec 15).addresses
} catch {
    Write-Host "Не удалось получить список Fastly ($($_.Exception.Message))." -ForegroundColor Red
    Write-Host "Пробую известные IP..." -ForegroundColor Yellow
    $ranges = @(
        "146.75.22.132", "146.75.30.132", "146.75.78.132", "146.75.84.132",
        "146.75.63.132", "146.75.79.132", "146.75.23.132", "146.75.31.132",
        "146.75.97.132", "146.75.96.132", "151.101.2.132", "151.101.66.132",
        "151.101.130.132", "151.101.194.132", "151.101.0.132", "151.101.64.132",
        "151.101.128.132", "151.101.192.132", "151.101.1.69", "151.101.65.69",
        "151.101.129.69", "151.101.193.69"
    )
}
if (-not $ranges -or $ranges.Count -eq 0) {
    Write-Host "Нет IP для проверки." -ForegroundColor Red
    Read-Host "Enter"
    exit 1
}

# 2) probe candidates: keep only IPs that serve the test URL
Write-Host "Проверяю кандидатов (может занять до минуты)..." -ForegroundColor DarkGray
$good = @()
foreach ($ip in $ranges) {
    if ($ip -notmatch "^\d+\.\d+\.\d+\.\d+$") { continue }
    $t0 = Get-Date
    $out = curl.exe -s -m 5 --connect-timeout 2 --resolve "$testHost`:443:$ip" $testUrl 2>$null
    $ms = ((Get-Date) - $t0).TotalMilliseconds
    if ($out -match "Pre-Release") {
        $good += [PSCustomObject]@{ IP = $ip; Ms = [math]::Round($ms) }
    }
}
if ($good.Count -eq 0) {
    Write-Host "Ни один Fastly-IP не отдаёт GitHub. Скорее всего блок сейчас везде — попробуйте позже или WARP." -ForegroundColor Yellow
    Read-Host "Enter"
    exit 1
}
$best = $good | Sort-Object Ms | Select-Object -First 1
Write-Host "Подходящие IP: $($good.IP -join ', ')" -ForegroundColor Green
Write-Host "Выбран: $($best.IP) ($($best.Ms) ms)" -ForegroundColor Green

# 3) update hosts
$content = Get-Content $hostsPath
$idx = [Array]::IndexOf($content, $marker)
if ($idx -ge 0) {
    # remove old auto-block
    $end = $idx
    while ($end -lt $content.Count -and $content[$end] -notmatch "^\S") { $end++ }
    $content = $content[0..($idx - 1)] + $content[$end..($content.Count - 1)]
}
$lines = @($content) + @($marker)
foreach ($d in $domains) {
    $lines += "$($best.IP) $d"
}
$lines += "# --- end Zapret2 GitHub fix ---"
$hostsContent = ($lines -join "`r`n") + "`r`n"
$bytes = [System.Text.Encoding]::ASCII.GetBytes($hostsContent)
$written = $false
for ($attempt = 1; $attempt -le 5 -and -not $written; $attempt++) {
    try {
        Copy-Item $hostsPath "$hostsPath.bak" -Force -ErrorAction SilentlyContinue
        # Atomic replace (MoveFileEx) — never truncate the live file:
        # FileMode::Create would leave an empty hosts if the process dies
        # between open and write.
        $tmp = "$hostsPath.tmp"
        [System.IO.File]::WriteAllBytes($tmp, $bytes)
        Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class HF {
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    public static extern bool MoveFileEx(string a, string b, int f);
}
"@ -ErrorAction SilentlyContinue
        if ([HF]::MoveFileEx($tmp, $hostsPath, 2)) {  # MOVEFILE_REPLACE_EXISTING
            $written = $true
        } else {
            Start-Sleep -Milliseconds 800
        }
    } catch {
        Start-Sleep -Milliseconds 800
    }
}
if ($written) {
    ipconfig /flushdns | Out-Null
    Write-Host "Hosts обновлён ($($domains.Count) доменов -> $($best.IP)). Резервная копия: hosts.bak" -ForegroundColor Green
} else {
    Write-Host "Не удалось записать hosts (файл занят). Закройте hosts-менеджеры и повторите." -ForegroundColor Red
}

# 4) verify
$check = curl.exe -s -m 6 --connect-timeout 2 $testUrl 2>$null
if ($check -match "Pre-Release") {
    Write-Host "Проверка: GitHub работает без VPN! ✅" -ForegroundColor Green
} else {
    Write-Host "Проверка: пока не работает (блок может быть временным)." -ForegroundColor Yellow
}
Read-Host "Enter"