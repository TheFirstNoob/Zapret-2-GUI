"""Быстрая смена системного DNS: два профиля, primary/secondary.

Задача: диагностика показывает DNS, но пользователю приходилось менять
серверы вручную в Windows. Здесь — явное действие из GUI: применить
Основной/Резервный профиль или вернуть исходный DNS. Ничего не меняется
автоматически; перед изменением сохраняется исходное состояние адаптера.

Профили — это просто два IP-адреса на каждый профиль. Провайдеры можно
смешивать (например, 1.1.1.1 + 8.8.8.8). DoH в браузере этим не управляется.

Скорость (аудит 2026-11-14, T21): состояние читается ОДНИМ PowerShell-запросом
с быстрым выбором адаптера через .NET NetworkInterface (~0.5 c) вместо
Get-NetIPConfiguration (3.2-3.7 c). Если быстрый путь не отработал -
используется прежний запрос (fallback), функция не теряется.
"""
from __future__ import annotations

import ipaddress
import json
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from core.applog import log as applog

_PS_HEAD = (
    "$ErrorActionPreference='Stop';"
    "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;"
)
# Состояние активного адаптера собирается PS-функцией: выбор адаптера через
# .NET NetworkInterface (~0.5 c) вместо Get-NetIPConfiguration (3.2-3.7 c на
# Win10/11 - замер 2026-11-14). Если .NET-путь не дал interface_index, внутри
# скрипта выполняется прежний выбор через Get-NetIPConfiguration - поведение
# не меняется ни на одной конфигурации.
_PS_STATE_FUNC = r"""
function Get-Z2DnsState {
  $idx = 0
  $adapter_name = ''
  $adapter_desc = ''
  $guid = ''
  try {
    $nics = @([System.Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces() |
      Where-Object {
        $_.OperationalStatus -eq 'Up' -and
        $_.NetworkInterfaceType -ne 'Loopback' -and
        (@($_.GetIPProperties().UnicastAddresses).Count -gt 0)
      })
    $with_gw = New-Object System.Collections.ArrayList
    foreach ($n in $nics) {
      $has_gw = $false
      try { $has_gw = (@($n.GetIPProperties().GatewayAddresses).Count -gt 0) }
      catch { $has_gw = $false }
      if ($has_gw) { [void]$with_gw.Add($n) }
    }
    $pick = $null
    if ($with_gw.Count -gt 0) { $pick = $with_gw[0] }
    elseif ($nics.Count -gt 0) { $pick = $nics[0] }
    if ($pick) {
      try {
        $p4 = $pick.GetIPProperties().GetIPv4Properties()
        if ($p4) { $idx = [int]$p4.Index }
      } catch { }
      if ($idx -le 0) {
        try {
          $p6 = $pick.GetIPProperties().GetIPv6Properties()
          if ($p6) { $idx = [int]$p6.Index }
        } catch { }
      }
      if ($idx -gt 0) {
        $adapter_name = [string]$pick.Name
        $adapter_desc = [string]$pick.Description
        $guid = [string]$pick.Id
      }
    }
  } catch { $idx = 0 }
  # Fallback: прежний выбор адаптера (Get-NetIPConfiguration).
  if ($idx -le 0) {
    $cfg = @(Get-NetIPConfiguration | Where-Object {
      $_.NetAdapter.Status -eq 'Up' -and
      ($null -ne $_.IPv4DefaultGateway -or $null -ne $_.IPv6DefaultGateway)
    }) | Select-Object -First 1
    if (-not $cfg) {
      $cfg = @(Get-NetIPConfiguration | Where-Object { $_.NetAdapter.Status -eq 'Up' }) |
             Select-Object -First 1
    }
    if (-not $cfg) {
      return [pscustomobject]@{ok=$false; error='Нет активного сетевого адаптера'}
    }
    $ad = $cfg.NetAdapter
    $idx = [int]$ad.ifIndex
    $adapter_name = [string]$ad.Name
    $adapter_desc = [string]$ad.InterfaceDescription
    $guid = [string]$ad.InterfaceGuid
  }
  # DNS-адреса: ОДИН вызов Get-DnsClientServerAddress на все семейства
  # (0.7 c) вместо двух вызовов по AddressFamily.
  $dns = @(Get-DnsClientServerAddress -ErrorAction SilentlyContinue |
           Where-Object { [int]$_.InterfaceIndex -eq $idx })
  $v4 = New-Object System.Collections.ArrayList
  $v6 = New-Object System.Collections.ArrayList
  foreach ($item in $dns) {
    foreach ($a in @($item.ServerAddresses)) {
      if (-not $a) { continue }
      $s = [string]$a
      if ($s.Contains(':')) {
        if (-not $v6.Contains($s)) { [void]$v6.Add($s) }
      } else {
        if (-not $v4.Contains($s)) { [void]$v4.Add($s) }
      }
    }
  }
  # DNSServerSearchOrder заполнен и для DHCP (Windows отдаёт выданные
  # серверы), поэтому по нему нельзя отличить DHCP от ручного DNS.
  # Надёжный признак статического DNS - NameServer в ветке интерфейса
  # Tcpip\Parameters\Interfaces (IPv4) / Tcpip6\Parameters\Interfaces (IPv6);
  # DhcpNameServer остаётся у DHCP. Флаги нужны по СЕМЕЙСТВАМ: статический
  # IPv4 + полученный по DHCP IPv6 - нормальная конфигурация, и reset не
  # должен превращать DHCP-адреса в статические.
  $reg = $null
  $reg6 = $null
  if ($guid) {
    $reg = Get-ItemProperty ("HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces\" + $guid) -ErrorAction SilentlyContinue
    $reg6 = Get-ItemProperty ("HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip6\Parameters\Interfaces\" + $guid) -ErrorAction SilentlyContinue
  }
  $static_dns = if ($reg) { [string]$reg.NameServer } else { "" }
  $static6_dns = if ($reg6) { [string]$reg6.NameServer } else { "" }
  $dhcp_dns = if ($reg) { [string]$reg.DhcpNameServer } else { "" }
  $static4 = [bool]($static_dns -and $static_dns.Trim())
  $static6 = [bool]($static6_dns -and $static6_dns.Trim())
  $dhcp = -not ($static4 -or $static6)
  if (-not $reg -and -not $reg6) {
    # Реестр недоступен: не считаем текущий DNS DHCP, чтобы reset случайно
    # не затёр ручные настройки. Лучше оставить статический backup.
    $wmi = Get-CimInstance Win32_NetworkAdapterConfiguration -Filter "InterfaceIndex=$idx" -ErrorAction SilentlyContinue
    if ($wmi -and $wmi.DNSServerSearchOrder -and
        @($wmi.DNSServerSearchOrder).Count -gt 0) {
      $dhcp = $false
    }
  }
  return [pscustomobject]@{
    ok = $true
    adapter = $adapter_name
    description = $adapter_desc
    interface_index = [int]$idx
    v4 = @($v4)
    v6 = @($v6)
    dhcp = [bool]$dhcp
    static4 = $static4
    static6 = $static6
    static_dns = $static_dns
    dhcp_dns = $dhcp_dns
  }
}
"""

