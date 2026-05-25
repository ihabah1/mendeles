# AI Agent – שינויי תוכן דרך Django Admin

## זרימה

1. **Django Admin** → `בקשות שינוי AI` → הוסף בקשה + prompt
2. **ייצר diff** – Gemini קורא רק `templates/` + `static/`, מחזיר unified diff
3. **תצוגה מקדימה** – בדוק את ה-diff באדמין
4. **אשר ויצור PR** – ענף חדש → commit → push → Pull Request (לא ל-main)

## משתני סביבה (חובה לשימוש)

| משתנה | חובה | תיאור |
|--------|------|--------|
| `AI_AGENT_ENABLED` | כן | `true` להפעלה |
| `GEMINI_API_KEY` | כן | [Google AI Studio](https://aistudio.google.com/apikey) |
| `GITHUB_TOKEN` | כן | Personal Access Token |
| `GITHUB_REPO` | כן | `ihabah1/mendeles` |
| `GITHUB_DEFAULT_BRANCH` | לא | ברירת מחדל `main` |
| `GEMINI_MODEL` | לא | ברירת מחדל `gemini-2.5-flash` |
| `AI_AGENT_WORK_DIR` | לא | תיקיית clone זמנית |

## הרשאות GitHub Token

צור **Fine-grained** או **Classic** token עם:

- `contents: read and write`
- `pull_requests: read and write`
- `metadata: read`

מומלץ token ייעודי לסביבה אחת (Railway), לא token אישי רחב.

## Railway

1. הוסף את כל משתני הסביבה למשתנהי השירות
2. ודא ש-`git` זמין (Nixpacks בדרך כלל כולל)
3. `AI_AGENT_WORK_DIR=/tmp/ai-agent-repos` – נשמר בין deploys רק ב-volume; בלי volume ה-clone מתבצע מחדש
4. **אל תסמוך על filesystem בקונטיינר לפרודקשן** – ה-PR הוא מקור האמת
5. הרץ `migrate` אחרי deploy (כבר ב-`scripts/start.sh`)

## אבטחה

- רק `templates/` ו-`static/` – נחסם בקוד
- אסור: settings, .env, migrations, auth, payment
- אין הרצת shell מה-AI
- אין push ל-`main`
- גישה לאדמין: superuser או `ADMIN_EMAIL` + staff
- הפעלה רק כש-`AI_AGENT_ENABLED=true`

## מבנה קוד

```
ai_agent/
  models.py          # AIChangeRequest
  admin.py           # ממשק + כפתורים
  services/
    gemini_service.py
    diff_validator.py
    path_guard.py
    workflow.py
  git_tools/
    repo.py
    github_pr.py
  prompts/
    system_prompt.txt
```
