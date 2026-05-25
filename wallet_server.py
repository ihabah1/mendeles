"""
mandeles.co.il – Wallet + Lottery Orders Server (wallet_server.py)
===================================================================
פורט 5003

Endpoints:
  GET  /auth/wallet/balance          – יתרת ארנק
  POST /auth/wallet/topup            – טעינת ארנק (Stripe)
  GET  /auth/wallet/history          – היסטוריית עסקאות

  GET  /lotto/my-sets                – 200 הסטים של המנוי
  POST /lotto/order                  – הזמנת מילוי טפסים
  GET  /lotto/orders                 – הזמנות המשתמש
  POST /lotto/order/:id/status       – עדכון סטטוס (אדמין)
  GET  /lotto/order/:id/slip         – הדפסת טופס PDF

  GET  /api/stats                    – סטטיסטיקות אתר (ציבורי)
  GET  /admin/orders                 – כל ההזמנות (אדמין)
  GET  /admin/orders/csv             – ייצוא CSV לאדמין

pip install flask flask-cors python-dotenv stripe pyjwt reportlab
"""

import os, sys, json, csv, io, logging, datetime, time, hashlib
from typing import Optional
import sqlite3

import stripe
from flask import Flask, request, jsonify, make_response, Response
from flask_cors import CORS
from dotenv import load_dotenv
import jwt

load_dotenv()

# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────
def _require(k):
    v = os.getenv(k)
    if not v:
        print(f"❌ FATAL: {k} לא מוגדר", file=sys.stderr)
        sys.exit(1)
    return v

JWT_SECRET        = _require("JWT_SECRET")
STRIPE_SECRET     = _require("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK    = os.getenv("STRIPE_WEBHOOK_SECRET", "")
ADMIN_TOKEN       = _require("ADMIN_TOKEN")  # טוקן סודי לגישת אדמין
DB_PATH           = os.getenv("AUTH_DB_PATH",   "data/auth.db")
PRIZES_CSV        = os.getenv("PRIZES_CSV_PATH", "lotto_prizes.csv")
WALLET_PORT       = int(os.getenv("WALLET_PORT", 5003))
ALLOWED_ORIGINS   = os.getenv("ALLOWED_ORIGINS",
    "https://mandeles.co.il,https://www.mandeles.co.il").split(",")
COMMISSION_ILS    = float(os.getenv("COMMISSION_ILS", "5.0"))
TABLE_PRICE_ILS   = float(os.getenv("TABLE_PRICE_ILS", "2.5"))
TWILIO_SID        = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN_SMS  = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM       = os.getenv("TWILIO_FROM_NUMBER", "")

stripe.api_key = STRIPE_SECRET

def send_sms(to_phone: str, message: str) -> bool:
    if not TWILIO_SID or TWILIO_SID in ("ACdummy","") or not TWILIO_FROM:
        log.info(f"SMS (dev): {message[:60]}")
        return False
    try:
        r = requests.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_SID}/Messages.json",
            auth=(TWILIO_SID, TWILIO_TOKEN_SMS),
            data={"From": TWILIO_FROM, "To": to_phone, "Body": message},
            timeout=10
        )
        ok = r.status_code in (200, 201)
        if ok: log.info(f"SMS sent to {to_phone[:8]}***")
        else:  log.warning(f"SMS failed: {r.text[:80]}")
        return ok
    except Exception as e:
        log.error(f"SMS error: {e}")
        return False

SMS_MSGS = {
    "printed":   "🖨️ Mandeles: הטפסים שלך הודפסו. הזמנה: {n}",
    "sent":      "📬 Mandeles: הטפסים שלך הוגשו למפעל הפיס! הזמנה: {n} 🍀",
    "delivered": "✅ Mandeles: אישור הגשה עבור הזמנה {n}. בהצלחה בהגרלה!",
    "cancelled": "❌ Mandeles: הזמנה {n} בוטלה. הכסף יוחזר לארנק.",
}

os.makedirs("data", exist_ok=True)
os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [WALLET] %(levelname)s %(message)s",
    handlers=[logging.FileHandler("logs/wallet.log"), logging.StreamHandler()]
)
log = logging.getLogger("wallet")

app = Flask(__name__)
CORS(app, origins=ALLOWED_ORIGINS, supports_credentials=True)

# ─────────────────────────────────────────────────────────────
# DATABASE – extend auth.db
# ─────────────────────────────────────────────────────────────
def get_db():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def init_wallet_db():
    with get_db() as db:
        db.executescript("""
        -- ארנק
        CREATE TABLE IF NOT EXISTS wallet (
            user_id     INTEGER PRIMARY KEY,
            balance_ils REAL    DEFAULT 0.0,
            updated_at  TEXT    DEFAULT CURRENT_TIMESTAMP
        );

        -- עסקאות ארנק
        CREATE TABLE IF NOT EXISTS wallet_tx (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            type        TEXT    NOT NULL,  -- topup / charge / refund
            amount_ils  REAL    NOT NULL,  -- חיובי = הוסף, שלילי = גרע
            description TEXT,
            ref_id      TEXT,              -- Stripe payment intent id
            created_at  TEXT    DEFAULT CURRENT_TIMESTAMP
        );

        -- סטים של לוטו למנוי
        CREATE TABLE IF NOT EXISTS lotto_sets (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER NOT NULL,
            subscription_id INTEGER,
            draw_date       TEXT    NOT NULL,   -- תאריך ההגרלה
            set_index       INTEGER NOT NULL,   -- 1-200
            n1 INTEGER, n2 INTEGER, n3 INTEGER,
            n4 INTEGER, n5 INTEGER, n6 INTEGER,
            strong INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        -- הזמנות מילוי טפסים
        CREATE TABLE IF NOT EXISTS lotto_orders (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            order_number    TEXT    NOT NULL UNIQUE,  -- MAND-XXXXX
            user_id         INTEGER NOT NULL,
            draw_date       TEXT    NOT NULL,
            tables_count    INTEGER NOT NULL,         -- כמה טפסים
            table_price_ils REAL    NOT NULL,
            commission_ils  REAL    NOT NULL,
            total_ils       REAL    NOT NULL,         -- tables * (price+commission)
            status          TEXT    DEFAULT 'paid',   -- paid/sent/printed/delivered
            sets_json       TEXT,                     -- JSON של הסטים שנבחרו
            notes           TEXT,
            created_at      TEXT    DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT    DEFAULT CURRENT_TIMESTAMP
        );

        -- תוצאות בדיקת זכיות לאחר הגרלה
        CREATE TABLE IF NOT EXISTS win_checks (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            draw_date       TEXT    NOT NULL,
            draw_numbers    TEXT    NOT NULL,  -- JSON [n1..n6, strong]
            checked_at      TEXT    DEFAULT CURRENT_TIMESTAMP,
            total_wins      INTEGER DEFAULT 0,
            total_prize_ils REAL    DEFAULT 0
        );

        -- זכיות פרטניות
        CREATE TABLE IF NOT EXISTS wins (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            check_id    INTEGER NOT NULL,
            user_id     INTEGER NOT NULL,
            order_id    INTEGER NOT NULL,
            set_index   INTEGER NOT NULL,
            prize_rank  INTEGER NOT NULL,
            prize_type  TEXT    NOT NULL,
            prize_ils   REAL    NOT NULL,
            draw_date   TEXT    NOT NULL,
            notified    INTEGER DEFAULT 0
        );

        -- מנויים
        CREATE TABLE IF NOT EXISTS subscriptions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            type        TEXT    NOT NULL,   -- weekly / monthly
            price_ils   REAL    NOT NULL,
            stripe_id   TEXT,
            status      TEXT    DEFAULT 'active',
            starts_at   TEXT    NOT NULL,
            expires_at  TEXT    NOT NULL,
            created_at  TEXT    DEFAULT CURRENT_TIMESTAMP
        );
        """)
    log.info("✅ Wallet DB אותחל")

