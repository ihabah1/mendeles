"""
start_all.py — מפעיל את כל שרתי Mandeles בבת אחת
===================================================
הפעלה:  python start_all.py

מה זה מפעיל:
  [5000] server.py        — לוטו API
  [5001] beckend_toto.py  — מנוע טוטו
  [5002] auth_server.py   — אימות משתמשים
  [5003] wallet_server.py — ארנק + סטים
  [8080] router.py        — ראוטר מרכזי (כניסה ראשית)

עצירה: Ctrl+C — עוצר את כולם
"""

import subprocess, sys, os, time, signal, threading, logging
from pathlib import Path

logging.basicConfig(
    level   = logging.INFO,
    format  = "%(asctime)s [START] %(message)s",
    datefmt = "%H:%M:%S"
)
log = logging.getLogger()

BASE = Path(__file__).parent   # תיקיית הפרויקט
PY  = sys.executable           # Python הנוכחי

# ─── רשימת השרתים — סדר ההפעלה חשוב! ─────────────────────
SERVICES = [
    {"name": "Auth Server",     "script": "auth_server.py",   "port": 5002, "delay": 0},
    {"name": "Wallet Server",   "script": "wallet_server.py", "port": 5003, "delay": 1},
    {"name": "Lotto API",       "script": "server.py",        "port": 5000, "delay": 1},
    {"name": "Toto Engine",     "script": "beckend_toto.py",  "port": 5001, "delay": 2},
    {"name": "Router (Main)",   "script": "router.py",        "port": 8080, "delay": 3},
]

procs = []

def _stream_output(proc, name):
    """מדפיס את הלוגים של כל שרת עם prefix"""
    colors = {
        "Auth Server":   "\033[36m",   # cyan
        "Wallet Server": "\033[35m",   # magenta
        "Lotto API":     "\033[33m",   # yellow
        "Toto Engine":   "\033[34m",   # blue
        "Router (Main)": "\033[32m",   # green
    }
    reset = "\033[0m"
    color = colors.get(name, "")
    try:
        for line in iter(proc.stdout.readline, b""):
            print(f"{color}[{name}]{reset} {line.decode('utf-8', errors='replace').rstrip()}")
    except Exception:
        pass

def start_service(svc):
    script = BASE / svc["script"]
    if not script.exists():
        log.warning(f"⚠️  לא נמצא: {svc['script']} — מדלג")
        return None

    time.sleep(svc["delay"])

    log.info(f"🔄  מפעיל [{svc['name']}] על פורט {svc['port']}...")
    env = os.environ.copy()
    env['PYTHONUTF8'] = '1'
    env['PYTHONIOENCODING'] = 'utf-8'
    proc = subprocess.Popen(
        [PY, str(script)],
        cwd    = str(BASE),
        stdout = subprocess.PIPE,
        stderr = subprocess.STDOUT,
        bufsize = 1,
        env    = env,
    )
    # thread שמדפיס לוגים
    t = threading.Thread(target=_stream_output, args=(proc, svc["name"]), daemon=True)
    t.start()
    log.info(f"✅  [{svc['name']}] PID {proc.pid}")
    return proc

def stop_all(signum=None, frame=None):
    print("\n")
    log.info("🛑  עוצר את כל השרתים...")
    for p in procs:
        if p and p.poll() is None:
            p.terminate()
    time.sleep(1)
    for p in procs:
        if p and p.poll() is None:
            p.kill()
    log.info("👋  כל השרתים עצרו.")
    sys.exit(0)

def check_health(port, retries=8, delay=0.8):
    """מחכה שהשרת יעלה על הפורט"""
    import socket
    for _ in range(retries):
        try:
            s = socket.create_connection(("127.0.0.1", port), timeout=1)
            s.close()
            return True
        except OSError:
            time.sleep(delay)
    return False

# ─── MAIN ────────────────────────────────────────────────
if __name__ == "__main__":
    signal.signal(signal.SIGINT,  stop_all)
    signal.signal(signal.SIGTERM, stop_all)

    print("=" * 55)
    print("🚀  Mandeles — מפעיל את כל השרתים")
    print("=" * 55)

    # הפעל בthread נפרד כדי שה-delay לא יחסום
    threads = []
    for svc in SERVICES:
        def _start(s=svc):
            p = start_service(s)
            if p:
                procs.append(p)
        t = threading.Thread(target=_start)
        t.start()
        threads.append(t)
        time.sleep(0.2)  # הפרדה קטנה בין הפעלות

    # המתן שכולם יתחילו
    for t in threads:
        t.join()

    time.sleep(3)

    print("\n" + "=" * 55)
    print(f"🌐  האתר עלה!  http://localhost:8080")
    print(f"🔍  בריאות:     http://localhost:8080/router/health")
    print("─" * 55)
    for svc in SERVICES:
        print(f"   [{svc['port']}] {svc['name']}")
    print("=" * 55)
    print("   Ctrl+C לעצירה\n")

    # שמור את התהליך הראשי חי
    try:
        while True:
            time.sleep(5)
            # בדוק שהראוטר עדיין חי — הכי חשוב
            dead = [p for p in procs if p and p.poll() is not None]
            if dead:
                log.warning(f"⚠️  {len(dead)} שרת/ים עצרו")
    except KeyboardInterrupt:
        stop_all()
