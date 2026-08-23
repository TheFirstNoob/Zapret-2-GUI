from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional


@dataclass
class AppConfig:
    root_dir: str = ""
    lua_dir: str = "lua"
    blobs_dir: str = "blobs"
    bin_dir: str = "bin"
    profiles_dir: str = "presets"
    lists_dir: str = "lists"
    auto_hostlist: str = "zapret-auto.txt"
    exclude_hostlist: str = "zapret-exclude.txt"
    theme: str = "dark"
    language: str = "ru"
    service_name: str = "zapret2"
    wf_tcp_out: str = "80,443"
    wf_udp_out: str = "443"
    last_profile: str = "default"
    tester_timeout: int = 8
    zapret1_dir: str = ""
    zapret1_last_strategy: str = ""
    game_filter_mode: str = "off"
    discord_voice: bool = False
    winws2_debug: bool = False
    autohostlist: bool = False


DEFAULT_PROFILE = "default"

# Application version.
VERSION = "Pre-Release 0.2"


class ConfigManager:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir)
        self.config_path = self.root_dir / "zapret2_config.json"
        self._config: Optional[AppConfig] = None

    def load(self) -> AppConfig:
        if self._config is not None:
            return self._config
        if self.config_path.exists():
            try:
                data = json.loads(self.config_path.read_text(encoding="utf-8"))
                self._config = AppConfig(**data)
            except (OSError, json.JSONDecodeError, TypeError):
                self._config = AppConfig(root_dir=str(self.root_dir))
        else:
            self._config = AppConfig(root_dir=str(self.root_dir))
        return self._config

    def save(self, config: AppConfig) -> bool:
        try:
            self.config_path.write_text(
                json.dumps(asdict(config), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            self._config = config
            return True
        except OSError:
            return False