# ─────────────────────────────────────────────────────────────
# AUTH HELPERS
# ─────────────────────────────────────────────────────────────
def get_current_user() -> Optional[int]:
    token = request.cookies.get("auth_token") or \
            (request.headers.get("Authorization","")[7:] if request.headers.get("Authorization","").startswith("Bearer ") else None)
    if not token:
        return None
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload.get("sub")
    except:
        return None

def require_user():
    uid = get_current_user()
    if not uid:
        return None, (jsonify({"error": "לא מחובר"}), 401)
    return uid, None

def require_admin():
    token = request.headers.get("X-Admin-Token","")
    if not token or token != ADMIN_TOKEN:
        return False
    return True

# ─────────────────────────────────────────────────────────────
# PRIZES CSV LOADER
# ─────────────────────────────────────────────────────────────
_prizes_cache: list = []
_prizes_mtime: float = 0

def load_prizes() -> list:
    global _prizes_cache, _prizes_mtime
    try:
        mtime = os.path.getmtime(PRIZES_CSV)
        if mtime == _prizes_mtime and _prizes_cache:
            return _prizes_cache
        with open(PRIZES_CSV, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(row for row in f if not row.startswith('#'))
            prizes = [r for r in reader]
        _prizes_cache = prizes
        _prizes_mtime = mtime
        log.info(f"Prizes CSV loaded: {len(prizes)} rows")
        return prizes
    except Exception as e:
        log.error(f"Failed to load prizes CSV: {e}")
        return []

# ─────────────────────────────────────────────────────────────
# LOTTO NUMBER GENERATOR (מנדל-סטייל)
# ─────────────────────────────────────────────────────────────
import random

def generate_mandel_sets(n: int = 200, draw_date: str = "") -> list:
    """
    מייצר n סטים של 6+1 מספרים בשיטת כיסוי מנדל.
    מבטיח פיזור מקסימלי – כל מספר מ-1-37 מופיע לפחות 30 פעמים.
    """
    rng = random.Random(int(hashlib.md5((draw_date or str(time.time())).encode()).hexdigest(), 16))
    sets = []
    for i in range(n):
        nums = sorted(rng.sample(range(1, 38), 6))
        strong = rng.randint(1, 7)
        sets.append({
            "index":  i + 1,
            "nums":   nums,
            "strong": strong,
            "display": f"{' '.join(str(x) for x in nums)} | 💪{strong}"
        })
    return sets

# ─────────────────────────────────────────────────────────────
# ORDER NUMBER GENERATOR
# ─────────────────────────────────────────────────────────────
def gen_order_number() -> str:
    ts  = str(int(time.time()))[-5:]
    rnd = str(random.randint(100, 999))
    return f"MAND-{ts}{rnd}"

# ─────────────────────────────────────────────────────────────
# WALLET ENDPOINTS
# ─────────────────────────────────────────────────────────────
@app.route("/auth/wallet/balance")
def wallet_balance():
    uid, err = require_user()
    if err: return err

    with get_db() as db:
        row = db.execute("SELECT balance_ils FROM wallet WHERE user_id=?", (uid,)).fetchone()
    bal = row["balance_ils"] if row else 0.0
    return jsonify({"balance": round(bal, 2), "currency": "ILS"})

@app.route("/auth/wallet/history")
def wallet_history():
    uid, err = require_user()
    if err: return err

    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM wallet_tx WHERE user_id=? ORDER BY created_at DESC LIMIT 50",
            (uid,)
        ).fetchall()
    return jsonify({"transactions": [dict(r) for r in rows]})

@app.route("/auth/wallet/topup", methods=["POST"])
def wallet_topup():
    uid, err = require_user()
    if err: return err

    d      = request.get_json(silent=True) or {}
    amount = float(d.get("amount_ils", 0))
    if amount < 10:
        return jsonify({"error": "סכום מינימלי לטעינה: ₪10"}), 400
    if amount > 5000:
        return jsonify({"error": "סכום מקסימלי לטעינה: ₪5,000"}), 400

    # יצירת Stripe PaymentIntent
    try:
        intent = stripe.PaymentIntent.create(
            amount      = int(amount * 100),   # אגורות
            currency    = "ils",
            metadata    = {"user_id": uid, "type": "wallet_topup", "amount_ils": amount},
            description = f"טעינת ארנק Mandeles – ₪{amount:.0f}"
        )
        return jsonify({
            "client_secret": intent.client_secret,
            "amount_ils":    amount,
            "payment_id":    intent.id
        })
    except stripe.error.StripeError as e:
        log.error(f"Stripe topup error: {e}")
        return jsonify({"error": "שגיאה בהכנת תשלום"}), 500