_PS_QUERY = _PS_HEAD + _PS_STATE_FUNC + r"""
try {
  Get-Z2DnsState | ConvertTo-Json -Compress -Depth 4
} catch {
  [pscustomobject]@{ok=$false; error=[string]$_.Exception.Message} |
    ConvertTo-Json -Compress
  exit 1
}
"""

# Прежний запрос состояния: медленный Get-NetIPConfiguration + два вызова
# Get-DnsClientServerAddress. Оставлен как fallback быстрого пути (старый
# .NET/усечённый PowerShell) - поля и семантика ответа те же.
_PS_QUERY_LEGACY = _PS_HEAD + r"""
try {
  $cfg = @(Get-NetIPConfiguration | Where-Object {
    $_.NetAdapter.Status -eq 'Up' -and
    ($null -ne $_.IPv4DefaultGateway -or $null -ne $_.IPv6DefaultGateway)
  }) | Select-Object -First 1
  if (-not $cfg) {
    $cfg = @(Get-NetIPConfiguration | Where-Object { $_.NetAdapter.Status -eq 'Up' }) |
           Select-Object -First 1
  }
  if (-not $cfg) {
    [pscustomobject]@{ok=$false; error='Нет активного сетевого адаптера'} |
      ConvertTo-Json -Compress
    exit 2
  }
  $ad = $cfg.NetAdapter
  $idx = [int]$ad.ifIndex
  $v4 = @(Get-DnsClientServerAddress -InterfaceIndex $idx -AddressFamily IPv4 `
          -ErrorAction SilentlyContinue | ForEach-Object { @($_.ServerAddresses) } |
          Where-Object { $_ })
  $v6 = @(Get-DnsClientServerAddress -InterfaceIndex $idx -AddressFamily IPv6 `
          -ErrorAction SilentlyContinue | ForEach-Object { @($_.ServerAddresses) } |
          Where-Object { $_ })
  $wmi = Get-CimInstance Win32_NetworkAdapterConfiguration `
         -Filter "InterfaceIndex=$idx" -ErrorAction SilentlyContinue
  # DNSServerSearchOrder заполнен и для DHCP (Windows отдаёт выданные
  # серверы), поэтому по нему нельзя отличить DHCP от ручного DNS.
  # Надёжный признак статического DNS — NameServer в ветке интерфейса
  # Tcpip\Parameters\Interfaces; DhcpNameServer остаётся у DHCP.
  $reg = Get-ItemProperty `
         ("HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces\" +
          [string]$ad.InterfaceGuid) -ErrorAction SilentlyContinue
  $static_dns = if ($reg) { [string]$reg.NameServer } else { "" }
  $dhcp_dns = if ($reg) { [string]$reg.DhcpNameServer } else { "" }
  $dhcp = $true
  if ($reg) {
    $dhcp = -not ($static_dns -and $static_dns.Trim())
  } elseif ($wmi -and $wmi.DNSServerSearchOrder -and
            @($wmi.DNSServerSearchOrder).Count -gt 0) {
    # Реестр недоступен: не считаем текущий DNS DHCP, чтобы reset случайно
    # не затёр ручные настройки. Лучше оставить статический backup.
    $dhcp = $false
  }
  [pscustomobject]@{
    ok = $true
    adapter = [string]$ad.Name
    description = [string]$ad.InterfaceDescription
    interface_index = $idx
    v4 = @($v4)
    v6 = @($v6)
    dhcp = [bool]$dhcp
    static_dns = $static_dns
    dhcp_dns = $dhcp_dns
  } | ConvertTo-Json -Compress -Depth 4
} catch {
  [pscustomobject]@{ok=$false; error=[string]$_.Exception.Message} |
    ConvertTo-Json -Compress
  exit 1
}
"""

