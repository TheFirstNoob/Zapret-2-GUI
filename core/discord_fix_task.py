"""Автозапуск Discord/Cloudflare helper через Планировщик задач Windows.

Почему не Windows-служба: путь к python/exe и аргументы в ImagePath -
историческая боль (пробелы/кириллица/portable/EXE/обновления). Задача
Планировщика запускает ТОТ ЖЕ файл, что и GUI, с аргументом
--discord-fix-helper; путь не дублируется в реестре служб.
"""
from __future__ import annotations

import subprocess
import sys
import xml.sax.saxutils as sax
from pathlib import Path
from typing import Optional

from core.applog import log as applog

TASK_NAME = "Zapret2GUI DiscordFix"
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _run(args: list[str], timeout: float = 25.0) -> tuple[int, str]:
    try:
        r = subprocess.run(["schtasks.exe"] + args, capture_output=True,
                           text=True, encoding="oem", errors="replace",
                           timeout=timeout, creationflags=_CREATE_NO_WINDOW)
        return int(r.returncode), ((r.stdout or "") + "\n" + (r.stderr or "")).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, f"{type(e).__name__}: {e}"


def action(root: Path) -> tuple[str, str]:
    root = Path(root)
    if getattr(sys, "frozen", False):
        return str(Path(sys.executable).resolve()), "--discord-fix-helper"
    main = root / "main.pyw"
    if not main.is_file():
        main = root / "main.py"
    return str(Path(sys.executable).resolve()), f'"{main.resolve()}" --discord-fix-helper'


def _xml(root: Path) -> str:
    exe, args = action(root)
    exe_x = sax.escape(exe, {'"': "&quot;"})
    args_x = sax.escape(args, {'"': "&quot;"})
    return f'''<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Zapret 2 GUI: Discord/Cloudflare helper (temporary)</Description>
  </RegistrationInfo>
  <Triggers>
    <BootTrigger>
      <Enabled>true</Enabled>
      <Delay>PT15S</Delay>
    </BootTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>S-1-5-18</UserId>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>true</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{exe_x}</Command>
      <Arguments>{args_x}</Arguments>
    </Exec>
  </Actions>
</Task>
'''


def install(root: Path) -> tuple[bool, str]:
    root = Path(root)
    xml = _xml(root)
    p = root / "logs" / "discord_fix_task.xml"
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        p.write_text(xml, encoding="utf-16")
    except OSError as e:
        return False, f"write xml: {e}"
    # /F пересоздаёт задачу; на старых системах XML-путь с пробелами
    # передаём отдельным аргументом (subprocess квотирует).
    rc, out = _run(["/Create", "/TN", TASK_NAME, "/XML", str(p), "/F"])
    if rc != 0:
        return False, out[:500]
    return True, ""


def installed() -> bool:
    rc, _ = _run(["/Query", "/TN", TASK_NAME], timeout=15)
    return rc == 0


def state() -> str:
    rc, out = _run(["/Query", "/TN", TASK_NAME, "/FO", "LIST"], timeout=15)
    if rc != 0:
        return "not_installed"
    low = out.lower()
    # Локализованный вывод: ищем оба варианта.
    if "running" in low or "выполняется" in low or "работает" in low:
        return "running"
    if "ready" in low or "готово" in low:
        return "ready"
    if "disabled" in low or "отключ" in low:
        return "disabled"
    if "queued" in low or "ожидан" in low:
        return "queued"
    return "unknown"


def start() -> tuple[bool, str]:
    if not installed():
        return False, "not installed"
    rc, out = _run(["/Run", "/TN", TASK_NAME], timeout=25)
    if rc != 0:
        return False, out[:400]
    return True, ""


def stop() -> tuple[bool, str]:
    if not installed():
        return True, "not installed"
    rc, out = _run(["/End", "/TN", TASK_NAME], timeout=25)
    if rc != 0:
        # 267011/267009 = not running / no instance - не ошибка
        if any(x in out for x in ("267011", "267009", "not running")):
            return True, ""
        return False, out[:400]
    return True, ""


def remove() -> tuple[bool, str]:
    stop()
    if not installed():
        return True, "not installed"
    rc, out = _run(["/Delete", "/TN", TASK_NAME, "/F"], timeout=20)
    if rc != 0:
        return False, out[:400]
    return True, ""
