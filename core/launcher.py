from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

from core.admin import enable_privilege, get_enabled_privileges
from core import games as games_store
from core.applog import log as _applog
from core.utils import short_path

_GAME_PORT = "1024-65535"

# Маркеры ошибок winws2 на неверные параметры (exit code ненадёжен: даже на
# "unknown option" возвращает 0 - вывод приходится сканировать).
_DRY_RUN_ERROR_MARKERS = (
    "unknown option",
    "bad file",
    "cannot access file",
    "cannot create",
    "cannot open",
    "invalid autottl",
    "lua error",
    "error loading",
)


def _winws2_env() -> dict[str, str]:
    """env для winws2: Cygwin ждёт UTF-8-локаль (кривой LANG у юзера ломает пути)."""
    env = os.environ.copy()
    env["LANG"] = "C.UTF-8"
    env["LC_ALL"] = "C.UTF-8"
    return env


def _conf_quote_token(t: str) -> str:
    """Токен конфига: DQ при пробелах/бэкслэшах/glob-символах.

    Unquoted-токены Cygwin прогоняет через globify (`'`, `[`, `]`, `(`, `)`,
    `{`, `}`, `?`, `*`, `~`) - пути с такими символами калечатся (внешнее
    ревью 14.10: путь с `'`/`[]` терял бэкслэши: `C:Users...`). Пути с
    бэкслэшами квотим всегда - единообразно и дёшево."""
    if any(c in t for c in " \t\\'(){}[]?*~"):
        return f'"{t}"'
    return t


def _conf_text(tokens: list[str]) -> str:
    return "\n".join(_conf_quote_token(str(t)) for t in tokens) + "\n"


def _winws2_raw_cmdline(exe_path: Path, conf_path: Path, *pre: str) -> str:
    """Командная строка вида `"exe" [pre...] @"conf"`.

    Кавычки вокруг ПУТИ, @ снаружи: только так Cygwin раскрывает @file
    (`"@conf"` - кавычка перед @ - отключает раскрытие, см.
    AI_DOCS/ARG_FILE_RESEARCH_2026-10-14.md, dcrt0.cc sawquote).
    `pre` - флаги безопасности (--dry-run/--intercept=0) ДУБЛИРУЮТСЯ в argv:
    если раскрытие @file когда-нибудь сломается (обновление winws2), процесс
    всё равно не уйдёт в живой перехват (fail-closed, внешнее ревью 14.10).
    """
    pre_str = " ".join(pre)
    return f'"{exe_path}" {pre_str + " " if pre_str else ""}@"{conf_path}"'


def write_run_conf(root_dir: Path, args: list[str], name: str = "run.conf") -> Path:
    """Пишет аргументы winws2 в logs/<name> (токен на строку, LF, UTF-8).

    Атомарная запись (tmp + os.replace): winws2 читает конфиг только целиком.
    """
    logs = root_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    conf = logs / name
    tmp = conf.with_name(conf.name + ".tmp")
    tmp.write_text(_conf_text(args), encoding="utf-8")
    os.replace(tmp, conf)
    return conf


def _write_temp_conf(tokens: list[str]) -> Path:
    """Временный conf для dry-run/lua-проверок (в TEMP)."""
    fd, name = tempfile.mkstemp(prefix="zapret2_preflight_", suffix=".conf")
    os.close(fd)
    p = Path(name)
    p.write_text(_conf_text(tokens), encoding="utf-8")
    return p