_PS_SET = _PS_HEAD + r"""
try {
  $servers = @({servers})
  Set-DnsClientServerAddress -InterfaceIndex {idx} -ServerAddresses $servers `
    -ErrorAction Stop
  Clear-DnsClientCache -ErrorAction SilentlyContinue
  [pscustomobject]@{ok=$true} | ConvertTo-Json -Compress
} catch {
  [pscustomobject]@{ok=$false; error=[string]$_.Exception.Message} |
    ConvertTo-Json -Compress
  exit 1
}
"""

_PS_RESET = _PS_HEAD + r"""
try {
  Set-DnsClientServerAddress -InterfaceIndex {idx} -ResetServerAddresses `
    -ErrorAction Stop
  Clear-DnsClientCache -ErrorAction SilentlyContinue
  [pscustomobject]@{ok=$true} | ConvertTo-Json -Compress
} catch {
  [pscustomobject]@{ok=$false; error=[string]$_.Exception.Message} |
    ConvertTo-Json -Compress
  exit 1
}
"""

_LOCK = threading.Lock()
_MAX_SERVERS = 2


class DnsError(RuntimeError):
    """Ошибка смены DNS с сообщением для UI."""


def _parse_ps_json(out: str) -> dict:
    """Последняя валидная JSON-строка вывода PowerShell.

    Раньше бралась буквально последняя строка: служебное предупреждение в
    stderr после JSON ломало разбор ("Некорректный ответ PowerShell" при
    успешно изменённом DNS). Идём с конца и берём первый разобранный объект.
    """
    for line in reversed([ln.strip() for ln in out.splitlines() if ln.strip()]):
        try:
            data = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(data, dict):
            return data
    raise DnsError(f"Некорректный ответ PowerShell: {out[:300]}")


