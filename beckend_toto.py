"""
mandeles.co.il – מנוע חישוב מתקדם v3 (SECURE)
================================================
פורט 5001 | עצמאי מ-server.py (5000)

מקורות נתונים:
  ┌─ API-Football  → תוצאות, הרכבים, פציעות, סטטיסטיקות שחקנים
  ├─ OpenWeatherMap → תחזית מזג אוויר לכל מגרש
  └─ SQLite DB     → cache מקומי של כל הנתונים

פלט לכל משחק:
  ┌─ ציון כולל 0-100 (Composite Score)
  ├─ הסתברויות P(1) / P(X) / P(2)
  ├─ ניקוד שחקנים (Squad Strength)
  ├─ מקדם עייפות קבוצה
  ├─ השפעת מזג אוויר
  └─ טבלת דירוג קבוצות מחושבת

pip install flask flask-cors requests scipy numpy python-dotenv apscheduler flask-limiter
"""

import os, sys, json, math, sqlite3, logging, datetime, time, hmac, hashlib, secrets, queue, threading
from typing import Optional
import requests
import numpy as np
from scipy.stats import poisson
from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    LIMITER_AVAILABLE = True
except ImportError:
    LIMITER_AVAILABLE = False

load_dotenv()

# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────
API_FOOTBALL_KEY  = os.getenv("API_FOOTBALL_KEY",  "DEMO")
WEATHER_KEY       = os.getenv("OPENWEATHER_KEY",   "DEMO")
ISRAEL_LEAGUE     = 382
SEASON            = 2025
DB_PATH           = os.getenv("ENGINE_DB_PATH", "data/engine.db")
ENGINE_PORT       = int(os.getenv("ENGINE_PORT", 5001))
DEMO              = (API_FOOTBALL_KEY == "DEMO")

# ── אבטחה: ENGINE_SECRET חובה ──────────────────────────────
ENGINE_SECRET = os.getenv("ENGINE_SECRET")
if not ENGINE_SECRET:
    print("❌ FATAL: ENGINE_SECRET לא מוגדר ב-.env – הפעלה נעצרת.", file=sys.stderr)
    sys.exit(1)
if ENGINE_SECRET in ("change-this", "secret", "password", "123456"):
    print("❌ FATAL: ENGINE_SECRET חלש מדי. השתמש בסוד ארוך ואקראי.", file=sys.stderr)
    sys.exit(1)

# ── דומיינים מורשים ─────────────────────────────────────────
ALLOWED_ORIGINS = os.getenv(
    "ALLOWED_ORIGINS",
    "https://mandeles.co.il,https://www.mandeles.co.il"
).split(",")

os.makedirs("data", exist_ok=True)
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [ENGINE] %(levelname)s %(message)s",
    handlers=[logging.FileHandler("logs/engine.log"), logging.StreamHandler()]
)
log = logging.getLogger("engine")

app = Flask(__name__)

# ── CORS מוגבל לדומיין בלבד ─────────────────────────────────
CORS(app, origins=ALLOWED_ORIGINS, supports_credentials=False)

# ── Rate Limiting ────────────────────────────────────────────
if LIMITER_AVAILABLE:
    limiter = Limiter(
        get_remote_address,
        app=app,
        default_limits=["200 per hour", "60 per minute"],
        storage_uri="memory://"
    )
    log.info("✅ Rate limiter פעיל")
else:
    log.warning("⚠️  flask-limiter לא מותקן – pip install flask-limiter")
    limiter = None

# ── SSE: תור שידורים לכל ה-clients ─────────────────────────
_sse_clients: list[queue.Queue] = []
_sse_lock = threading.Lock()

def _sse_broadcast(event: str, data: dict):
    """שולח אירוע SSE לכל הדפדפנים המחוברים."""
    payload = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
    with _sse_lock:
        dead = []
        for q in _sse_clients:
            try:
                q.put_nowait(payload)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _sse_clients.remove(q)

# ── fingerprint נתונים לזיהוי שינויים ─────────────────────
def _data_fingerprint() -> str:
    """מחשב hash של כל האנליזות הקיימות לזיהוי שינוי."""
    with get_db() as db:
        rows = db.execute(
            "SELECT fixture_id, p1, px, p2, score_home, score_away, updated_at "
            "FROM analysis ORDER BY fixture_id"
        ).fetchall()
    digest = hashlib.md5(
        json.dumps([dict(r) for r in rows], ensure_ascii=False).encode()
    ).hexdigest()
    return digest

_last_fingerprint: str = ""

