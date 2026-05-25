"""
mandeles.co.il — שרת Routing מרכזי
=====================================
מאזין על פורט 8080 (או PORT מה-.env)
מגיש קבצי HTML סטטיים
מנתב קריאות API לשרתים הנכונים:

  /api/*          → שרת לוטו        :5000  (server.py)
  /engine/*       → מנוע טוטו       :5001  (beckend_toto.py)
  /auth/*         → שרת auth        :5002  (auth_server.py)
  /lotto/*        → שרת ארנק/סטים   :5003  (wallet_server.py)
  /admin/*        → שרת ארנק/אדמין  :5003  (wallet_server.py)

הפעלה:
  python router.py

דרישות:
  pip install flask flask-cors requests python-dotenv
"""

import os, logging, requests as req
from pathlib import Path
from flask import Flask, request, Response, send_from_directory, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────
STATIC_DIR  = Path(__file__).parent          # תיקיית קבצי HTML
ROUTER_PORT = int(os.getenv("SITE_PORT", 8080))

# כתובות השרתים הפנימיים
BACKENDS = {
    "lotto_engine": f"http://localhost:{os.getenv('ENGINE_PORT', 5001)}",
    "auth":         f"http://localhost:{os.getenv('AUTH_PORT',   5002)}",
    "wallet":       f"http://localhost:{os.getenv('WALLET_PORT', 5003)}",
    "api":          f"http://localhost:5000",
}

# ─────────────────────────────────────────────────────────
# ROUTING TABLE
# prefix → backend key
# ─────────────────────────────────────────────────────────
ROUTES = [
    ("/engine/",  "lotto_engine"),
    ("/auth/",    "auth"),
    ("/lotto/",   "wallet"),
    ("/admin/",   "wallet"),
    ("/api/",     "api"),
]

# ─────────────────────────────────────────────────────────
# APP
# ─────────────────────────────────────────────────────────
app = Flask(__name__, static_folder=None)
CORS(app, supports_credentials=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [ROUTER] %(levelname)s  %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("router")

# ─────────────────────────────────────────────────────────
# PROXY HELPER
# ─────────────────────────────────────────────────────────
SKIP_HEADERS = {"host", "content-length", "transfer-encoding", "connection"}

def _proxy(backend_url: str) -> Response:
    """
    מעביר את הבקשה הנוכחית לbackend_url
    ומחזיר את התגובה כמו שהיא (כולל headers וסטטוס).
    """
    url = backend_url + request.full_path.rstrip("?") if not request.query_string \
          else backend_url + request.full_path

    # העתק headers (ללא כאלו שעלולים לשבור את החיבור)
    fwd_headers = {
        k: v for k, v in request.headers
        if k.lower() not in SKIP_HEADERS
    }

    try:
        resp = req.request(
            method   = request.method,
            url      = url,
            headers  = fwd_headers,
            data     = request.get_data(),
            params   = request.args,
            stream   = True,
            timeout  = 30,
            allow_redirects = False,
        )
        # בנה response חזרה ללקוח
        excluded_resp = {"content-encoding", "transfer-encoding", "connection"}
        resp_headers = {
            k: v for k, v in resp.headers.items()
            if k.lower() not in excluded_resp
        }
        return Response(
            response = resp.iter_content(chunk_size=4096),
            status   = resp.status_code,
            headers  = resp_headers,
            direct_passthrough = True,
        )

    except req.exceptions.ConnectionError:
        log.warning(f"❌ Backend לא פעיל: {backend_url}")
        return jsonify({"error": "שרת backend לא פעיל", "backend": backend_url}), 503

    except req.exceptions.Timeout:
        log.warning(f"⏱️ Timeout: {backend_url}")
        return jsonify({"error": "תם הזמן לbackend"}), 504

    except Exception as e:
        log.error(f"Proxy error: {e}")
        return jsonify({"error": str(e)}), 500

# ─────────────────────────────────────────────────────────
# PROXY ROUTE — מנתב לפי הprefix
# ─────────────────────────────────────────────────────────
@app.route("/<path:path>", methods=["GET","POST","PUT","PATCH","DELETE","OPTIONS"])
def proxy_or_static(path: str):
    full = "/" + path

    # 1. בדוק אם זו קריאת API — נתב לbackend המתאים
    for prefix, backend_key in ROUTES:
        if full.startswith(prefix):
            target = BACKENDS[backend_key] + full
            log.info(f"→ {request.method} {full}  ⟶  {backend_key} ({BACKENDS[backend_key]})")
            return _proxy(BACKENDS[backend_key])

    # 2. קובץ סטטי — HTML, CSS, JS, CSV וכו'
    file_path = STATIC_DIR / path
    if file_path.is_file():
        log.info(f"📄 {full}")
        return send_from_directory(str(STATIC_DIR), path)

    # 3. לא נמצא — החזר index (SPA fallback)
    index = STATIC_DIR / "new_stite.html"
    if index.exists():
        log.info(f"↩️  SPA fallback: {full} → new_stite.html")
        return send_from_directory(str(STATIC_DIR), "new_stite.html")

    return jsonify({"error": "לא נמצא"}), 404

# ─────────────────────────────────────────────────────────
# ROOT — הגש index.html / new_stite.html
# ─────────────────────────────────────────────────────────
@app.route("/")
def root():
    # נסה new_stite.html קודם (הדף הראשי האמיתי), אחר כך index.html
    for name in ("new_stite.html", "index.html"):
        f = STATIC_DIR / name
        if f.exists():
            log.info(f"🏠 / → {name}")
            return send_from_directory(str(STATIC_DIR), name)
    return jsonify({"error": "index לא נמצא"}), 404

# ─────────────────────────────────────────────────────────
# HEALTH — בדיקת חיות הראוטר + כל הbackends
# ─────────────────────────────────────────────────────────
@app.route("/router/health")
def router_health():
    status = {}
    for name, url in BACKENDS.items():
        try:
            r = req.get(url + "/health", timeout=2)
            status[name] = {"ok": r.ok, "code": r.status_code}
        except Exception as e:
            status[name] = {"ok": False, "error": str(e)}
    all_ok = all(v["ok"] for v in status.values())
    return jsonify({
        "router": "ok",
        "port":   ROUTER_PORT,
        "backends": status
    }), 200 if all_ok else 207

# ─────────────────────────────────────────────────────────
# STARTUP
# ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    log.info("=" * 55)
    log.info(f"🚀  Mandeles Router מופעל על פורט {ROUTER_PORT}")
    log.info(f"📁  קבצים סטטיים: {STATIC_DIR}")
    log.info("─" * 55)
    for prefix, key in ROUTES:
        log.info(f"   {prefix:<18} → {key:<14} ({BACKENDS[key]})")
    log.info("=" * 55)
    log.info(f"🌐  פתח בדפדפן: http://localhost:{ROUTER_PORT}")
    log.info(f"🔍  בדיקת בריאות: http://localhost:{ROUTER_PORT}/router/health")
    log.info("=" * 55)

    app.run(
        host  = "0.0.0.0",
        port  = ROUTER_PORT,
        debug = os.getenv("FLASK_ENV") == "development",
        threaded = True,
    )