def _ps_run(script: str, timeout: float = 20.0,
            require_ok: bool = True) -> dict:
    """Выполнить PS-скрипт и разобрать JSON-ответ.

    require_ok=False - вернуть ответ даже с ok=false (нужно для запроса
    состояния: "нет активного адаптера" - штатный ответ, а не повод для
    fallback на медленный запрос)."""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise DnsError(f"PowerShell недоступен: {type(e).__name__}") from e
    out = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()
    if not out:
        raise DnsError("PowerShell не вернул результат")
    data = _parse_ps_json(out)
    if require_ok and not data.get("ok"):
        raise DnsError(str(data.get("error") or "не удалось изменить DNS"))
    return data


def normalize_servers(primary: str, secondary: str = "") -> list[str]:
    """Проверить 1-2 адреса; вернуть канонические строки без дублей."""
    raw = [str(primary or "").strip(), str(secondary or "").strip()]
    values: list[str] = []
    for value in raw:
        if not value:
            continue
        try:
            ip = ipaddress.ip_address(value)
        except ValueError as e:
            raise DnsError(f"Некорректный DNS-сервер: {value}") from e
        canonical = str(ip)
        if canonical not in values:
            values.append(canonical)
    if not values:
        raise DnsError("Укажите основной DNS-сервер")
    if len(values) > _MAX_SERVERS:
        raise DnsError("Можно указать не больше двух DNS-серверов")
    return values


def profile_servers(cfg, profile: str) -> list[str]:
    if profile == "main":
        return normalize_servers(cfg.dns_main_primary, cfg.dns_main_secondary)
    if profile == "reserve":
        return normalize_servers(cfg.dns_reserve_primary,
                                 cfg.dns_reserve_secondary)
    raise DnsError("Неизвестный DNS-профиль")


def profiles_payload(cfg) -> dict:
    out = {}
    for key, p1, p2 in (
        ("main", cfg.dns_main_primary, cfg.dns_main_secondary),
        ("reserve", cfg.dns_reserve_primary, cfg.dns_reserve_secondary),
    ):
        try:
            servers = normalize_servers(p1, p2)
        except DnsError:
            servers = []
        out[key] = {
            "primary": str(p1 or ""),
            "secondary": str(p2 or ""),
            "servers": servers,
        }
    return out


def _backup_path(root_dir: Path) -> Path:
    return Path(root_dir) / "logs" / "dns_backup.json"


def _read_backup(root_dir: Path) -> dict | None:
    p = _backup_path(root_dir)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def _as_str_list(value: object) -> list[str]:
    """Непустые строки из значения PowerShell-ответа (не list -> пусто)."""
    if not isinstance(value, (list, tuple)):
        return []
    return [str(x).strip() for x in value if str(x).strip()]


def _canonical_servers(values: Iterable[object], family: int) -> list[str]:
    """Канонические адреса ОДНОГО семейства без дублей; мусор - пропуск.

    Восстановление обязано вернуть ВСЕ адреса (аудит 2026-11-14: reset терял
    3-й и последующие DNS - normalize_servers режет список до двух).
    """
    out: list[str] = []
    for raw in values:
        try:
            ip = ipaddress.ip_address(str(raw).strip())
        except ValueError:
            continue
        if ip.version != family:
            continue
        canonical = str(ip)
        if canonical not in out:
            out.append(canonical)
    return out


def _static_families(data: dict) -> dict[str, bool]:
    """Какие семейства в исходном состоянии были СТАТИЧЕСКИМИ.

    Нет данных (старый backup/состояние) - считаем статическими все семейства:
    так адреса не теряются (поведение прежней версии).
    """
    raw = data.get("static")
    if isinstance(raw, dict):
        return {"v4": bool(raw.get("v4")), "v6": bool(raw.get("v6"))}
    if "static4" in data or "static6" in data:
        return {"v4": bool(data.get("static4")), "v6": bool(data.get("static6"))}
    return {"v4": True, "v6": True}