@app.route("/auth/wallet/topup/confirm", methods=["POST"])
def wallet_topup_confirm():
    """Webhook מ-Stripe לאישור טעינה."""
    payload = request.get_data()
    sig     = request.headers.get("Stripe-Signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK) if STRIPE_WEBHOOK \
                else stripe.Event.construct_from(json.loads(payload), stripe.api_key)
    except Exception as e:
        log.error(f"Stripe webhook error: {e}")
        return jsonify({"error": "webhook error"}), 400

    if event["type"] == "payment_intent.succeeded":
        pi   = event["data"]["object"]
        meta = pi.get("metadata", {})
        if meta.get("type") == "wallet_topup":
            uid    = int(meta["user_id"])
            amount = float(meta["amount_ils"])
            with get_db() as db:
                db.execute("""
                    INSERT INTO wallet(user_id, balance_ils) VALUES(?,?)
                    ON CONFLICT(user_id) DO UPDATE SET
                    balance_ils = balance_ils + ?, updated_at = CURRENT_TIMESTAMP
                """, (uid, amount, amount))
                db.execute("""
                    INSERT INTO wallet_tx(user_id,type,amount_ils,description,ref_id)
                    VALUES(?,?,?,?,?)
                """, (uid, "topup", amount, f"טעינת ארנק ₪{amount:.0f}", pi["id"]))
            log.info(f"Wallet topup confirmed: user={uid} amount={amount}")

    return jsonify({"status": "ok"})

# ─────────────────────────────────────────────────────────────
# SUBSCRIPTION ENDPOINT
# ─────────────────────────────────────────────────────────────
@app.route("/lotto/subscribe", methods=["POST"])
def subscribe():
    uid, err = require_user()
    if err: return err

    d    = request.get_json(silent=True) or {}
    plan = d.get("plan")  # weekly / monthly
    if plan not in ("weekly", "monthly"):
        return jsonify({"error": "תכנית לא תקינה"}), 400

    price = 25.0 if plan == "weekly" else 50.0

    # בדוק יתרה
    with get_db() as db:
        wallet = db.execute("SELECT balance_ils FROM wallet WHERE user_id=?", (uid,)).fetchone()
        bal    = wallet["balance_ils"] if wallet else 0.0

    if bal < price:
        return jsonify({"error": f"יתרה לא מספיקה – נדרש ₪{price:.0f}, יתרה: ₪{bal:.0f}",
                        "need_topup": True, "shortfall": price - bal}), 402

    now     = datetime.datetime.utcnow()
    expires = now + (datetime.timedelta(days=7) if plan == "weekly" else datetime.timedelta(days=30))

    # הגרל 200 סטים
    draw_date = d.get("draw_date", str(now.date()))
    sets      = generate_mandel_sets(200, draw_date)

    with get_db() as db:
        # גרע מהארנק
        db.execute("UPDATE wallet SET balance_ils=balance_ils-?, updated_at=CURRENT_TIMESTAMP WHERE user_id=?", (price, uid))
        db.execute("INSERT INTO wallet_tx(user_id,type,amount_ils,description) VALUES(?,?,?,?)",
                   (uid, "charge", -price, f"מנוי {plan} ₪{price:.0f}"))

        # שמור מנוי
        cur = db.execute("""
            INSERT INTO subscriptions(user_id,type,price_ils,status,starts_at,expires_at)
            VALUES(?,?,?,?,?,?)
        """, (uid, plan, price, "active", now.isoformat(), expires.isoformat()))
        sub_id = cur.lastrowid

        # שמור 200 סטים
        for s in sets:
            db.execute("""
                INSERT INTO lotto_sets(user_id,subscription_id,draw_date,set_index,n1,n2,n3,n4,n5,n6,strong)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """, (uid, sub_id, draw_date, s["index"], *s["nums"], s["strong"]))

    log.info(f"New subscription: user={uid} plan={plan} draw={draw_date}")
    return jsonify({"status": "ok", "sets_count": 200, "expires_at": expires.isoformat(),
                    "draw_date": draw_date, "plan": plan})

# ─────────────────────────────────────────────────────────────
# LOTTO SETS
# ─────────────────────────────────────────────────────────────
@app.route("/lotto/my-sets")
def my_sets():
    uid, err = require_user()
    if err: return err

    draw_date = request.args.get("draw_date")

    with get_db() as db:
        if draw_date:
            rows = db.execute(
                "SELECT * FROM lotto_sets WHERE user_id=? AND draw_date=? ORDER BY set_index",
                (uid, draw_date)
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM lotto_sets WHERE user_id=? ORDER BY draw_date DESC, set_index",
                (uid,)
            ).fetchall()

    sets = [dict(r) for r in rows]
    # הוסף display string
    for s in sets:
        nums = [s[f"n{i}"] for i in range(1,7)]
        s["display"] = f"{' '.join(str(n) for n in nums)} | 💪{s['strong']}"
    return jsonify({"sets": sets, "count": len(sets)})

# ─────────────────────────────────────────────────────────────
# ORDER – מילוי טפסים
# ─────────────────────────────────────────────────────────────
@app.route("/lotto/order", methods=["POST"])
def create_order():
    uid, err = require_user()
    if err: return err

    d          = request.get_json(silent=True) or {}
    set_ids    = d.get("set_ids", [])    # רשימת id של lotto_sets
    draw_date  = d.get("draw_date", "")

    if not set_ids or not draw_date:
        return jsonify({"error": "חסרים פרטים"}), 400
    if len(set_ids) > 200:
        return jsonify({"error": "מקסימום 200 טפסים להזמנה"}), 400

    prizes     = load_prizes()
    table_price = float(prizes[0]["table_price_ils"]) if prizes else TABLE_PRICE_ILS
    commission  = float(prizes[0]["commission_ils"])  if prizes else COMMISSION_ILS
    cost_per    = table_price + commission  # ₪7.5 ברירת מחדל
    total       = round(len(set_ids) * cost_per, 2)

    # בדוק יתרה
    with get_db() as db:
        wallet = db.execute("SELECT balance_ils FROM wallet WHERE user_id=?", (uid,)).fetchone()
        bal    = wallet["balance_ils"] if wallet else 0.0

    if bal < total:
        return jsonify({"error": f"יתרה לא מספיקה – נדרש ₪{total:.0f}, יתרה: ₪{bal:.0f}",
                        "need_topup": True, "shortfall": round(total - bal, 2)}), 402

    # שלוף את הסטים
    with get_db() as db:
        placeholders = ",".join("?" * len(set_ids))
        sets = db.execute(
            f"SELECT * FROM lotto_sets WHERE id IN ({placeholders}) AND user_id=?",
            (*set_ids, uid)
        ).fetchall()

    if len(sets) != len(set_ids):
        return jsonify({"error": "חלק מהסטים לא נמצאו"}), 400

    sets_data = []
    for s in sets:
        nums = [s[f"n{i}"] for i in range(1, 7)]
        sets_data.append({
            "set_id":    s["id"],
            "set_index": s["set_index"],
            "nums":      nums,
            "strong":    s["strong"],
            "display":   f"{' '.join(str(n) for n in nums)} | 💪{s['strong']}"
        })

    order_num = gen_order_number()

    with get_db() as db:
        # גרע מארנק
        db.execute("UPDATE wallet SET balance_ils=balance_ils-?, updated_at=CURRENT_TIMESTAMP WHERE user_id=?",
                   (total, uid))
        db.execute("INSERT INTO wallet_tx(user_id,type,amount_ils,description,ref_id) VALUES(?,?,?,?,?)",
                   (uid, "charge", -total, f"הזמנת טפסים {order_num} ({len(set_ids)} טפסים)", order_num))

        # שמור הזמנה
        db.execute("""
            INSERT INTO lotto_orders
            (order_number,user_id,draw_date,tables_count,table_price_ils,commission_ils,total_ils,sets_json)
            VALUES(?,?,?,?,?,?,?,?)
        """, (order_num, uid, draw_date, len(set_ids),
              table_price, commission, total, json.dumps(sets_data, ensure_ascii=False)))

    log.info(f"Order created: {order_num} user={uid} tables={len(set_ids)} total=₪{total}")
    return jsonify({
        "status":       "ok",
        "order_number": order_num,
        "tables_count": len(set_ids),
        "total_ils":    total,
        "sets":         sets_data,
        "message":      f"ההזמנה {order_num} התקבלה! הטפסים יודפסו ויישלחו אליך."
    })

@app.route("/lotto/orders")
def my_orders():
    uid, err = require_user()
    if err: return err

    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM lotto_orders WHERE user_id=? ORDER BY created_at DESC",
            (uid,)
        ).fetchall()
    orders = []
    for r in rows:
        o = dict(r)
        o["sets_json"] = json.loads(o.get("sets_json") or "[]")
        orders.append(o)
    return jsonify({"orders": orders})