def _read_stderr_sink(root_dir: Path, limit: int = 1500) -> str:
    """Перехваченный вывод winws2 (logs/winws2_last_stderr.log).

    Ранние ошибки (getopt/lua) печатаются в НАЧАЛЕ вывода, поэтому при
    длинном тексте возвращаем начало+конец, а не только хвост.
    """
    p = root_dir / "logs" / "winws2_last_stderr.log"
    try:
        data = p.read_bytes()
    except OSError:
        return ""
    text = data.decode("utf-8", "replace").strip()
    if len(text) <= limit:
        return text
    head = text[: limit // 2].strip()
    tail = text[-limit // 2:].strip()
    return head + "\n...\n" + tail


def validate_args(exe_path: Path, args: list[str], cwd: Optional[Path] = None, timeout: float = 10.0) -> tuple[bool, str]:
    """Проверка аргументов winws2 через --dry-run перед реальным запуском.

    Гоняет настоящий бинарник в режиме проверки (~0.1-0.3с) и ищет в выводе
    известные маркеры ошибок.  Возвращает (True, "") при валидных аргументах
    или (False, первая проблемная строка вывода).  WinDivert не грузится -
    состояние драйвера не затрагивается.
    """
    conf = _write_temp_conf(list(args) + ["--dry-run"])
    try:
        r = subprocess.run(
            _winws2_raw_cmdline(exe_path, conf, "--dry-run"),
            capture_output=True,
            text=True,
            encoding="oem",
            errors="replace",
            timeout=timeout,
            cwd=str(cwd) if cwd else None,
            creationflags=subprocess.CREATE_NO_WINDOW,
            env=_winws2_env(),
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        return False, f"winws2 --dry-run не выполнился: {e}"
    finally:
        conf.unlink(missing_ok=True)
    output = ((r.stdout or "") + "\n" + (r.stderr or "")).lower()
    for line in output.splitlines():
        stripped = line.strip()
        if any(marker in stripped for marker in _DRY_RUN_ERROR_MARKERS):
            return False, f"winws2 отклонил параметры: {stripped}"
    return validate_lua(exe_path, args, cwd, timeout)


_LUA_ERROR_MARKERS = (
    "lua error",
    "not accessible",
    "unexpected symbol",
    "' expected",
    "attempt to",
    "stack traceback",
    "bad argument",
)


def validate_lua(exe_path: Path, args: list[str], cwd: Optional[Path] = None, timeout: float = 10.0) -> tuple[bool, str]:
    """Компиляционная проверка Lua-модулей из args через --intercept=0.

    --dry-run НЕ инициализирует Lua, поэтому опечатка в кастомном lua-файле
    (например, zapret-custom.lua) проходит её и валит winws2 при реальном
    запуске.  --intercept=0 загружает и компилирует lua-init-файлы и выходит
    без захвата.  Передаются только lua/blob-токены - без фильтров, поэтому
    хендл WinDivert не трогается даже при работающем другом экземпляре.
    """
    lua_tokens = [t for t in args if t.startswith("--lua-init") or t.startswith("--blob") or t.startswith("--lua-gc")]
    if not lua_tokens:
        return True, ""
    conf = _write_temp_conf(lua_tokens + ["--intercept=0"])
    try:
        r = subprocess.run(
            _winws2_raw_cmdline(exe_path, conf, "--intercept=0"),
            capture_output=True,
            text=True,
            encoding="oem",
            errors="replace",
            timeout=timeout,
            cwd=str(cwd) if cwd else None,
            creationflags=subprocess.CREATE_NO_WINDOW,
            env=_winws2_env(),
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        return False, f"winws2 --intercept=0 не выполнился: {e}"
    finally:
        conf.unlink(missing_ok=True)
    output = ((r.stdout or "") + "\n" + (r.stderr or "")).lower()
    for line in output.splitlines():
        stripped = line.strip()
        if any(marker in stripped for marker in _LUA_ERROR_MARKERS):
            return False, f"winws2: ошибка Lua: {stripped}"
    return True, ""


def _append_wf_udp_ports(tokens: list[str], ports: str) -> None:
    """Дописать порты в --wf-udp-out (его значение - следующий токен)."""
    for i, t in enumerate(tokens):
        if t == "--wf-udp-out" and i + 1 < len(tokens):
            cur = tokens[i + 1]
            have = cur.split(",")
            missing = [p for p in ports.split(",") if p and p not in have]
            if missing:
                tokens[i + 1] = cur + "," + ",".join(missing)
            return
    tokens.insert(0, f"--wf-udp-out={ports}")


def build_args_from_preset(
    root_dir: Path,
    lua_dir: Path,
    blobs_dir: Path,
    preset_path: Path,
    lists_dir: Optional[Path] = None,
    windivert_dir: Optional[Path] = None,
    debug: bool = False,
    game_filter_mode: str = "off",
    discord_voice: bool = False,
    discord_voice_mode: str = "",
    autohostlist: bool = False,
    ipset_catchall: bool = False,
    fake_blob: str = "",
    discord_alt: bool = False,
) -> list[str]:
    """Читает .txt пресет и возвращает токены командной строки.

    @lua/ и @blobs/ остаются с @ (--lua-init/--blob), @lists/ и @windivert/
    разворачиваются в короткие пути без @ (--hostlist, --ipset).
    %GameFilter% -> 1024-65535 при включённом game_filter_mode, иначе
    вырезается.  ipset_catchall заменяет list-general на IP-catch-all,
    отбрасывая SNI-include: winws2 AND-ит ipset с hostlist, и включение
    обнулило бы catch-all; list-exclude и юзер-исключения действуют.
    debug дописывает --debug=@debug_winws2.log.  Токены НЕ квотируются -
    это делает write_run_bat через subprocess.list2cmdline.

    discord_alt: альтернативный режим Discord (вернуть :nodrop в Discord-профили)
    - для сетей, где базовый drop-режим не пробивает «холодный старт».
    """
    if lists_dir is None:
        lists_dir = root_dir / "lists"
    if windivert_dir is None:
        windivert_dir = root_dir / "windivert"
    lists_base = str(lists_dir)
    lines = preset_path.read_text(encoding="utf-8-sig").strip().splitlines()
    game_on = game_filter_mode != "off"
    # Discord Voice: legacy bool + новый селект. Неизвестное значение -> off.
    voice_mode = (discord_voice_mode or ("fake" if discord_voice else "off")).strip().lower()
    if voice_mode not in ("off", "fake", "udplen"):
        voice_mode = "off"
    tokens: list[str] = []

    auto_file = lists_dir / "zapret-auto.txt"
    if autohostlist:
        if not auto_file.exists():
            auto_file.write_text("", encoding="utf-8")
        auto_path = str(auto_file)

    # User IP-include list: только непустой файл меняет args - пустой не
    # должен трогать конфиг вообще (байт-в-байт прежний default).
    ipset_inc_file = lists_dir / "ipset-include-user.txt"
    ipset_inc_path = ""
    if ipset_inc_file.exists():
        try:
            has_entry = any(l.strip() and not l.strip().startswith("#")
                            for l in ipset_inc_file.read_text(encoding="utf-8-sig").splitlines())
        except OSError:
            has_entry = False
        if has_entry:
            ipset_inc_path = str(ipset_inc_file)

    # User IP-exclude list: exclude всегда сильнее include (ipset.c проверяет
    # ips_exclude первым) - без этой связки редактор «IP-сети - исключения»
    # писал в файл, который winws2 никогда не получал.
    ipset_excl_file = lists_dir / "ipset-exclude-user.txt"
    ipset_excl_path = ""
    if ipset_excl_file.exists():
        try:
            has_entry = any(l.strip() and not l.strip().startswith("#")
                            for l in ipset_excl_file.read_text(encoding="utf-8-sig").splitlines())
        except OSError:
            has_entry = False
        if has_entry:
            ipset_excl_path = str(ipset_excl_file)

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("--comment"):
            continue
        # Targeted-mode override: SNI-блоки list-general -> IP catch-all.
        if ipset_catchall and line.startswith("--hostlist=") and "list-general.txt" in line:
            tokens.append(f"--ipset={lists_base}\\ipset-all.txt.gz")
            if ipset_inc_path:
                # Несколько --ipset OR-ятся (winws2 help: "multiple ipsets
                # allowed") - юзер-подсети десинкаются тоже.
                tokens.append(f"--ipset={ipset_inc_path}")
            tokens.append(f"--ipset-exclude={lists_base}\\ipset-exclude.txt")
            if ipset_excl_path:
                # Несколько exclude коллекций поддерживаются (ipset.c
                # итерирует список); юзер-сети сильнее ipset-all.
                tokens.append(f"--ipset-exclude={ipset_excl_path}")
            if autohostlist:
                # catch-all заменяет hostlist на ipset, но --hostlist-auto
                # должен остаться: иначе тумблер молча холостой (аудит 2026-10)
                tokens.append(f"--hostlist-auto={auto_path}")
            continue
        if "@lists/" in line:
            line = line.replace("@lists/", str(lists_base) + "\\")
        for dir_name, dir_path in [("@lua/", lua_dir), ("@blobs/", blobs_dir), ("@windivert/", windivert_dir)]:
            if dir_name in line:
                line = line.replace(dir_name, "@" + str(dir_path) + "\\")
        if "%GameFilter%" in line:
            port = _GAME_PORT if game_on else ""
            cleaned = line.replace("%GameFilter%", port).strip(",").strip()
            if not cleaned:
                continue
            line = cleaned
        tokens.append(line)
        # --autohostlist добавляется в блоки фильтра list-general
        if autohostlist and "--hostlist=" in line and "list-general" in line:
            tokens.append(f"--hostlist-auto={auto_path}")
    # ── Fake blob selector: подмена TLS-фейка без записи в пресет ──
    # Регистрируется отдельное имя alt_tls на новый файл и переписываются
    # ТОЛЬКО fake:blob=<tls-blob> - seqovl_pattern (выравнивание перекрытия)
    # и QUIC/HTTP блобы остаются родными.
    if fake_blob:
        alt_file = blobs_dir / f"tls_clienthello_{fake_blob}.bin"
        if not alt_file.exists() and fake_blob.startswith("blob_"):
            # цифро-ключи сервер отдаёт в селект как "blob_<key>" (имена с
            # цифры winws2 не принимает) - резолвим алиас к реальному файлу
            alt_file = blobs_dir / f"tls_clienthello_{fake_blob[5:]}.bin"
        if alt_file.exists():
            # имена --blob, чьи файлы - TLS clienthello (не quic/http)
            tls_blob_names = set()
            for i, t in enumerate(tokens):
                if t == "--blob" and i + 1 < len(tokens) and "tls_clienthello_" in tokens[i + 1]:
                    tls_blob_names.add(tokens[i + 1].split(":", 1)[0])
            tokens.insert(0, "--blob")
            tokens.insert(1, f"alt_tls:@{alt_file}")
            def _swap_fake_ref(t: str) -> str:
                if not t.startswith("--lua-desync=fake:blob="):
                    return t
                for n in tls_blob_names:
                    if t == f"--lua-desync=fake:blob={n}":
                        return "--lua-desync=fake:blob=alt_tls"
                    if t.startswith(f"--lua-desync=fake:blob={n}:"):
                        return t.replace(f"fake:blob={n}", "fake:blob=alt_tls", 1)
                return t
            tokens = [_swap_fake_ref(t) for t in tokens]
    # ── Discord Voice udplen: переписать инлайн голосовой блок ──
    # Гипотеза (STRATEGY_ROADMAP §1): UDP-сегментации нет, DPI с жёсткой
    # привязкой к длине/сигнатуре голосовых пакетов промахивается при сдвиге
    # длины. Блок независим (сегментация --new) - переписывается на месте:
    # без --payload/--out-range (медиа-поток непрерывный), udplen вместо fake.
    if voice_mode == "udplen":
        segs: list[list[str]] = [[]]
        for t in tokens:
            if t == "--new":
                segs.append([])
            else:
                segs[-1].append(t)
        rebuilt: list[str] = []
        for si, seg in enumerate(segs):
            if si > 0:
                rebuilt.append("--new")
            is_voice = any("19294-19344,50000-50100" in t for t in seg)
            for t in seg:
                if is_voice:
                    if t == "--payload" or t == "--out-range":
                        continue  # пары (option, value) выкидываем с ключом
                    if t == "discord_ip_discovery" or t == "-d10":
                        continue
                    if t.startswith("--lua-desync=") and "fake:blob=quic_google" in t:
                        rebuilt.append("--lua-desync=udplen:increment=5:pattern=0xDEADBEEF")
                        continue
                rebuilt.append(t)
        tokens = rebuilt
    # CRITICAL (AGENTS.md §23): --lua-init @path отдельным аргументом с путём
    # БЕЗ пробелов убивает парсинг winws2 - все опции после молча отбрасываются,
    # остаётся 1 профиль no_action → десинка нет, результаты всех пресетов
    # идентичны. Форма `=` работает с любым путём.
    merged: list[str] = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t == "--lua-init" and i + 1 < len(tokens) and tokens[i + 1].startswith("@"):
            merged.append(t + "=" + tokens[i + 1])
            i += 2
        else:
            merged.append(t)
            i += 1
    tokens = merged
    # Юзер-списки инжектятся в КАЖДЫЙ блок с hostlist. winws2 (desync.c
    # dp_match/dp_find) матчит hostlist ПО ПРОФИЛЮ и берёт ПЕРВЫЙ подходящий
    # профиль; несколько --hostlist внутри профиля объединяются (hostlist.c
    # AppendHostList). Добавление в конец затрагивало только последний
    # (QUIC) блок - TCP-блоки юзерских доменов не видели. Инжект - сразу
    # после первого hostlist-токена.
    # Ссылаемся на user-файлы ВСЕГДА (даже пустые): winws2 перечитывает
    # hostlist/ipset на лету по mtime (проверено 2026-09-14), поэтому первая
    # же правка применится к новым подключениям без перезапуска обхода.
    # Пустой файл не влияет на выбор профиля (0 доменов = нет фильтра).
    exclude_file = lists_dir / "list-exclude-user.txt"
    user_excl = ""
    if exclude_file.exists():
        user_excl = f"--hostlist-exclude={exclude_file}"
    # User + games домены - ОДИН union-файл и один --hostlist-токен вместо
    # двух (2026-09-25): файлы-владельцы не смешиваются (user-файл юзерский,
    # list-games.txt генерируемый), но args не растут от числа игр.
    include_file = lists_dir / "list-include-user.txt"
    include_path = games_store.sync_include_list(root_dir, include_file)
    user_inc = ""
    if include_path is not None:
        user_inc = f"--hostlist={include_path}"
    if user_excl or user_inc:
        # winws2 ANDs --ipset с --hostlist внутри профиля (§24.2): инжект
        # SNI-include в ipset-сегмент схлопнул бы catch-all до доменов юзера.
        # hostlist-exclude безопасен в обоих случаях.
        segs: list[list[str]] = [[]]
        for t in tokens:
            if t == "--new":
                segs.append([])
            else:
                segs[-1].append(t)
        out: list[str] = []
        for i, seg in enumerate(segs):
            if i > 0:
                out.append("--new")
            has_ipset = any(t.startswith("--ipset=") for t in seg)
            injected_once = False
            for t in seg:
                if not injected_once and (t.startswith("--hostlist=")
                                          or t.startswith("--hostlist-exclude=")):
                    if user_excl:
                        out.append(user_excl)
                    if user_inc and not has_ipset:
                        out.append(user_inc)
                    injected_once = True
                out.append(t)
        tokens = out
    # ── GameFilter: захват высоких портов + catch-all профили ──
    if game_filter_mode in ("udp", "both"):
        # Raw-части не покрывают 1024-65535 → явный --wf-udp-out
        tokens.insert(0, "--wf-udp-out=1024-65535")
    if game_filter_mode in ("tcp", "both"):
        tokens.append("--new")
        tokens.append("--filter-tcp=1024-65535")
        tokens.append("--filter-l7=tls")
        tokens.append("--out-range")
        tokens.append("-d10")
        tokens.append("--payload")
        tokens.append("tls_client_hello")
        # Выбранный fake_blob (секция «Fake blob selector» выше) должен
        # применяться и здесь: сегмент добавляется ПОСЛЕ подмены, поэтому
        # имя выбираем сами (аудит 2026-10: alt_tls не доходил до игрового TLS).
        game_tls_blob = "google_tls"
        if fake_blob:
            _alt = blobs_dir / f"tls_clienthello_{fake_blob}.bin"
            if not _alt.exists() and fake_blob.startswith("blob_"):
                _alt = blobs_dir / f"tls_clienthello_{fake_blob[5:]}.bin"
            if _alt.exists():
                game_tls_blob = "alt_tls"
        tokens.append(f"--lua-desync=fake:blob={game_tls_blob}:repeats=6")
    if game_filter_mode in ("udp", "both"):
        tokens.append("--new")
        tokens.append("--filter-udp=1024-65535")
        tokens.append("--out-range")
        tokens.append("-d10")
        # payload=all обязателен: lua fake по умолчанию не трогает unknown-UDP
        # (игровой трафик) - без него тоггл «Игровые порты» был холостым
        tokens.append("--lua-desync=fake:blob=quic_google:repeats=10:payload=all")
    # ── Discord Voice: фикс UDP ──
    # Отдельный сегмент добавляем ТОЛЬКО пресетам без инлайн-голосового
    # блока: у релизных он уже есть (fake - как есть, udplen - переписан
    # трансформацией выше), добавление давало дубль профиля (аудит 2026-10:
    # 9 сегментов вместо 8).
    has_inline_voice = any("19294-19344,50000-50100" in t for t in tokens)
    if voice_mode == "udplen" and not has_inline_voice:
        tokens.append("--new")
        tokens.append("--filter-udp=19294-19344,50000-50100")
        tokens.append("--filter-l7=discord,stun")
        tokens.append("--lua-desync=udplen:increment=5:pattern=0xDEADBEEF")
    elif voice_mode == "fake" and not has_inline_voice:
        tokens.append("--new")
        tokens.append("--filter-udp=19294-19344,50000-50100")
        tokens.append("--filter-l7=discord,stun")
        tokens.append("--payload=discord_ip_discovery")
        tokens.append("--out-range=-d10")
        tokens.append("--lua-desync=fake:blob=quic_google")
    # ── Игровые блокировки: UDP-фиксы (только старт соединения) ──
    # Пул (2026-09-25): ОДИН --new-сегмент на группу правил с одинаковыми
    # repeats/cutoff; порты - списком, CIDR всех правил группы - в общий
    # pool-файл. Раньше каждый сегмент весил ~150 симв. и args пухли от игр.
    # fake с payload=all обязателен: lua не трогает unknown-UDP (игровой
    # трафик) без явного аргумента.
    game_rules = games_store.enabled_udp_rules(games_store.load_games(root_dir))
    if game_rules and game_filter_mode in ("udp", "both"):
        # GameFilter уже ловит 1024-65535 с payload=all: отдельные игровые
        # правила и дописывание портов избыточны (порты уже в диапазоне).
        _applog("games", f"UDP-правила игр пропущены: GameFilter="
                         f"{game_filter_mode} покрывает порты "
                         f"({len(game_rules)} правил)")
    elif game_rules:
        if not any(t.startswith("quic_google:") for t in tokens):
            # Тот же блоб, что объявляют пресеты, но ПУТЬ АБСОЛЮТНЫЙ (как
            # @blobs/ в строках пресета, :210-212). Относительный путь
            # резолвится движком относительно cwd: validate_args всегда
            # гоняет с cwd=root (зелёный), а служба стартует winws2 с
            # cwd=%SystemRoot%\System32 → «cannot access file
            # 'blobs/quic_initial_www_google_com.bin'» и обход не поднимается
            # вообще (REVIEW_VERDICT.md §2.5).
            quic_blob = blobs_dir / "quic_initial_www_google_com.bin"
            if quic_blob.exists():
                tokens += ["--blob",
                           f"quic_google:@{quic_blob}"]
            else:
                _applog("games", "UDP-пул: quic_google блоб не найден "
                                 f"({quic_blob}) - игровые сегменты пропущены")
                game_rules = []
        # Группируем и по наличию подсетей: правила без CIDR идут «широким»
        # пулом без --ipset (весь трафик на порту - для ручных правил игр).
        groups: dict[tuple[int, int, bool], list[dict]] = {}
        for rule in game_rules:
            wide = not rule["cidrs"]
            groups.setdefault((rule["cutoff"], rule["repeats"], wide),
                              []).append(rule)
        for (cutoff, repeats, wide), rules in groups.items():
            ports = ",".join(dict.fromkeys(str(r["ports"]) for r in rules))
            seg = ["--new", f"--filter-udp={ports}"]
            if not wide:
                cidrs = [c for r in rules for c in r["cidrs"]]
                pool = games_store.write_cidr_pool_file(
                    root_dir, f"d{cutoff}r{repeats}", cidrs)
                seg.append(f"--ipset={pool}")
            seg += ["--out-range", f"-d{cutoff}",
                    "--lua-desync=fake:blob=quic_google:"
                    f"repeats={repeats}:payload=all"]
            _append_wf_udp_ports(tokens, ports)
            tokens += seg
        _applog("games", f"UDP-пул: rules={len(game_rules)} "
                         f"pools={len(groups)} "
                         f"wide={sum(1 for k in groups if k[2])}")
    # ── Юзерские IP-include, targeted-режим ──
    # winws2 ANDs --ipset с --hostlist внутри профиля, поэтому юзер-подсети
    # не могут жить в общем блоке. Дублируем каждый блок с list-general и
    # меняем SNI-hostlist на --ipset=<user file>: те же фильтры/payload/desync,
    # но матчинг по IP назначения.
    if ipset_inc_path and not ipset_catchall:
        segs: list[list[str]] = [[]]
        for t in tokens:
            if t == "--new":
                segs.append([])
            else:
                segs[-1].append(t)
        out_segs: list[list[str]] = []
        for seg in segs:
            out_segs.append(seg)
            if not any(t.startswith("--hostlist=") and "list-general.txt" in t for t in seg):
                continue
            dup: list[str] = []
            for t in seg:
                if t.startswith("--hostlist=") and "list-general.txt" in t:
                    dup.append(f"--ipset={ipset_inc_path}")
                    dup.append(f"--ipset-exclude={lists_base}\\ipset-exclude.txt")
                    if ipset_excl_path:
                        dup.append(f"--ipset-exclude={ipset_excl_path}")
                elif t.startswith("--hostlist=") or t.startswith("--hostlist-auto="):
                    continue  # SNI-include бессмысленен в IP-дубле
                else:
                    dup.append(t)
            out_segs.append(dup)
        tokens = [x for i, s in enumerate(out_segs) for x in ([] if i == 0 else ["--new"]) + s]
    if discord_alt:
        # ALT-режим Discord: вернуть :nodrop в lua-desync Discord-профилей
        # (профиль определяется по hostlist list-discord; voice-профиль не
        # затрагивается). Для сетей, где drop-режим не бьёт холодный старт.
        segs_alt: list[list[str]] = [[]]
        for t in tokens:
            if t == "--new":
                segs_alt.append([])
            else:
                segs_alt[-1].append(t)
        for seg in segs_alt:
            if not any(t.startswith("--hostlist=") and "list-discord" in t
                       for t in seg):
                continue
            for i, t in enumerate(seg):
                if t.startswith("--lua-desync=") and ":nodrop" not in t:
                    seg[i] = t + ":nodrop"
        tokens = [x for i, s in enumerate(segs_alt)
                  for x in ([] if i == 0 else ["--new"]) + s]
    if debug:
        debug_file = root_dir / "debug_winws2.log"
        if not debug_file.exists():
            debug_file.write_text("")
        debug_path = str(debug_file)
        tokens.append(f"--debug=@{debug_path}")
    return tokens


def write_run_bat(
    root_dir: Path,
    bat_path: Path,
    exe_path: Path,
    args: list[str],
) -> None:
    """Пишет .bat, запускающий winws2 через `start /min` (аргументы - из conf).

    Как и в прямом запуске, аргументы идут через logs/run.conf: bat не зависит
    от длины и кавычек аргументов. Короткие пути убирают не-ASCII из ASCII-bat.
    """
    conf = write_run_conf(root_dir, args)
    short_exe = short_path(exe_path)
    short_root = short_path(root_dir)
    short_conf = short_path(conf)
    bat_path.write_text(
        f'@echo off\r\ncd /d "{short_root}"\r\n'
        f'start "zapret2" /min "{short_exe}" @"{short_conf}"',
        encoding="ascii",
        errors="replace",
    )


def _arg_path_token(t: str) -> str:
    """Путь к файлу из токена аргументов (@-файлы, blobs, hostlist/ipset)."""
    if t.startswith("@") and "\\" in t:
        return t[1:]
    if ":@" in t:
        return t.split(":@", 1)[1]
    if "=@" in t:
        return t.split("=@", 1)[1]
    if t.startswith("--") and "=" in t and "\\" in t:
        return t.split("=", 1)[1]
    return ""


def _launch_preflight(root_dir: Path, exe_path: Path, args: list[str],
                      method: str) -> tuple[bool, str]:
    """Префлайт запуска + запись в операционный лог (logs/zapret2.log).

    Разбор «у кого-то запускается, у кого-то нет» без пользователя у экрана:
    фиксируем frozen-раскладку, наличие exe, число и суммарную длину
    аргументов, пустые аргументы, битые @-пути (lua/blob/hostlist/ipset).
    Фатально: нет exe или пустой аргумент (стратегия/тоггл сгенерил "").
    """
    import sys as _sys
    exe_ok = exe_path.is_file()
    empties = [i for i, a in enumerate(args) if not str(a)]
    cmdlen = sum(len(str(a)) + 1 for a in args) + len(str(exe_path)) + 1
    _applog("launch", f"preflight[{method}]: frozen={bool(getattr(_sys, 'frozen', False))} "
                      f"exe={exe_path} exists={exe_ok} cwd={root_dir} "
                      f"args={len(args)} cmdlen={cmdlen} empty={len(empties)}")
    checked = 0
    missing: list[str] = []
    for i, a in enumerate(args):
        p = _arg_path_token(str(a))
        if not p:
            continue
        checked += 1
        if not Path(p).exists():
            missing.append(f"#{i}={a}")
    if checked or missing:
        tail = f" -> {'; '.join(missing[:5])}" if missing else ""
        _applog("launch", f"preflight[{method}]: paths checked={checked} "
                          f"missing={len(missing)}{tail}")
    if not exe_ok:
        return False, f"winws2.exe не найден: {exe_path}"
    if empties:
        i = empties[0]
        ctx = [str(x) for x in args[max(0, i - 3):i + 2]]
        return False, (f"пустой аргумент #{i} (рядом: {ctx}) - стратегия или "
                       f"тоггл формирует пустую строку")
    return True, ""


def _prepare_winws2_launch(root_dir: Path) -> None:
    """Драйвер + SeLoadDriverPrivilege до запуска (общее для direct и bat).

    CreateProcess наследует ТЕКУЩИЙ токен: у UAC-elevated Python привилегия
    часто выключена, без неё WinDivert не грузится.
    """
    try:
        from core.utils import fix_stale_windivert_services
        fix_stale_windivert_services(root_dir)
    except Exception:
        pass
    if "SeLoadDriverPrivilege" not in get_enabled_privileges():
        enable_privilege("SeLoadDriverPrivilege")
        enable_privilege("SeDebugPrivilege")
    privs = get_enabled_privileges()
    if "SeLoadDriverPrivilege" not in privs:
        _applog("launch", f"WARN: SeLoadDriverPrivilege OFF (privs={privs})")
    else:
        _applog("launch", "SeLoadDriverPrivilege ON")
    # Пауза на случай перезапуска сразу после taskkill.
    time.sleep(0.5)


def _wait_winws2_alive(timeout: float,
                       proc: Optional[subprocess.Popen] = None) -> bool:
    """Ждёт появления winws2.exe в tasklist (только по имени образа)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc is not None and proc.poll() is not None:
            return False  # процесс уже упал - ждать нечего
        try:
            r = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq winws2.exe", "/NH"],
                capture_output=True, text=True, encoding="oem",
                errors="replace", timeout=3,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if "winws2.exe" in r.stdout:
                return True
        except (subprocess.TimeoutExpired, OSError):
            pass
        time.sleep(0.2)
    return False


def launch_winws2_direct(root_dir: Path, exe_path: Path, args: list[str],
                         timeout: float = 5.0,
                         ) -> tuple[Optional[subprocess.Popen], str]:
    """Прямой запуск winws2.exe через @config_file. -> (proc | None, ошибка).

    Аргументы пишутся в logs/run.conf, командная строка - `"exe" @"conf"`:
    @file раскрывает Cygwin-рантайм ещё до main() (это снимает лимиты длины
    cmd 8191/CreateProcess), кавычки стоят ПОСЛЕ @ (см. _winws2_raw_cmdline).
    stdout/stderr winws2 пишутся в logs/winws2_last_stderr.log (PIPE без
    чтения использовать нельзя - deadlock на полном буфере).
    """
    ok, msg = _launch_preflight(root_dir, exe_path, args, "direct")
    if not ok:
        _applog("launch", f"preflight FAIL: {msg}")
        return None, msg
    try:
        conf = write_run_conf(root_dir, args)
    except OSError as e:
        _applog("launch", f"run.conf write FAIL: {e!r}")
        return None, f"run.conf: {e}"
    _prepare_winws2_launch(root_dir)
    sink = None
    try:
        sink = open(root_dir / "logs" / "winws2_last_stderr.log", "wb")
    except OSError:
        sink = None
    kw: dict = dict(cwd=str(root_dir),
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    close_fds=True, env=_winws2_env())
    if sink is not None:
        kw.update(stdout=sink, stderr=subprocess.STDOUT)
    try:
        proc = subprocess.Popen(
            _winws2_raw_cmdline(exe_path, conf),
            executable=str(exe_path),
            **kw,
        )
    except (OSError, subprocess.SubprocessError) as e:
        _applog("launch", f"direct Popen FAIL: {e!r}")
        return None, f"Popen: {e}"
    finally:
        if sink is not None:
            sink.close()
    _applog("launch", f"direct Popen ok pid={proc.pid} conf=logs/{conf.name}")
    return proc, ""


def launch_winws2(root_dir: Path, exe_path: Path, args: list[str],
                  timeout: float = 5.0) -> bool:
    """Умный запуск: прямой Popen (основной) -> bat (аварийный фолбэк).

    bat остаётся для проблемных машин/отладки: если прямой запуск не дал
    живого winws2, повторяем через `start /min` и пишем это в лог.
    """
    proc, err = launch_winws2_direct(root_dir, exe_path, args, timeout)
    if proc is not None and _wait_winws2_alive(timeout, proc):
        _applog("launch", "direct OK: winws2 жив")
        return True
    if proc is not None and proc.poll() is None:
        # процесс жив, но tasklist его не увидел - не плодим дубль
        _applog("launch", "direct: процесс жив, tasklist без winws2 - успех")
        return True
    if proc is not None:
        _applog("launch", f"direct FAIL: winws2 упал rc={proc.returncode}")
    elif err:
        _applog("launch", f"direct FAIL: {err}")
    tail = _read_stderr_sink(root_dir)
    if tail:
        _applog("launch", f"winws2 stderr: {tail}")
    bat = root_dir / "_zapret_run.bat"
    write_run_bat(root_dir, bat, exe_path, args)
    ok = launch_winws2_bat(bat, root_dir, timeout=timeout)
    _applog("launch", f"bat fallback: {'OK' if ok else 'FAIL'}")
    return ok


def launch_winws2_bat(
    bat_path: Path,
    root_dir: Path,
    timeout: float = 5.0,
) -> bool:
    """Запускает .bat с winws2, включив SeLoadDriverPrivilege (аварийный путь)."""
    _prepare_winws2_launch(root_dir)
    try:
        subprocess.Popen(
            ["cmd.exe", "/c", str(bat_path)],
            cwd=str(root_dir),
            creationflags=subprocess.CREATE_NO_WINDOW,
            close_fds=True,
        )
    except (OSError, subprocess.SubprocessError) as e:
        _applog("launch-bat", f"Popen cmd FAIL: {e!r}")
        return False
    ok = _wait_winws2_alive(timeout)
    _applog("launch-bat", f"winws2 {'жив' if ok else 'НЕ появился'} ({timeout}s)")
    return ok