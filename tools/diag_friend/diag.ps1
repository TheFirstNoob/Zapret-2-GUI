$ErrorActionPreference = 'Continue'
$log = Join-Path $PSScriptRoot ("zapret2_diag_{0}.log" -f (Get-Date -Format 'yyyyMMdd_HHmmss'))
Start-Transcript -Path $log -Force | Out-Null

Write-Output ("=== ZAPRET2 DIAG {0} ===" -f (Get-Date))
Write-Output ""
Write-Output "--- OS / HW ---"
$os = Get-CimInstance Win32_OperatingSystem
Write-Output ("OS: {0} | v{1} build {2} | {3}" -f $os.Caption, $os.Version, $os.BuildNumber, $os.OSArchitecture)
Write-Output ("LastBoot: {0}" -f $os.LastBootUpTime)
$cs = Get-CimInstance Win32_ComputerSystem
Write-Output ("RAM: {0:N1} GB" -f ($cs.TotalPhysicalMemory / 1GB))
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
Write-Output ("CPU: {0}" -f $cpu.Name)
try {
  $av = Get-CimInstance -Namespace root/SecurityCenter2 -ClassName AntiVirusProduct -ErrorAction Stop |
        Select-Object -ExpandProperty displayName
  Write-Output ("AV: {0}" -f ($av -join ', '))
} catch { Write-Output "AV: (SecurityCenter2 not available)" }
Write-Output ""

Write-Output "--- Service zapret2: query ---"
sc.exe query zapret2
Write-Output "--- Service zapret2: config (binPath) ---"
sc.exe qc zapret2
Write-Output "--- Service zapret2: failure actions ---"
sc.exe qfailure zapret2
Write-Output ""

Write-Output "--- Processes ---"
tasklist /FI "IMAGENAME eq winws2.exe"
tasklist /FI "IMAGENAME eq winws.exe"
Write-Output ""

Write-Output "--- System events: zapret/WinDivert (last 2 days) ---"
Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName='Service Control Manager';
  StartTime=(Get-Date).AddDays(-2)} -MaxEvents 500 -ErrorAction SilentlyContinue |
  Where-Object { $_.Message -match 'zapret|WinDivert' } |
  ForEach-Object { "{0} [ID {1}] {2}" -f $_.TimeCreated, $_.Id, ($_.Message -replace "`r`n", " ") }
Write-Output ""

Write-Output "--- Application errors: winws/WinDivert (last 2 days) ---"
Get-WinEvent -FilterHashtable @{LogName='Application'; StartTime=(Get-Date).AddDays(-2)} -MaxEvents 500 -ErrorAction SilentlyContinue |
  Where-Object { $_.Message -match 'winws2?\.exe|WinDivert' } |
  ForEach-Object {
    $m = $_.Message -replace "`r`n", " "
    "{0} [ID {1}] {2}" -f $_.TimeCreated, $_.Id, $m.Substring(0, [Math]::Min(320, $m.Length))
  }
Write-Output ""

Write-Output "--- Find winws2.exe ---"
$candidates = @()
foreach ($root in @($PSScriptRoot, (Join-Path $PSScriptRoot 'bin'))) {
  $p = Join-Path $root 'winws2.exe'
  if (Test-Path $p) { $candidates += $p }
}
foreach ($base in @($env:USERPROFILE + '\Desktop', 'C:\Users', $env:ProgramFiles, ${env:ProgramFiles(x86)})) {
  if ($base -and (Test-Path $base)) {
    Get-ChildItem -Path $base -Filter 'winws2.exe' -Recurse -Depth 6 -ErrorAction SilentlyContinue |
      ForEach-Object { $candidates += $_.FullName }
  }
}
$candidates = $candidates | Select-Object -Unique
if (-not $candidates) {
  Write-Output "winws2.exe NOT FOUND (checked script folder, Desktop, C:\Users, Program Files)"
}
foreach ($exe in $candidates) {
  Write-Output ("--- Dry-run: {0} ---" -f $exe)
  $parent = Split-Path -Parent $exe
  $rootDir = if (Test-Path (Join-Path $parent '..\presets')) { Split-Path -Parent $parent } else { $parent }
  Push-Location $rootDir
  $out = cmd /c "`"$exe`" --dry-run 2>&1"
  $out | Select-Object -First 50
  Write-Output ("ExitCode: {0}" -f $LASTEXITCODE)
  Pop-Location
  Write-Output ""
}
Write-Output ("=== END ===")
Stop-Transcript | Out-Null
Write-Output ("Log saved: {0}" -f $log)