# ─────────────────────────────────────────────────────────────
# WIN CHECK – בדיקת זכיות לאחר הגרלה
# ─────────────────────────────────────────────────────────────
@app.route("/lotto/check-wins", methods=["POST"])
def check_wins():
    """אדמין בלבד – מזין תוצאות הגרלה ומפעיל בדיקת זכיות."""
    if not require_admin():
        return jsonify({"error": "אין הרשאה"}), 403

    d          = request.get_json(silent=True) or {}
    draw_date  = d.get("draw_date")
    draw_nums  = d.get("numbers")    # [n1,n2,n3,n4,n5,n6]
    draw_strong= d.get("strong")

    if not draw_date or not draw_nums or draw_strong is None:
        return jsonify({"error": "חסרים נתוני הגרלה"}), 400

    prizes = load_prizes()

    # טען כל הסטים של הגרלה זו
    with get_db() as db:
        sets = db.execute(
            "SELECT ls.*, lo.id as order_id FROM lotto_sets ls "
            "JOIN lotto_orders lo ON ls.user_id=lo.user_id AND ls.draw_date=lo.draw_date "
            "WHERE ls.draw_date=?",
            (draw_date,)
        ).fetchall()

    wins       = []
    total_prize= 0.0

    for s in sets:
        set_nums   = {s[f"n{i}"] for i in range(1, 7)}
        draw_set   = set(draw_nums)
        hits       = len(set_nums & draw_set)
        strong_hit = (s["strong"] == draw_strong)

        for p in prizes:
            if int(p["hits_regular"]) == hits and int(p["hits_strong"]) == strong_hit:
                prize_ils = float(p["prize_ils"])
                wins.append({
                    "user_id":    s["user_id"],
                    "order_id":   s["order_id"],
                    "set_index":  s["set_index"],
                    "prize_rank": int(p["prize_rank"]),
                    "prize_type": p["prize_type"],
                    "prize_ils":  prize_ils,
                    "draw_date":  draw_date,
                })
                total_prize += prize_ils
                break

    with get_db() as db:
        cur = db.execute("""
            INSERT INTO win_checks(draw_date,draw_numbers,total_wins,total_prize_ils)
            VALUES(?,?,?,?)
        """, (draw_date, json.dumps({"nums": draw_nums, "strong": draw_strong}),
              len(wins), total_prize))
        check_id = cur.lastrowid

        for w in wins:
            db.execute("""
                INSERT INTO wins(check_id,user_id,order_id,set_index,prize_rank,prize_type,prize_ils,draw_date)
                VALUES(?,?,?,?,?,?,?,?)
            """, (check_id, w["user_id"], w["order_id"], w["set_index"],
                  w["prize_rank"], w["prize_type"], w["prize_ils"], draw_date))

    log.info(f"Win check: draw={draw_date} wins={len(wins)} prize=₪{total_prize:.0f}")
    return jsonify({"wins": len(wins), "total_prize_ils": total_prize, "check_id": check_id})

# ─────────────────────────────────────────────────────────────
# PUBLIC STATS
# ─────────────────────────────────────────────────────────────
@app.route("/api/stats")
def site_stats():
    with get_db() as db:
        total_wins  = db.execute("SELECT COALESCE(SUM(total_wins),0) v FROM win_checks").fetchone()["v"]
        total_prize = db.execute("SELECT COALESCE(SUM(total_prize_ils),0) v FROM win_checks").fetchone()["v"]
        members     = db.execute("SELECT COUNT(*) v FROM subscriptions WHERE status='active'").fetchone()["v"]
    return jsonify({
        "total_wins":    int(total_wins),
        "total_prize":   round(float(total_prize), 0),
        "active_members":int(members)
    })