def _families(data: dict) -> tuple[list[str], list[str]]:
    """Адреса состояния/бэкапа по семействам: (v4, v6).

    Формат v2 хранит v4/v6 раздельно; старый v1 хранил один общий список
    servers - раскладываем по виду адреса (миграция без потерь).
    """
    raw4 = data.get("v4")
    raw6 = data.get("v6")
    if isinstance(raw4, list) or isinstance(raw6, list):
        return (_canonical_servers(raw4 if isinstance(raw4, list) else [], 4),
                _canonical_servers(raw6 if isinstance(raw6, list) else [], 6))
    servers = data.get("servers")
    if not isinstance(servers, list):
        return [], []
    return _canonical_servers(servers, 4), _canonical_servers(servers, 6)


def _write_backup(root_dir: Path, state: dict) -> None:
    v4, v6 = _families(state)
    static = _static_families(state)
    if not state.get("dhcp", True) and not (static["v4"] or static["v6"]):
        # dhcp=False, но семейства неизвестны (реестр недоступен, статику
        # подтвердил только WMI-fallback): консервативно считаем сохранённые
        # адреса статическими, иначе reset не восстановит ничего.
        static = {"v4": True, "v6": True}
    p = _backup_path(root_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    payload = {
        "version": 2,
        "adapter": state.get("adapter", ""),
        "interface_index": state.get("interface_index"),
        "dhcp": bool(state.get("dhcp", True)),
        "v4": v4,
        "v6": v6,
        # Какие семейства были статическими: DHCP-семейство при reset не
        # трогаем, иначе адреса из DHCPv6 закреплялись бы статикой.
        "static": static,
        # Общий список оставлен для совместимости: прежняя версия читает
        # только его и не потеряет DNS при откате на 0.10.
        "servers": v4 + v6,
        "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(p)


def _drop_backup(root_dir: Path) -> None:
    try:
        _backup_path(root_dir).unlink(missing_ok=True)
    except OSError:
        pass


def has_backup(root_dir: Path) -> bool:
    """Есть ли сохранённый исходный DNS для безопасного reset."""
    return _read_backup(Path(root_dir)) is not None


def _status_from_data(data: dict) -> dict:
    """Ответ PowerShell -> публичное состояние для API/UI (не бросает)."""
    v4 = _as_str_list(data.get("v4"))
    v6 = _as_str_list(data.get("v6"))
    try:
        interface_index = int(data.get("interface_index") or 0)
    except (TypeError, ValueError):
        interface_index = 0
    static4 = data.get("static4")
    if static4 is None:
        # Прежний запрос (fallback) отдаёт только static_dns по IPv4.
        static4 = bool(str(data.get("static_dns") or "").strip())
    return {
        "ok": True,
        "adapter": str(data.get("adapter") or ""),
        "description": str(data.get("description") or ""),
        "interface_index": interface_index,
        "v4": v4,
        "v6": v6,
        "servers": v4 + v6,
        "dhcp": bool(data.get("dhcp", True)),
        "static4": bool(static4),
        "static6": bool(data.get("static6", False)),
    }


def current_status() -> dict:
    """Текущий DNS активного адаптера: быстрый запрос + fallback прежним."""
    try:
        # require_ok=False: ответ "нет активного адаптера" штатный - отдаём
        # его без медленного fallback (иначе каждая страница DNS на машине
        # без сети стоила бы fast+legacy подряд).
        data = _ps_run(_PS_QUERY, require_ok=False)
    except DnsError as e:
        # Быстрый путь не отработал (нет .NET/CIM, усечённый PowerShell):
        # функция не должна пропадать целиком - повторяем прежним запросом.
        applog("dns", f"быстрый запрос состояния DNS не удался ({e}); "
                      f"fallback на прежний запрос")
        data = _ps_run(_PS_QUERY_LEGACY, require_ok=False)
    if not data.get("ok"):
        raise DnsError(str(data.get("error")
                           or "Нет активного сетевого адаптера"))
    return _status_from_data(data)


def active_profile(cfg, status: dict) -> str:
    current: set[str] = set()
    for value in (status.get("servers") or []):
        if not value:
            continue
        try:
            current.add(str(ipaddress.ip_address(value)))
        except ValueError:
            return "custom"
    if not current:
        return "system"
    for name in ("main", "reserve"):
        try:
            servers = {str(ipaddress.ip_address(x)) for x in profile_servers(cfg, name)}
        except DnsError:
            continue
        if servers == current:
            return name
    return "custom"


def _apply_script(idx: int, servers: Iterable[str]) -> str:
    arr = ",".join("'" + s.replace("'", "") + "'" for s in servers)
    return _PS_SET.replace("{servers}", arr).replace("{idx}", str(int(idx)))


def _reset_script(idx: int) -> str:
    return _PS_RESET.replace("{idx}", str(int(idx)))


def apply_profile(root_dir: Path, cfg, profile: str) -> dict:
    servers = profile_servers(cfg, profile)
    with _LOCK:
        before = current_status()
        if not before.get("ok"):
            raise DnsError("Нет активного сетевого адаптера")
        idx = int(before["interface_index"])
        backup = _read_backup(root_dir)
        # Не перезаписываем исходный backup повторным применением профиля.
        if not backup or backup.get("interface_index") != idx:
            _write_backup(root_dir, before)
        try:
            _ps_run(_apply_script(idx, servers))
            after = current_status()
            want = {str(ipaddress.ip_address(x)) for x in servers}
            # Сравниваем ТОЛЬКО семейства профиля (аудит 2026-11-14, P1):
            # IPv4-профиль + оставшийся IPv6 DNS на адаптере давали ложное
            # "Windows не применил DNS" и откат, профиль навсегда "custom".
            want_versions = {ipaddress.ip_address(x).version for x in want}
            got = {str(ipaddress.ip_address(x)) for x in after.get("servers") or []
                   if ipaddress.ip_address(x).version in want_versions}
            if got != want:
                raise DnsError("Windows не применил DNS (проверьте права администратора)")
        except Exception:
            # Пытаемся вернуть исходное состояние, чтобы не оставить без DNS.
            try:
                _restore(root_dir, before, backup or before)
            except Exception:
                pass
            raise
        applog("dns", f"apply {profile}: adapter={before.get('adapter')} "
                      f"index={idx} servers={servers}")
        return after


def _restore(root_dir: Path, current: dict, backup: dict) -> dict:
    idx = int(current.get("interface_index") or backup.get("interface_index") or 0)
    if not idx:
        raise DnsError("Нет активного сетевого адаптера")
    if backup.get("dhcp", True):
        _ps_run(_reset_script(idx))
    else:
        v4, v6 = _families(backup)
        static = _static_families(backup)
        # Возвращаем ВСЕ адреса (аудит 2026-11-14): раньше reset применял
        # только первые два и молча терял остальные. Отдельный Set-вызов на
        # семейство: команда не трогает семейства, которые не заданы
        # (документация Set-DnsClientServerAddress). Семейство, которое было
        # на DHCP, не трогаем: иначе DHCPv6-адреса закрепились бы статикой
        # (сброс к DHCP без семейства невозможен).
        applied = 0
        for family, servers in (("v4", v4), ("v6", v6)):
            if servers and static.get(family, True):
                _ps_run(_apply_script(idx, servers))
                applied += 1
        if not applied:
            raise DnsError("В сохранённом DNS нет статических адресов "
                           "для восстановления")
    return current_status()


def reset(root_dir: Path) -> dict:
    with _LOCK:
        before = current_status()
        backup = _read_backup(root_dir)
        if not backup:
            raise DnsError("Нет сохранённого исходного DNS: сначала примените профиль")
        saved_idx = int(backup.get("interface_index") or 0)
        current_idx = int(before.get("interface_index") or 0)
        if saved_idx and current_idx and saved_idx != current_idx:
            raise DnsError("Сохранённый DNS относится к другому сетевому адаптеру; "
                           "верните его вручную")
        result = _restore(root_dir, before, backup)
        _drop_backup(root_dir)
        applog("dns", f"reset: adapter={before.get('adapter')} "
                      f"backup_dhcp={backup.get('dhcp')}")
        return result
