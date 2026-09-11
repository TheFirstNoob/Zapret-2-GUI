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

def kill_winws2():
    subprocess.run(["taskkill", "/F", "/IM", "winws2.exe"], capture_output=True, timeout=15)
    time.sleep(1)

def start(preset):
    args = build_args_from_preset(root, lua, blobs, root / 'presets' / preset)
    subprocess.Popen([str(exe)] + args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(5)

def curl_code(host):
    try:
        r = subprocess.run(
            ["curl.exe", "-4", "-s", "-o", "NUL", "-w", "%{http_code}", "-m", "6",
             "-H", "User-Agent: Mozilla/5.0", host],
            capture_output=True, text=True, timeout=12)
        return r.stdout.strip() or "ERR"
    except Exception:
        return "TMO"

def run_one(preset):
    print(f"\n===== {preset} =====", flush=True)
    kill_winws2()
    start(preset)
    for h in TEST_HOSTS:
        print(f"  {h:<42} -> {curl_code(h)}", flush=True)
    kill_winws2()
    # restore default so user is never left unprotected
    start("default.txt")
    print("  [restored default]", flush=True)

if __name__ == "__main__":
    preset = sys.argv[1]
    run_one(preset)
    print("===== DONE =====", flush=True)