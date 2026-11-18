# Discord/Cloudflare standalone fix for Zapret Lite / Zapret 1 users.
# No Python, no GUI. Task Scheduler + local scoped DNS + hosts + NRPT.
param(
  [ValidateSet('Install','Uninstall','Status','Run')]
  [string]$Action = 'Status',
  [int]$DnsPort = 53,
  [string]$StateDir = $PSScriptRoot
)
$ErrorActionPreference = 'Stop'
$StateDir = $StateDir.TrimEnd('\')
$TaskName = 'DiscordCloudflareFix'
$RuleName = 'DiscordCloudflareFix'
$HostsPath = Join-Path $env:SystemRoot 'System32\drivers\etc\hosts'
$ScriptPath = $PSCommandPath
if (-not $ScriptPath) { $ScriptPath = $MyInvocation.MyCommand.Path }
$StatePath = Join-Path $StateDir 'discord-fix-state.json'
$BackupPath = Join-Path $StateDir 'discord-fix-hosts.backup.txt'
$CandidatesPath = Join-Path $StateDir 'discord-candidates.json'

$Zones = @(
  '.discord', '.discord.com', '.discord.gg', '.discord.media',
  '.discordapp.com', '.discordapp.net',
  '.cloudflare.com', '.cloudflareaccess.com', '.cloudflare-dns.com',
  '.auth0.com', '.epicgames.dev', '.epicgames.com', '.fandom.com'
)
$Apex = @(
  'discord.com','www.discord.com','gateway.discord.gg','cdn.discordapp.com',
  'discordapp.com','discordapp.net','discord.media','media.discordapp.net',
  'updates.discord.com','discord.gg',
  'cloudflare.com','www.cloudflare.com','dash.cloudflare.com',
  'api.cloudflare.com','support.cloudflare.com','cloudflareaccess.com',
  'cloudflare-dns.com','challenges.cloudflare.com','cloudflare-ech.com',
  'auth0.com','www.auth0.com','api.epicgames.dev','www.epicgames.com',
  'store.epicgames.com','fandom.com','www.fandom.com'
)
$BlockBegin = '# >>> DiscordCloudflareFix >>>'
$BlockEnd = '# <<< DiscordCloudflareFix <<<'
$FallbackCandidates = @(
  '23.227.38.5','23.227.38.24','23.227.38.74','23.227.38.112',
  '23.227.38.177','23.227.38.234','23.227.38.180','23.227.38.94'
)

function Test-Admin {
  $p = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
  return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-Candidates {
  if (Test-Path $CandidatesPath) {
    try {
      $data = Get-Content $CandidatesPath -Raw -Encoding UTF8 | ConvertFrom-Json
      if ($data -is [array] -and $data.Count -gt 0) { return @($data) }
    } catch {}
  }
  return $FallbackCandidates
}

function Test-Candidate([string]$Ip) {
  try {
    $out = & curl.exe -sS -o NUL -w "%{http_code}" --max-time 4 --resolve "discord.com:443:$Ip" "https://discord.com/" 2>$null
    return ($out -match '200|301|302')
  } catch { return $false }
}

function Select-Candidate {
  $pool = @(Get-Candidates)
  $rand = New-Object System.Random
  for ($i = 0; $i -lt 20 -and $pool.Count -gt 0; $i++) {
    $idx = $rand.Next(0, $pool.Count)
    $ip = [string]$pool[$idx]
    if (Test-Candidate $ip) { return $ip }
    $pool = @($pool | Where-Object { $_ -ne $ip })
  }
  return $null
}

function Read-HostsLines {
  if (Test-Path $HostsPath) { return @(Get-Content $HostsPath -Encoding UTF8) }
  return @()
}

function Write-HostsLines([string[]]$Lines) {
  $enc = New-Object System.Text.UTF8Encoding($false)
  $tmp = "$HostsPath.discordfix.tmp"
  [IO.File]::WriteAllLines($tmp, $Lines, $enc)
  if (Test-Path $HostsPath) { Copy-Item $HostsPath "$HostsPath.discordfix.bak" -Force }
  Move-Item $tmp $HostsPath -Force
}

function Test-ManagedHost([string]$HostName) {
  $h = $HostName.ToLower().TrimEnd('.')
  if ($Apex -contains $h) { return $true }
  foreach ($z in $Zones) {
    if ($h.EndsWith($z, [StringComparison]::OrdinalIgnoreCase)) { return $true }
  }
  return $false
}

function Install-Hosts([string]$Ip) {
  $lines = Read-HostsLines
  if (Test-Path $HostsPath) { Copy-Item $HostsPath $BackupPath -Force }
  $out = New-Object System.Collections.Generic.List[string]
  foreach ($line in $lines) {
    $s = $line.Trim()
    if ($s -eq $BlockBegin -or $s -eq $BlockEnd) { continue }
    if ($s -and -not $s.StartsWith('#')) {
      $parts = $s -split '\s+'
      if ($parts.Count -ge 2) {
        $managed = $false
        for ($i=1; $i -lt $parts.Count; $i++) {
          if (Test-ManagedHost $parts[$i]) { $managed = $true; break }
        }
        if ($managed) { continue }
      }
    }
    $out.Add($line)
  }
  $out.Add('')
  $out.Add($BlockBegin)
  $out.Add('# temporary workaround; remove with DiscordCloudflareFix.ps1 -Action Uninstall')
  foreach ($h in $Apex) { $out.Add("$Ip $h") }
  $out.Add($BlockEnd)
  Write-HostsLines $out.ToArray()
  ipconfig /flushdns | Out-Null
}

function Remove-Hosts {
  $lines = Read-HostsLines
  $out = New-Object System.Collections.Generic.List[string]
  $skip = $false
  foreach ($line in $lines) {
    $s = $line.Trim()
    if ($s -eq $BlockBegin) { $skip = $true; continue }
    if ($s -eq $BlockEnd) { $skip = $false; continue }
    if (-not $skip) { $out.Add($line) }
  }
  Write-HostsLines $out.ToArray()
  ipconfig /flushdns | Out-Null
}

function Install-Nrpt {
  Get-DnsClientNrptRule | Where-Object { $_.DisplayName -eq $RuleName } | Remove-DnsClientNrptRule -Force -ErrorAction SilentlyContinue
  foreach ($z in $Zones) {
    Add-DnsClientNrptRule -Namespace $z -NameServers '127.0.0.1' -DisplayName $RuleName -ErrorAction Stop | Out-Null
  }
}

function Remove-Nrpt {
  Get-DnsClientNrptRule | Where-Object { $_.DisplayName -eq $RuleName } | Remove-DnsClientNrptRule -Force -ErrorAction SilentlyContinue
  ipconfig /flushdns | Out-Null
}

function Escape-Xml([string]$s) {
  return [Security.SecurityElement]::Escape($s)
}

function Install-Task {
  $cmd = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
  $taskArgs = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $ScriptPath + '" -Action Run -DnsPort 53 -StateDir "' + $StateDir + '"'
  $c = Escape-Xml $cmd
  $a = Escape-Xml $taskArgs
  $xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Discord/Cloudflare temporary fix</Description></RegistrationInfo>
  <Triggers><BootTrigger><Enabled>true</Enabled><Delay>PT15S</Delay></BootTrigger></Triggers>
  <Principals><Principal id="Author"><UserId>S-1-5-18</UserId><RunLevel>HighestAvailable</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled><Hidden>true</Hidden>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
  </Settings>
  <Actions Context="Author"><Exec><Command>$c</Command><Arguments>$a</Arguments></Exec></Actions>
</Task>
"@
  $tmp = Join-Path $StateDir 'discord-fix-task.xml'
  [IO.File]::WriteAllText($tmp, $xml, (New-Object System.Text.UnicodeEncoding($false,$true)))
  & schtasks.exe /Create /TN $TaskName /XML $tmp /F | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "schtasks /Create failed: $LASTEXITCODE" }
  & schtasks.exe /Run /TN $TaskName | Out-Null
}

function Remove-Task {
  $sched = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
  if ($sched) {
    & schtasks.exe /End /TN $TaskName 2>$null | Out-Null
    & schtasks.exe /Delete /TN $TaskName /F 2>$null | Out-Null
  }
}

function Get-State {
  if (Test-Path $StatePath) {
    try { return Get-Content $StatePath -Raw -Encoding UTF8 | ConvertFrom-Json } catch {}
  }
  return $null
}

function Set-State([string]$Ip) {
  $o = [ordered]@{ enabled=$true; selected_ip=$Ip; task_root=$StateDir; updated=(Get-Date).ToUniversalTime().ToString('o') }
  $o | ConvertTo-Json | Set-Content $StatePath -Encoding UTF8
}

function Show-Status {
  $st = Get-State
  $sched = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
  $installed = [bool]$sched
  $nrpt = @(Get-DnsClientNrptRule | Where-Object { $_.DisplayName -eq $RuleName }).Count
  $hosts = (Test-Path $HostsPath) -and ((Read-HostsLines) -contains $BlockBegin)
  Write-Output "task_installed=$installed"
  if ($installed) { Write-Output "task_state=$($sched.State)" }
  $stateIp = ''
  if ($st) { $stateIp = $st.selected_ip }
  Write-Output "state_ip=$stateIp"
  Write-Output "nrpt_rules=$nrpt hosts_block=$hosts"
}

function Assert-DnsPortFree {
  $ep = Get-NetUDPEndpoint -LocalPort 53 -ErrorAction SilentlyContinue | Where-Object { $_.OwningProcess -ne $PID }
  if ($ep) {
    throw 'Port 53 is busy. Disable the Zapret2 Discord fix first; only one helper can run.'
  }
}

function Install-Fix {
  if (-not (Test-Admin)) { throw 'Run as Administrator' }
  Remove-Task
  Start-Sleep -Milliseconds 700
  Assert-DnsPortFree
  $ip = Select-Candidate
  if (-not $ip) { throw 'no working candidate IP' }
  Install-Hosts $ip
  Install-Nrpt
  Set-State $ip
  Install-Task
  Write-Output "installed ip=$ip"
}

function Uninstall-Fix {
  if (-not (Test-Admin)) { throw 'Run as Administrator' }
  Remove-Task
  Remove-Nrpt
  Remove-Hosts
  Remove-Item $StatePath -Force -ErrorAction SilentlyContinue
  Write-Output 'uninstalled'
}

$DnsCsharp = @"
using System;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;

public class DiscordFixDns : IDisposable {
  private readonly string _ip;
  private readonly int _port;
  private readonly string[] _zones;
  private UdpClient _udp;
  private TcpListener _tcp;
  private volatile bool _stop;

  public DiscordFixDns(string ip, int port, string[] zones) {
    _ip = ip; _port = port; _zones = zones;
  }

  private bool Managed(string name) {
    name = name.ToLowerInvariant().TrimEnd('.');
    foreach (string z in _zones) {
      if (name.EndsWith(z, StringComparison.OrdinalIgnoreCase)) return true;
    }
    return false;
  }

  private static bool ParseQuestion(byte[] q, out string name, out int qtype, out int qend) {
    name = null; qtype = 0; qend = 0;
    if (q == null || q.Length < 12) return false;
    int i = 12;
    var sb = new StringBuilder();
    while (i < q.Length) {
      int n = q[i];
      if (n == 0) { i++; break; }
      if ((n & 0xC0) != 0 || i + 1 + n > q.Length) return false;
      i++;
      if (sb.Length > 0) sb.Append('.');
      sb.Append(Encoding.ASCII.GetString(q, i, n));
      i += n;
    }
    if (i + 4 > q.Length) return false;
    qtype = (q[i] << 8) | q[i+1];
    qend = i + 4;
    name = sb.ToString();
    return true;
  }

  private static byte[] Header(byte[] q, int an) {
    return new byte[] {
      q[0], q[1], 0x81, 0x80,
      0, 1, (byte)(an >> 8), (byte)(an & 0xFF),
      0, 0, 0, 0
    };
  }

  private byte[] AnswerA(byte[] q, int qend) {
    byte[] ip = IPAddress.Parse(_ip).GetAddressBytes();
    byte[] head = Header(q, 1);
    byte[] outb = new byte[head.Length + (qend - 12) + 16];
    Buffer.BlockCopy(head, 0, outb, 0, head.Length);
    Buffer.BlockCopy(q, 12, outb, head.Length, qend - 12);
    int p = head.Length + (qend - 12);
    outb[p++] = 0xC0; outb[p++] = 0x0C;
    outb[p++] = 0; outb[p++] = 1;
    outb[p++] = 0; outb[p++] = 1;
    outb[p++] = 0; outb[p++] = 0; outb[p++] = 0; outb[p++] = 30;
    outb[p++] = 0; outb[p++] = 4;
    Buffer.BlockCopy(ip, 0, outb, p, 4); p += 4;
    return outb;
  }

  private byte[] Nodata(byte[] q, int qend) {
    byte[] head = Header(q, 0);
    byte[] outb = new byte[head.Length + (qend - 12)];
    Buffer.BlockCopy(head, 0, outb, 0, head.Length);
    Buffer.BlockCopy(q, 12, outb, head.Length, qend - 12);
    return outb;
  }

  private byte[] Forward(byte[] q) {
    try {
      using (var u = new UdpClient()) {
        u.Client.ReceiveTimeout = 1200;
        u.Send(q, q.Length, new IPEndPoint(IPAddress.Parse("1.1.1.1"), 53));
        var ep = new IPEndPoint(IPAddress.Any, 0);
        return u.Receive(ref ep);
      }
    } catch { return null; }
  }

  private byte[] Handle(byte[] q) {
    string name; int qtype, qend;
    if (!ParseQuestion(q, out name, out qtype, out qend)) return null;
    if (Managed(name)) {
      if (qtype == 1) return AnswerA(q, qend);
      return Nodata(q, qend);
    }
    return Forward(q);
  }

  private void OnUdp(IAsyncResult ar) {
    try {
      var ep = new IPEndPoint(IPAddress.Any, 0);
      byte[] data = _udp.EndReceive(ar, ref ep);
      byte[] resp = Handle(data);
      if (resp != null) _udp.Send(resp, resp.Length, ep);
    } catch {}
    if (!_stop) { try { _udp.BeginReceive(OnUdp, null); } catch {} }
  }

  private void TcpLoop() {
    while (!_stop) {
      try {
        using (TcpClient c = _tcp.AcceptTcpClient()) {
          c.ReceiveTimeout = 3000;
          var s = c.GetStream();
          byte[] lenb = new byte[2];
          if (s.Read(lenb, 0, 2) != 2) continue;
          int len = (lenb[0] << 8) | lenb[1];
          byte[] q = new byte[len];
          int off = 0;
          while (off < len) {
            int n = s.Read(q, off, len - off);
            if (n <= 0) break;
            off += n;
          }
          byte[] resp = Handle(q);
          if (resp != null) {
            s.WriteByte((byte)(resp.Length >> 8));
            s.WriteByte((byte)(resp.Length & 0xFF));
            s.Write(resp, 0, resp.Length);
          }
        }
      } catch { Thread.Sleep(50); }
    }
  }

  public void Start() {
    _udp = new UdpClient(new IPEndPoint(IPAddress.Loopback, _port));
    _udp.BeginReceive(OnUdp, null);
    _tcp = new TcpListener(IPAddress.Loopback, _port);
    _tcp.Start();
    var t = new Thread(TcpLoop);
    t.IsBackground = true;
    t.Start();
  }

  public void Dispose() {
    _stop = true;
    try { if (_udp != null) _udp.Close(); } catch {}
    try { if (_tcp != null) _tcp.Stop(); } catch {}
  }
}
"@

function Run-Helper {
  $st = Get-State
  if (-not $st -or -not $st.selected_ip) { Write-Output 'no state'; return }
  if (-not ('DiscordFixDns' -as [type])) { Add-Type -TypeDefinition $DnsCsharp -Language CSharp }
  $ip = [string]$st.selected_ip
  $dns = New-Object -TypeName DiscordFixDns -ArgumentList $ip, $DnsPort, ([string[]]$Zones)
  $dns.Start()
  Write-Output "helper started ip=$ip port=$DnsPort"
  try {
    while ($true) { Start-Sleep -Seconds 5 }
  } finally {
    $dns.Dispose()
  }
}

if ($Action -ne 'Status' -and -not (Test-Admin)) {
  $argLine = '-NoProfile -ExecutionPolicy Bypass -File "' + $ScriptPath + '" -Action ' + $Action + ' -StateDir "' + $StateDir + '"'
  Start-Process -FilePath powershell.exe -Verb RunAs -ArgumentList $argLine
  return
}

switch ($Action) {
  'Status'  { Show-Status }
  'Install' { Install-Fix }
  'Uninstall' { Uninstall-Fix }
  'Run'     { Run-Helper }
}
