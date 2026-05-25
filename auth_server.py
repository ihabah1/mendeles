"""
mandeles.co.il – Auth Server (auth_server.py)
=============================================
פורט 5002 | עצמאי מה-engine (5001)

מה מטפל כאן:
  POST /auth/login/email        – כניסה אימייל + סיסמה
  POST /auth/otp/send           – שלח SMS OTP (Twilio Verify)
  POST /auth/otp/verify         – אמת OTP
  POST /auth/register           – הרשמה (email+pw+phone או phone בלבד)
  POST /auth/forgot-password    – שלח מייל לאיפוס
  POST /auth/reset-password     – איפוס סיסמה
  GET  /auth/google             – Google OAuth redirect
  GET  /auth/google/callback    – Google OAuth callback
  GET  /auth/apple              – Apple Sign In redirect
  POST /auth/apple/callback     – Apple Sign In callback
  GET  /auth/me                 – פרטי משתמש מחובר (JWT)
  POST /auth/logout             – התנתקות

pip install flask flask-cors python-dotenv bcrypt pyjwt requests cryptography
"""

import os, sys, json, secrets, logging, datetime, hashlib, hmac, time
from typing import Optional
import sqlite3

import requests
import bcrypt
import jwt
from flask import Flask, request, jsonify, redirect, make_response
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────────────────────
# CONFIG – חובה ב-.env
# ─────────────────────────────────────────────────────────────
def _require(key: str) -> str:
    v = os.getenv(key)
    if not v:
        print(f"❌ FATAL: {key} לא מוגדר ב-.env", file=sys.stderr)
        sys.exit(1)
    return v

