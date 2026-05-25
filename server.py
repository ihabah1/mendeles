"""
מנדל לוטו – שרת Backend מלא
===============================
תלויות: pip install flask flask-cors stripe requests python-dotenv

קובץ .env נדרש עם המשתנים הבאים:
  STRIPE_SECRET_KEY=sk_live_...
  STRIPE_WEBHOOK_SECRET=whsec_...
  PAYPAL_CLIENT_ID=...
  PAYPAL_CLIENT_SECRET=...
  ICOUNT_CID=...          (Company ID ב-iCount)
  ICOUNT_USER=...
  ICOUNT_PASS=...
  FRONTEND_URL=https://your-domain.co.il
  NEXT_DRAW_DATE=2026-05-20   (מתעדכן לפני כל הגרלה)
"""

import os, json, hashlib, hmac, datetime, logging
import stripe, requests
from flask import Flask, request, jsonify, abort
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app, origins=[os.getenv("FRONTEND_URL", "*")])

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

PAYPAL_CLIENT_ID     = os.getenv("PAYPAL_CLIENT_ID")
PAYPAL_CLIENT_SECRET = os.getenv("PAYPAL_CLIENT_SECRET")
PAYPAL_BASE          = "https://api-m.paypal.com"   # sandbox: api-m.sandbox.paypal.com

ICOUNT_BASE = "https://api.icount.co.il/api/v3.php"
ICOUNT_CID  = os.getenv("ICOUNT_CID")
ICOUNT_USER = os.getenv("ICOUNT_USER")
ICOUNT_PASS = os.getenv("ICOUNT_PASS")

FRONTEND_URL    = os.getenv("FRONTEND_URL", "http://localhost:3000")
NEXT_DRAW_DATE  = os.getenv("NEXT_DRAW_DATE", "2026-05-20")   # עדכן לפני כל הגרלה

# ─────────────────────────────────────────────
# PLANS
# ─────────────────────────────────────────────
PLANS = {
    "one-time": {
        "amount": 2900,          # אגורות (₪29)
        "currency": "ils",
        "name": "מנדל לוטו – רכישה חד-פעמית",
        "description": f"גישה לצירופים עד הגרלה {NEXT_DRAW_DATE}",
        "mode": "payment"
    },
    "monthly": {
        "amount": 4900,          # אגורות (₪49)
        "currency": "ils",
        "name": "מנדל לוטו – מנוי חודשי",
        "description": "גישה בלתי מוגבלת, מתעדכן אחרי כל הגרלה",
        "mode": "subscription",
        "price_id": os.getenv("STRIPE_MONTHLY_PRICE_ID")   # מוגדר ב-Stripe Dashboard
    }
}

# ─────────────────────────────────────────────
# DATA – ניהול המאגר (לדוגמה, בפרודקשן → DB)
# ─────────────────────────────────────────────

