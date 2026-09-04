from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Optional

from core.admin import enable_privilege, get_enabled_privileges
from core.utils import short_path

_GAME_PORT = "1024-65535"

# Error markers winws2 prints for invalid parameters (exit code is unreliable:
# it returns 0 even on "unknown option", so output must be scanned).
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


def validate_args(exe_path: Path, args: list[str], cwd: Optional[Path] = None, timeout: float = 10.0) -> tuple[bool, str]:
    """Verify winws2 arguments via --dry-run before an actual launch.

    Runs the real binary in verification mode (~0.1-0.3s) and scans its output
    for known error markers.  Returns (True, "") when arguments are valid,
    otherwise (False, first offending output line).  --dry-run does not load
    WinDivert, so no driver state is touched.
    """
    try:
        r = subprocess.run(
            [str(exe_path), "--dry-run"] + args,
            capture_output=True,
            text=True,
            encoding="oem",
            errors="replace",
            timeout=timeout,
            cwd=str(cwd) if cwd else None,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        return False, f"winws2 --dry-run не выполнился: {e}"
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
    """Compile-check the Lua modules referenced by args via --intercept=0.

    --dry-run does NOT initialize Lua, so a typo in a custom lua file (e.g.
    zapret-custom.lua) passes it and kills winws2 at real launch.  --intercept=0
    loads and compiles the lua-init files, then exits without capturing.
    Only the lua/blob-related tokens are passed — no filters, so no WinDivert
    handle is touched even if another instance is running.
    """
    lua_tokens = [t for t in args if t.startswith("--lua-init") or t.startswith("--blob") or t.startswith("--lua-gc")]
    if not lua_tokens:
        return True, ""
    try:
        r = subprocess.run(
            [str(exe_path), "--intercept=0"] + lua_tokens,
            capture_output=True,
            text=True,
            encoding="oem",
            errors="replace",
            timeout=timeout,
            cwd=str(cwd) if cwd else None,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        return False, f"winws2 --intercept=0 не выполнился: {e}"
    output = ((r.stdout or "") + "\n" + (r.stderr or "")).lower()
    for line in output.splitlines():
        stripped = line.strip()
        if any(marker in stripped for marker in _LUA_ERROR_MARKERS):
            return False, f"winws2: ошибка Lua: {stripped}"
    return True, ""


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
    autohostlist: bool = False,
    ipset_catchall: bool = False,
) -> list[str]:
    """Read a .txt preset and return a list of command-line tokens.

    Resolves @lua/, @blobs/, @lists/, and @windivert/ prefixes to absolute
    short paths.  @lua/ and @blobs/ get an @ prefix (for --lua-init, --blob
    file refs).  @lists/ and @windivert/ resolve bare (for --hostlist,
    --hostlist-exclude, --ipset file paths).

    ``%GameFilter%`` placeholders in the preset are replaced with
    ``1024-65535`` when *game_filter_mode* is not ``"off"``, or removed
    (with trailing-comma cleanup) otherwise.

    When *ipset_catchall* is True, every ``--hostlist=@lists/list-general.txt``
    block is replaced with an IP-based catch-all (``--ipset=ipset-all.txt.gz``
    + ``--ipset-exclude=ipset-exclude.txt``).  This mirrors the Zapret 1
    "general" block: desync applies to ALL traffic in the known-blocked
    subnets (no SNI hostlist include — winws2 ANDs ipset with hostlist, so
    keeping the include would neuter the catch-all).  The SNI-based
    list-exclude and user exclusions still apply.

    When *debug* is True, appends ``--debug=@debug_winws2.log`` so that
    winws2 writes a diagnostic log into the root directory.  The caller's ZIP
    collector (export_data_package) will pick that file up automatically.

    The returned tokens are NOT quoted here; quoting happens in write_run_bat via
    subprocess.list2cmdline so that paths with spaces are handled correctly.
    """
    if lists_dir is None:
        lists_dir = root_dir / "lists"
    if windivert_dir is None:
        windivert_dir = root_dir / "windivert"
    short_lists = short_path(lists_dir)
    lines = preset_path.read_text(encoding="utf-8-sig").strip().splitlines()
    game_on = game_filter_mode != "off"
    tokens: list[str] = []

    auto_file = lists_dir / "zapret-auto.txt"
    if autohostlist:
        if not auto_file.exists():
            auto_file.write_text("", encoding="utf-8")
        auto_path = short_path(auto_file)

    # User IP-include list (page «Списки»).  Only counts when it has real
    # entries — an empty file must not change the args at all (the working
    # default configuration stays byte-for-byte the same).
    ipset_inc_file = lists_dir / "ipset-include-user.txt"
    ipset_inc_path = ""
    if ipset_inc_file.exists():
        try:
            has_entry = any(l.strip() and not l.strip().startswith("#")
                            for l in ipset_inc_file.read_text(encoding="utf-8-sig").splitlines())
        except OSError:
            has_entry = False
        if has_entry:
            ipset_inc_path = str(short_path(ipset_inc_file))

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("--comment"):
            continue
        # Targeted-mode override: turn list-general SNI blocks into an
        # IP-based catch-all when the toggle is on (see docstring).
        if ipset_catchall and line.startswith("--hostlist=") and "list-general.txt" in line:
            tokens.append(f"--ipset={short_lists}\\ipset-all.txt.gz")
            if ipset_inc_path:
                # Multiple --ipset tokens OR together (winws2 help: "multiple
                # ipsets allowed") — user subnets are always desynced too.
                tokens.append(f"--ipset={ipset_inc_path}")
            tokens.append(f"--ipset-exclude={short_lists}\\ipset-exclude.txt")
            continue
        if "@lists/" in line:
            line = line.replace("@lists/", str(short_lists) + "\\")
        for dir_name, dir_path in [("@lua/", lua_dir), ("@blobs/", blobs_dir), ("@windivert/", windivert_dir)]:
            if dir_name in line:
                line = line.replace(dir_name, "@" + str(dir_path) + "\\")
        # Expand %GameFilter% placeholder
        if "%GameFilter%" in line:
            port = _GAME_PORT if game_on else ""
            cleaned = line.replace("%GameFilter%", port).strip(",").strip()
            if not cleaned:
                continue
            line = cleaned
        tokens.append(line)
        # Inject --autohostlist into list-general filter blocks
        if autohostlist and "--hostlist=" in line and "list-general" in line:
            tokens.append(f"--hostlist-auto={auto_path}")
    # CRITICAL: --lua-init @path in SEPARATE-arg form kills winws2's option
    # parsing when the path contains NO spaces (a real winws2 bug, see
    # AGENTS.md §23): everything after the option is silently dropped, only
    # the default no_action profile remains → no desync at all, identical
    # results across all presets.  The `=` form works with any path.
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
    # Auto-inject user lists into EVERY hostlist-bearing profile block.
    # winws2 (v1.0.2 source: desync.c dp_match/dp_find) evaluates hostlist
    # PER PROFILE and picks the FIRST profile whose filter+hostlist match;
    # multiple --hostlist inside one profile UNION (hostlist.c AppendHostList).
    # Appending user lists at the very end only touched the LAST (QUIC) block
    # — TCP blocks never saw user domains.  Inject right after the first
    # hostlist token of each profile instead.
    exclude_file = lists_dir / "list-exclude-user.txt"
    user_excl = ""
    if exclude_file.exists() and exclude_file.stat().st_size > 0:
        user_excl = f"--hostlist-exclude={short_path(exclude_file)}"
    include_file = lists_dir / "list-include-user.txt"
    user_inc = ""
    if include_file.exists() and include_file.stat().st_size > 0:
        user_inc = f"--hostlist={short_path(include_file)}"
    if user_excl or user_inc:
        # Per-segment processing: winws2 ANDs --ipset with --hostlist inside
        # one profile (AGENTS.md §24.2) — injecting the SNI include into an
        # ipset-bearing segment would collapse the catch-all to only the
        # user's listed domains.  hostlist-exclude stays safe in both.
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
    # ── GameFilter: high-port capture + catchall profiles ──
    if game_filter_mode in ("udp", "both"):
        # Raw parts don't cover 1024-65535 → add explicit --wf-udp-out
        tokens.insert(0, "--wf-udp-out=1024-65535")
    if game_filter_mode in ("tcp", "both"):
        tokens.append("--new")
        tokens.append("--filter-tcp=1024-65535")
        tokens.append("--filter-l7=tls")
        tokens.append("--out-range")
        tokens.append("-d10")
        tokens.append("--payload")
        tokens.append("tls_client_hello")
        tokens.append("--lua-desync=fake:blob=google_tls:repeats=6")
    if game_filter_mode in ("udp", "both"):
        tokens.append("--new")
        tokens.append("--filter-udp=1024-65535")
        tokens.append("--out-range")
        tokens.append("-d10")
        tokens.append("--lua-desync=fake:blob=quic_google:repeats=10")
    # ── Discord Voice UDP fix ──
    if discord_voice:
        tokens.append("--new")
        tokens.append("--filter-udp=19294-19344,50000-50100")
        tokens.append("--filter-l7=discord,stun")
        tokens.append("--payload=discord_ip_discovery")
        tokens.append("--out-range=-d10")
        tokens.append("--lua-desync=fake:blob=quic_google")
    # ── User IP-includes, targeted mode ──
    # winws2 ANDs --ipset with --hostlist inside one profile, so user subnets
    # cannot share the general block.  Duplicate every profile block that
    # carries list-general and swap its SNI hostlist for --ipset=<user file>:
    # same filters/payload/desync, but matched by destination IP instead.
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
                    dup.append(f"--ipset-exclude={short_lists}\\ipset-exclude.txt")
                elif t.startswith("--hostlist=") or t.startswith("--hostlist-auto="):
                    continue  # SNI-based includes are meaningless in an IP-matched dup
                else:
                    dup.append(t)
            out_segs.append(dup)
        tokens = [x for i, s in enumerate(out_segs) for x in ([] if i == 0 else ["--new"]) + s]
    if debug:
        debug_file = root_dir / "debug_winws2.log"
        if not debug_file.exists():
            debug_file.write_text("")
        debug_path = short_path(debug_file)
        tokens.append(f"--debug=@{debug_path}")
    return tokens


def write_run_bat(
    root_dir: Path,
    bat_path: Path,
    exe_path: Path,
    args: list[str],
) -> None:
    """Write a .bat that starts winws2 via `start /min`.

    Uses subprocess.list2cmdline to quote tokens with spaces correctly and
    short paths to avoid non-ASCII characters in the .bat file.
    """
    short_exe = short_path(exe_path)
    short_root = short_path(root_dir)
    cmd_line = subprocess.list2cmdline([str(short_exe)] + args)
    bat_path.write_text(
        f'@echo off\r\ncd /d "{short_root}"\r\nstart "zapret2" /min {cmd_line}',
        encoding="ascii",
        errors="replace",
    )


def launch_winws2_bat(
    bat_path: Path,
    root_dir: Path,
    timeout: float = 5.0,
) -> bool:
    """Launch a winws2 .bat with SeLoadDriverPrivilege enabled.

    Uses CreateProcess (subprocess.Popen) so the child inherits the current
    token. We enable SeLoadDriverPrivilege first because UAC-elevated Python
    processes often have it disabled, which prevents WinDivert from loading.
    """
    # Enable the privilege in our token; child processes will inherit it.
    privileges_before = get_enabled_privileges()
    se_load_enabled_before = "SeLoadDriverPrivilege" in privileges_before

    if not se_load_enabled_before:
        enable_privilege("SeLoadDriverPrivilege")
        enable_privilege("SeDebugPrivilege")

    privileges_after = get_enabled_privileges()
    se_load_enabled_after = "SeLoadDriverPrivilege" in privileges_after

    if not se_load_enabled_after:
        print(
            f"[zapret2] SeLoadDriverPrivilege still OFF — all privs: {privileges_after}"
        )

    # Give the OS a moment if this is a relaunch after taskkill.
    time.sleep(0.5)

    try:
        subprocess.Popen(
            ["cmd.exe", "/c", str(bat_path)],
            cwd=str(root_dir),
            creationflags=subprocess.CREATE_NO_WINDOW,
            close_fds=True,
        )
    except (OSError, subprocess.SubprocessError):
        return False

    # Wait briefly and verify winws2 started.
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq winws2.exe", "/NH"],
                capture_output=True,
                text=True,
                encoding="oem",
                errors="replace",
                timeout=3,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if "winws2.exe" in r.stdout:
                return True
        except (subprocess.TimeoutExpired, OSError):
            pass
        time.sleep(0.2)
    return False
