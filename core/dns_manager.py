"""Быстрая смена системного DNS: два профиля, primary/secondary.

Задача: диагностика показывает DNS, но пользователю приходилось менять
серверы вручную в Windows. Здесь — явное действие из GUI: применить
Основной/Резервный профиль или вернуть исходный DNS. Ничего не меняется
автоматически; перед изменением сохраняется исходное состояние адаптера.

Профили — это просто два IP-адреса на каждый профиль. Провайдеры можно
смешивать (например, 1.1.1.1 + 8.8.8.8). DoH в браузере этим не управляется.
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
_PS_QUERY = _PS_HEAD + r"""
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
  $dhcp = $true
  if ($wmi -and $wmi.DNSServerSearchOrder -and @($wmi.DNSServerSearchOrder).Count -gt 0) {
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


def _ps_run(script: str, timeout: float = 20.0) -> dict:
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise DnsError(f"PowerShell недоступен: {type(e).__name__}") from e
    out = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()
    # JSON — последняя строка; stderr может содержать предупреждения.
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    if not lines:
        raise DnsError("PowerShell не вернул результат")
    try:
        data = json.loads(lines[-1])
    except (ValueError, TypeError):
        raise DnsError(f"Некорректный ответ PowerShell: {out[:300]}") from None
    if not isinstance(data, dict):
        raise DnsError("Некорректный ответ PowerShell")
    if not data.get("ok"):
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


def _write_backup(root_dir: Path, state: dict) -> None:
    p = _backup_path(root_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    payload = {
        "adapter": state.get("adapter", ""),
        "interface_index": state.get("interface_index"),
        "dhcp": bool(state.get("dhcp", True)),
        "servers": list(state.get("servers") or []),
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


def current_status() -> dict:
    data = _ps_run(_PS_QUERY)
    v4 = [str(x) for x in (data.get("v4") or []) if x]
    v6 = [str(x) for x in (data.get("v6") or []) if x]
    servers = v4 + v6
    return {
        "ok": True,
        "adapter": str(data.get("adapter") or ""),
        "description": str(data.get("description") or ""),
        "interface_index": int(data.get("interface_index") or 0),
        "v4": v4,
        "v6": v6,
        "servers": servers,
        "dhcp": bool(data.get("dhcp", True)),
    }


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
            got = {str(ipaddress.ip_address(x)) for x in after.get("servers") or []}
            want = {str(ipaddress.ip_address(x)) for x in servers}
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
        servers = normalize_servers(
            (backup.get("servers") or [""])[0],
            (backup.get("servers") or ["", ""])[1] if len(backup.get("servers") or []) > 1 else "",
        )
        _ps_run(_apply_script(idx, servers))
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
