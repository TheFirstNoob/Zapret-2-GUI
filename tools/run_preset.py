import sys, subprocess, time
from pathlib import Path

sys.path.insert(0, '.')
from core.launcher import build_args_from_preset

root = Path('.')
lua = root / 'lua'
blobs = root / 'blobs'
exe = root / 'bin' / 'winws2.exe'

TEST_HOSTS = [
    "https://github.com/",
    "https://discord.com/",
    "https://www.youtube.com/",
    "https://www.google.com/",
    "https://www.gstatic.com/",
]

def check_clean():
    """Return list of winws2 pids if any running (conflict) else []."""
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq winws2.exe", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True, encoding="oem", errors="replace",
                         timeout=20).stdout
    if out is None:
        return []
    pids = []
    for line in out.splitlines():
        parts = line.strip('"').split('","')
        if len(parts) > 1 and parts[0].lower() == "winws2.exe":
            pids.append(parts[1])
    return pids

def curl_code(host):
    try:
        r = subprocess.run(
            ["curl.exe", "-4", "-s", "-o", "NUL", "-w", "%{http_code}", "-m", "6",
             "-H", "User-Agent: Mozilla/5.0", host],
            capture_output=True, text=True, timeout=15)
        return r.stdout.strip() or "ERR"
    except subprocess.TimeoutExpired:
        return "TMO"
    except Exception:
        return "ERR"

def run_one(preset):
    # 1. conflict check — abort if anything running
    pids = check_clean()
    if pids:
        print(f"ABORT: winws2 already running pid={pids} — stop zapret first", flush=True)
        sys.exit(3)

    # 2. start test preset, track OUR pid
    args = build_args_from_preset(root, lua, blobs, root / 'presets' / preset)
    proc = subprocess.Popen([str(exe)] + args,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"[{preset}] started pid={proc.pid}", flush=True)
    time.sleep(5)

    # 3. run curls
    print(f"\n===== {preset} =====", flush=True)
    for h in TEST_HOSTS:
        print(f"  {h:<42} -> {curl_code(h)}", flush=True)

    # 4. kill ONLY our pid
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    print("  [stopped]", flush=True)

    # 5. verify clean
    left = check_clean()
    if left:
        print(f"  WARN: winws2 still running: {left}", flush=True)
    else:
        print("  [clean]", flush=True)

if __name__ == "__main__":
    run_one(sys.argv[1])
    print("===== DONE =====", flush=True)