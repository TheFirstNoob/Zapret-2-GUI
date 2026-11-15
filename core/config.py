from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

from core.applog import log as _applog


@dataclass
class AppConfig:
    root_dir: str = ""
    last_profile: str = "default"
    zapret1_dir: str = ""
    zapret1_last_strategy: str = ""
    game_filter_mode: str = "off"
    discord_voice: bool = False
    discord_voice_mode: str = "off"  # off | fake | udplen
    fake_blob: str = ""                # ключ tls_clienthello_<key>.bin; пусто = как в пресете (google)
    winws2_debug: bool = False
    autohostlist: bool = False
    ipset_catchall: bool = False
    discord_alt: bool = False          # альт-режим Discord (nodrop) для капризных сетей
    tour_done: bool = False
    notice_done: bool = False
    # Два DNS-профиля для быстрой смены (Diagnostics → DNS).
    # Каждый профиль — primary + secondary; провайдеры можно смешивать.
    dns_main_primary: str = "8.8.8.8"
    dns_main_secondary: str = "8.8.4.4"
    dns_reserve_primary: str = "1.1.1.1"
    dns_reserve_secondary: str = "1.0.0.1"


DEFAULT_PROFILE = "default"

VERSION = "Pre-Release 0.11.1"

# Допустимые значения enum-полей (совпадают с server/api_config.py).
GAME_FILTER_MODES = ("off", "tcp", "udp", "both")
VOICE_MODES = ("off", "fake", "udplen")

_BOOL_FIELDS = frozenset({
    "discord_voice", "winws2_debug", "autohostlist", "ipset_catchall",
    "discord_alt", "tour_done", "notice_done",
})
# Строковые поля: не-строка (int/list/None из ручной правки или импорта
# настроек) откатывается на дефолт поля, а не роняет build_args
# AttributeError (аудит T9 №4: fake_blob=5 / discord_voice_mode=5).
_STR_FIELDS = frozenset({
    "root_dir", "last_profile", "zapret1_dir", "zapret1_last_strategy",
    "fake_blob", "dns_main_primary", "dns_main_secondary",
    "dns_reserve_primary", "dns_reserve_secondary",
})

_TRUE_TOKENS = frozenset({"1", "true", "yes", "on"})
_FALSE_TOKENS = frozenset({"0", "false", "no", "off", ""})


def _field_default(name: str) -> object:
    return AppConfig.__dataclass_fields__[name].default


def _warn(msg: str) -> None:
    """Операционный лог (logs/zapret2.log); в тестах подменяется monkeypatch."""
    _applog("config", msg)


def _as_default(name: str, value: object, reason: str) -> object:
    default = _field_default(name)
    _warn(f"{name}={value!r}: {reason} - использую {default!r}")
    return default


