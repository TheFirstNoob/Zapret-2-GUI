import sys, subprocess, time, os
from pathlib import Path
sys.path.insert(0, '.')

from core.launcher import build_args_from_preset

root = Path('.')
lua = root / 'lua'
blobs = root / 'blobs'
exe = root / 'bin' / 'winws2.exe'

TEST_HOSTS = [
    "https://discord.com/",
    "https://gateway.discord.gg/",
    "https://cdn.discordapp.com/",
    "https://updates.discord.com/",
]

def curl_code(host, timeout=8):
    r = subprocess.run(
        ["curl.exe", "-4", "-s", "-o", "NUL", "-w", "%{http_code}", "-m", str(timeout),
         "-H", "User-Agent: Mozilla/5.0", host],
        capture_output=True, text=True, timeout=timeout+5)
    return r.stdout.strip()

def test_preset(preset_name):
    print(f"\n===== {preset_name} =====")
    args = build_args_from_preset(root, lua, blobs, Path('presets') / preset_name)
    winws = exe
    if not winws.exists():
        print("winws2 not found")
        return
    proc = subprocess.Popen([str(winws)] + args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3.5)
    for host in TEST_HOSTS:
        code = curl_code(host)
        print(f"  {host:<45} -> {code}")
        if code != "200":
            time.sleep(1)
    proc.terminate()
    time.sleep(1)
    proc.kill()
    subprocess.run(["taskkill", "/F", "/IM", "winws2.exe"], capture_output=True)
    time.sleep(1)

presets = sys.argv[1:] or [
    "test-discord-1-sni-del.txt",
    "test-discord-2-sni-swap.txt",
    "test-discord-3-tcpseg.txt",
    "test-discord-4-multisplit-midsld.txt",
    "test-discord-5-multidisorder.txt",
    "test-discord-6-combo.txt",
]
for p in presets:
    test_preset(p)
print("\n===== DONE =====")