<#
net_reset.ps1 - reset the Windows network stack to defaults.

Fixes leftovers from "tweakers", VPN/proxy tools, old/broken Windows:
  - Winsock catalog
  - TCP/IP (IPv4 + IPv6)
  - TCP global parameters
  - WinHTTP proxy + per-user proxy
  - Windows Firewall (back to defaults)
  - DNS cache and DNS servers (back to automatic/DHCP)
  - Core network services (DNS/DHCP/WLAN/NLA/Netman) to automatic + started

A REBOOT IS REQUIRED afterwards.

Usage: net_reset.bat   (requests admin rights automatically)
#>
$ErrorActionPreference = 'Continue'

function Show-Info {
    Write-Host ""
    Write-Host "=== CURRENT STATE (for the report) ===" -ForegroundColor Cyan

    Write-Host "--- Proxy (WinHTTP) ---"
    netsh winhttp show proxy

    Write-Host "--- Proxy (user, registry) ---"
    $pe = (Get-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' -Name ProxyEnable -ErrorAction SilentlyContinue).ProxyEnable
    $ps = (Get-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' -Name ProxyServer -ErrorAction SilentlyContinue).ProxyServer
    Write-Host "ProxyEnable = $pe ; ProxyServer = $ps"

    Write-Host "--- DNS servers ---"
    Get-DnsClientServerAddress -AddressFamily IPv4 | Where-Object { $_.ServerAddresses } | ForEach-Object {
        Write-Host ("  {0}: {1}" -f $_.InterfaceAlias, ($_.ServerAddresses -join ", "))
    }

    Write-Host "--- MTU (non-1500 is a tweaker sign) ---"
    netsh interface ipv4 show subinterfaces

    Write-Host "--- IPv6 DisabledComponents (0 = default) ---"
    $dc = (Get-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip6\Parameters' -Name DisabledComponents -ErrorAction SilentlyContinue).DisabledComponents
    Write-Host "DisabledComponents = $dc"

    Write-Host "--- hosts file (non-comment lines) ---"
    $hosts = Get-Content "$env:SystemRoot\System32\drivers\etc\hosts" -ErrorAction SilentlyContinue | Where-Object { $_ -and -not $_.StartsWith('#') }
    if ($hosts) { $hosts | Select-Object -First 20 | ForEach-Object { Write-Host "  $_" } } else { Write-Host "  (empty)" }
}

function Reset-Network {
    Write-Host ""
    Write-Host "[1/9] DNS cache flush..."
    ipconfig /flushdns | Out-Null

    Write-Host "[2/9] Winsock catalog reset..."
    netsh winsock reset | Out-Null

    Write-Host "[3/9] TCP/IP stack reset (v4 + v6)..."
    netsh int ip reset | Out-Null

    Write-Host "[4/9] TCP global parameters reset..."
    netsh int tcp reset | Out-Null

    Write-Host "[5/9] WinHTTP proxy reset..."
    netsh winhttp reset proxy | Out-Null

    Write-Host "[6/9] User proxy off (registry)..."
    reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyEnable /t REG_DWORD /d 0 /f | Out-Null
    reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyServer /f 2>$null | Out-Null

    Write-Host "[7/9] Windows Firewall reset (back to defaults)..."
    netsh advfirewall reset | Out-Null

    Write-Host "[8/9] Core network services -> automatic + started..."
    foreach ($svc in @('Dnscache', 'Dhcp', 'WlanSvc', 'NlaSvc', 'Netman', 'netprofm', 'iphlpsvc')) {
        sc.exe config $svc start= auto | Out-Null
        sc.exe start $svc | Out-Null
    }

    Write-Host "[9/9] DNS servers -> automatic (DHCP) for active adapters..."
    $ifaces = Get-NetAdapter | Where-Object { $_.Status -eq 'Up' } | Select-Object -ExpandProperty Name
    foreach ($i in $ifaces) {
        netsh interface ip set dns name="$i" source=dhcp | Out-Null
        netsh interface ipv6 set dns name="$i" source=dhcp | Out-Null
    }
}

Write-Host ""
Write-Host "=== net_reset ===" -ForegroundColor Cyan
Write-Host "This will reset the network stack to defaults:"
Write-Host "  Winsock, TCP/IP (v4/v6), TCP params, proxies, firewall,"
Write-Host "  DNS cache/servers, core network services."
Write-Host "A REBOOT IS REQUIRED afterwards." -ForegroundColor Yellow
Write-Host ""

$ans = Read-Host "Continue? (Y/N)"
if ($ans -notmatch '^[Yy]') { Write-Host "Cancelled."; exit 0 }

Show-Info
Reset-Network

Write-Host ""
Write-Host "=== DONE ===" -ForegroundColor Green
Write-Host "REBOOT NOW to apply the changes." -ForegroundColor Yellow
Write-Host ""
Write-Host "After reboot, run game_probe again and send the log."
