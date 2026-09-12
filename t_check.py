import subprocess, sys

for ref in ['64163e6', '757f0dd', '5f7965e']:
    out = subprocess.run(['git', 'show', f'{ref}:core/tester.py'], capture_output=True, text=True, encoding='utf-8', errors='replace').stdout
    lines = out.splitlines()
    start = next((i for i, l in enumerate(lines) if 'NAKED_BASELINE_HOSTS' in l), -1)
    print(f'--- {ref}: ' + ' | '.join(l.strip() for l in lines[start:start+12] if l.strip()))