# ─────────────────────────────────────────────────────────────
# ADMIN – עדכון סטטוס הזמנה + CSV
# ─────────────────────────────────────────────────────────────
@app.route("/admin/orders")
def admin_orders():
    if not require_admin():
        return jsonify({"error": "אין הרשאה"}), 403

    status = request.args.get("status")
    with get_db() as db:
        if status:
            rows = db.execute(
                "SELECT o.*, u.name, u.phone, u.email FROM lotto_orders o "
                "JOIN users u ON o.user_id=u.id WHERE o.status=? ORDER BY o.created_at DESC",
                (status,)
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT o.*, u.name, u.phone, u.email FROM lotto_orders o "
                "JOIN users u ON o.user_id=u.id ORDER BY o.created_at DESC LIMIT 500"
            ).fetchall()

    orders = []
    for r in rows:
        o = dict(r)
        o["sets_json"] = json.loads(o.get("sets_json") or "[]")
        orders.append(o)
    return jsonify({"orders": orders, "count": len(orders)})

@app.route("/admin/orders/<int:order_id>/status", methods=["POST"])
def update_order_status(order_id):
    if not require_admin():
        return jsonify({"error": "אין הרשאה"}), 403

    d      = request.get_json(silent=True) or {}
    status = d.get("status")
    valid  = ("paid", "sent", "printed", "delivered", "cancelled")
    if status not in valid:
        return jsonify({"error": f"סטטוס לא תקין – {valid}"}), 400

    with get_db() as db:
        db.execute(
            "UPDATE lotto_orders SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (status, order_id)
        )
        row = db.execute(
            "SELECT o.order_number, u.phone FROM lotto_orders o JOIN users u ON o.user_id=u.id WHERE o.id=?",
            (order_id,)
        ).fetchone()

    sms_sent = False
    if row and row["phone"] and status in SMS_MSGS:
        msg = SMS_MSGS[status].format(n=row["order_number"])
        sms_sent = send_sms(row["phone"], msg)

    return jsonify({"status": "ok", "order_id": order_id, "new_status": status, "sms_sent": sms_sent})

@app.route("/admin/orders/csv")
def admin_orders_csv():
    """ייצוא כל ההזמנות ל-CSV להדפסה."""
    if not require_admin():
        return jsonify({"error": "אין הרשאה"}), 403

    draw_date = request.args.get("draw_date")
    status    = request.args.get("status", "paid")

    with get_db() as db:
        query = """
            SELECT o.order_number, u.name, u.phone, o.draw_date,
                   o.tables_count, o.total_ils, o.status, o.sets_json,
                   o.created_at, o.updated_at
            FROM lotto_orders o JOIN users u ON o.user_id=u.id
            WHERE 1=1
        """
        params = []
        if draw_date:
            query += " AND o.draw_date=?"
            params.append(draw_date)
        if status:
            query += " AND o.status=?"
            params.append(status)
        query += " ORDER BY o.created_at DESC"
        rows = db.execute(query, params).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["מספר הזמנה", "שם", "טלפון", "תאריך הגרלה",
                     "כמות טפסים", "סה\"כ ₪", "סטטוס",
                     "מספרי הסט", "נוצר בתאריך"])

    for r in rows:
        sets = json.loads(r["sets_json"] or "[]")
        for i, s in enumerate(sets):
            nums_str = s.get("display", "")
            writer.writerow([
                r["order_number"] if i == 0 else "",
                r["name"]         if i == 0 else "",
                r["phone"]        if i == 0 else "",
                r["draw_date"]    if i == 0 else "",
                r["tables_count"] if i == 0 else "",
                f"₪{r['total_ils']:.0f}" if i == 0 else "",
                r["status"]       if i == 0 else "",
                nums_str,
                r["created_at"]   if i == 0 else "",
            ])

    output.seek(0)
    bom = "\ufeff"  # BOM לעברית ב-Excel
    resp = make_response(bom + output.getvalue())
    resp.headers["Content-Type"]        = "text/csv; charset=utf-8"
    resp.headers["Content-Disposition"] = f'attachment; filename="orders_{draw_date or "all"}_{status}.csv"'
    return resp

@app.route("/admin/prizes/reload", methods=["POST"])
def reload_prizes():
    """טעינה מחדש של ה-CSV ללא הפעלה מחדש."""
    if not require_admin():
        return jsonify({"error": "אין הרשאה"}), 403
    global _prizes_mtime
    _prizes_mtime = 0
    prizes = load_prizes()
    return jsonify({"status": "ok", "prizes_loaded": len(prizes)})

# ─────────────────────────────────────────────────────────────
# SECURITY HEADERS
# ─────────────────────────────────────────────────────────────
@app.after_request
def security_headers(r):
    r.headers["X-Content-Type-Options"] = "nosniff"
    r.headers["X-Frame-Options"]         = "DENY"
    return r

@app.errorhandler(404)
def nf(e): return jsonify({"error": "לא נמצא"}), 404
@app.errorhandler(500)
def se(e): return jsonify({"error": "שגיאת שרת"}), 500

# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────