# ─────────────────────────────────────────────────────────────
# STADIUM COORDINATES (ליגת העל)
# ─────────────────────────────────────────────────────────────
STADIUMS = {
    "מכבי חיפה":           {"lat": 32.794, "lon": 34.989, "name": "סמי עופר"},
    'מכבי ת"א':            {"lat": 32.066, "lon": 34.763, "name": "בלומפילד"},
    'הפועל ב"ש':           {"lat": 31.234, "lon": 34.791, "name": "טרנר"},
    'בית"ר י-ם':           {"lat": 31.769, "lon": 35.191, "name": "טדי"},
    'הפועל ת"א':           {"lat": 32.066, "lon": 34.763, "name": "בלומפילד"},
    "עירוני קריות":        {"lat": 32.831, "lon": 35.083, "name": "סמי עופר"},
    "אשדוד":               {"lat": 31.804, "lon": 34.655, "name": "אשדוד"},
    "הפועל חיפה":          {"lat": 32.794, "lon": 34.989, "name": "סמי עופר"},
    "בני סכנין":           {"lat": 32.857, "lon": 35.298, "name": "דוחא"},
    "מ.ס. אשדוד":          {"lat": 31.804, "lon": 34.655, "name": "אשדוד"},
    "הפועל ירושלים":       {"lat": 31.769, "lon": 35.191, "name": "טדי"},
    "עירוני נס ציונה":     {"lat": 31.930, "lon": 34.798, "name": "נס ציונה"},
}

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
        CREATE TABLE IF NOT EXISTS matches (
            fixture_id   INTEGER PRIMARY KEY,
            home_id      INTEGER,
            away_id      INTEGER,
            home_name    TEXT,
            away_name    TEXT,
            match_date   TEXT,
            match_time   TEXT,
            round        TEXT,
            status       TEXT,
            home_goals   INTEGER,
            away_goals   INTEGER,
            home_xg      REAL,
            away_xg      REAL
        );

        CREATE TABLE IF NOT EXISTS players (
            player_id    INTEGER PRIMARY KEY,
            team_id      INTEGER,
            team_name    TEXT,
            name         TEXT,
            position     TEXT,         -- G / D / M / F
            rating       REAL,         -- ממוצע ניקוד עונה (0-10)
            minutes      INTEGER,      -- דקות משחק עונה
            goals        INTEGER,
            assists      INTEGER,
            is_key       INTEGER DEFAULT 0,   -- 1 = שחקן מפתח
            updated_at   TEXT
        );

        CREATE TABLE IF NOT EXISTS injuries (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            fixture_id   INTEGER,
            team_id      INTEGER,
            player_id    INTEGER,
            player_name  TEXT,
            reason       TEXT,         -- "Injury" / "Suspension"
            position     TEXT
        );

        CREATE TABLE IF NOT EXISTS weather_cache (
            cache_key    TEXT PRIMARY KEY,   -- home_name|date
            condition    TEXT,               -- Clear / Rain / Thunderstorm / Snow / Fog
            temp_c       REAL,
            wind_kmh     REAL,
            humidity_pct INTEGER,
            rain_mm      REAL,
            fetched_at   TEXT
        );

        CREATE TABLE IF NOT EXISTS analysis (
            fixture_id        INTEGER PRIMARY KEY,
            home_id           INTEGER,
            away_id           INTEGER,
            home_name         TEXT,
            away_name         TEXT,
            match_date        TEXT,
            round             TEXT,
            -- הסתברויות פואסון
            p1                REAL,
            px                REAL,
            p2                REAL,
            lambda_home       REAL,
            lambda_away       REAL,
            -- ציון כולל
            score_home        REAL,   -- composite 0-100
            score_away        REAL,
            -- רכיבי ניקוד
            momentum_home     REAL,
            momentum_away     REAL,
            squad_str_home    REAL,   -- חוזק הרכב 0-100
            squad_str_away    REAL,
            fatigue_home      REAL,   -- מקדם עייפות 0-1 (1=ללא עייפות)
            fatigue_away      REAL,
            weather_factor    REAL,   -- השפעת מזג האוויר על ביתי (-1 עד +1)
            home_win_pct      REAL,
            away_win_pct      REAL,
            home_xg           REAL,
            away_xg           REAL,
            -- נתוני תצוגה
            home_form         TEXT,   -- JSON
            away_form         TEXT,
            missing_home      TEXT,   -- JSON רשימת נעדרים
            missing_away      TEXT,
            weather_json      TEXT,
            h2h               TEXT,
            factors           TEXT,
            value_pick        TEXT,
            confidence        TEXT,
            recommendation    TEXT,
            updated_at        TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS team_rankings (
            team_id      INTEGER PRIMARY KEY,
            team_name    TEXT,
            rank         INTEGER,
            points       INTEGER,
            played       INTEGER,
            won          INTEGER,
            drawn        INTEGER,
            lost         INTEGER,
            gf           INTEGER,
            ga           INTEGER,
            gd           INTEGER,
            elo          REAL,        -- Elo rating מחושב
            squad_avg    REAL,        -- ממוצע ניקוד שחקנים
            updated_at   TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS engine_log (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            event    TEXT,
            details  TEXT,
            status   TEXT,
            ran_at   TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """)
    log.info("✅ DB אותחל")

# ─────────────────────────────────────────────────────────────
# LAYER 1 – API-FOOTBALL FETCHER
# ─────────────────────────────────────────────────────────────
class FootballAPI:
    BASE = "https://v3.football.api-sports.io"

    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update({"x-apisports-key": API_FOOTBALL_KEY})

    def _get(self, ep, params):
        if DEMO: return {}
        try:
            r = self.s.get(f"{self.BASE}/{ep}", params=params, timeout=15)
            r.raise_for_status()
            rem = r.headers.get("x-ratelimit-requests-remaining","?")
            log.info(f"API {ep} | remaining:{rem}")
            return r.json()
        except Exception as e:
            log.error(f"API שגיאה {ep}: {e}")
            return {}

    # ── Fixtures ──────────────────────────────────────────────
    def fetch_upcoming(self, n=20):
        d = self._get("fixtures", {"league": ISRAEL_LEAGUE, "season": SEASON, "next": n})
        return d.get("response", [])

    def fetch_finished(self, n=60):
        d = self._get("fixtures", {"league": ISRAEL_LEAGUE, "season": SEASON,
                                    "last": n, "status": "FT"})
        return d.get("response", [])

    def fetch_h2h(self, t1, t2):
        d = self._get("fixtures/headtohead", {"h2h": f"{t1}-{t2}", "last": 8})
        return d.get("response", [])

    # ── Players & Squads ──────────────────────────────────────
    def fetch_squad(self, team_id):
        """הרכב קבוצה + ניקוד שחקנים לעונה"""
        d = self._get("players", {"team": team_id, "league": ISRAEL_LEAGUE,
                                   "season": SEASON, "page": 1})
        return d.get("response", [])

    def fetch_fixture_players(self, fixture_id):
        """סטטיסטיקות שחקנים ממשחק ספציפי"""
        d = self._get("fixtures/players", {"fixture": fixture_id})
        return d.get("response", [])

    # ── Injuries ──────────────────────────────────────────────
    def fetch_injuries(self, team_id, fixture_id):
        d = self._get("injuries", {"team": team_id, "fixture": fixture_id})
        return d.get("response", [])

    # ── Standings ─────────────────────────────────────────────
    def fetch_standings(self):
        d = self._get("standings", {"league": ISRAEL_LEAGUE, "season": SEASON})
        try:
            return d["response"][0]["league"]["standings"][0]
        except Exception:
            return []

    def store_fixtures(self, fixtures, status_filter=None):
        with get_db() as db:
            for f in fixtures:
                fix   = f.get("fixture", {})
                teams = f.get("teams", {})
                goals = f.get("goals", {})
                st    = fix.get("status", {}).get("short", "")
                if status_filter and st not in status_filter:
                    continue
                dt = fix.get("date", "")
                db.execute("""
                    INSERT OR REPLACE INTO matches
                    (fixture_id,home_id,away_id,home_name,away_name,
                     match_date,match_time,round,status,home_goals,away_goals)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    fix.get("id"),
                    teams.get("home",{}).get("id"),
                    teams.get("away",{}).get("id"),
                    teams.get("home",{}).get("name"),
                    teams.get("away",{}).get("name"),
                    dt[:10] if dt else None,
                    dt[11:16] if len(dt) > 10 else "20:00",
                    f.get("league",{}).get("round",""),
                    st,
                    goals.get("home"), goals.get("away")
                ))

    def store_squad(self, team_id, team_name, players_data):
        """מנתח ושומר ניקוד שחקנים"""
        with get_db() as db:
            for entry in players_data:
                p     = entry.get("player", {})
                stats = (entry.get("statistics") or [{}])[0]
                games = stats.get("games", {})
                goals = stats.get("goals", {})

                rating   = float(games.get("rating") or 0)
                minutes  = int(games.get("minutes") or 0)
                position = games.get("position", "M")
                n_goals  = int(goals.get("total") or 0)
                assists  = int(goals.get("assists") or 0)
                is_key   = 1 if (rating >= 7.0 and minutes >= 500) else 0

                db.execute("""
                    INSERT OR REPLACE INTO players
                    (player_id,team_id,team_name,name,position,
                     rating,minutes,goals,assists,is_key,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
                """, (
                    p.get("id"), team_id, team_name,
                    p.get("name",""), position[:1].upper(),
                    rating, minutes, n_goals, assists, is_key
                ))

    def store_standings(self, standings):
        with get_db() as db:
            for s in standings:
                team = s.get("team", {})
                all_ = s.get("all", {})
                db.execute("""
                    INSERT OR REPLACE INTO team_rankings
                    (team_id,team_name,rank,points,played,won,drawn,lost,gf,ga,gd)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    team.get("id"), team.get("name"),
                    s.get("rank",0), s.get("points",0),
                    all_.get("played",0), all_.get("win",0),
                    all_.get("draw",0),  all_.get("lose",0),
                    all_.get("goals",{}).get("for",0),
                    all_.get("goals",{}).get("against",0),
                    s.get("goalsDiff",0)
                ))

    def store_injuries(self, fixture_id, team_id, injuries_data):
        with get_db() as db:
            db.execute("DELETE FROM injuries WHERE fixture_id=? AND team_id=?",
                       (fixture_id, team_id))
            for inj in injuries_data:
                p = inj.get("player", {})
                db.execute("""
                    INSERT INTO injuries
                    (fixture_id,team_id,player_id,player_name,reason,position)
                    VALUES (?,?,?,?,?,?)
                """, (
                    fixture_id, team_id, p.get("id"), p.get("name"),
                    p.get("type","Injury"), p.get("position","")
                ))

    # ── DEMO DATA ─────────────────────────────────────────────
    def demo_fixtures(self):
        today = datetime.date.today()
        base  = [
            (1001,1,2,"מכבי חיפה",'הפועל ב"ש',"20:45"),
            (1002,3,4,'מכבי ת"א','בית"ר י-ם',"21:00"),
            (1003,5,6,'הפועל ת"א',"עירוני קריות","19:30"),
            (1004,7,8,"אשדוד","הפועל חיפה","20:00"),
            (1005,9,10,"בני סכנין","מ.ס. אשדוד","19:00"),
            (1006,11,12,"הפועל ירושלים","עירוני נס ציונה","20:30"),
        ]
        with get_db() as db:
            for i,(fid,hid,aid,hn,an,tm) in enumerate(base):
                db.execute("""
                    INSERT OR REPLACE INTO matches
                    (fixture_id,home_id,away_id,home_name,away_name,
                     match_date,match_time,round,status)
                    VALUES (?,?,?,?,?,?,?,'סבב 28','NS')
                """, (fid,hid,aid,hn,an,
                      str(today+datetime.timedelta(days=i//2)),tm))

    def demo_past(self):
        """50 תוצאות עבר ריאליסטיות"""
        import random; random.seed(42)
        teams = [(1,"מכבי חיפה"),(2,'הפועל ב"ש'),(3,'מכבי ת"א'),
                 (4,'בית"ר י-ם'),(5,'הפועל ת"א'),(6,"עירוני קריות"),
                 (7,"אשדוד"),(8,"הפועל חיפה"),(9,"בני סכנין"),
                 (10,"מ.ס. אשדוד"),(11,"הפועל ירושלים"),(12,"עירוני נס ציונה")]
        # ביתיות חזקות
        strong = {1,3,4,11}
        with get_db() as db:
            fid = 2000
            for _ in range(50):
                h,a = random.sample(teams,2)
                home_bias = 0.3 if h[0] in strong else 0.15
                hg = random.choices([0,1,2,3,4],
                    weights=[10,25+int(home_bias*30),30,20,15])[0]
                ag = random.choices([0,1,2,3,4],
                    weights=[25,35,25,10,5])[0]
                d  = str(datetime.date.today()-datetime.timedelta(days=random.randint(7,200)))
                db.execute("""
                    INSERT OR REPLACE INTO matches
                    (fixture_id,home_id,away_id,home_name,away_name,
                     match_date,match_time,round,status,home_goals,away_goals)
                    VALUES (?,?,?,?,?,?,'20:00','–','FT',?,?)
                """, (fid,h[0],a[0],h[1],a[1],d,hg,ag))
                fid += 1

    def demo_players(self):
        """ניקוד שחקנים לדוגמה"""
        squads = {
            (1,"מכבי חיפה"):    [("א. כהן","G",7.4),("ב. לוי","D",7.1),("ג. כץ","D",6.8),("ד. אבי","M",7.6),("ה. שם","F",8.1)],
            (2,'הפועל ב"ש'):    [("ו. דן","G",6.9),("ז. עם","D",6.5),("ח. אל","M",6.7),("ט. בן","F",7.0),("י. גל","F",6.4)],
            (3,'מכבי ת"א'):     [("כ. רן","G",7.8),("ל. ים","D",7.3),("מ. אור","M",7.9),("נ. שן","M",7.5),("ס. קו","F",8.3)],
            (4,'בית"ר י-ם'):    [("ע. תל","G",7.2),("פ. אב","D",6.9),("צ. כד","M",7.1),("ק. שר","F",7.4),("ר. מת","F",6.8)],
            (5,'הפועל ת"א'):    [("ש. אנ","G",7.0),("ת. בע","D",6.8),("א. גב","M",7.2),("ב. הב","F",7.3),("ג. ות","F",6.6)],
            (6,"עירוני קריות"): [("ד. עב","G",7.3),("ה. מז","D",7.0),("ו. נח","M",7.4),("ז. קל","F",7.8),("ח. דל","F",7.1)],
            (7,"אשדוד"):        [("ט. שמ","G",6.5),("י. ח","D",6.3),("כ. כ","M",6.4),("ל. ש","F",6.7),("מ. ב","F",6.1)],
            (8,"הפועל חיפה"):   [("נ. מ","G",7.1),("ס. ת","D",6.9),("ע. פ","M",7.3),("פ. צ","F",7.5),("צ. ק","F",7.0)],
            (9,"בני סכנין"):    [("ק. ר","G",6.8),("ר. ש","D",6.6),("ש. ת","M",7.0),("ת. א","F",7.2),("א. ב","F",6.5)],
            (10,"מ.ס. אשדוד"):  [("ב. ג","G",6.7),("ג. ד","D",6.5),("ד. ה","M",6.9),("ה. ו","F",7.1),("ו. ז","F",6.4)],
            (11,"הפועל ירושלים"):[("ז. ח","G",7.5),("ח. ט","D",7.2),("ט. י","M",7.6),("י. כ","F",7.9),("כ. ל","F",7.3)],
            (12,"עירוני נס ציונה"):[("ל. מ","G",6.6),("מ. נ","D",6.4),("נ. ס","M",6.8),("ס. ע","F",7.0),("ע. פ","F",6.3)],
        }
        with get_db() as db:
            pid = 1
            for (tid,tname), players in squads.items():
                for name, pos, rating in players:
                    mins = int(rating * 120)
                    is_key = 1 if rating >= 7.5 else 0
                    db.execute("""
                        INSERT OR REPLACE INTO players
                        (player_id,team_id,team_name,name,position,
                         rating,minutes,goals,assists,is_key,updated_at)
                        VALUES (?,?,?,?,?,?,?,0,0,?,CURRENT_TIMESTAMP)
                    """, (pid,tid,tname,name,pos,rating,mins,is_key))
                    pid += 1

    def demo_h2h(self, t1, t2):
        import random; random.seed(t1*100+t2)
        results = []
        for i in range(4):
            hg = random.randint(0,3); ag = random.randint(0,2)
            d  = str(datetime.date.today()-datetime.timedelta(days=60*(i+1)))
            results.append({"date":d,"score":f"{hg}–{ag}",
                "result":"W" if hg>ag else("D" if hg==ag else "L")})
        return results


# ─────────────────────────────────────────────────────────────
# LAYER 2 – WEATHER FETCHER
# ─────────────────────────────────────────────────────────────
class WeatherFetcher:
    OWM_BASE = "https://api.openweathermap.org/data/2.5"

    def fetch(self, home_name: str, match_date: str, match_time: str = "20:00") -> dict:
        cache_key = f"{home_name}|{match_date}"
        with get_db() as db:
            cached = db.execute(
                "SELECT * FROM weather_cache WHERE cache_key=?", (cache_key,)
            ).fetchone()
            if cached:
                age = (datetime.datetime.utcnow() -
                       datetime.datetime.fromisoformat(cached["fetched_at"])).total_seconds()
                if age < 21600:   # cache 6 שעות
                    return dict(cached)

        stadium = STADIUMS.get(home_name)
        if not stadium or WEATHER_KEY == "DEMO":
            return self._demo_weather(home_name, match_date)

        try:
            params = {
                "lat": stadium["lat"], "lon": stadium["lon"],
                "appid": WEATHER_KEY, "units": "metric", "cnt": 40
            }
            r = requests.get(f"{self.OWM_BASE}/forecast", params=params, timeout=10)
            r.raise_for_status()
            data = r.json()

            # מחפש את תחזית השעה הקרובה ביותר למשחק
            target_dt = f"{match_date} {match_time}"
            best = min(data.get("list",[]), default=None,
                       key=lambda x: abs(x.get("dt_txt","") < target_dt))

            if not best:
                return self._demo_weather(home_name, match_date)

            weather = {
                "cache_key":    cache_key,
                "condition":    best["weather"][0]["main"],
                "temp_c":       best["main"]["temp"],
                "wind_kmh":     best["wind"]["speed"] * 3.6,
                "humidity_pct": best["main"]["humidity"],
                "rain_mm":      best.get("rain", {}).get("3h", 0.0),
                "fetched_at":   datetime.datetime.utcnow().isoformat()
            }
        except Exception as e:
            log.warning(f"מזג אוויר שגיאה: {e}")
            return self._demo_weather(home_name, match_date)

        with get_db() as db:
            db.execute("""
                INSERT OR REPLACE INTO weather_cache
                (cache_key,condition,temp_c,wind_kmh,humidity_pct,rain_mm,fetched_at)
                VALUES (?,?,?,?,?,?,?)
            """, (cache_key, weather["condition"], weather["temp_c"],
                  weather["wind_kmh"], weather["humidity_pct"],
                  weather["rain_mm"], weather["fetched_at"]))
        return weather

    def _demo_weather(self, home_name: str, match_date: str) -> dict:
        import random; random.seed(hash(home_name+match_date) % 999)
        conditions = ["Clear","Clear","Cloudy","Rain","Rain","Thunderstorm"]
        cond = random.choice(conditions)
        return {
            "cache_key": f"{home_name}|{match_date}",
            "condition": cond,
            "temp_c":    random.uniform(12, 32),
            "wind_kmh":  random.uniform(5, 40),
            "humidity_pct": random.randint(30, 85),
            "rain_mm":   random.uniform(0,15) if cond in ("Rain","Thunderstorm") else 0.0,
            "fetched_at": datetime.datetime.utcnow().isoformat()
        }

    def calc_weather_factor(self, weather: dict) -> tuple:
        """
        מחשב השפעת מזג אוויר על ביתי (-1 עד +1) ומילוי טקסטואלי.
        חוקי:
          גשם חזק  → אורחים מופחתים (ביתי רגיל למגרש)   → +0.06
          סערה     → שניהם מופחתים, ביתי מוכר יותר       → +0.10
          חום קיצוני (>35) → עייפות, ביתי מתורגל          → +0.04
          קור קיצוני (<8)  → ניטרלי בישראל                → 0
          רוח חזקה (>50)   → מפריעה לשחק ארוכות          → -0.05 לביתי
        """
        cond   = weather.get("condition","Clear")
        rain   = weather.get("rain_mm", 0)
        wind   = weather.get("wind_kmh", 10)
        temp   = weather.get("temp_c", 22)

        factor = 0.0
        notes  = []

        if cond == "Thunderstorm":
            factor += 0.10
            notes.append("⛈️ סערה – יתרון ביתי מוגבר")
        elif cond == "Rain" and rain > 5:
            factor += 0.06
            notes.append(f"🌧️ גשם ({rain:.0f}mm) – יתרון ביתי קל")
        elif cond == "Rain":
            notes.append("🌦️ גשם קל – השפעה קטנה")

        if temp > 35:
            factor += 0.04
            notes.append(f"🌡️ חום גבוה ({temp:.0f}°C) – ביתי מורגל")
        elif temp < 8:
            notes.append(f"❄️ קר ({temp:.0f}°C) – ניטרלי")

        if wind > 50:
            factor -= 0.05
            notes.append(f"💨 רוח חזקה ({wind:.0f}km/h) – מפריע לשחק")
        elif wind > 35:
            notes.append(f"🌬️ רוח ({wind:.0f}km/h) – השפעה קלה")

        if not notes:
            notes.append(f"☀️ תנאים טובים ({temp:.0f}°C)")

        return round(factor, 3), notes


# ─────────────────────────────────────────────────────────────
# LAYER 3 – SQUAD STRENGTH CALCULATOR
# ─────────────────────────────────────────────────────────────
class SquadCalculator:
    """
    מחשב חוזק הרכב 0-100 תוך התחשבות בנעדרים.

    שיטה:
      1. לוקח את 11 השחקנים הטובים של הקבוצה (לפי rating × דקות)
      2. מחסיר שחקנים פצועים/מושעים
      3. מחשב ממוצע משוקלל לפי עמדה (שוער × 0.15, הגנה × 0.30, קשר × 0.30, התקפה × 0.25)
      4. מנרמל ל-100
    """
    POS_WEIGHTS = {"G": 0.15, "D": 0.30, "M": 0.30, "F": 0.25}
    MAX_RATING  = 10.0

    def calc(self, team_id: int, missing_ids: list) -> tuple:
        with get_db() as db:
            players = db.execute("""
                SELECT * FROM players
                WHERE team_id=? AND minutes >= 200
                ORDER BY rating DESC
            """, (team_id,)).fetchall()

        if not players:
            return 65.0, []   # ברירת מחדל

        players = [dict(p) for p in players]
        missing_names = []

        # מסיר נעדרים
        available = []
        for p in players:
            if p["player_id"] in missing_ids:
                missing_names.append(f"{p['name']} ({p['position']})")
            else:
                available.append(p)

        # בוחר 11 הטובים (1G + מקסימום 4D + 4M + 3F, אחרת best 11)
        lineup = self._pick_lineup(available)

        # ממוצע משוקלל לפי עמדה
        by_pos = {"G":[], "D":[], "M":[], "F":[]}
        for p in lineup:
            pos = p["position"][:1].upper()
            if pos in by_pos:
                by_pos[pos].append(p["rating"])

        total_w, total_r = 0, 0
        for pos, ratings in by_pos.items():
            if ratings:
                avg = sum(ratings) / len(ratings)
                w   = self.POS_WEIGHTS.get(pos, 0.25)
                total_r += avg * w
                total_w += w

        if total_w == 0:
            squad_score = 65.0
        else:
            avg_rating   = total_r / total_w          # 0-10
            squad_score  = (avg_rating / self.MAX_RATING) * 100

        # קנס על נעדרי מפתח
        missing_key = sum(1 for p in players
                          if p["player_id"] in missing_ids and p["is_key"])
        squad_score -= missing_key * 4.0   # -4 נקודות לכל שחקן מפתח חסר
        squad_score  = max(20, min(100, round(squad_score, 1)))

        return squad_score, missing_names

    def _pick_lineup(self, players):
        # מסדר לפי rating ובוחר 11 הטובים
        return sorted(players, key=lambda p: p["rating"], reverse=True)[:11]


# ─────────────────────────────────────────────────────────────
# LAYER 4 – FATIGUE CALCULATOR
# ─────────────────────────────────────────────────────────────
class FatigueCalc:
    """
    מחשב מקדם עייפות 0-1 (1 = רענן, 0 = מאוד עייף).

    גורמים:
      - כמה משחקים ב-10 ימים האחרונים
      - האם שיחקו בגביע / אירופה בשבוע האחרון
      - מנוחה בימים מהמשחק הקודם
    """

    def calc(self, team_id: int, match_date: str) -> tuple:
        try:
            ref = datetime.date.fromisoformat(match_date)
        except Exception:
            return 1.0, "מידע לא זמין"

        since_10 = str(ref - datetime.timedelta(days=10))
        since_4  = str(ref - datetime.timedelta(days=4))

        with get_db() as db:
            # משחקים ב-10 ימים האחרונים
            count_10 = db.execute("""
                SELECT COUNT(*) FROM matches
                WHERE status='FT' AND (home_id=? OR away_id=?)
                AND match_date >= ? AND match_date < ?
            """, (team_id, team_id, since_10, match_date)).fetchone()[0]

            # המשחק האחרון
            last = db.execute("""
                SELECT match_date FROM matches
                WHERE status='FT' AND (home_id=? OR away_id=?)
                AND match_date < ?
                ORDER BY match_date DESC LIMIT 1
            """, (team_id, team_id, match_date)).fetchone()

        days_rest = 99
        if last:
            try:
                days_rest = (ref - datetime.date.fromisoformat(last["match_date"])).days
            except Exception:
                pass

        # חישוב ציון עייפות
        fatigue = 1.0

        # משחקים רבים = עייפות
        if count_10 >= 4:
            fatigue -= 0.20
            level = "גבוהה מאוד"
        elif count_10 == 3:
            fatigue -= 0.12
            level = "גבוהה"
        elif count_10 == 2:
            fatigue -= 0.06
            level = "בינונית"
        else:
            level = "נמוכה"

        # מעט מנוחה = עייפות נוספת
        if days_rest <= 2:
            fatigue -= 0.10
            level = "קריטית – " + str(days_rest) + " ימי מנוחה"
        elif days_rest <= 4:
            fatigue -= 0.04

        fatigue = max(0.5, min(1.0, round(fatigue, 3)))

        if days_rest == 99:
            desc = "אין מידע על מנוחה"
        elif days_rest <= 2:
            desc = f"⚠️ {days_rest} ימי מנוחה בלבד – עייפות {level}"
        elif count_10 >= 3:
            desc = f"⚠️ {count_10} משחקים ב-10 ימים – עייפות {level}"
        else:
            desc = f"✅ {days_rest} ימי מנוחה – מצב טוב"

        return fatigue, desc


# ─────────────────────────────────────────────────────────────
# LAYER 5 – ELO CALCULATOR
# ─────────────────────────────────────────────────────────────
class EloEngine:
    """
    מחשב Elo Rating לכל קבוצה מסך כל תוצאות העונה.
    מתחיל מ-1500 לכולם, K=32 לכל משחק.
    """
    K = 32
    BASE = 1500

    def recalculate_all(self):
        with get_db() as db:
            matches = db.execute("""
                SELECT home_id,away_id,home_goals,away_goals
                FROM matches WHERE status='FT' AND home_goals IS NOT NULL
                ORDER BY match_date
            """).fetchall()

        elo = {}

        for m in matches:
            h, a = m["home_id"], m["away_id"]
            if h not in elo: elo[h] = self.BASE
            if a not in elo: elo[a] = self.BASE

            eh, ea = elo[h], elo[a]
            # יתרון ביתי קבוע +100
            exp_h = 1 / (1 + 10 ** ((ea - eh - 100) / 400))
            exp_a = 1 - exp_h

            hg = m["home_goals"] or 0
            ag = m["away_goals"] or 0
            if hg > ag:   sh, sa = 1.0, 0.0
            elif hg == ag: sh, sa = 0.5, 0.5
            else:          sh, sa = 0.0, 1.0

            # שינוי Elo
            elo[h] = round(eh + self.K * (sh - exp_h), 1)
            elo[a] = round(ea + self.K * (sa - exp_a), 1)

        # שמור ב-DB
        with get_db() as db:
            for team_id, rating in elo.items():
                db.execute("""
                    UPDATE team_rankings SET elo=? WHERE team_id=?
                """, (rating, team_id))

        return elo


# ─────────────────────────────────────────────────────────────
# LAYER 6 – POISSON ENGINE (משופר עם כל הגורמים)
# ─────────────────────────────────────────────────────────────
class PoissonEngine:
    AVG_HOME = 1.42
    AVG_AWAY = 1.05

    def __init__(self):
        self._recalc_avgs()

    def _recalc_avgs(self):
        with get_db() as db:
            r = db.execute("""
                SELECT AVG(home_goals) hg, AVG(away_goals) ag, COUNT(*) n
                FROM matches WHERE status='FT' AND home_goals IS NOT NULL
            """).fetchone()
        if r and r["n"] and r["n"] >= 15:
            self.AVG_HOME = r["hg"] or 1.42
            self.AVG_AWAY = r["ag"] or 1.05

    def _avg_goals(self, team_id, side, venue="all", n=10):
        with get_db() as db:
            if venue == "home":
                sql = "SELECT home_goals g FROM matches WHERE status='FT' AND home_id=? ORDER BY match_date DESC LIMIT ?"
                rows = db.execute(sql,(team_id,n)).fetchall()
                vals = [r["g"] for r in rows if r["g"] is not None]
            elif venue == "away":
                sql = "SELECT away_goals g FROM matches WHERE status='FT' AND away_id=? ORDER BY match_date DESC LIMIT ?"
                rows = db.execute(sql,(team_id,n)).fetchall()
                vals = [r["g"] for r in rows if r["g"] is not None]
            else:
                rows = db.execute("""
                    SELECT home_id, home_goals, away_goals FROM matches
                    WHERE status='FT' AND (home_id=? OR away_id=?)
                    ORDER BY match_date DESC LIMIT ?
                """,(team_id,team_id,n)).fetchall()
                if side == "scored":
                    vals = [(r["home_goals"] if r["home_id"]==team_id else r["away_goals"])
                            for r in rows if r["home_goals"] is not None]
                else:
                    vals = [(r["away_goals"] if r["home_id"]==team_id else r["home_goals"])
                            for r in rows if r["home_goals"] is not None]
        return sum(vals)/len(vals) if vals else (self.AVG_HOME if venue=="home" else self.AVG_AWAY)

    def calc(self, home_id, away_id,
             momentum_home, momentum_away,
             squad_home, squad_away,
             fatigue_home, fatigue_away,
             weather_factor,
             elo_home=None, elo_away=None) -> dict:
        """
        מחשב lambda משולב מכל הגורמים.

        משקלי הגורמים:
          60% – מודל פואסון בסיסי (התקפה/הגנה היסטורית)
          15% – חוזק הרכב (squad strength)
          10% – מומנטום
           8% – Elo (אם זמין)
           5% – עייפות
           2% – מזג אוויר
        """
        # ── פואסון בסיסי ──────────────────────────────────────
        ha = self._avg_goals(home_id, "scored",   "home") / self.AVG_HOME
        hd = self._avg_goals(home_id, "conceded", "home") / self.AVG_AWAY
        aa = self._avg_goals(away_id, "scored",   "away") / self.AVG_AWAY
        ad = self._avg_goals(away_id, "conceded", "away") / self.AVG_HOME

        lh_base = self.AVG_HOME * ha * ad
        la_base = self.AVG_AWAY * aa * hd

        # ── מקדם Elo ──────────────────────────────────────────
        elo_adj = 0.0
        if elo_home and elo_away:
            diff = (elo_home - elo_away) / 400
            elo_adj = diff * 0.08   # +8% לכל 400 נקודות הפרש

        # ── מקדם חוזק הרכב ────────────────────────────────────
        # squad_home ו-squad_away הם 0-100
        squad_diff = (squad_home - squad_away) / 100   # -1 עד +1
        squad_adj  = squad_diff * 0.15

        # ── מקדם מומנטום ──────────────────────────────────────
        mom_diff = (momentum_home - momentum_away)   # -1 עד +1
        mom_adj  = mom_diff * 0.10

        # ── עייפות ────────────────────────────────────────────
        # fatigue הוא 0.5-1.0 (1=רענן). מחלק את lambda ב-fatigue
        # עייף → lambda קטן יותר
        fatigue_adj_h = fatigue_home   # 0.5-1.0
        fatigue_adj_a = fatigue_away

        # ── מזג אוויר ─────────────────────────────────────────
        # weather_factor: +/- השפעה על ביתי
        weather_adj = weather_factor * 0.02

        # ── שילוב ─────────────────────────────────────────────
        total_adj_h = 1 + elo_adj + squad_adj + mom_adj + weather_adj
        total_adj_a = 1 - elo_adj - squad_adj - mom_adj - weather_adj

        lh = lh_base * total_adj_h * fatigue_adj_h
        la = la_base * total_adj_a * fatigue_adj_a

        # גבולות
        lh = max(0.3, min(4.0, lh))
        la = max(0.3, min(4.0, la))

        # ── מטריצת פואסון ─────────────────────────────────────
        p1 = px = p2 = 0.0
        for i in range(10):
            for j in range(10):
                p = poisson.pmf(i,lh) * poisson.pmf(j,la)
                if i > j:   p1 += p
                elif i==j:  px += p
                else:        p2 += p

        total = p1 + px + p2
        return {
            "p1":            round(p1/total*100, 1),
            "px":            round(px/total*100, 1),
            "p2":            round(p2/total*100, 1),
            "lambda_home":   round(lh, 3),
            "lambda_away":   round(la, 3),
            "adjustments": {
                "elo":     round(elo_adj, 4),
                "squad":   round(squad_adj, 4),
                "momentum":round(mom_adj, 4),
                "fatigue_h":round(fatigue_adj_h,3),
                "fatigue_a":round(fatigue_adj_a,3),
                "weather": round(weather_adj, 4),
            }
        }


# ─────────────────────────────────────────────────────────────
# LAYER 7 – COMPOSITE SCORE & VALUE
# ─────────────────────────────────────────────────────────────
class CompositeScorer:
    """
    מחשב ציון כולל 0-100 לכל קבוצה ומזהה ערך.

    ציון כולל = ממוצע משוקלל של:
      30% – הסתברות לנצחון (מהמודל)
      20% – חוזק הרכב (squad)
      20% – מומנטום
      15% – Elo
      10% – יתרון בית/חוץ היסטורי
       5% – עייפות (הפוכה)
    """

    def calc_score(self, win_prob, squad_str, momentum,
                   elo, elo_avg, venue_pct, fatigue) -> float:
        # נרמולים
        prob_n    = win_prob / 100                 # 0-1
        squad_n   = squad_str / 100                # 0-1
        mom_n     = momentum                        # 0-1
        elo_n     = min(1, max(0, (elo - 1200) / 600)) if elo else 0.5
        venue_n   = venue_pct                       # 0-1
        fatigue_n = fatigue                         # 0.5-1 (1=רענן)

        score = (
            prob_n   * 30 +
            squad_n  * 20 +
            mom_n    * 20 +
            elo_n    * 15 +
            venue_n  * 10 +
            fatigue_n * 5
        )
        return round(min(100, max(0, score)), 1)

    def value_pick(self, p1, px, p2, score_h, score_a) -> dict:
        score_diff = score_h - score_a   # חיובי = ביתי עדיף

        if score_diff >= 15 and p1 >= 55:
            pick   = "1"
            reason = f"ביתי מועדף בבירור – ציון {score_h:.0f} מול {score_a:.0f}"
            conf   = "high"
        elif score_diff <= -15 and p2 >= 50:
            pick   = "2"
            reason = f"אורחים מועדפים – ציון {score_a:.0f} מול {score_h:.0f}"
            conf   = "high"
        elif px >= 30 and abs(score_diff) < 10:
            pick   = "X"
            reason = f"משחק מאוזן מאוד – תיקו סביר ({px}%)"
            conf   = "medium"
        elif score_diff > 5 and p1 >= 45:
            pick   = "1X"
            reason = f"ביתי עדיף קלות – כפול 1X מכסה {p1+px:.0f}%"
            conf   = "medium"
        elif score_diff < -5 and p2 >= 40:
            pick   = "X2"
            reason = f"אורחים קלות עדיפים – כפול X2 מכסה {px+p2:.0f}%"
            conf   = "medium"
        else:
            pick   = "X1" if score_diff >= 0 else "X2"
            reason = f"משחק לא בטוח – כפול מומלץ"
            conf   = "low"

        rec_map = {
            "1":  f"נצחון ביתי ({p1}%) – בטוח יחסית",
            "2":  f"נצחון אורחים ({p2}%) – ערך פוטנציאלי",
            "X":  f"תיקו ({px}%) – שקול כפול X1",
            "1X": f"כפול 1X – מכסה {p1+px:.0f}%",
            "X2": f"כפול X2 – מכסה {px+p2:.0f}%",
            "X1": f"כפול X1 – מכסה {px+p1:.0f}%",
        }

        return {"pick": pick, "confidence": conf,
                "reason": reason, "recommendation": rec_map[pick]}


# ─────────────────────────────────────────────────────────────
# MASTER ANALYZER
# ─────────────────────────────────────────────────────────────
class MasterAnalyzer:
    def __init__(self):
        self.api     = FootballAPI()
        self.weather = WeatherFetcher()
        self.squad   = SquadCalculator()
        self.fatigue = FatigueCalc()
        self.elo     = EloEngine()
        self.poisson = PoissonEngine()
        self.scorer  = CompositeScorer()

    # ── עדכון נתונים מלא ──────────────────────────────────────
    def refresh_data(self):
        log.info("🔄 מתחיל עדכון נתונים...")
        if DEMO:
            self.api.demo_fixtures()
            self.api.demo_past()
            self.api.demo_players()
        else:
            # משחקים
            finished = self.api.fetch_finished(60)
            self.api.store_fixtures(finished, {"FT"})
            upcoming = self.api.fetch_upcoming(20)
            self.api.store_fixtures(upcoming, {"NS","TBD","PST"})

            # טבלת ליגה
            standings = self.api.fetch_standings()
            self.api.store_standings(standings)

            # שחקנים (מגביל ל-12 קבוצות × 1 בקשה)
            with get_db() as db:
                teams = db.execute(
                    "SELECT DISTINCT home_id id, home_name name FROM matches LIMIT 20"
                ).fetchall()
            for t in teams:
                pdata = self.api.fetch_squad(t["id"])
                self.api.store_squad(t["id"], t["name"], pdata)
                time.sleep(0.5)   # rate limit

        # Elo מחדש
        self.elo.recalculate_all()
        # Poisson אמוצעי ליגה מחדש
        self.poisson._recalc_avgs()
        log.info("✅ עדכון נתונים הושלם")

    # ── ניתוח משחק בודד ──────────────────────────────────────
    def analyze(self, fixture_id: int) -> dict:
        with get_db() as db:
            m = db.execute(
                "SELECT * FROM matches WHERE fixture_id=?", (fixture_id,)
            ).fetchone()
        if not m:
            return {"error": "משחק לא נמצא"}
        m = dict(m)

        home_id    = m["home_id"]
        away_id    = m["away_id"]
        match_date = m.get("match_date") or str(datetime.date.today())
        match_time = m.get("match_time","20:00")

        log.info(f"מנתח: {m['home_name']} vs {m['away_name']}")

        # ── פציעות ────────────────────────────────────────────
        if DEMO:
            home_inj_ids, away_inj_ids = [], []
            home_missing, away_missing = [], []
        else:
            h_inj = self.api.fetch_injuries(home_id, fixture_id)
            a_inj = self.api.fetch_injuries(away_id, fixture_id)
            self.api.store_injuries(fixture_id, home_id, h_inj)
            self.api.store_injuries(fixture_id, away_id, a_inj)
            home_inj_ids = [x.get("player",{}).get("id") for x in h_inj]
            away_inj_ids = [x.get("player",{}).get("id") for x in a_inj]
            home_missing = [x.get("player",{}).get("name") for x in h_inj]
            away_missing = [x.get("player",{}).get("name") for x in a_inj]

        # ── חוזק הרכב ─────────────────────────────────────────
        squad_h, missing_h = self.squad.calc(home_id, home_inj_ids)
        squad_a, missing_a = self.squad.calc(away_id, away_inj_ids)

        # ── עייפות ────────────────────────────────────────────
        fatigue_h, fatigue_desc_h = self.fatigue.calc(home_id, match_date)
        fatigue_a, fatigue_desc_a = self.fatigue.calc(away_id, match_date)

        # ── מזג אוויר ─────────────────────────────────────────
        weather     = self.weather.fetch(m["home_name"], match_date, match_time)
        w_factor, w_notes = self.weather.calc_weather_factor(weather)

        # ── מומנטום ───────────────────────────────────────────
        mom_h, form_h = self._momentum(home_id)
        mom_a, form_a = self._momentum(away_id)

        # ── Elo ───────────────────────────────────────────────
        elo_h, elo_a = self._elo(home_id), self._elo(away_id)

        # ── % ניצחונות מגרש ───────────────────────────────────
        home_pct = self._venue_pct(home_id, "home")
        away_pct = self._venue_pct(away_id, "away")

        # ── H2H ───────────────────────────────────────────────
        if DEMO:
            h2h = self.api.demo_h2h(home_id, away_id)
        else:
            raw  = self.api.fetch_h2h(home_id, away_id)
            h2h  = self._parse_h2h(home_id, raw)

        # ── פואסון ────────────────────────────────────────────
        probs = self.poisson.calc(
            home_id, away_id,
            mom_h, mom_a,
            squad_h, squad_a,
            fatigue_h, fatigue_a,
            w_factor, elo_h, elo_a
        )
        p1, px, p2 = probs["p1"], probs["px"], probs["p2"]

        # ── ציון כולל ─────────────────────────────────────────
        score_h = self.scorer.calc_score(
            p1, squad_h, mom_h, elo_h, 1500, home_pct, fatigue_h)
        score_a = self.scorer.calc_score(
            p2, squad_a, mom_a, elo_a, 1500, away_pct, fatigue_a)

        # ── המלצה ─────────────────────────────────────────────
        val = self.scorer.value_pick(p1, px, p2, score_h, score_a)

        # ── גורמי X ───────────────────────────────────────────
        factors = self._build_factors(
            m["home_name"], m["away_name"],
            fatigue_h, fatigue_a, fatigue_desc_h, fatigue_desc_a,
            missing_h or home_missing, missing_a or away_missing,
            squad_h, squad_a, mom_h, mom_a, home_pct,
            w_notes, elo_h, elo_a, probs["adjustments"]
        )

        # ── שמירה ─────────────────────────────────────────────
        result = {
            "fixture_id":    fixture_id,
            "home_id":       home_id, "away_id": away_id,
            "home_name":     m["home_name"], "away_name": m["away_name"],
            "match_date":    match_date, "round": m.get("round",""),
            "p1": p1, "px": px, "p2": p2,
            "lambda_home":   probs["lambda_home"],
            "lambda_away":   probs["lambda_away"],
            "score_home":    score_h, "score_away": score_a,
            "momentum_home": mom_h,   "momentum_away": mom_a,
            "squad_str_home":squad_h, "squad_str_away":squad_a,
            "fatigue_home":  fatigue_h,"fatigue_away": fatigue_a,
            "weather_factor":w_factor,
            "home_win_pct":  round(home_pct*100,1),
            "away_win_pct":  round(away_pct*100,1),
            "home_xg":       probs["lambda_home"],
            "away_xg":       probs["lambda_away"],
            "home_form":     form_h, "away_form": form_a,
            "missing_home":  missing_h or home_missing,
            "missing_away":  missing_a or away_missing,
            "weather":       weather,
            "h2h":           h2h,
            "factors":       factors,
            "value_pick":    val["pick"],
            "confidence":    val["confidence"],
            "recommendation":val["recommendation"],
            "adjustments":   probs["adjustments"],
        }

        with get_db() as db:
            db.execute("""
                INSERT OR REPLACE INTO analysis
                (fixture_id,home_id,away_id,home_name,away_name,match_date,round,
                 p1,px,p2,lambda_home,lambda_away,
                 score_home,score_away,
                 momentum_home,momentum_away,
                 squad_str_home,squad_str_away,
                 fatigue_home,fatigue_away,weather_factor,
                 home_win_pct,away_win_pct,home_xg,away_xg,
                 home_form,away_form,missing_home,missing_away,
                 weather_json,h2h,factors,
                 value_pick,confidence,recommendation,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,
                        CURRENT_TIMESTAMP)
            """, (
                fixture_id,home_id,away_id,m["home_name"],m["away_name"],
                match_date,m.get("round",""),
                p1,px,p2,probs["lambda_home"],probs["lambda_away"],
                score_h,score_a,
                mom_h,mom_a,squad_h,squad_a,
                fatigue_h,fatigue_a,w_factor,
                round(home_pct*100,1),round(away_pct*100,1),
                probs["lambda_home"],probs["lambda_away"],
                json.dumps(form_h),json.dumps(form_a),
                json.dumps(missing_h or home_missing),
                json.dumps(missing_a or away_missing),
                json.dumps(weather),json.dumps(h2h),json.dumps(factors),
                val["pick"],val["confidence"],val["recommendation"]
            ))

        log.info(f"✅ {m['home_name']} {p1}% | X:{px}% | {m['away_name']} {p2}% | ציון {score_h}-{score_a}")
        return result

    # ── HELPERS ───────────────────────────────────────────────
    def _momentum(self, team_id, n=5):
        with get_db() as db:
            rows = db.execute("""
                SELECT home_id,home_goals,away_goals FROM matches
                WHERE status='FT' AND (home_id=? OR away_id=?)
                AND home_goals IS NOT NULL
                ORDER BY match_date DESC LIMIT ?
            """, (team_id,team_id,n)).fetchall()
        if not rows: return 0.5, []
        w = [0.35,0.25,0.20,0.12,0.08]
        form, scores = [], []
        for m in rows:
            hg = m["home_goals"] or 0; ag = m["away_goals"] or 0
            gf,ga = (hg,ag) if m["home_id"]==team_id else (ag,hg)
            if gf>ga:   form.append("W"); scores.append(1.0)
            elif gf==ga: form.append("D"); scores.append(0.5)
            else:        form.append("L"); scores.append(0.0)
        wts = w[:len(scores)]
        return round(sum(s*wt for s,wt in zip(scores,wts))/sum(wts),3), form

    def _elo(self, team_id) -> Optional[float]:
        with get_db() as db:
            r = db.execute("SELECT elo FROM team_rankings WHERE team_id=?",
                           (team_id,)).fetchone()
        return r["elo"] if r and r["elo"] else None

    def _venue_pct(self, team_id, venue, n=15) -> float:
        with get_db() as db:
            if venue == "home":
                rows = db.execute("""
                    SELECT home_goals,away_goals FROM matches
                    WHERE status='FT' AND home_id=? AND home_goals IS NOT NULL
                    ORDER BY match_date DESC LIMIT ?
                """,(team_id,n)).fetchall()
                wins = sum(1 for r in rows if (r["home_goals"] or 0) > (r["away_goals"] or 0))
            else:
                rows = db.execute("""
                    SELECT home_goals,away_goals FROM matches
                    WHERE status='FT' AND away_id=? AND home_goals IS NOT NULL
                    ORDER BY match_date DESC LIMIT ?
                """,(team_id,n)).fetchall()
                wins = sum(1 for r in rows if (r["away_goals"] or 0) > (r["home_goals"] or 0))
        return wins/len(rows) if rows else 0.40

    def _parse_h2h(self, home_id, raw):
        out = []
        for f in raw[:5]:
            g  = f.get("goals",{})
            hg = g.get("home",0) or 0; ag = g.get("away",0) or 0
            is_home = f.get("teams",{}).get("home",{}).get("id") == home_id
            r = ("W" if (hg>ag and is_home) or (ag>hg and not is_home) else
                 "D" if hg==ag else "L")
            dt = f.get("fixture",{}).get("date","")[:10]
            out.append({"date":dt,"score":f"{hg}–{ag}","result":r})
        return out

    def _build_factors(self, hn, an,
                       fh, fa, fdh, fda,
                       missing_h, missing_a,
                       sq_h, sq_a, mom_h, mom_a,
                       home_pct, w_notes,
                       elo_h, elo_a, adj) -> list:
        factors = []

        # עייפות ביתי
        if fh < 0.85:
            factors.append({"type":"warn","icon":"😓","text":f"<strong>עייפות {hn}</strong>: {fdh}"})
        # עייפות אורחים
        if fa < 0.85:
            factors.append({"type":"neutral","icon":"😓","text":f"<strong>עייפות {an}</strong>: {fda}"})

        # נעדרים ביתי
        if missing_h:
            factors.append({"type":"warn","icon":"🏥",
                "text":f"<strong>נעדרים ב{hn}</strong>: {', '.join(missing_h[:3])}"})
        # נעדרים אורחים
        if missing_a:
            factors.append({"type":"warn","icon":"🏥",
                "text":f"<strong>נעדרים ב{an}</strong>: {', '.join(missing_a[:3])}"})

        # חוזק הרכב
        sq_diff = sq_h - sq_a
        if abs(sq_diff) >= 8:
            favor = hn if sq_diff > 0 else an
            factors.append({"type":"good" if sq_diff>0 else "neutral","icon":"⭐",
                "text":f"<strong>חוזק הרכב</strong>: {hn} {sq_h:.0f} מול {an} {sq_a:.0f} – יתרון ל{favor}"})

        # Elo
        if elo_h and elo_a:
            ed = elo_h - elo_a
            if abs(ed) >= 50:
                favor = hn if ed>0 else an
                factors.append({"type":"good" if ed>0 else "neutral","icon":"📈",
                    "text":f"<strong>Elo</strong>: {hn} {elo_h:.0f} מול {an} {elo_a:.0f} – {favor} מדורגת גבוה יותר"})

        # יתרון ביתי
        if home_pct >= 0.60:
            factors.append({"type":"good","icon":"🏠",
                "text":f"<strong>יתרון ביתי</strong>: {hn} זוכה {home_pct*100:.0f}% בבית"})
        elif home_pct <= 0.30:
            factors.append({"type":"neutral","icon":"🏟️",
                "text":f"<strong>מגרש חלש</strong>: {hn} זוכה רק {home_pct*100:.0f}% בבית"})

        # מזג אוויר
        for note in w_notes:
            factors.append({"type":"neutral","icon":"🌤️","text":note})

        # מומנטום
        if mom_h >= 0.75:
            factors.append({"type":"good","icon":"🔥",
                "text":f"<strong>מומנטום גבוה</strong>: {hn} בסדרה חיובית"})
        if mom_a >= 0.75:
            factors.append({"type":"warn","icon":"🔥",
                "text":f"<strong>אורחים בפורמה</strong>: {an} מגיעים עם ביטחון"})

        return factors[:6]

    # ── מחזור מלא ─────────────────────────────────────────────
    def run_full_cycle(self) -> dict:
        start = time.time()
        self.refresh_data()

        with get_db() as db:
            upcoming = db.execute("""
                SELECT fixture_id FROM matches
                WHERE status IN ('NS','TBD','PST')
                ORDER BY match_date, match_time
            """).fetchall()

        results, errors = [], []
        for row in upcoming:
            try:
                self.analyze(row["fixture_id"])
                results.append(row["fixture_id"])
            except Exception as e:
                log.error(f"שגיאה fixture {row['fixture_id']}: {e}")
                errors.append(str(row["fixture_id"]))

        elapsed = round(time.time()-start, 2)
        with get_db() as db:
            db.execute(
                "INSERT INTO engine_log(event,details,status) VALUES(?,?,?)",
                ("full_cycle", json.dumps({
                    "analyzed": len(results), "errors": len(errors),
                    "elapsed_sec": elapsed, "demo": DEMO
                }), "ok" if not errors else "partial")
            )
        log.info(f"✅ מחזור הושלם | {len(results)} משחקים | {elapsed}s")
        result_data = {"analyzed": len(results), "errors": errors, "elapsed_sec": elapsed}

        # שדר עדכון לכל הדפדפנים המחוברים
        global _last_fingerprint
        new_fp = _data_fingerprint()
        if new_fp != _last_fingerprint:
            _last_fingerprint = new_fp
            try:
                with get_db() as db:
                    rows = db.execute("""
                        SELECT a.*, m.status, m.match_time FROM analysis a
                        JOIN matches m ON a.fixture_id=m.fixture_id
                        ORDER BY a.match_date, m.match_time
                    """).fetchall()
                fixtures = [_load_analysis(r) for r in rows]
                _sse_broadcast("update", {"fixtures": fixtures, "count": len(fixtures),
                                          "elapsed_sec": elapsed})
                log.info(f"📡 SSE: שידר עדכון ל-{len(_sse_clients)} clients")
            except Exception as e:
                log.error(f"SSE broadcast error: {e}")

        return result_data


# ─────────────────────────────────────────────────────────────
# FLASK API
# ─────────────────────────────────────────────────────────────
init_db()   # חובה לפני יצירת MasterAnalyzer
master = MasterAnalyzer()

def auth(req) -> bool:
    """
    אימות HMAC עם הגנת Replay.
    Headers נדרשים:
      X-Engine-Secret  – HMAC-SHA256(ENGINE_SECRET, timestamp)
      X-Engine-TS      – Unix timestamp (שניות)
    """
    secret = req.headers.get("X-Engine-Secret", "")
    ts_str = req.headers.get("X-Engine-TS", "")

    if not secret or not ts_str:
        log.warning(f"auth: missing headers from {req.remote_addr}")
        return False

    try:
        ts = int(ts_str)
    except ValueError:
        log.warning(f"auth: invalid timestamp from {req.remote_addr}")
        return False

    age = abs(int(time.time()) - ts)
    if age > 60:
        log.warning(f"auth: stale timestamp (age={age}s) from {req.remote_addr}")
        return False

    expected = hmac.new(
        ENGINE_SECRET.encode(),
        msg=ts_str.encode(),
        digestmod=hashlib.sha256
    ).hexdigest()

    ok = hmac.compare_digest(secret, expected)
    if not ok:
        log.warning(f"auth: invalid secret from {req.remote_addr} endpoint={req.path}")
    return ok

def _sanitize_str(v):
    """מסיר תגיות HTML מסוכנות מ-string (XSS protection בצד שרת)."""
    if not isinstance(v, str):
        return v
    import re
    # מאפשר רק <strong> <br> – חוסם הכל אחר
    v = re.sub(r"<(?!/?(?:strong|br))[^>]+>", "", v)
    return v

def _sanitize_deep(obj):
    """רקורסיבית מנקה strings בכל המבנה."""
    if isinstance(obj, str):
        return _sanitize_str(obj)
    if isinstance(obj, list):
        return [_sanitize_deep(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _sanitize_deep(v) for k, v in obj.items()}
    return obj

def _load_analysis(row):
    d = dict(row)
    for k in ("home_form","away_form","missing_home","missing_away",
              "weather_json","h2h","factors"):
        d[k] = json.loads(d.get(k) or "[]")
    # נקה XSS מכל שדות הטקסט
    return _sanitize_deep(d)

@app.route("/engine/health")
def health():
    with get_db() as db:
        last = db.execute(
            "SELECT ran_at,details FROM engine_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        n_fix  = db.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
        n_anal = db.execute("SELECT COUNT(*) FROM analysis").fetchone()[0]
        n_play = db.execute("SELECT COUNT(*) FROM players").fetchone()[0]
    return jsonify({
        "status":"ok", "demo_mode":DEMO,
        "fixtures":n_fix, "analysis":n_anal, "players":n_play,
        "last_run": dict(last) if last else None,
        "ts": datetime.datetime.utcnow().isoformat(),
        "fingerprint": _data_fingerprint()
    })

# ── Server-Sent Events – עדכונים חיים ───────────────────────
@app.route("/engine/stream")
def stream():
    """
    SSE endpoint – הדפדפן מתחבר פעם אחת ומקבל push כשיש עדכון.
    אין צורך בpolling – החיבור נשאר פתוח.
    """
    client_q: queue.Queue = queue.Queue(maxsize=50)
    with _sse_lock:
        _sse_clients.append(client_q)

    def generate():
        # שלח מיד snapshot ראשוני
        try:
            with get_db() as db:
                rows = db.execute("""
                    SELECT a.*, m.status, m.match_time FROM analysis a
                    JOIN matches m ON a.fixture_id=m.fixture_id
                    ORDER BY a.match_date, m.match_time
                """).fetchall()
            snapshot = [_load_analysis(r) for r in rows]
            msg = "event: snapshot\n"
            msg += "data: " + json.dumps({'fixtures': snapshot, 'count': len(snapshot)}, ensure_ascii=False) + "\n\n"
            yield msg
        except Exception as e:
            log.error(f"SSE snapshot error: {e}")

        # keepalive + push loop
        while True:
            try:
                msg = client_q.get(timeout=25)
                yield msg
            except queue.Empty:
                # keepalive כל 25 שניות כדי שהחיבור לא ייסגר
                yield ": keepalive\n\n"
            except GeneratorExit:
                break

    resp = Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        }
    )
    return resp

@app.route("/engine/fixtures")
def get_fixtures():
    with get_db() as db:
        rows = db.execute("""
            SELECT a.*, m.status, m.match_time FROM analysis a
            JOIN matches m ON a.fixture_id=m.fixture_id
            ORDER BY a.match_date, m.match_time
        """).fetchall()
    return jsonify({"fixtures":[_load_analysis(r) for r in rows],"count":len(rows)})

@app.route("/engine/fixture/<int:fid>")
def get_fixture(fid):
    with get_db() as db:
        row = db.execute("SELECT * FROM analysis WHERE fixture_id=?",(fid,)).fetchone()
    if row: return jsonify(_load_analysis(row))
    result = master.analyze(fid)
    return jsonify(result), (404 if "error" in result else 200)

@app.route("/engine/rankings")
def get_rankings():
    with get_db() as db:
        rows = db.execute("""
            SELECT r.*, p.squad_avg FROM team_rankings r
            LEFT JOIN (
                SELECT team_id, AVG(rating) squad_avg FROM players
                WHERE minutes >= 200 GROUP BY team_id
            ) p ON r.team_id=p.team_id
            ORDER BY r.rank
        """).fetchall()
    return jsonify({"rankings":[dict(r) for r in rows]})

@app.route("/engine/run", methods=["POST"])
def run_engine():
    if not auth(request): return jsonify({"error":"גישה נדחתה"}),403
    result = master.run_full_cycle()
    return jsonify({"status":"ok",**result})

@app.route("/engine/analyze/<int:fid>", methods=["POST"])
def analyze_one(fid):
    if not auth(request): return jsonify({"error":"גישה נדחתה"}),403
    return jsonify(master.analyze(fid))

@app.route("/engine/logs")
def get_logs():
    if not auth(request): return jsonify({"error":"גישה נדחתה"}),403
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM engine_log ORDER BY id DESC LIMIT 50"
        ).fetchall()
    return jsonify({"logs":[dict(r) for r in rows]})

@app.errorhandler(404)
def nf(e): return jsonify({"error":"לא נמצא"}),404
@app.errorhandler(500)
def se(e): return jsonify({"error":"שגיאת שרת"}),500

@app.after_request
def security_headers(response):
    """מוסיף security headers לכל תשובה."""
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    # לא מוסיפים HSTS כאן – זה עניין של ה-reverse proxy
    return response

# ─────────────────────────────────────────────────────────────
# SCHEDULER
# ─────────────────────────────────────────────────────────────
def _quick_update_check():
    """
    רץ כל דקה – בודק אם יש שינוי ב-API (ניצחון, תוצאה, הרכב).
    אם יש – מריץ analyze על המשחקים ומשדר SSE.
    """
    global _last_fingerprint
    if DEMO:
        return   # במצב DEMO אין API אמיתי לסקור
    try:
        upcoming = master.api.fetch_upcoming(5)   # רק 5 הבאים – זול ב-API
        if not upcoming:
            return
        master.api.store_fixtures(upcoming, {"NS","TBD","PST","LIVE","1H","2H","HT"})

        # בדיקת fingerprint לפני ניתוח כבד
        new_fp = _data_fingerprint()
        if new_fp == _last_fingerprint:
            return

        # יש שינוי – נתח רק משחקי Live/ממש קרובים
        with get_db() as db:
            live = db.execute("""
                SELECT fixture_id FROM matches
                WHERE status IN ('LIVE','1H','2H','HT','NS')
                AND match_date = ?
                ORDER BY match_time
            """, (str(datetime.date.today()),)).fetchall()

        for row in live:
            try:
                master.analyze(row["fixture_id"])
            except Exception as e:
                log.error(f"quick_update analyze error: {e}")

        new_fp2 = _data_fingerprint()
        if new_fp2 != _last_fingerprint:
            _last_fingerprint = new_fp2
            with get_db() as db:
                rows = db.execute("""
                    SELECT a.*, m.status, m.match_time FROM analysis a
                    JOIN matches m ON a.fixture_id=m.fixture_id
                    ORDER BY a.match_date, m.match_time
                """).fetchall()
            fixtures = [_load_analysis(r) for r in rows]
            _sse_broadcast("update", {"fixtures": fixtures, "count": len(fixtures)})
            log.info(f"📡 quick_update: שינוי זוהה ושודר ל-{len(_sse_clients)} clients")

    except Exception as e:
        log.error(f"quick_update_check error: {e}")


def start_scheduler():
    sched = BackgroundScheduler(timezone="Asia/Jerusalem")
    # מחזור מלא כל 6 שעות + בוקר
    sched.add_job(master.run_full_cycle, "interval", hours=6, id="cycle",
                  next_run_time=datetime.datetime.now()+datetime.timedelta(seconds=8))
    sched.add_job(master.run_full_cycle, "cron", hour=8, minute=0, id="morning")
    # בדיקת שינויים מהירה כל דקה (בימי משחק – יכול להפחית ל-30 שניות)
    sched.add_job(_quick_update_check, "interval", seconds=60, id="quick_check")
    sched.start()
    log.info("✅ Scheduler פעיל – כל 6 שעות + 08:00 + בדיקה כל דקה")
    return sched

# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    log.info(f"🚀 Engine v2 | פורט {ENGINE_PORT} | DEMO={DEMO}")
    sched = start_scheduler()
    try:
        app.run(host="0.0.0.0", port=ENGINE_PORT, debug=False)
    except (KeyboardInterrupt, SystemExit):
        sched.shutdown()