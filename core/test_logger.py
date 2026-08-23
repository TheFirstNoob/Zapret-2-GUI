from __future__ import annotations

import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.config import VERSION


class TestLogger:
    """Потокобезопасный логгер тестовой сессии. Пишет человекочитаемый лог в root_dir."""

    def __init__(self, root_dir: Path, mode: str = "lite"):
        self.root_dir = Path(root_dir)
        self.mode = mode
        self.log_path = self.root_dir / "test_session.log"
        self._lock = threading.Lock()
        self._write("=" * 60)
        self._write(f"Zapret2 {VERSION} test session started at {datetime.now().isoformat()}")
        self._write(f"Mode: {mode}")
        self._write("=" * 60)

    def _write(self, line: str) -> None:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            try:
                with open(self.log_path, "a", encoding="utf-8", errors="replace") as f:
                    f.write(f"[{ts}] {line}\n")
            except OSError:
                pass

    def progress(self, profile: str, message: str) -> None:
        self._write(f"[{profile}] {message}")

    def log(self, message: str) -> None:
        """Generic log line (used for helper steps like service stop)."""
        self._write(message)

    def result(self, profile: str, ok_count: int, fail_count: int, success_rate: float,
               provider_hop: Optional[int] = None, provider_ip: str = "") -> None:
        total = ok_count + fail_count
        hop_info = f" hop={provider_hop} ip={provider_ip}" if provider_hop else ""
        self._write(
            f"[{profile}] RESULT {ok_count}/{total} OK ({success_rate:.0f}%){hop_info}"
        )

    def summary(self, current_score: float, naked_score: float, best_score: float,
                best_profile: str = "") -> None:
        self._write("-" * 60)
        self._write("SUMMARY")
        self._write(f"  Current Zapret score: {current_score:.2f}")
        self._write(f"  Naked score:          {naked_score:.2f}")
        self._write(f"  Best Zapret2 score:   {best_score:.2f} ({best_profile})")
        self._write("-" * 60)

    def close(self) -> None:
        self._write(f"Session finished at {datetime.now().isoformat()}")
        self._write("=" * 60)

    def get_path(self) -> Path:
        return self.log_path