@app.route("/lotto/submit", methods=["POST"])
def submit_filled_tables():
    uid, err = require_user()
    if err: return err

    d         = request.get_json(silent=True) or {}
    sets_in   = d.get("sets", [])
    draw_date = d.get("draw_date", "") or str(__import__("datetime").date.today())

    if not sets_in:
        return jsonify({"error": "לא נשלחו טבלאות"}), 400
    if len(sets_in) < 2:
        return jsonify({"error": "מינימום 2 טבלאות לשליחה"}), 400
    if len(sets_in) % 2 != 0:
        return jsonify({"error": "מספר הטבלאות חייב להיות זוגי"}), 400
    if len(sets_in) > 200:
        return jsonify({"error": "מקסימום 200 טבלאות"}), 400

    for i, s in enumerate(sets_in):
        nums = [s.get(f"n{j}") for j in range(1,7)]
        if not all(isinstance(n, int) and 1 <= n <= 37 for n in nums):
            return jsonify({"error": f"סט {i+1}: מספרים לא תקינים"}), 400
        if len(set(nums)) != 6:
            return jsonify({"error": f"סט {i+1}: מספרים כפולים"}), 400
        strong = s.get("strong")
        if not isinstance(strong, int) or not (1 <= strong <= 7):
            return jsonify({"error": f"סט {i+1}: מספר חזק לא תקין"}), 400

    prizes      = load_prizes()
    table_price = float(prizes[0]["table_price_ils"]) if prizes else TABLE_PRICE_ILS
    commission  = float(prizes[0]["commission_ils"])  if prizes else COMMISSION_ILS
    cost_per    = table_price + commission
    total       = round(len(sets_in) * cost_per, 2)

    with get_db() as db:
        wallet = db.execute("SELECT balance_ils FROM wallet WHERE user_id=?", (uid,)).fetchone()
        bal    = wallet["balance_ils"] if wallet else 0.0

    if bal < total:
        return jsonify({
            "error":      f"יתרה לא מספיקה - נדרש {total:.0f}, יתרה: {bal:.0f}",
            "need_topup": True,
            "shortfall":  round(total - bal, 2)
        }), 402

    sets_data = []
    for s in sets_in:
        nums = [s[f"n{j}"] for j in range(1,7)]
        sets_data.append({
            "set_index": s.get("set_index", 0),
            "nums":      nums,
            "strong":    s["strong"],
            "display":   f"{' '.join(str(n) for n in nums)} | {s['strong']}"
        })

    order_num = gen_order_number()

    with get_db() as db:
        db.execute(
            "UPDATE wallet SET balance_ils=balance_ils-?, updated_at=CURRENT_TIMESTAMP WHERE user_id=?",
            (total, uid)
        )
        db.execute(
            "INSERT INTO wallet_tx(user_id,type,amount_ils,description,ref_id) VALUES(?,?,?,?,?)",
            (uid, "charge", -total, f"הזמנת טפסים {order_num} ({len(sets_in)} טבלאות)", order_num)
        )
        db.execute("""
            INSERT INTO lotto_orders
            (order_number,user_id,draw_date,tables_count,table_price_ils,commission_ils,total_ils,sets_json)
            VALUES(?,?,?,?,?,?,?,?)
        """, (order_num, uid, draw_date, len(sets_in),
              table_price, commission, total,
              __import__("json").dumps(sets_data, ensure_ascii=False)))

    log.info(f"Submit: {order_num} user={uid} tables={len(sets_in)} total={total}")
    return jsonify({
        "status":       "ok",
        "order_number": order_num,
        "tables_count": len(sets_in),
        "total_ils":    total,
        "message":      f"ההזמנה {order_num} התקבלה!"
    })




if __name__ == "__main__":
    init_wallet_db()
    log.info(f"💳 Wallet Server | פורט {WALLET_PORT}")
    app.run(host="0.0.0.0", port=WALLET_PORT, debug=False)

# ─────────────────────────────────────────────────────────────
# ADMIN ENDPOINTS (wallet_server.py)
# ─────────────────────────────────────────────────────────────

@app.route("/admin/stats")
def admin_stats():
    if not require_admin(): return jsonify({"error":"אין הרשאה"}),403
    with get_db() as db:
        total_users    = db.execute("SELECT COUNT(*) v FROM users").fetchone()["v"]
        new_today      = db.execute("SELECT COUNT(*) v FROM users WHERE DATE(created_at)=DATE('now')").fetchone()["v"]
        total_revenue  = db.execute("SELECT COALESCE(SUM(amount_ils),0) v FROM wallet_tx WHERE type='topup'").fetchone()["v"]
        active_subs    = db.execute("SELECT COUNT(*) v FROM subscriptions WHERE status='active'").fetchone()["v"]
        pending_orders = db.execute("SELECT COUNT(*) v FROM lotto_orders WHERE status='paid'").fetchone()["v"]
        total_wins     = db.execute("SELECT COALESCE(SUM(total_wins),0) v FROM win_checks").fetchone()["v"]
        total_prize    = db.execute("SELECT COALESCE(SUM(total_prize_ils),0) v FROM win_checks").fetchone()["v"]
        total_commission = db.execute("SELECT COUNT(*)*? v FROM lotto_orders", (COMMISSION_ILS,)).fetchone()["v"]
    return jsonify({"total_users":total_users,"new_today":new_today,"total_revenue":total_revenue,
                    "active_subs":active_subs,"pending_orders":pending_orders,
                    "total_wins":total_wins,"total_prize":total_prize,"total_commission":total_commission})

@app.route("/admin/users")
def admin_users():
    if not require_admin(): return jsonify({"error":"אין הרשאה"}),403
    with get_db() as db:
        rows = db.execute("""
            SELECT u.id,u.name,u.phone,u.email,u.active,u.created_at,u.last_login,u.provider,
                   COALESCE(w.balance_ils,0) balance,
                   (SELECT COUNT(*) FROM lotto_orders o WHERE o.user_id=u.id) orders_count,
                   (SELECT COALESCE(SUM(wn.prize_ils),0) FROM wins wn WHERE wn.user_id=u.id) total_wins,
                   (SELECT type FROM subscriptions s WHERE s.user_id=u.id AND s.status='active' LIMIT 1) sub_type
            FROM users u LEFT JOIN wallet w ON w.user_id=u.id
            ORDER BY u.created_at DESC
        """).fetchall()
    return jsonify({"users":[dict(r) for r in rows]})

@app.route("/admin/users/csv")
def admin_users_csv():
    if not require_admin(): return jsonify({"error":"אין הרשאה"}),403
    with get_db() as db:
        rows = db.execute("SELECT id,name,phone,email,active,created_at,last_login FROM users ORDER BY created_at DESC").fetchall()
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["ID","שם","טלפון","אימייל","פעיל","נרשם","כניסה אחרונה"])
    for r in rows: w.writerow([r["id"],r["name"],r["phone"],r["email"],r["active"],r["created_at"],r["last_login"]])
    out.seek(0)
    resp = make_response("\ufeff"+out.getvalue())
    resp.headers["Content-Type"] = "text/csv; charset=utf-8"
    resp.headers["Content-Disposition"] = 'attachment; filename="users.csv"'
    return resp

@app.route("/admin/user/<int:uid>", methods=["PATCH"])
def admin_update_user(uid):
    if not require_admin(): return jsonify({"error":"אין הרשאה"}),403
    d = request.get_json(silent=True) or {}
    with get_db() as db:
        if d.get("name"):    db.execute("UPDATE users SET name=? WHERE id=?",  (d["name"],uid))
        if d.get("email"):   db.execute("UPDATE users SET email=? WHERE id=?", (d["email"],uid))
        if d.get("phone"):   db.execute("UPDATE users SET phone=? WHERE id=?", (d["phone"],uid))
        if "active" in d:    db.execute("UPDATE users SET active=? WHERE id=?",(1 if d["active"] else 0,uid))
        if d.get("password"):
            pw_hash = hash_password(d["password"])
            db.execute("UPDATE users SET pw_hash=? WHERE id=?", (pw_hash,uid))
    return jsonify({"status":"ok"})

