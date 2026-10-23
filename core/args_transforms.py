"""args_transforms.py - постобработки токенов пресета (аудит #4).

Каждый шаг: (tokens, ctx) -> токены. Порядок КРИТИЧЕН и зафиксирован
PIPELINE (историческая последовательность build_args_from_preset; комментарии-
инварианты перенесены вместе с логикой). Публичный вход -
core.launcher.build_args_from_preset (сигнатуру не менять: её зовут
build_lite/build_portable и server._prepare_service_args).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core import games as games_store
from core.applog import log as _applog
from core.preset_parse import HIGH_PORTS

VOICE_PORTS = "19294-19344,50000-50100"


@dataclass(frozen=True)
class ArgsCtx:
    """Контекст шагов: пути, флаги и заранее резолвнутые пути файлов."""
    root_dir: Path
    lua_dir: Path
    blobs_dir: Path
    lists_dir: Path
    windivert_dir: Path
    game_filter_mode: str   # off|udp|tcp|both
    voice_mode: str         # off|fake|udplen
    debug: bool
    fake_blob: str
    autohostlist: bool
    ipset_catchall: bool
    discord_alt: bool
    auto_path: str          # "" если autohostlist выключен
    ipset_inc_path: str     # "" если файл пуст/отсутствует
    ipset_excl_path: str

    @property
    def lists_base(self) -> str:
        return str(self.lists_dir)


def _append_wf_udp_ports(tokens: list[str], ports: str) -> None:
    """Дописать порты в --wf-udp-out (его значение - следующий токен)."""
    for i, t in enumerate(tokens):
        if t == "--wf-udp-out" and i + 1 < len(tokens):
            cur = tokens[i + 1]
            have = cur.split(",")
            missing = [p for p in ports.split(",") if p and p not in have]
            if missing:
                tokens[i + 1] = cur + "," + ",".join(missing)


def transform_fake_blob(tokens: list[str], ctx: ArgsCtx) -> list[str]:
    """Fake blob selector: подмена TLS-фейка без записи в пресет.

    Регистрируется отдельное имя alt_tls на новый файл и переписываются
    ТОЛЬКО fake:blob=<tls-blob> - seqovl_pattern (выравнивание перекрытия) и
    QUIC/HTTP блобы остаются родными."""
    if not ctx.fake_blob:
        return tokens
    alt_file = ctx.blobs_dir / f"tls_clienthello_{ctx.fake_blob}.bin"
    if not alt_file.exists() and ctx.fake_blob.startswith("blob_"):
        # цифро-ключи сервер отдаёт в селект как "blob_<key>" (имена с цифры
        # winws2 не принимает) - резолвим алиас к реальному файлу
        alt_file = ctx.blobs_dir / f"tls_clienthello_{ctx.fake_blob[5:]}.bin"
    if not alt_file.exists():
        return tokens
    # имена --blob, чьи файлы - TLS clienthello (не quic/http)
    tls_blob_names = set()
    for i, t in enumerate(tokens):
        if t == "--blob" and i + 1 < len(tokens) and "tls_clienthello_" in tokens[i + 1]:
            tls_blob_names.add(tokens[i + 1].split(":", 1)[0])
    tokens = list(tokens)
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

    return [_swap_fake_ref(t) for t in tokens]


def transform_voice_udplen_rewrite(tokens: list[str], ctx: ArgsCtx) -> list[str]:
    """Discord Voice udplen: переписать инлайн голосовой блок.

    UDP-сегментации нет, DPI с жёсткой привязкой к длине/сигнатуре голосовых
    пакетов промахивается при сдвиге длины. Блок независим (сегментация
    --new) - переписывается на месте: без --payload/--out-range (медиа-поток
    непрерывный), udplen вместо fake."""
    if ctx.voice_mode != "udplen":
        return tokens
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
        is_voice = any(VOICE_PORTS in t for t in seg)
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
    return rebuilt


def transform_merge_lua_init(tokens: list[str], ctx: ArgsCtx) -> list[str]:
    """CRITICAL (AGENTS.md §23): --lua-init @path отдельным аргументом с путём
    БЕЗ пробелов убивает парсинг winws2 - все опции после молча отбрасываются,
    остаётся 1 профиль no_action → десинка нет, результаты всех пресетов
    идентичны. Форма `=` работает с любым путём (плюс Cygwin-экспансия @file
    больше не задевает такой токен: слово начинается с `-`)."""
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
    return merged


def transform_user_lists(tokens: list[str], ctx: ArgsCtx) -> list[str]:
    """Юзер-списки инжектятся в КАЖДЫЙ блок с hostlist.

    winws2 (desync.c dp_match/dp_find) матчит hostlist ПО ПРОФИЛЮ и берёт
    ПЕРВЫЙ подходящий профиль; несколько --hostlist внутри профиля
    объединяются (hostlist.c AppendHostList). Добавление в конец затрагивало
    только последний (QUIC) блок - TCP-блоки юзерских доменов не видели.
    Инжект - сразу после первого hostlist-токена. Ссылаемся на user-файлы
    ВСЕГДА (даже пустые): winws2 перечитывает hostlist/ipset на лету по mtime
    (проверено 2026-09-14), первая же правка применится без перезапуска.
    User + games домены - ОДИН union-файл и один --hostlist-токен вместо двух
    (2026-09-25): файлы-владельцы не смешиваются, args не растут от числа игр."""
    exclude_file = ctx.lists_dir / "list-exclude-user.txt"
    user_excl = f"--hostlist-exclude={exclude_file}" if exclude_file.exists() else ""
    include_file = ctx.lists_dir / "list-include-user.txt"
    include_path = games_store.sync_include_list(ctx.root_dir, include_file)
    user_inc = f"--hostlist={include_path}" if include_path is not None else ""
    if not (user_excl or user_inc):
        return tokens
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
    return out


def transform_gamefilter_segments(tokens: list[str], ctx: ArgsCtx) -> list[str]:
    """GameFilter: захват высоких портов + catch-all профили."""
    tokens = list(tokens)
    if ctx.game_filter_mode in ("udp", "both"):
        # Raw-части не покрывают HIGH_PORTS → явный --wf-udp-out
        tokens.insert(0, f"--wf-udp-out={HIGH_PORTS}")
    if ctx.game_filter_mode in ("tcp", "both"):
        tokens.append("--new")
        tokens.append(f"--filter-tcp={HIGH_PORTS}")
        tokens.append("--filter-l7=tls")
        tokens.append("--out-range")
        tokens.append("-d10")
        tokens.append("--payload")
        tokens.append("tls_client_hello")
        # Выбранный fake_blob должен применяться и здесь: сегмент добавляется
        # ПОСЛЕ подмены (transform_fake_blob), имя выбираем сами (аудит
        # 2026-10: alt_tls не доходил до игрового TLS).
        game_tls_blob = "google_tls"
        if ctx.fake_blob:
            _alt = ctx.blobs_dir / f"tls_clienthello_{ctx.fake_blob}.bin"
            if not _alt.exists() and ctx.fake_blob.startswith("blob_"):
                _alt = ctx.blobs_dir / f"tls_clienthello_{ctx.fake_blob[5:]}.bin"
            if _alt.exists():
                game_tls_blob = "alt_tls"
        tokens.append(f"--lua-desync=fake:blob={game_tls_blob}:repeats=6")
    if ctx.game_filter_mode in ("udp", "both"):
        tokens.append("--new")
        tokens.append(f"--filter-udp={HIGH_PORTS}")
        tokens.append("--out-range")
        tokens.append("-d10")
        # payload=all обязателен: lua fake по умолчанию не трогает unknown-UDP
        # (игровой трафик) - без него тоггл «Игровые порты» был холостым
        tokens.append("--lua-desync=fake:blob=quic_google:repeats=10:payload=all")
    return tokens


def transform_voice_segment(tokens: list[str], ctx: ArgsCtx) -> list[str]:
    """Discord Voice: фикс UDP (отдельный сегмент).

    Добавляем ТОЛЬКО пресетам без инлайн-голосового блока: у релизных он уже
    есть (fake - как есть, udplen - переписан трансформацией выше),
    добавление давало дубль профиля (аудит 2026-10: 9 сегментов вместо 8)."""
    has_inline_voice = any(VOICE_PORTS in t for t in tokens)
    if ctx.voice_mode == "udplen" and not has_inline_voice:
        tokens.append("--new")
        tokens.append(f"--filter-udp={VOICE_PORTS}")
        tokens.append("--filter-l7=discord,stun")
        tokens.append("--lua-desync=udplen:increment=5:pattern=0xDEADBEEF")
    elif ctx.voice_mode == "fake" and not has_inline_voice:
        tokens.append("--new")
        tokens.append(f"--filter-udp={VOICE_PORTS}")
        tokens.append("--filter-l7=discord,stun")
        tokens.append("--payload=discord_ip_discovery")
        tokens.append("--out-range=-d10")
        tokens.append("--lua-desync=fake:blob=quic_google")
    return tokens


def transform_game_udp_pool(tokens: list[str], ctx: ArgsCtx) -> list[str]:
    """Игровые блокировки: UDP-фиксы (только старт соединения).

    Пул (2026-09-25): ОДИН --new-сегмент на группу правил с одинаковыми
    repeats/cutoff; порты - списком, CIDR всех правил группы - в общий
    pool-файл. fake с payload=all обязателен: lua не трогает unknown-UDP
    (игровой трафик) без явного аргумента."""
    game_rules = games_store.enabled_udp_rules(games_store.load_games(ctx.root_dir))
    if game_rules and ctx.game_filter_mode in ("udp", "both"):
        # GameFilter уже ловит HIGH_PORTS с payload=all: отдельные игровые
        # правила и дописывание портов избыточны.
        _applog("games", f"UDP-правила игр пропущены: GameFilter="
                         f"{ctx.game_filter_mode} покрывает порты "
                         f"({len(game_rules)} правил)")
    elif game_rules:
        if not any(t.startswith("quic_google:") for t in tokens):
            # Тот же блоб, что объявляют пресеты, но ПУТЬ АБСОЛЮТНЫЙ:
            # относительный резолвится движком от cwd, а служба стартует
            # winws2 с cwd=%SystemRoot%\System32 → «cannot access file
            # 'blobs/quic_initial_www_google_com.bin'» и обход не поднимается
            # вообще (REVIEW_VERDICT.md §2.5).
            quic_blob = ctx.blobs_dir / "quic_initial_www_google_com.bin"
            if quic_blob.exists():
                tokens += ["--blob", f"quic_google:@{quic_blob}"]
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
                key = f"d{cutoff}r{repeats}"
                try:
                    pool = games_store.write_cidr_pool_file(
                        ctx.root_dir, key, cidrs)
                except OSError as e:
                    # Не роняем установку службы 500-й: пропускаем группу,
                    # пишем причину в applog (ревью 23.10).
                    _applog("games", f"UDP-пул: не удалось записать pool "
                                     f"{key}: {e} - группа пропущена "
                                     f"(порты {ports})")
                    continue
                seg.append(f"--ipset={pool}")
            seg += ["--out-range", f"-d{cutoff}",
                    "--lua-desync=fake:blob=quic_google:"
                    f"repeats={repeats}:payload=all"]
            _append_wf_udp_ports(tokens, ports)
            tokens += seg
        _applog("games", f"UDP-пул: rules={len(game_rules)} "
                         f"pools={len(groups)} "
                         f"wide={sum(1 for k in groups if k[2])}")
    return tokens


def transform_ipset_include_dup(tokens: list[str], ctx: ArgsCtx) -> list[str]:
    """Юзерские IP-include, targeted-режим.

    winws2 ANDs --ipset с --hostlist внутри профиля, поэтому юзер-подсети не
    могут жить в общем блоке. Дублируем каждый блок с list-general и меняем
    SNI-hostlist на --ipset=<user file>: те же фильтры/payload/desync, но
    матчинг по IP назначения."""
    if not (ctx.ipset_inc_path and not ctx.ipset_catchall):
        return tokens
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
                dup.append(f"--ipset={ctx.ipset_inc_path}")
                dup.append(f"--ipset-exclude={ctx.lists_base}\\ipset-exclude.txt")
                if ctx.ipset_excl_path:
                    dup.append(f"--ipset-exclude={ctx.ipset_excl_path}")
            elif t.startswith("--hostlist=") or t.startswith("--hostlist-auto="):
                continue  # SNI-include бессмысленен в IP-дубле
            else:
                dup.append(t)
        out_segs.append(dup)
    return [x for i, s in enumerate(out_segs) for x in ([] if i == 0 else ["--new"]) + s]


def transform_discord_alt(tokens: list[str], ctx: ArgsCtx) -> list[str]:
    """ALT-режим Discord: вернуть :nodrop в lua-desync Discord-профилей.

    Профиль определяется по hostlist list-discord; voice-профиль не
    затрагивается. Для сетей, где drop-режим не бьёт холодный старт."""
    if not ctx.discord_alt:
        return tokens
    segs_alt: list[list[str]] = [[]]
    for t in tokens:
        if t == "--new":
            segs_alt.append([])
        else:
            segs_alt[-1].append(t)
    for seg in segs_alt:
        if not any(t.startswith("--hostlist=") and "list-discord" in t for t in seg):
            continue
        for i, t in enumerate(seg):
            if t.startswith("--lua-desync=") and ":nodrop" not in t:
                seg[i] = t + ":nodrop"
    return [x for i, s in enumerate(segs_alt)
            for x in ([] if i == 0 else ["--new"]) + s]


def transform_debug(tokens: list[str], ctx: ArgsCtx) -> list[str]:
    """Дописать --debug=@debug_winws2.log (файл создаём заранее)."""
    if not ctx.debug:
        return tokens
    debug_file = ctx.root_dir / "debug_winws2.log"
    if not debug_file.exists():
        debug_file.write_text("")
    return tokens + [f"--debug=@{debug_file}"]


# Порядок критичен (историческая последовательность build_args_from_preset):
# подмена блоба → переписывание voice-udplen → merge lua-init → инжект
# юзер-списков → GameFilter-сегменты → голосовой сегмент → игровой UDP-пул →
# дублирование ipset-include → discord-alt → debug.
PIPELINE = (
    transform_fake_blob,
    transform_voice_udplen_rewrite,
    transform_merge_lua_init,
    transform_user_lists,
    transform_gamefilter_segments,
    transform_voice_segment,
    transform_game_udp_pool,
    transform_ipset_include_dup,
    transform_discord_alt,
    transform_debug,
)