def _coerce_bool(name: str, value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        token = value.strip().lower()
        if token in _TRUE_TOKENS:
            return True
        if token in _FALSE_TOKENS:
            return False
    return bool(_as_default(name, value, "неверный тип/значение"))


def _coerce_str(name: str, value: object) -> str:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            default = _field_default(name)
            if isinstance(default, str) and default:
                # Пустая строка не валидна для last_profile (presets/.txt)
                # и DNS-профилей (normalize_servers: "Укажите основной DNS").
                _warn(f"{name} пуст - использую {default!r}")
                return default
        return text
    default = _as_default(name, value, "ждали строку")
    return str(default)


def _coerce_choice(name: str, value: object, allowed: tuple[str, ...],
                   fallback: str) -> str:
    if isinstance(value, str) and value.strip().lower() in allowed:
        return value.strip().lower()
    _warn(f"{name}={value!r}: допустимо {allowed} - использую {fallback!r}")
    return fallback


def normalize_config(data: dict) -> dict:
    """Привести значения известных полей конфига к типам AppConfig.

    Fail-open (как hardening 2026-10-24): валидные значения сохраняются,
    битые по типу - дефолт поля + запись в лог. Так ручная правка/импорт
    zapret2_config.json (fake_blob: 5, game_filter_mode: "botth") не валит
    старт/диагностику AttributeError и не расширяет окна GameFilter молча.
    Неизвестные ключи отбрасывает вызывающий (filter по dataclass-полям).
    """
    out = dict(data)
    # discord_voice первым: от него зависит fallback невалидного voice-mode.
    if "discord_voice" in out:
        out["discord_voice"] = _coerce_bool("discord_voice", out["discord_voice"])
    if "discord_voice_mode" in out:
        raw = out["discord_voice_mode"]
        if isinstance(raw, str) and raw.strip().lower() in VOICE_MODES:
            out["discord_voice_mode"] = raw.strip().lower()
        else:
            # Невалидный режим = как отсутствующий: legacy-bool сохраняет
            # прежний смысл (fake), иначе off.
            fallback = "fake" if out.get("discord_voice") else "off"
            _warn(f"discord_voice_mode={raw!r}: допустимо {VOICE_MODES} - "
                  f"использую {fallback!r}")
            out["discord_voice_mode"] = fallback
    if "game_filter_mode" in out:
        out["game_filter_mode"] = _coerce_choice(
            "game_filter_mode", out["game_filter_mode"], GAME_FILTER_MODES, "off")
    for name in _BOOL_FIELDS:
        if name in out and name != "discord_voice":
            out[name] = _coerce_bool(name, out[name])
    for name in _STR_FIELDS:
        if name in out:
            out[name] = _coerce_str(name, out[name])
    return out


class ConfigManager:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir)
        self.config_path = self.root_dir / "zapret2_config.json"
        self._config: Optional[AppConfig] = None

    def load(self) -> AppConfig:
        if self._config is not None:
            return self._config
        known: dict = {}
        if self.config_path.exists():
            try:
                # utf-8-sig: BOM из «Блокнота» не должен сбрасывать конфиг.
                data = json.loads(self.config_path.read_text(encoding="utf-8-sig"))
                if not isinstance(data, dict):
                    raise ValueError("config root is not an object")
                # Отбрасываем ключи вне AppConfig (старые/чужие поля),
                # иначе TypeError валит загрузку и теряется last_profile.
                known = {k: v for k, v in data.items()
                         if k in AppConfig.__dataclass_fields__}
                known = normalize_config(known)
                self._config = AppConfig(**known)
            except (OSError, ValueError, TypeError, AttributeError):
                self._quarantine_bad_config()
                self._config = AppConfig(root_dir=str(self.root_dir))
        else:
            self._config = AppConfig(root_dir=str(self.root_dir))
        # Миграция старых конфигов (bool discord_voice без discord_voice_mode).
        if "discord_voice_mode" not in known and self._config.discord_voice:
            self._config.discord_voice_mode = "fake"
        return self._config

    def _quarantine_bad_config(self) -> None:
        """Не терять исходник, если config валиден как JSON, но не объект."""
        bad = self.config_path.with_suffix(self.config_path.suffix + ".bad")
        try:
            self.config_path.replace(bad)
        except OSError:
            pass

    def save(self, config: AppConfig) -> bool:
        tmp: Optional[Path] = None
        try:
            # Нормализуем и в памяти, и на диске: битый объект от внешнего
            # кода (импорт/тесты) не должен осесть в кэше/конфиге.
            known = normalize_config(
                {name: getattr(config, name)
                 for name in AppConfig.__dataclass_fields__})
            normalized = AppConfig(**known)
            # атомарная запись (L5): обрыв посреди write_text делал конфиг
            # битым json - сбрасывался в дефолт. Уникальное имя temp: два
            # параллельных POST /api/config сталкивались на общем .tmp
            # (аудит 2026-10)
            tmp = self.config_path.with_name(
                f"{self.config_path.name}.{os.getpid()}."
                f"{threading.get_ident()}.tmp")
            tmp.write_text(
                json.dumps(asdict(normalized), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            os.replace(tmp, self.config_path)
            self._config = normalized
            return True
        except OSError:
            try:
                if tmp is not None:
                    tmp.unlink(missing_ok=True)
            except OSError:
                pass
            return False