JWT_SECRET          = _require("JWT_SECRET")
TWILIO_ACCOUNT_SID  = _require("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN   = _require("TWILIO_AUTH_TOKEN")
TWILIO_VERIFY_SID   = _require("TWILIO_VERIFY_SID")   # Verify Service SID
GOOGLE_CLIENT_ID    = _require("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET= _require("GOOGLE_CLIENT_SECRET")
APPLE_CLIENT_ID     = _require("APPLE_CLIENT_ID")      # "com.mandeles.web"
APPLE_TEAM_ID       = _require("APPLE_TEAM_ID")
APPLE_KEY_ID        = _require("APPLE_KEY_ID")
APPLE_PRIVATE_KEY   = _require("APPLE_PRIVATE_KEY").replace("\\n", "\n")
SITE_URL            = os.getenv("SITE_URL",   "https://mandeles.co.il")
AUTH_PORT           = int(os.getenv("AUTH_PORT", 5002))
ALLOWED_ORIGINS     = os.getenv("ALLOWED_ORIGINS",
                                 "https://mandeles.co.il,https://www.mandeles.co.il").split(",")
DB_PATH             = os.getenv("AUTH_DB_PATH", "data/auth.db")
JWT_EXPIRE_DAYS     = int(os.getenv("JWT_EXPIRE_DAYS", 30))
SMTP_HOST           = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT           = int(os.getenv("SMTP_PORT", 587))
SMTP_USER           = os.getenv("SMTP_USER", "")
SMTP_PASS           = os.getenv("SMTP_PASS", "")
FROM_EMAIL          = os.getenv("FROM_EMAIL", "noreply@mandeles.co.il")

os.makedirs("data", exist_ok=True)
os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [AUTH] %(levelname)s %(message)s",
    handlers=[logging.FileHandler("logs/auth.log"), logging.StreamHandler()]
)
log = logging.getLogger("auth")

app = Flask(__name__)
CORS(app, origins=ALLOWED_ORIGINS, supports_credentials=True)

# ─────────────────────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────────────────────
def get_db():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    with get_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL,
            email       TEXT    UNIQUE,
            phone       TEXT    UNIQUE,
            pw_hash     TEXT,                  -- NULL עבור OAuth
            provider    TEXT    DEFAULT 'local',  -- local/google/apple/phone
            provider_id TEXT,
            email_verified INTEGER DEFAULT 0,
            phone_verified INTEGER DEFAULT 0,
            active       INTEGER DEFAULT 1,
            created_at   TEXT    DEFAULT CURRENT_TIMESTAMP,
            last_login   TEXT
        );

        CREATE TABLE IF NOT EXISTS reset_tokens (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            token      TEXT    NOT NULL UNIQUE,
            expires_at TEXT    NOT NULL,
            used       INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS auth_log (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id   INTEGER,
            event     TEXT,
            ip        TEXT,
            user_agent TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """)
    log.info("✅ Auth DB אותחל")

# ─────────────────────────────────────────────────────────────
# JWT HELPERS
# ─────────────────────────────────────────────────────────────
def create_jwt(user_id: int, email: str = None, phone: str = None) -> str:
    payload = {
        "sub":    user_id,
        "email":  email,
        "phone":  phone,
        "iat":    int(time.time()),
        "exp":    int(time.time()) + JWT_EXPIRE_DAYS * 86400,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def verify_jwt(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

def get_token_from_request() -> Optional[str]:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return request.cookies.get("auth_token")

def jwt_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        token = get_token_from_request()
        if not token:
            return jsonify({"error": "לא מחובר"}), 401
        payload = verify_jwt(token)
        if not payload:
            return jsonify({"error": "טוקן לא תקין או פג תוקף"}), 401
        request.user_id = payload["sub"]
        return f(*args, **kwargs)
    return decorated

def _auth_response(user_row: sqlite3.Row) -> dict:
    """בונה תשובת JSON + JWT cookie עם redirect."""
    token = create_jwt(user_row["id"], user_row["email"], user_row["phone"])
    return {
        "token":    token,
        "user": {
            "id":    user_row["id"],
            "name":  user_row["name"],
            "email": user_row["email"],
            "phone": user_row["phone"],
        },
        "redirect": "/"
    }

def _set_cookie(resp, token: str):
    resp.set_cookie(
        "auth_token", token,
        max_age=JWT_EXPIRE_DAYS * 86400,
        httponly=True,
        secure=True,
        samesite="Lax",
        domain=".mandeles.co.il"   # שנה לפי הדומיין שלך
    )

def _log_event(user_id, event: str):
    try:
        with get_db() as db:
            db.execute(
                "INSERT INTO auth_log(user_id,event,ip,user_agent) VALUES(?,?,?,?)",
                (user_id, event,
                 request.headers.get("X-Forwarded-For", request.remote_addr),
                 request.headers.get("User-Agent", "")[:200])
            )
    except Exception as e:
        log.error(f"log_event error: {e}")

# ─────────────────────────────────────────────────────────────
# PASSWORD HELPERS
# ─────────────────────────────────────────────────────────────
def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(12)).decode()

def check_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except Exception:
        return False

def validate_password(pw: str) -> Optional[str]:
    if len(pw) < 8:
        return "סיסמה חייבת להכיל לפחות 8 תווים"
    return None

# ─────────────────────────────────────────────────────────────
# TWILIO VERIFY (SMS OTP)
# ─────────────────────────────────────────────────────────────
class TwilioVerify:
    BASE = f"https://verify.twilio.com/v2/Services/{TWILIO_VERIFY_SID}"

    def send(self, phone: str) -> tuple[bool, str]:
        """שולח קוד OTP ל-phone."""
        try:
            r = requests.post(
                f"{self.BASE}/Verifications",
                auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
                data={"To": phone, "Channel": "sms", "Locale": "he"},
                timeout=10
            )
            if r.status_code in (200, 201):
                return True, "נשלח"
            err = r.json().get("message", "שגיאה")
            log.warning(f"Twilio send error {r.status_code}: {err}")
            return False, err
        except Exception as e:
            log.error(f"Twilio send exception: {e}")
            return False, "שגיאת תקשורת"

    def verify(self, phone: str, code: str) -> bool:
        """מאמת קוד OTP."""
        try:
            r = requests.post(
                f"{self.BASE}/VerificationChecks",
                auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
                data={"To": phone, "Code": code},
                timeout=10
            )
            d = r.json()
            return d.get("status") == "approved"
        except Exception as e:
            log.error(f"Twilio verify exception: {e}")
            return False

twilio = TwilioVerify()

# ─────────────────────────────────────────────────────────────
# EMAIL (SMTP – לאיפוס סיסמה)
# ─────────────────────────────────────────────────────────────
def send_reset_email(to_email: str, reset_link: str):
    if not SMTP_USER:
        log.warning("SMTP לא מוגדר – דלג על שליחת מייל (dev mode)")
        return
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "איפוס סיסמה – Mandeles.co.il"
    msg["From"]    = FROM_EMAIL
    msg["To"]      = to_email

    html = f"""
    <div dir="rtl" style="font-family:Heebo,sans-serif;max-width:480px;margin:0 auto;background:#0d1b2a;padding:32px;border-radius:12px">
      <h2 style="color:#c9a84c;font-size:1.3rem;margin-bottom:16px">🎯 Mandeles.co.il – איפוס סיסמה</h2>
      <p style="color:#e8dcc8;font-size:.9rem;line-height:1.6">קיבלנו בקשה לאיפוס הסיסמה שלך.</p>
      <p style="margin:20px 0">
        <a href="{reset_link}" style="background:#c9a84c;color:#0d1b2a;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:800;font-size:.9rem">איפוס סיסמה</a>
      </p>
      <p style="color:#8aaabe;font-size:.76rem">הקישור תקף ל-2 שעות. אם לא ביקשת איפוס – התעלם ממייל זה.</p>
    </div>
    """
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(FROM_EMAIL, to_email, msg.as_string())
        log.info(f"Reset email sent to {to_email}")
    except Exception as e:
        log.error(f"SMTP error: {e}")

# ─────────────────────────────────────────────────────────────
# GOOGLE OAUTH
# ─────────────────────────────────────────────────────────────
GOOGLE_AUTH_URL     = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL    = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

# state: random token stored in cookie for CSRF protection
_google_states: dict = {}

@app.route("/auth/google")
def google_login():
    state = secrets.token_urlsafe(32)
    mode  = request.args.get("mode", "login")
    _google_states[state] = {"mode": mode, "ts": time.time()}

    params = {
        "client_id":     GOOGLE_CLIENT_ID,
        "redirect_uri":  f"{SITE_URL}/auth/google/callback",
        "response_type": "code",
        "scope":         "openid email profile",
        "state":         state,
        "prompt":        "select_account",
        "access_type":   "online"
    }
    url = GOOGLE_AUTH_URL + "?" + "&".join(f"{k}={requests.utils.quote(v)}" for k,v in params.items())
    resp = make_response(redirect(url))
    resp.set_cookie("g_state", state, httponly=True, secure=True, samesite="Lax", max_age=600)
    return resp

@app.route("/auth/google/callback")
def google_callback():
    code       = request.args.get("code")
    state      = request.args.get("state")
    state_data = _google_states.pop(state, None)

    if not code or not state_data or (time.time() - state_data["ts"]) > 600:
        return redirect(f"{SITE_URL}/auth?error=google_state")

    # Exchange code for token
    try:
        r = requests.post(GOOGLE_TOKEN_URL, data={
            "code":          code,
            "client_id":     GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri":  f"{SITE_URL}/auth/google/callback",
            "grant_type":    "authorization_code"
        }, timeout=10)
        tokens    = r.json()
        id_token  = tokens.get("id_token")
        if not id_token:
            return redirect(f"{SITE_URL}/auth?error=google_token")

        # Get user info
        ui = requests.get(GOOGLE_USERINFO_URL,
                          headers={"Authorization": f"Bearer {tokens['access_token']}"},
                          timeout=10).json()
    except Exception as e:
        log.error(f"Google callback error: {e}")
        return redirect(f"{SITE_URL}/auth?error=google_fetch")

    email       = ui.get("email", "").lower()
    name        = ui.get("name", "")
    provider_id = ui.get("sub", "")

    with get_db() as db:
        user = db.execute(
            "SELECT * FROM users WHERE provider='google' AND provider_id=?", (provider_id,)
        ).fetchone()
        if not user:
            user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()

        if not user:
            # הרשמה חדשה
            cur = db.execute(
                "INSERT INTO users(name,email,provider,provider_id,email_verified) VALUES(?,?,?,?,1)",
                (name, email, "google", provider_id)
            )
            user_id = cur.lastrowid
            user    = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            log.info(f"New Google user: {email}")
        else:
            db.execute("UPDATE users SET last_login=CURRENT_TIMESTAMP WHERE id=?", (user["id"],))

    _log_event(user["id"], "google_login")
    token = create_jwt(user["id"], user["email"], user["phone"])
    resp  = make_response(redirect(SITE_URL))
    _set_cookie(resp, token)
    return resp

# ─────────────────────────────────────────────────────────────
# APPLE SIGN IN
# ─────────────────────────────────────────────────────────────
_apple_states: dict = {}

def _apple_client_secret() -> str:
    """יוצר JWT חתום עם המפתח הפרטי של Apple."""
    now = int(time.time())
    payload = {
        "iss": APPLE_TEAM_ID,
        "iat": now,
        "exp": now + 86400,
        "aud": "https://appleid.apple.com",
        "sub": APPLE_CLIENT_ID,
    }
    return jwt.encode(payload, APPLE_PRIVATE_KEY,
                      algorithm="ES256",
                      headers={"kid": APPLE_KEY_ID})

@app.route("/auth/apple")
def apple_login():
    state = secrets.token_urlsafe(32)
    _apple_states[state] = {"ts": time.time()}

    params = {
        "client_id":     APPLE_CLIENT_ID,
        "redirect_uri":  f"{SITE_URL}/auth/apple/callback",
        "response_type": "code id_token",
        "scope":         "name email",
        "response_mode": "form_post",
        "state":         state,
    }
    url = "https://appleid.apple.com/auth/authorize?" + "&".join(
        f"{k}={requests.utils.quote(str(v))}" for k,v in params.items()
    )
    resp = make_response(redirect(url))
    resp.set_cookie("a_state", state, httponly=True, secure=True, samesite="None", max_age=600)
    return resp

@app.route("/auth/apple/callback", methods=["POST"])
def apple_callback():
    code       = request.form.get("code")
    state      = request.form.get("state")
    id_token   = request.form.get("id_token")
    user_json  = request.form.get("user")   # רק בהרשמה ראשונה
    state_data = _apple_states.pop(state, None)

    if not code or not state_data or (time.time() - state_data["ts"]) > 600:
        return redirect(f"{SITE_URL}/auth?error=apple_state")

    try:
        # decode id_token (skip verify in dev – use python-jwt verify in prod)
        claims = jwt.decode(id_token, options={"verify_signature": False})
        email  = claims.get("email", "")
        sub    = claims.get("sub", "")   # Apple user ID

        name = ""
        if user_json:
            u_data = json.loads(user_json)
            fn = u_data.get("name", {}).get("firstName", "")
            ln = u_data.get("name", {}).get("lastName", "")
            name = f"{fn} {ln}".strip()

    except Exception as e:
        log.error(f"Apple callback decode error: {e}")
        return redirect(f"{SITE_URL}/auth?error=apple_decode")

    with get_db() as db:
        user = db.execute(
            "SELECT * FROM users WHERE provider='apple' AND provider_id=?", (sub,)
        ).fetchone()
        if not user and email:
            user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()

        if not user:
            cur = db.execute(
                "INSERT INTO users(name,email,provider,provider_id,email_verified) VALUES(?,?,?,?,1)",
                (name or email, email, "apple", sub)
            )
            user_id = cur.lastrowid
            user    = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            log.info(f"New Apple user: {email or sub}")
        else:
            db.execute("UPDATE users SET last_login=CURRENT_TIMESTAMP WHERE id=?", (user["id"],))

    _log_event(user["id"], "apple_login")
    token = create_jwt(user["id"], user["email"], user["phone"])
    resp  = make_response(redirect(SITE_URL))
    _set_cookie(resp, token)
    return resp

# ─────────────────────────────────────────────────────────────
# EMAIL + PASSWORD
# ─────────────────────────────────────────────────────────────
@app.route("/auth/login/email", methods=["POST"])
def login_email():
    d     = request.get_json(silent=True) or {}
    email = (d.get("email") or "").strip().lower()
    pw    = d.get("password") or ""

    if not email or not pw:
        return jsonify({"error": "חסרים פרטים"}), 400

    with get_db() as db:
        user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()

    if not user or not user["pw_hash"] or not check_password(pw, user["pw_hash"]):
        _log_event(None, f"login_fail_email:{email[:30]}")
        return jsonify({"error": "אימייל או סיסמה שגויים"}), 401

    if not user["active"]:
        return jsonify({"error": "חשבון מושהה – צור קשר עם התמיכה"}), 403

    with get_db() as db:
        db.execute("UPDATE users SET last_login=CURRENT_TIMESTAMP WHERE id=?", (user["id"],))

    _log_event(user["id"], "email_login")
    data  = _auth_response(user)
    resp  = make_response(jsonify(data))
    _set_cookie(resp, data["token"])
    return resp

# ─────────────────────────────────────────────────────────────
# OTP – שלח / אמת
# ─────────────────────────────────────────────────────────────
@app.route("/auth/otp/send", methods=["POST"])
def otp_send():
    d       = request.get_json(silent=True) or {}
    phone   = (d.get("phone") or "").strip()
    context = d.get("context", "login")

    if not phone or len(phone) < 7:
        return jsonify({"error": "מספר טלפון לא תקין"}), 400

    ok, msg = twilio.send(phone)
    if not ok:
        return jsonify({"error": msg}), 500

    log.info(f"OTP sent to {phone[:6]}***  context={context}")
    return jsonify({"status": "sent"})

@app.route("/auth/otp/verify", methods=["POST"])
def otp_verify():
    d       = request.get_json(silent=True) or {}
    phone   = (d.get("phone") or "").strip()
    code    = (d.get("code")  or "").strip()
    context = d.get("context", "login")

    if not phone or not code or len(code) != 6:
        return jsonify({"error": "חסרים פרטים"}), 400

    if not twilio.verify(phone, code):
        _log_event(None, f"otp_fail:{phone[:7]}")
        return jsonify({"error": "קוד שגוי או פג תוקף"}), 401

    # Login via phone
    with get_db() as db:
        user = db.execute("SELECT * FROM users WHERE phone=?", (phone,)).fetchone()

    if not user:
        return jsonify({"error": "מספר טלפון לא רשום – אנא הירשם"}), 404

    if not user["active"]:
        return jsonify({"error": "חשבון מושהה"}), 403

    with get_db() as db:
        db.execute("UPDATE users SET last_login=CURRENT_TIMESTAMP, phone_verified=1 WHERE id=?", (user["id"],))

    _log_event(user["id"], "otp_login")
    data = _auth_response(user)
    resp = make_response(jsonify(data))
    _set_cookie(resp, data["token"])
    return resp

# ─────────────────────────────────────────────────────────────
# REGISTER
# ─────────────────────────────────────────────────────────────
@app.route("/auth/register", methods=["POST"])
def register():
    d       = request.get_json(silent=True) or {}
    phone   = (d.get("phone")    or "").strip()
    code    = (d.get("code")     or "").strip()
    method  = d.get("method",  "phone")
    name    = (d.get("name")     or "").strip()
    email   = (d.get("email")    or "").strip().lower()
    pw      = d.get("password") or ""

    if not phone or not code or not name:
        return jsonify({"error": "חסרים פרטים"}), 400

    # אמת OTP
    if not twilio.verify(phone, code):
        return jsonify({"error": "קוד אימות שגוי"}), 401

    # בדוק כפילות
    with get_db() as db:
        if db.execute("SELECT id FROM users WHERE phone=?", (phone,)).fetchone():
            return jsonify({"error": "מספר טלפון כבר רשום – אנא התחבר"}), 409

        if email and db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
            return jsonify({"error": "אימייל כבר רשום – אנא התחבר"}), 409

    # ולידציה
    if method == "email":
        if not email:
            return jsonify({"error": "נא לספק אימייל"}), 400
        pw_err = validate_password(pw)
        if pw_err:
            return jsonify({"error": pw_err}), 400
        pw_hash = hash_password(pw)
    else:
        pw_hash = None

    with get_db() as db:
        cur = db.execute(
            """INSERT INTO users
               (name, email, phone, pw_hash, provider, phone_verified, email_verified)
               VALUES (?,?,?,?,?,1,?)""",
            (name, email or None, phone, pw_hash,
             "local", 1 if email else 0)
        )
        user_id = cur.lastrowid
        user    = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()

    _log_event(user["id"], "register")
    log.info(f"New user registered: {phone[:7]}*** method={method}")
    data = _auth_response(user)
    resp = make_response(jsonify(data))
    _set_cookie(resp, data["token"])
    return resp, 201

# ─────────────────────────────────────────────────────────────
# FORGOT / RESET PASSWORD
# ─────────────────────────────────────────────────────────────
@app.route("/auth/forgot-password", methods=["POST"])
def forgot_password():
    d     = request.get_json(silent=True) or {}
    email = (d.get("email") or "").strip().lower()
    if not email:
        return jsonify({"error": "נא לספק אימייל"}), 400

    with get_db() as db:
        user = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()

    # תמיד החזר OK כדי לא לחשוף אם המייל קיים
    if user:
        token   = secrets.token_urlsafe(48)
        expires = (datetime.datetime.utcnow() + datetime.timedelta(hours=2)).isoformat()
        with get_db() as db:
            db.execute(
                "INSERT INTO reset_tokens(user_id,token,expires_at) VALUES(?,?,?)",
                (user["id"], token, expires)
            )
        reset_link = f"{SITE_URL}/reset-password?token={token}"
        send_reset_email(email, reset_link)

    return jsonify({"status": "ok", "message": f"אם {email} קיים, ישלח קישור"})

@app.route("/auth/reset-password", methods=["POST"])
def reset_password():
    d     = request.get_json(silent=True) or {}
    token = (d.get("token") or "").strip()
    pw    = d.get("password") or ""

    if not token or not pw:
        return jsonify({"error": "חסרים פרטים"}), 400

    pw_err = validate_password(pw)
    if pw_err:
        return jsonify({"error": pw_err}), 400

    with get_db() as db:
        row = db.execute(
            "SELECT * FROM reset_tokens WHERE token=? AND used=0", (token,)
        ).fetchone()

    if not row:
        return jsonify({"error": "טוקן לא תקין"}), 400

    if datetime.datetime.utcnow().isoformat() > row["expires_at"]:
        return jsonify({"error": "הטוקן פג תוקף – בקש קישור חדש"}), 400

    pw_hash = hash_password(pw)
    with get_db() as db:
        db.execute("UPDATE users SET pw_hash=? WHERE id=?", (pw_hash, row["user_id"]))
        db.execute("UPDATE reset_tokens SET used=1 WHERE id=?", (row["id"],))

    _log_event(row["user_id"], "password_reset")
    return jsonify({"status": "ok", "message": "הסיסמה עודכנה – אנא התחבר"})

# ─────────────────────────────────────────────────────────────
# ME + LOGOUT
# ─────────────────────────────────────────────────────────────
@app.route("/auth/me")
@jwt_required
def me():
    with get_db() as db:
        user = db.execute(
            "SELECT id,name,email,phone,provider,created_at,last_login FROM users WHERE id=?",
            (request.user_id,)
        ).fetchone()
    if not user:
        return jsonify({"error": "משתמש לא נמצא"}), 404
    return jsonify(dict(user))

@app.route("/auth/logout", methods=["POST"])
def logout():
    resp = make_response(jsonify({"status": "ok"}))
    resp.set_cookie("auth_token", "", expires=0, httponly=True, secure=True,
                    samesite="Lax", domain=".mandeles.co.il")
    return resp

# ─────────────────────────────────────────────────────────────
# SECURITY HEADERS
# ─────────────────────────────────────────────────────────────
@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"]         = "DENY"
    response.headers["Referrer-Policy"]          = "no-referrer"
    return response

@app.errorhandler(404)
def nf(e): return jsonify({"error": "לא נמצא"}), 404
@app.errorhandler(500)
def se(e): return jsonify({"error": "שגיאת שרת"}), 500

# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    log.info(f"🔐 Auth Server | פורט {AUTH_PORT}")
    app.run(host="0.0.0.0", port=AUTH_PORT, debug=False)