def load_approved_combos() -> list[list[int]]:
    """
    טוען צירופים מאושרים מקובץ JSON.
    קובץ: data/approved_combos.json
    פורמט: [[1,5,12,23,30,36], ...]
    בפרודקשן – החלף ב-DB query.
    """
    try:
        with open("data/approved_combos.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        log.warning("approved_combos.json לא נמצא, משתמש במאגר הדגמה")
        return _demo_combos()

def _demo_combos() -> list[list[int]]:
    """200 צירופים לדוגמה למצב פיתוח"""
    import random
    random.seed(42)
    combos = []
    while len(combos) < 200:
        c = sorted(random.sample(range(1, 38), 6))
        if c not in combos:
            combos.append(c)
    return combos

def load_active_users() -> dict:
    """
    מחזיר מילון {email: {plan, valid_until, active}}
    בפרודקשן – החלף ב-DB query.
    """
    try:
        with open("data/users.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_user(email: str, plan: str, valid_until: str):
    users = load_active_users()
    users[email] = {"plan": plan, "valid_until": valid_until, "active": True}
    os.makedirs("data", exist_ok=True)
    with open("data/users.json", "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)
    log.info(f"משתמש נשמר: {email} | תוכנית: {plan} | בתוקף עד: {valid_until}")

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def get_validity_date(plan: str) -> str:
    """מחזיר תאריך תוקף לפי סוג תוכנית"""
    if plan == "monthly":
        return (datetime.date.today() + datetime.timedelta(days=30)).isoformat()
    return NEXT_DRAW_DATE   # חד-פעמי – עד ההגרלה הבאה

def is_combo_approved(numbers: list[int]) -> bool:
    """בודק אם צירוף קיים ברשימה המאושרת"""
    approved = load_approved_combos()
    return sorted(numbers) in [sorted(c) for c in approved]

def validate_numbers(numbers) -> tuple[bool, str]:
    """ולידציה בסיסית"""
    if not isinstance(numbers, list) or len(numbers) != 6:
        return False, "יש לשלוח בדיוק 6 מספרים"
    if not all(isinstance(n, int) and 1 <= n <= 37 for n in numbers):
        return False, "כל המספרים חייבים להיות בין 1 ל-37"
    if len(set(numbers)) != 6:
        return False, "כל המספרים חייבים להיות שונים"
    return True, ""

# ─────────────────────────────────────────────
# iCOUNT – חשבוניות
# ─────────────────────────────────────────────

def create_icount_invoice(email: str, amount_ils: float, plan_name: str) -> dict:
    """
    מפיק חשבונית מס ב-iCount ושולח לאימייל הלקוח.
    תיעוד API: https://www.icount.co.il/api/
    """
    payload = {
        "cid":      ICOUNT_CID,
        "user":     ICOUNT_USER,
        "pass":     ICOUNT_PASS,
        "doc_type": "invrec",          # חשבונית מס + קבלה
        "lang":     "he",
        "client_email":   email,
        "income_subject": plan_name,
        "items": json.dumps([{
            "details": plan_name,
            "amount":  1,
            "price":   amount_ils,
            "vat_type": "1"            # עם מע"מ
        }]),
        "send_email": "1"
    }
    try:
        resp = requests.post(ICOUNT_BASE, data=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status"):
            log.info(f"חשבונית iCount נשלחה ל-{email}: {data.get('doc_num')}")
            return {"success": True, "doc_num": data.get("doc_num"), "doc_url": data.get("doc_url")}
        else:
            log.error(f"iCount שגיאה: {data}")
            return {"success": False, "error": data.get("reason")}
    except Exception as e:
        log.error(f"iCount חיבור נכשל: {e}")
        return {"success": False, "error": str(e)}

# ─────────────────────────────────────────────
# PAYPAL HELPERS
# ─────────────────────────────────────────────

def paypal_get_token() -> str:
    r = requests.post(
        f"{PAYPAL_BASE}/v1/oauth2/token",
        data={"grant_type": "client_credentials"},
        auth=(PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET),
        timeout=10
    )
    r.raise_for_status()
    return r.json()["access_token"]

def paypal_capture_order(order_id: str) -> dict:
    token = paypal_get_token()
    r = requests.post(
        f"{PAYPAL_BASE}/v2/checkout/orders/{order_id}/capture",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=10
    )
    r.raise_for_status()
    return r.json()

# ─────────────────────────────────────────────
# ROUTES – FREE
# ─────────────────────────────────────────────

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "next_draw": NEXT_DRAW_DATE, "ts": datetime.datetime.utcnow().isoformat()})

@app.route("/api/check", methods=["POST"])
def check_combo():
    """
    בדיקת צירוף חינמית.
    Body: {"numbers": [1,5,12,23,30,36]}
    """
    data = request.get_json(silent=True) or {}
    numbers = data.get("numbers", [])

    valid, msg = validate_numbers(numbers)
    if not valid:
        return jsonify({"status": "error", "message": msg}), 400

    if is_combo_approved(numbers):
        return jsonify({
            "status":  "approved",
            "message": f"✅ הצירוף עבר את הסינון הסטטיסטי! תקף עד הגרלה {NEXT_DRAW_DATE}",
            "valid_until": NEXT_DRAW_DATE
        })
    return jsonify({
        "status":  "rejected",
        "message": "❌ הצירוף לא עמד בקריטריוני הסינון הסטטיסטי"
    })

@app.route("/api/next-draw", methods=["GET"])
def next_draw():
    """מחזיר את תאריך ההגרלה הבאה"""
    return jsonify({"next_draw_date": NEXT_DRAW_DATE})

# ─────────────────────────────────────────────
# ROUTES – PREMIUM (דורשים אימות)
# ─────────────────────────────────────────────

def require_active_subscription(f):
    """Decorator – בודק שיש ללקוח מנוי פעיל"""
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        email = request.headers.get("X-User-Email", "").lower().strip()
        if not email:
            return jsonify({"error": "נדרשת אימות – שלח X-User-Email header"}), 401
        users = load_active_users()
        user  = users.get(email)
        if not user or not user.get("active"):
            return jsonify({"error": "אין מנוי פעיל"}), 403
        # בדיקת תוקף
        try:
            valid_until = datetime.date.fromisoformat(user["valid_until"])
            if datetime.date.today() > valid_until:
                return jsonify({
                    "error": "הצירופים פגו תוקפם לאחר ההגרלה האחרונה. יש לרכוש מחדש.",
                    "expired_on": user["valid_until"],
                    "next_draw":  NEXT_DRAW_DATE
                }), 403
        except Exception:
            pass
        return f(*args, **kwargs)
    return decorated

@app.route("/api/suggest/coverage", methods=["GET"])
@require_active_subscription
def suggest_coverage():
    count  = min(int(request.args.get("count", 200)), 200)
    combos = load_approved_combos()[:count]
    return jsonify({
        "suggestions": combos,
        "count": len(combos),
        "valid_until": NEXT_DRAW_DATE,
        "note": f"הצירופים תקפים עד הגרלה {NEXT_DRAW_DATE} בלבד"
    })

@app.route("/api/suggest/top-stat", methods=["GET"])
@require_active_subscription
def suggest_top_stat():
    """מחזיר צירופים עם Hot Numbers (המספרים בעלי תדירות גבוהה)"""
    combos = load_approved_combos()
    # דוגמה: מיון לפי סכום (בפרודקשן – לפי תדירות היסטורית אמיתית)
    hot = sorted(combos, key=lambda c: -sum(c))[:50]
    return jsonify({
        "top_statistical_suggestions": hot,
        "count": len(hot),
        "valid_until": NEXT_DRAW_DATE,
        "note": f"הצירופים תקפים עד הגרלה {NEXT_DRAW_DATE} בלבד"
    })

@app.route("/api/suggest/diverse", methods=["GET"])
@require_active_subscription
def suggest_diverse():
    """מחזיר צירופים עם גיוון עשרויות מקסימלי"""
    combos = load_approved_combos()
    # מסנן צירופים שיש בהם מספרים מ-3 עשרויות שונות לפחות
    def diversity_score(c):
        decades = len(set((n - 1) // 10 for n in c))
        return -decades
    diverse = sorted(combos, key=diversity_score)[:50]
    return jsonify({
        "diverse_suggestions": diverse,
        "count": len(diverse),
        "valid_until": NEXT_DRAW_DATE,
        "note": f"הצירופים תקפים עד הגרלה {NEXT_DRAW_DATE} בלבד"
    })

# ─────────────────────────────────────────────
# STRIPE – יצירת Checkout Session
# ─────────────────────────────────────────────

@app.route("/api/payment/stripe/create-session", methods=["POST"])
def stripe_create_session():
    """
    יוצר Stripe Checkout Session.
    Body: {"plan": "one-time" | "monthly", "email": "user@example.com"}
    """
    data  = request.get_json(silent=True) or {}
    plan  = data.get("plan", "one-time")
    email = data.get("email", "")

    if plan not in PLANS:
        return jsonify({"error": "תוכנית לא תקינה"}), 400

    p = PLANS[plan]

    try:
        if plan == "monthly" and p.get("price_id"):
            # מנוי – Subscription
            session = stripe.checkout.Session.create(
                mode="subscription",
                customer_email=email or None,
                line_items=[{"price": p["price_id"], "quantity": 1}],
                success_url=f"{FRONTEND_URL}?payment=success&session_id={{CHECKOUT_SESSION_ID}}",
                cancel_url=f"{FRONTEND_URL}?payment=cancelled",
                metadata={"plan": plan, "email": email}
            )
        else:
            # תשלום חד-פעמי
            session = stripe.checkout.Session.create(
                mode="payment",
                customer_email=email or None,
                line_items=[{
                    "price_data": {
                        "currency":     p["currency"],
                        "unit_amount":  p["amount"],
                        "product_data": {"name": p["name"], "description": p["description"]}
                    },
                    "quantity": 1
                }],
                success_url=f"{FRONTEND_URL}?payment=success&session_id={{CHECKOUT_SESSION_ID}}",
                cancel_url=f"{FRONTEND_URL}?payment=cancelled",
                metadata={"plan": plan, "email": email}
            )

        log.info(f"Stripe session נוצר: {session.id} | תוכנית: {plan} | email: {email}")
        return jsonify({"session_url": session.url, "session_id": session.id})

    except stripe.error.StripeError as e:
        log.error(f"Stripe שגיאה: {e}")
        return jsonify({"error": str(e.user_message)}), 500

# ─────────────────────────────────────────────
# STRIPE WEBHOOK – לאחר תשלום מוצלח
# ─────────────────────────────────────────────

@app.route("/api/webhook/stripe", methods=["POST"])
def stripe_webhook():
    payload   = request.data
    sig_header = request.headers.get("Stripe-Signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except stripe.error.SignatureVerificationError:
        log.warning("Stripe webhook: חתימה לא תקינה")
        abort(400)

    etype = event["type"]
    log.info(f"Stripe webhook: {etype}")

    if etype in ("checkout.session.completed", "invoice.payment_succeeded"):
        obj   = event["data"]["object"]
        email = (obj.get("customer_email") or obj.get("customer_details", {}).get("email", "")).lower()
        meta  = obj.get("metadata", {})
        plan  = meta.get("plan", "one-time")

        if email:
            valid_until = get_validity_date(plan)
            save_user(email, plan, valid_until)

            # הפקת חשבונית iCount
            amount = PLANS.get(plan, {}).get("amount", 2900) / 100
            create_icount_invoice(email, amount, PLANS.get(plan, {}).get("name", "מנדל לוטו"))

    elif etype == "customer.subscription.deleted":
        # ביטול מנוי
        obj   = event["data"]["object"]
        email = obj.get("customer_email", "").lower()
        if email:
            users = load_active_users()
            if email in users:
                users[email]["active"] = False
                with open("data/users.json", "w", encoding="utf-8") as f:
                    json.dump(users, f, ensure_ascii=False, indent=2)
                log.info(f"מנוי בוטל: {email}")

    return jsonify({"received": True})

# ─────────────────────────────────────────────
# PAYPAL – יצירת Order
# ─────────────────────────────────────────────

@app.route("/api/payment/paypal/create-order", methods=["POST"])
def paypal_create_order():
    """
    יוצר PayPal Order.
    Body: {"plan": "one-time" | "monthly"}
    """
    data = request.get_json(silent=True) or {}
    plan = data.get("plan", "one-time")
    if plan not in PLANS:
        return jsonify({"error": "תוכנית לא תקינה"}), 400

    amount = PLANS[plan]["amount"] / 100   # לשקלים

    try:
        token = paypal_get_token()
        r = requests.post(
            f"{PAYPAL_BASE}/v2/checkout/orders",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "intent": "CAPTURE",
                "purchase_units": [{
                    "amount": {"currency_code": "ILS", "value": f"{amount:.2f}"},
                    "description": PLANS[plan]["name"]
                }],
                "application_context": {
                    "return_url": f"{FRONTEND_URL}?payment=success",
                    "cancel_url": f"{FRONTEND_URL}?payment=cancelled"
                }
            },
            timeout=10
        )
        r.raise_for_status()
        order = r.json()
        approve_url = next((l["href"] for l in order["links"] if l["rel"]=="approve"), None)
        log.info(f"PayPal order נוצר: {order['id']}")
        return jsonify({"order_id": order["id"], "approve_url": approve_url})
    except Exception as e:
        log.error(f"PayPal שגיאה: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/payment/paypal/capture", methods=["POST"])
def paypal_capture():
    """
    לאחר אישור הלקוח – Capture התשלום.
    Body: {"order_id": "...", "email": "...", "plan": "..."}
    """
    data     = request.get_json(silent=True) or {}
    order_id = data.get("order_id")
    email    = data.get("email", "").lower()
    plan     = data.get("plan", "one-time")

    if not order_id:
        return jsonify({"error": "חסר order_id"}), 400

    try:
        result = paypal_capture_order(order_id)
        status = result.get("status")

        if status == "COMPLETED":
            valid_until = get_validity_date(plan)
            if email:
                save_user(email, plan, valid_until)
                amount = PLANS.get(plan, {}).get("amount", 2900) / 100
                create_icount_invoice(email, amount, PLANS.get(plan, {}).get("name", "מנדל לוטו"))

            log.info(f"PayPal תשלום הושלם: {order_id} | {email}")
            return jsonify({"status": "success", "valid_until": valid_until})
        else:
            return jsonify({"status": "pending", "paypal_status": status})
    except Exception as e:
        log.error(f"PayPal capture שגיאה: {e}")
        return jsonify({"error": str(e)}), 500

# ─────────────────────────────────────────────
# ADMIN – עדכון הגרלה (מוגן)
# ─────────────────────────────────────────────

@app.route("/api/admin/update-draw", methods=["POST"])
def admin_update_draw():
    """
    מעדכן את תאריך ההגרלה הבאה ומחליף את מאגר הצירופים.
    Body: {"admin_key": "...", "next_draw_date": "2026-05-27", "combos": [[1,2,...], ...]}
    """
    global NEXT_DRAW_DATE
    data      = request.get_json(silent=True) or {}
    admin_key = data.get("admin_key", "")

    # אבטחה פשוטה – בפרודקשן השתמש ב-JWT
    expected = os.getenv("ADMIN_KEY", "change-this-secret")
    if not hmac.compare_digest(admin_key, expected):
        return jsonify({"error": "גישה נדחתה"}), 403

    new_date = data.get("next_draw_date")
    combos   = data.get("combos")

    if new_date:
        NEXT_DRAW_DATE = new_date
        log.info(f"NEXT_DRAW_DATE עודכן: {NEXT_DRAW_DATE}")

    if combos and isinstance(combos, list):
        os.makedirs("data", exist_ok=True)
        with open("data/approved_combos.json", "w", encoding="utf-8") as f:
            json.dump(combos, f, ensure_ascii=False)
        log.info(f"מאגר צירופים עודכן: {len(combos)} צירופים")

    return jsonify({
        "status": "updated",
        "next_draw_date": NEXT_DRAW_DATE,
        "combos_count": len(combos) if combos else "לא עודכן"
    })

# ─────────────────────────────────────────────
# ERROR HANDLERS
# ─────────────────────────────────────────────

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "נקודת קצה לא נמצאה"}), 404

@app.errorhandler(500)
def server_error(e):
    log.error(f"שגיאת שרת: {e}")
    return jsonify({"error": "שגיאה פנימית בשרת"}), 500

# ─────────────────────────────────────────────
# RUN
# ─────────────────────────────────────────────

if __name__ == "__main__":
    os.makedirs("data", exist_ok=True)
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_ENV", "production") == "development"
    log.info(f"שרת מנדל לוטו מופעל על פורט {port} | הגרלה הבאה: {NEXT_DRAW_DATE}")
    app.run(host="0.0.0.0", port=port, debug=debug)