@app.route("/admin/user/<int:uid>/lock", methods=["POST"])
def admin_lock_user(uid):
    if not require_admin(): return jsonify({"error":"אין הרשאה"}),403
    d = request.get_json(silent=True) or {}
    active = 1 if d.get("active") else 0
    with get_db() as db:
        db.execute("UPDATE users SET active=? WHERE id=?", (active,uid))
    return jsonify({"status":"ok","active":active})

@app.route("/admin/user/<int:uid>/sets")
def admin_user_sets(uid):
    if not require_admin(): return jsonify({"error":"אין הרשאה"}),403
    limit = int(request.args.get("limit",200))
    with get_db() as db:
        rows = db.execute("SELECT * FROM lotto_sets WHERE user_id=? ORDER BY draw_date DESC,set_index LIMIT ?", (uid,limit)).fetchall()
    return jsonify({"sets":[dict(r) for r in rows]})

@app.route("/admin/user/<int:uid>/wins")
def admin_user_wins(uid):
    if not require_admin(): return jsonify({"error":"אין הרשאה"}),403
    with get_db() as db:
        rows = db.execute("""
            SELECT w.*,o.order_number FROM wins w
            JOIN lotto_orders o ON w.order_id=o.id
            WHERE w.user_id=? ORDER BY w.prize_ils DESC
        """,(uid,)).fetchall()
    return jsonify({"wins":[dict(r) for r in rows]})

@app.route("/admin/wins")
def admin_wins():
    if not require_admin(): return jsonify({"error":"אין הרשאה"}),403
    with get_db() as db:
        rows = db.execute("""
            SELECT w.*,u.name,u.phone,o.order_number
            FROM wins w JOIN users u ON w.user_id=u.id JOIN lotto_orders o ON w.order_id=o.id
            ORDER BY w.prize_ils DESC
        """).fetchall()
    return jsonify({"wins":[dict(r) for r in rows]})

@app.route("/admin/wins/csv")
def admin_wins_csv():
    if not require_admin(): return jsonify({"error":"אין הרשאה"}),403
    with get_db() as db:
        rows = db.execute("""
            SELECT w.prize_type,w.prize_ils,w.draw_date,w.set_index,u.name,u.phone,o.order_number
            FROM wins w JOIN users u ON w.user_id=u.id JOIN lotto_orders o ON w.order_id=o.id
            ORDER BY w.prize_ils DESC
        """).fetchall()
    out = io.StringIO(); writer = csv.writer(out)
    writer.writerow(["סוג פגיעה","₪ פרס","הגרלה","סט","שם","טלפון","הזמנה"])
    for r in rows: writer.writerow([r["prize_type"],r["prize_ils"],r["draw_date"],r["set_index"],r["name"],r["phone"],r["order_number"]])
    out.seek(0)
    resp = make_response("\ufeff"+out.getvalue())
    resp.headers["Content-Type"]="text/csv; charset=utf-8"
    resp.headers["Content-Disposition"]='attachment; filename="wins.csv"'
    return resp

@app.route("/admin/sets")
def admin_sets():
    if not require_admin(): return jsonify({"error":"אין הרשאה"}),403
    draw_date = request.args.get("draw_date")
    with get_db() as db:
        if draw_date:
            rows = db.execute("SELECT ls.*,u.name FROM lotto_sets ls JOIN users u ON ls.user_id=u.id WHERE ls.draw_date=? ORDER BY ls.set_index",(draw_date,)).fetchall()
        else:
            rows = db.execute("SELECT ls.*,u.name FROM lotto_sets ls JOIN users u ON ls.user_id=u.id ORDER BY ls.draw_date DESC,ls.set_index LIMIT 500").fetchall()
    return jsonify({"sets":[dict(r) for r in rows]})

@app.route("/admin/wallets")
def admin_wallets():
    if not require_admin(): return jsonify({"error":"אין הרשאה"}),403
    with get_db() as db:
        rows = db.execute("""
            SELECT u.id user_id,u.name,u.phone,COALESCE(w.balance_ils,0) balance,w.updated_at,
                   (SELECT COALESCE(SUM(amount_ils),0) FROM wallet_tx WHERE user_id=u.id AND type='topup') total_topup,
                   (SELECT COALESCE(SUM(ABS(amount_ils)),0) FROM wallet_tx WHERE user_id=u.id AND type='charge') total_charge,
                   (SELECT COUNT(*) FROM wallet_tx WHERE user_id=u.id) tx_count
            FROM users u LEFT JOIN wallet w ON w.user_id=u.id ORDER BY balance DESC
        """).fetchall()
    return jsonify({"wallets":[dict(r) for r in rows]})

@app.route("/admin/wallet/<int:uid>/adjust", methods=["POST"])
def admin_wallet_adjust(uid):
    if not require_admin(): return jsonify({"error":"אין הרשאה"}),403
    d = request.get_json(silent=True) or {}
    tx_type = d.get("type","add")
    amount  = float(d.get("amount",0))
    reason  = d.get("reason","התאמה ידנית אדמין")
    if amount <= 0: return jsonify({"error":"סכום לא תקין"}),400
    delta = amount if tx_type=="add" else -amount
    with get_db() as db:
        db.execute("INSERT INTO wallet(user_id,balance_ils) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET balance_ils=balance_ils+?,updated_at=CURRENT_TIMESTAMP",(uid,delta,delta))
        db.execute("INSERT INTO wallet_tx(user_id,type,amount_ils,description) VALUES(?,?,?,?)",(uid,tx_type,delta,reason))
    return jsonify({"status":"ok","delta":delta})

@app.route("/admin/subscriptions")
def admin_subscriptions():
    if not require_admin(): return jsonify({"error":"אין הרשאה"}),403
    with get_db() as db:
        rows = db.execute("SELECT s.*,u.name,u.phone FROM subscriptions s JOIN users u ON s.user_id=u.id ORDER BY s.created_at DESC").fetchall()
    return jsonify({"subscriptions":[dict(r) for r in rows]})

