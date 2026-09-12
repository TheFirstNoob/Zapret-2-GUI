import subprocess

script = (
    "$c = Get-NetTCPConnection -ErrorAction SilentlyContinue | "
    "Where-Object { $_.RemoteAddress -and $_.RemoteAddress -ne '0.0.0.0' "
    "-and $_.RemoteAddress -ne '::' } | ForEach-Object { $_.OwningProcess }; "
    "$u = Get-NetUDPEndpoint -ErrorAction SilentlyContinue | "
    "Where-Object { $_.RemoteAddress -and $_.RemoteAddress -ne '0.0.0.0' "
    "-and $_.RemoteAddress -ne '::' } | ForEach-Object { $_.OwningProcess }; "
    "$pids = @($c + $u) | Sort-Object -Unique; "
    "if (-not $pids) { '[]'; exit }; "
    "Get-Process -Id $pids -ErrorAction SilentlyContinue | "
    "Select-Object ProcessName,Id,MainWindowTitle | Sort-Object ProcessName | "
    "ConvertTo-Json -Compress"
)
for policy in ('RemoteSigned', 'Bypass'):
    r = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', policy, '-Command', script],
                       capture_output=True, text=True, encoding='oem', errors='replace', timeout=25)
    print(f'--- policy={policy} rc={r.returncode}')
    print('OUT:', r.stdout[:160].replace('\n', ' | '))
    print('ERR:', r.stderr[:160].replace('\n', ' | '))