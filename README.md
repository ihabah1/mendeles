# Mandeles Portal

פרויקט Django אחד על **פורט 8000 בלבד**.

## מבנה (סדר ברור)

| כתובת | מה מוצג |
|--------|---------|
| `http://127.0.0.1:8000/` | **אתר ראשי React** – לוטו וטוטו (Mandeles.co.il) |
| `http://127.0.0.1:8000/manage/login/` | **כניסת מנהל** לדשבורד ניהול |
| `http://127.0.0.1:8000/manage/` | דשבורד ניהול (לקוחות, הזמנות, אשראי…) |
| `http://127.0.0.1:8000/django-admin/` | Django Admin מסורתי (אופציונלי) |

### מה **לא** דף ראשי

| קובץ / פורט | הסבר |
|-------------|------|
| `templates/portal/home.html` | דף ישן – **לא בשימוש** (נשאר בארכיון) |
| פורט **8088** | שרת ישן – **לא להריץ** |
| `admin.html` בדיסק | HTML סטטי ישן – לא מחובר |

קישור **ניהול** בסרגל האתר → `/manage/` (מנהלים) או "אין כניסה" (משתמש רגיל).

## הרצה

```powershell
cd c:\Users\ihaba\Downloads\250526
pip install -r requirements.txt
python manage.py migrate
python manage.py setup_portal
.\run.ps1
```

או: `py manage.py runserver` (ברירת מחדל 8000).

## כניסת מנהל

| | |
|---|---|
| URL | http://127.0.0.1:8000/manage/login/ |
| אימייל | admin@admin.com |
| סיסמה | admin |

## גרסה

`v2.2.8` – בלוגו, בכותרת הדף ובפוטר של אתר React.

**מנהל קבוע:** `admin@admin.com` / `admin` (נוצר אוטומטית ב־`setup_portal` ובאתחול).

## פריסה (Railway / Render / Docker)

השגיאה `unable to open database file` נגרמת כי תיקיית `data/` לא קיימת בקונטיינר. אחרי העדכון האחרון:

| משתנה | חובה בפרודקשן | דוגמה |
|--------|----------------|--------|
| `DJANGO_SECRET_KEY` | כן | מחרוזת אקראית ארוכה |
| `DJANGO_DEBUG` | כן | `false` |
| `ALLOWED_HOSTS` | כן | `your-app.up.railway.app` |
| `CSRF_TRUSTED_ORIGINS` | מומלץ | `https://your-app.up.railway.app` |
| `DATABASE_URL` | מומלץ | Postgres מהפלטפורמה |

בלי `DATABASE_URL` – SQLite נשמר ב־`/tmp/mendeles-data` (נתונים עלולים להימחק בריסטארט).

פקודת start מומלצת:

```bash
python manage.py migrate --noinput
python manage.py setup_portal
python manage.py collectstatic --noinput
gunicorn mandeles_portal.wsgi:application --bind 0.0.0.0:$PORT
```

או השתמש ב־`Procfile` שבשורש הפרויקט.

## בניית Frontend מחדש

```powershell
cd c:\Users\ihaba\Downloads\mandeles-react-test5\mandeles-react
npm run build
robocopy ..\static\frontend ..\..\250526\static\frontend /E
```
