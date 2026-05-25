"""
check_and_fix_demo.py
=====================
בודק אם משתמש הדמו קיים ומתקן אם צריך.
הרץ: python check_and_fix_demo.py
"""
import sqlite3, os, time, sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except: pass

AUTH_DB    = os.getenv('AUTH_DB_PATH', 'data/auth.db')
JWT_SECRET = os.getenv('JWT_SECRET', 'b39571f6a28e6937a149bf4e3305119fd30eb3ff2be4be4d22dc6bcc3809ce18')
JWT_DAYS   = int(os.getenv('JWT_EXPIRE_DAYS', 30))

DEMO_EMAIL = 'demo@mandeles.co.il'
DEMO_PASS  = 'Demo1234!'
DEMO_NAME  = 'חשבון דמו'

# ── בדוק אם DB קיים ──
if not Path(AUTH_DB).exists():
    print(f'❌ DB לא נמצא: {AUTH_DB}')
    print('   הרץ את השרתים קודם: python start_all.py')
    sys.exit(1)

db = sqlite3.connect(AUTH_DB)
db.row_factory = sqlite3.Row

# ── בדוק משתמש ──
user = db.execute('SELECT * FROM users WHERE email=?', (DEMO_EMAIL,)).fetchone()
print(f'\n📋 בדיקת משתמש דמו ({DEMO_EMAIL}):')

if user:
    print(f'  ✅ קיים — ID: {user["id"]}, active: {user["active"]}, pw_hash: {"✓" if user["pw_hash"] else "✗ ריק!"}')
    uid = user['id']
    # תקן אם לא active
    if not user['active']:
        db.execute('UPDATE users SET active=1 WHERE id=?', (uid,))
        db.commit()
        print('  🔧 הופעל')
else:
    print('  ❌ לא קיים — יוצר...')
    try:
        import bcrypt
        pw_hash = bcrypt.hashpw(DEMO_PASS.encode(), bcrypt.gensalt(12)).decode()
    except ImportError:
        print('  ❌ pip install bcrypt')
        sys.exit(1)
    # מחק לפי טלפון אם קיים
    db.execute("DELETE FROM users WHERE phone='+972500000000'")
    db.execute('''INSERT INTO users (name,email,pw_hash,provider,email_verified,active)
                  VALUES (?,?,?,?,?,?)''', (DEMO_NAME, DEMO_EMAIL, pw_hash, 'local', 1, 1))
    db.commit()
    uid = db.execute('SELECT last_insert_rowid()').fetchone()[0]
    print(f'  ✅ נוצר — ID: {uid}')

# ── תקן סיסמה ──
try:
    import bcrypt
    new_hash = bcrypt.hashpw(DEMO_PASS.encode(), bcrypt.gensalt(12)).decode()
    db.execute('UPDATE users SET pw_hash=?, active=1, email_verified=1 WHERE id=?', (new_hash, uid))
    db.commit()
    print(f'  🔧 סיסמה עודכנה: {DEMO_PASS}')
except ImportError:
    pass

# ── בדוק wallet ──
wallet = db.execute('SELECT * FROM wallet WHERE user_id=?', (uid,)).fetchone()
if not wallet:
    db.execute('INSERT INTO wallet (user_id, balance_ils) VALUES (?,?)', (uid, 500.0))
    db.commit()
    print(f'  💰 ארנק נוצר: ₪500')
else:
    print(f'  💰 ארנק: ₪{wallet["balance_ils"]:.2f}')
    if wallet['balance_ils'] < 50:
        db.execute('UPDATE wallet SET balance_ils=500 WHERE user_id=?', (uid,))
        db.commit()
        print('  🔧 יתרה אופסה ל-₪500')

db.close()

# ── צור JWT ──
try:
    import jwt as pyjwt
    token = pyjwt.encode({
        'sub': uid, 'email': DEMO_EMAIL, 'name': DEMO_NAME,
        'is_premium': True, 'sets_purchased': 200,
        'iat': int(time.time()),
        'exp': int(time.time()) + JWT_DAYS * 86400,
    }, JWT_SECRET, algorithm='HS256')

    print(f'\n{"="*55}')
    print('✅ חשבון דמו מוכן!')
    print(f'   אימייל:  {DEMO_EMAIL}')
    print(f'   סיסמה:   {DEMO_PASS}')
    print(f'   user_id: {uid}')
    print(f'\n{"─"*55}')
    print('הרץ בConsole של הדפדפן:')
    print(f'\nfetch("/auth/login/email",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{email:"{DEMO_EMAIL}",password:"{DEMO_PASS}"}})}}).then(r=>r.json()).then(d=>{{if(d.token){{localStorage.setItem("auth_token",d.token);localStorage.setItem("demo_mode","1");console.log("✅ מחובר!",d)}}else console.error("❌",d)}})')
    print(f'\n{"="*55}')

    Path('data').mkdir(exist_ok=True)
    Path('data/demo_token.txt').write_text(token)
    print(f'\n📄 Token נשמר: data/demo_token.txt')

except ImportError:
    print('pip install pyjwt')