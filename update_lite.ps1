# Zapret 2 lite - проверка обновлений (ТОЛЬКО уведомление, без автообновления)
# Запуск: update.bat (или service.bat -> пункт 6). Права админа не нужны.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSCommandPath
Set-Location $root

$local = ""
$vf = Join-Path $root "VERSION"
if (Test-Path $vf) { $local = (Get-Content $vf -Raw).Trim() }
Write-Host "Zapret 2 lite - проверка обновлений"
Write-Host "Установлено: $local`n"

# Источники: GitHub raw -> jsDelivr-зеркало -> GitHub API (contents/VERSION).
$urls = @(
    "https://raw.githubusercontent.com/TheFirstNoob/Zapret-2-GUI/main/VERSION",
    "https://cdn.jsdelivr.net/gh/TheFirstNoob/Zapret-2-GUI@main/VERSION",
    "https://api.github.com/repos/TheFirstNoob/Zapret-2-GUI/contents/VERSION"
)
$latest = ""
foreach ($u in $urls) {
    try {
        $r = & curl.exe -4 -s -m 8 -H "Accept: application/vnd.github.raw+json" $u 2>$null
        $txt = ($r -join "`n")
        if ($u -match "api\.github\.com") {
            try {
                $j = $txt | ConvertFrom-Json
                if ($j.content) {
                    $b64 = ($j.content -replace "\s", "")
                    $txt = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($b64))
                }
            } catch { }
        }
        $m = [regex]::Match($txt, "\d+(?:\.\d+)*")
        if ($m.Success) { $latest = $m.Value; break }
    } catch { }
}
if (-not $latest) {
    Write-Host "Не удалось проверить обновления (нет сети или GitHub недоступен)." -ForegroundColor Yellow
    Write-Host "Повторите позже или откройте страницу релизов вручную:"
    Write-Host "  https://github.com/TheFirstNoob/Zapret-2-GUI/releases"
    Read-Host "Enter"
    exit 1
}
Write-Host "Доступно: $latest`n"

function Ver-Parts([string]$v) {
    $out = @()
    foreach ($p in ($v -split "\.")) {
        if ($p -match "^\d+$") { $out += [int]$p }
    }
    return $out
}
$lp = @(Ver-Parts $local)
$rp = @(Ver-Parts $latest)
$len = [Math]::Max($lp.Count, $rp.Count)
$newer = $false
for ($i = 0; $i -lt $len; $i++) {
    $a = if ($i -lt $lp.Count) { $lp[$i] } else { 0 }
    $b = if ($i -lt $rp.Count) { $rp[$i] } else { 0 }
    if ($b -gt $a) { $newer = $true; break }
    if ($b -lt $a) { break }
}

if ($newer) {
    Write-Host "Доступна новая версия: $latest (у вас $local)." -ForegroundColor Green
    Write-Host "Скачать:  https://github.com/TheFirstNoob/Zapret-2-GUI/releases"
    Write-Host "Зеркало:  https://cdn.jsdelivr.net/gh/TheFirstNoob/Zapret-2-GUI@main/Windows%20build/Zapret2GUI-lite.zip"
    Write-Host ""
    Write-Host "Автообновления в lite нет: скачайте архив и распакуйте поверх," -ForegroundColor Yellow
    Write-Host "сохранив свои lists\*user*.txt и правки списков." -ForegroundColor Yellow
} else {
    Write-Host "Обновлений нет: установлена актуальная версия." -ForegroundColor Green
}
Read-Host "Enter"
