#!/usr/bin/env python3
"""מפעיל שירותי Flask ברקע (בלי router – Django הוא הכניסה)."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable

SERVICES = [
    ('auth_server.py', 5002, 0),
    ('wallet_server.py', 5003, 1),
    ('server.py', 5000, 1),
    ('beckend_toto.py', 5001, 2),
]


def main():
    os.chdir(ROOT)
    os.environ.setdefault('PYTHONUTF8', '1')
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    log_path = ROOT / 'data' / 'legacy_pids.log'
    log_path.parent.mkdir(parents=True, exist_ok=True)

    started = []
    for script, port, delay in SERVICES:
        path = ROOT / script
        if not path.is_file():
            print(f'skip missing {script}', flush=True)
            continue
        time.sleep(delay)
        proc = subprocess.Popen(
            [PY, str(path)],
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        started.append((script, port, proc.pid))
        print(f'started {script} pid={proc.pid} port={port}', flush=True)

    with log_path.open('a', encoding='utf-8') as f:
        f.write(f'\n--- batch {time.strftime("%Y-%m-%d %H:%M:%S")} ---\n')
        for script, port, pid in started:
            f.write(f'{script} {port} {pid}\n')

    print(f'legacy services: {len(started)} processes', flush=True)


if __name__ == '__main__':
    main()
