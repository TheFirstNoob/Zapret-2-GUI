import subprocess, sys, re

def run_one(preset, n):
    stats = {"discord": [], "yt": [], "google": []}
    for i in range(n):
        r = subprocess.run([sys.executable, "_run_clean.py", preset],
                           capture_output=True, text=True, encoding="oem", errors="replace",
                           timeout=90)
        out = r.stdout or ""
        for host, key in [("discord.com", "discord"), ("www.youtube.com", "yt"), ("www.google.com", "google")]:
            m = re.search(re.escape(host) + r"/?\s*->\s*(\d+)", out)
            stats[key].append(m.group(1) if m else "?")
        print(f"  run{i+1}: discord={stats['discord'][-1]} yt={stats['yt'][-1]} google={stats['google'][-1]}", flush=True)
    return stats

if __name__ == "__main__":
    preset = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    print(f"=== {preset} x{n} ===", flush=True)
    s = run_one(preset, n)
    for k in ["discord", "yt"]:
        ok = s[k].count("200")
        print(f"{k}: {ok}/{n} = {100*ok//n}%", flush=True)