from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from core.launcher import build_args_from_preset, write_run_bat, launch_winws2_bat, validate_args



@dataclass
class ZapretStatus:
    running: bool = False
    pid: Optional[int] = None
    strategy: Optional[str] = None


class ZapretController:
    def __init__(self, root_dir: Path, config_manager=None) -> None:
        self.root_dir = Path(root_dir)
        self.bin_dir = self.root_dir / "bin"
        self.lua_dir = self.root_dir / "lua"
        self.blobs_dir = self.root_dir / "blobs"
        self.lists_dir = self.root_dir / "lists"
        self.current_strategy: Optional[str] = None
        self._winws2_path: Optional[Path] = None
        self._config_manager = config_manager
        self._cached_pid: Optional[int] = None
        self._cached_pid_at: float = 0.0
        # Восстанавливаем last_profile из config
        if self._config_manager is not None:
            cfg = self._config_manager.load()
            if getattr(cfg, "last_profile", ""):
                self.current_strategy = cfg.last_profile

    @property
    def winws2_path(self) -> Optional[Path]:
        if self._winws2_path and self._winws2_path.exists():
            return self._winws2_path
        candidates = [
            self.bin_dir / "winws2.exe",
            self.root_dir / "winws2.exe",
        ]
        for p in candidates:
            if p.exists():
                self._winws2_path = p
                return p
        return None

    def start(self, profile: str, game_filter_mode: str = "off", discord_voice: bool = False, winws2_debug: bool = False, autohostlist: bool = False, ipset_catchall: bool = False) -> tuple[bool, str]:
        if not isinstance(profile, str):
            return False, "Profile must be a preset name string"

        exe_path = self.winws2_path
        if exe_path is None:
            return False, "winws2.exe не найден"

        preset = self.root_dir / "presets" / f"{profile}.txt"
        if not preset.exists():
            return False, f"Пресет '{profile}.txt' не найден"

        args = build_args_from_preset(
            self.root_dir, self.lua_dir, self.blobs_dir, preset,
            debug=winws2_debug,
            game_filter_mode=game_filter_mode,
            discord_voice=discord_voice,
            autohostlist=autohostlist,
            ipset_catchall=ipset_catchall,
        )

        # Validate BEFORE stopping the running instance: a failed check must
        # not leave the user unprotected.
        ok, err = validate_args(exe_path, args, cwd=self.root_dir)
        if not ok:
            return False, err

        self.stop()

        from core.tcp_timestamps import enable_for_engine
        ts_ok, ts_note = enable_for_engine()

        bat = self.root_dir / "_zapret_run.bat"
        write_run_bat(self.root_dir, bat, exe_path, args)

        ok = launch_winws2_bat(bat, self.root_dir, timeout=5.0)
        if not ok:
            return False, "winws2.exe не удалось запустить (проверьте права администратора)"

        self.current_strategy = profile
        return True, "Запущен" + (f" ({ts_note})" if ts_note else "")

    def stop(self) -> bool:
        pid = self.get_running_pid(force=True)
        if pid is not None:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(pid)],
                    capture_output=True, timeout=5,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                self.current_strategy = None
                return True
            except (subprocess.TimeoutExpired, OSError):
                pass

        return False

    def restart(self, profile: Optional[str] = None) -> bool:
        self.stop()
        time.sleep(0.5)
        if profile is not None:
            ok, _ = self.start(profile)
            return ok
        if self.current_strategy is not None:
            ok, _ = self.start(self.current_strategy)
            return ok
        return False

    def status(self) -> ZapretStatus:
        result = ZapretStatus()
        pid = self.get_running_pid()
        if pid is not None:
            result.running = True
            result.pid = pid
            result.strategy = self.current_strategy
        return result

    def is_running(self) -> bool:
        return self.get_running_pid() is not None

    def get_running_pid(self, force: bool = False) -> Optional[int]:
        now = time.time()
        if not force and self._cached_pid is not None and (now - self._cached_pid_at) < 1.0:
            return self._cached_pid
        try:
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq winws2.exe", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=5,
                encoding="oem", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            for line in result.stdout.strip().splitlines():
                if not line:
                    continue
                parts = line.split(",")
                if len(parts) >= 2 and "winws2.exe" in parts[0]:
                    pid_str = parts[1].strip('"')
                    try:
                        self._cached_pid = int(pid_str)
                        self._cached_pid_at = now
                        return self._cached_pid
                    except ValueError:
                        pass
        except (subprocess.TimeoutExpired, OSError):
            pass
        self._cached_pid = None
        self._cached_pid_at = now
        return None

    @staticmethod
    def stop_all_instances() -> None:
        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", "winws2.exe"],
                capture_output=True, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except (subprocess.TimeoutExpired, OSError):
            pass
