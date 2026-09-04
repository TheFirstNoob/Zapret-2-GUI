from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional


@dataclass
class AppConfig:
    root_dir: str = ""
    last_profile: str = "default"
    zapret1_dir: str = ""
    zapret1_last_strategy: str = ""
    game_filter_mode: str = "off"
    discord_voice: bool = False
    winws2_debug: bool = False
    autohostlist: bool = False
    ipset_catchall: bool = False


DEFAULT_PROFILE = "default"

# Application version.
VERSION = "Pre-Release 0.5"


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
                # Отбрасываем ключи, которых нет в AppConfig (старые/чужие поля),
                # иначе TypeError валит всю загрузку и теряется last_profile.
                known = {k: v for k, v in data.items()
                         if k in AppConfig.__dataclass_fields__}
                self._config = AppConfig(**known)
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