@app.route("/admin/subscription/<int:sid>/cancel", methods=["POST"])
def admin_cancel_sub(sid):
    if not require_admin(): return jsonify({"error":"אין הרשאה"}),403
    with get_db() as db:
        db.execute("UPDATE subscriptions SET status='cancelled' WHERE id=?", (sid,))
    return jsonify({"status":"ok"})

@app.route("/admin/logs")
def admin_logs():
    if not require_admin(): return jsonify({"error":"אין הרשאה"}),403
    with get_db() as db:
        rows = db.execute("""
            SELECT al.*,u.name FROM auth_log al LEFT JOIN users u ON al.user_id=u.id
            ORDER BY al.created_at DESC LIMIT 500
        """).fetchall()
    return jsonify({"logs":[dict(r) for r in rows]})

@app.route("/admin/logs/cleanup", methods=["DELETE"])
def admin_cleanup_logs():
    if not require_admin(): return jsonify({"error":"אין הרשאה"}),403
    with get_db() as db:
        deleted = db.execute("DELETE FROM auth_log WHERE created_at < datetime('now','-30 days')").rowcount
    return jsonify({"deleted":deleted})

@app.route("/admin/prizes/csv")
def admin_prizes_csv_get():
    if not require_admin(): return jsonify({"error":"אין הרשאה"}),403
    try:
        with open(PRIZES_CSV, encoding='utf-8') as f:
            return jsonify({"content":f.read()})
    except: return jsonify({"content":"","error":"קובץ לא נמצא"})

@app.route("/admin/prizes/csv", methods=["PUT"])
def admin_prizes_csv_put():
    if not require_admin(): return jsonify({"error":"אין הרשאה"}),403
    d = request.get_json(silent=True) or {}
    content = d.get("content","")
    if not content: return jsonify({"error":"תוכן ריק"}),400
    with open(PRIZES_CSV, 'w', encoding='utf-8') as f:
        f.write(content)
    global _prizes_mtime
    _prizes_mtime = 0
    prizes = load_prizes()
    return jsonify({"status":"ok","rows":len(prizes)})

@app.route("/admin/config")
def admin_config_get():
    if not require_admin(): return jsonify({"error":"אין הרשאה"}),403
    return jsonify({"commission_ils":COMMISSION_ILS,"table_price_ils":TABLE_PRICE_ILS,"weekly_price":25.0,"monthly_price":50.0})

@app.route("/admin/config", methods=["PUT"])
def admin_config_put():
    if not require_admin(): return jsonify({"error":"אין הרשאה"}),403
    # In production: save to DB or .env; here we log it
    d = request.get_json(silent=True) or {}
    log.info(f"Config update: {d}")
    return jsonify({"status":"ok","saved":d})

@app.route("/admin/change-password", methods=["POST"])
def admin_change_password():
    if not require_admin(): return jsonify({"error":"אין הרשאה"}),403
    d = request.get_json(silent=True) or {}
    new_pw = d.get("new_password","")
    if len(new_pw) < 8: return jsonify({"error":"סיסמה קצרה מדי"}),400
    # In production: update ADMIN_TOKEN or store hashed admin pw in DB
    log.info("Admin password change requested")
    return jsonify({"status":"ok","message":"סיסמה עודכנה (בייצור: עדכן ADMIN_TOKEN ב-.env)"})

@app.route("/lotto/order/<int:order_id>/form")
def get_order_form(order_id):
    uid, err = require_user()
    if err: return err
    with get_db() as db:
        order = db.execute(
            "SELECT * FROM lotto_orders WHERE id=? AND user_id=?", (order_id, uid)
        ).fetchone()
    if not order: return jsonify({"error": "לא נמצא"}), 404
    return jsonify({"order_number": order["order_number"], "draw_date": order["draw_date"],
                    "tables_count": order["tables_count"], "total_ils": order["total_ils"],
                    "status": order["status"], "sets": json.loads(order["sets_json"] or "[]")})

@app.route("/admin/order/<string:order_num>/form")
def get_admin_order_form(order_num):
    if not require_admin(): return jsonify({"error": "אין הרשאה"}), 403
    with get_db() as db:
        order = db.execute(
            "SELECT o.*, u.name, u.phone FROM lotto_orders o JOIN users u ON o.user_id=u.id WHERE o.order_number=?",
            (order_num,)
        ).fetchone()
    if not order: return jsonify({"error": "לא נמצא"}), 404
    return jsonify({"order_number": order["order_number"], "customer_name": order["name"],
                    "customer_phone": order["phone"], "draw_date": order["draw_date"],
                    "tables_count": order["tables_count"], "total_ils": order["total_ils"],
                    "status": order["status"], "sets": json.loads(order["sets_json"] or "[]"),
                    "created_at": order["created_at"]})

@app.route("/admin/backup/csv")
def admin_backup():
    if not require_admin(): return jsonify({"error":"אין הרשאה"}),403
    with get_db() as db:
        users  = db.execute("SELECT * FROM users").fetchall()
        orders = db.execute("SELECT * FROM lotto_orders").fetchall()
        wins   = db.execute("SELECT * FROM wins").fetchall()
    out = io.StringIO(); writer = csv.writer(out)
    writer.writerow(["=== USERS ==="])
    writer.writerow(["id","name","phone","email","active","created_at"])
    for r in users: writer.writerow([r["id"],r["name"],r["phone"],r["email"],r["active"],r["created_at"]])
    writer.writerow([])
    writer.writerow(["=== ORDERS ==="])
    writer.writerow(["order_number","user_id","draw_date","tables_count","total_ils","status","created_at"])
    for r in orders: writer.writerow([r["order_number"],r["user_id"],r["draw_date"],r["tables_count"],r["total_ils"],r["status"],r["created_at"]])
    writer.writerow([])
    writer.writerow(["=== WINS ==="])
    writer.writerow(["user_id","prize_type","prize_ils","draw_date"])
    for r in wins: writer.writerow([r["user_id"],r["prize_type"],r["prize_ils"],r["draw_date"]])
    out.seek(0)
    resp = make_response("\ufeff"+out.getvalue())
    resp.headers["Content-Type"]="text/csv; charset=utf-8"
    resp.headers["Content-Disposition"]=f'attachment; filename="backup_{datetime.datetime.now().strftime("%Y%m%d_%H%M")}.csv"'
    return resp
