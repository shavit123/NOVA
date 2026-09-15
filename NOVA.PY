#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NOVA · POWERED BY SK · v9.0 · Creator: Shavit Klein · Render Edition"""

import os, sys, json, time, uuid, re, io, secrets, hashlib, hmac, random, threading, urllib.error, urllib.parse, urllib.request, base64
from datetime import datetime
from threading import Lock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ===== AUTO INSTALL =====
def _auto(pkg, imp=None):
    try: __import__(imp or pkg); return
    except ImportError:
        print(f"[NOVA] Installing {pkg}...")
        import subprocess
        try: subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", pkg], timeout=300)
        except Exception as e: print(f"  Failed: {e}")

_auto("groq"); _auto("psycopg2-binary", "psycopg2")

try: import psycopg2
except ImportError: psycopg2 = None
try: from groq import Groq
except ImportError: Groq = None

# ===== CONFIG =====
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip() or "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"
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
PORT = int(os.environ.get("PORT", "10000"))
HOST = os.environ.get("HOST", "0.0.0.0")

APP_NAME, VERSION, CREATOR, BRAND = "NOVA", "9.0", "Shavit Klein", "POWERED BY SK"
ADMIN_USER = "sk"
MAX_BODY = 25 * 1024 * 1024
MODEL_TIMEOUT = 90
DB_LOCK = Lock()
USAGE = {"tokens":0,"messages":0,"total_latency":0,"images":0}

GROQ_CLIENT = Groq(api_key=GROQ_API_KEY) if Groq else None

DEV_PASSWORD = "2214"
VIP_CODE = "0000"

def log(msg, level="INFO"):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [{level}] {msg}", flush=True)

def now(): return time.time()

# ===== DB =====
def db():
    if not DATABASE_URL: raise RuntimeError("DATABASE_URL not set")
    return psycopg2.connect(DATABASE_URL, sslmode="require")

def init_db():
    with DB_LOCK:
        c = db(); cur = c.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, username TEXT UNIQUE NOT NULL,
          email TEXT, password_hash TEXT, salt TEXT, is_guest INTEGER DEFAULT 0, role TEXT DEFAULT 'user',
          banned INTEGER DEFAULT 0, created_at DOUBLE PRECISION, last_login DOUBLE PRECISION,
          first_name TEXT, last_name TEXT, phone TEXT, gender TEXT, vip INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, user_id INTEGER,
          expires_at DOUBLE PRECISION, created_at DOUBLE PRECISION);
        CREATE TABLE IF NOT EXISTS chats (id TEXT PRIMARY KEY, user_id INTEGER, title TEXT,
          mode TEXT DEFAULT 'General', level INTEGER DEFAULT 0, agent_id INTEGER,
          pinned INTEGER DEFAULT 0, auto_titled INTEGER DEFAULT 0,
          created_at DOUBLE PRECISION, updated_at DOUBLE PRECISION);
        CREATE TABLE IF NOT EXISTS messages (id SERIAL PRIMARY KEY, chat_id TEXT, role TEXT,
          content TEXT, model TEXT, mode TEXT, level INTEGER DEFAULT 3,
          latency_ms INTEGER DEFAULT 0, reasoning TEXT, edited INTEGER DEFAULT 0,
          created_at DOUBLE PRECISION);
        CREATE TABLE IF NOT EXISTS memories (id SERIAL PRIMARY KEY, user_id INTEGER, text TEXT,
          category TEXT DEFAULT 'Preference', importance INTEGER DEFAULT 3,
          created_at DOUBLE PRECISION, updated_at DOUBLE PRECISION);
        CREATE TABLE IF NOT EXISTS agents (id SERIAL PRIMARY KEY, user_id INTEGER, name TEXT,
          icon TEXT, description TEXT, prompt TEXT, created_at DOUBLE PRECISION);
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS feedback (id SERIAL PRIMARY KEY, user_id INTEGER, username TEXT,
          category TEXT DEFAULT 'general', text TEXT, created_at DOUBLE PRECISION, handled INTEGER DEFAULT 0);
        """)
        c.commit(); cur.close(); c.close()
        log("DB initialized")

DEFAULT_SETTINGS = {"voice_output":"false","voice_gender":"female","memory_enabled":"true",
    "auto_model":"true","auto_mode":"true","save_history":"true","default_model":"",
    "personality":"default","image_model":"flux","profile_custom":"","avatar":"",
    "display_name":"","gender":"","onboarded":"false","level":"auto","show_reasoning":"false"}

def get_setting(k, d=None):
    c = db(); cur = c.cursor()
    cur.execute("SELECT value FROM settings WHERE key=%s", (k,))
    r = cur.fetchone(); cur.close(); c.close()
    return r[0] if r else (d if d is not None else DEFAULT_SETTINGS.get(k))

def set_setting(k, v):
    with DB_LOCK:
        c = db(); cur = c.cursor()
        cur.execute("INSERT INTO settings(key,value) VALUES(%s,%s) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value", (k, str(v)))
        c.commit(); cur.close(); c.close()

def get_user_setting(uid, key, default=None):
    c = db(); cur = c.cursor()
    cur.execute("SELECT value FROM settings WHERE key=%s", (f"u{uid}_{key}",))
    r = cur.fetchone(); cur.close(); c.close()
    return r[0] if r else (default if default is not None else DEFAULT_SETTINGS.get(key))

def set_user_setting(uid, key, val): set_setting(f"u{uid}_{key}", val)

# ===== AUTH =====
def _hash_pwd(p, s=None):
    if s is None: s = secrets.token_hex(16)
    return hashlib.pbkdf2_hmac("sha256", p.encode(), s.encode(), 200_000).hex(), s

def _verify_pwd(p, stored, salt):
    n, _ = _hash_pwd(p, salt); return hmac.compare_digest(n, stored)

def _hash_tok(t): return hashlib.sha256(t.encode()).hexdigest()

def create_user(username, email, password, first_name="", last_name="", phone="", gender=""):
    username = str(username).strip(); first_name = str(first_name).strip()
    last_name = str(last_name).strip(); email = str(email).strip()
    phone = str(phone).strip(); gender = str(gender).strip()
    if len(username) < 3: return {"ok": False, "error": "שם משתמש חייב להיות לפחות 3 תווים"}
    if len(first_name) < 2: return {"ok": False, "error": "שם פרטי חייב להיות לפחות 2 תווים"}
    if len(last_name) < 2: return {"ok": False, "error": "שם משפחה חייב להיות לפחות 2 תווים"}
    if not email or "@" not in email: return {"ok": False, "error": "אימייל לא תקין"}
    if len(phone) < 9: return {"ok": False, "error": "טלפון לא תקין"}
    if gender not in ("male","female","other"): return {"ok": False, "error": "בחר מין"}
    if password and len(password) < 6: return {"ok": False, "error": "סיסמה חייבת להיות לפחות 6 תווים"}
    ph, salt = _hash_pwd(password or secrets.token_urlsafe(16)); ts = now(); role = "user"
    try:
        c = db(); cur = c.cursor()
        cur.execute("SELECT COUNT(*) FROM users WHERE is_guest=0")
        cnt = cur.fetchone()[0]; cur.close(); c.close()
        if cnt == 0 or username.lower() == ADMIN_USER: role = "admin"
    except Exception: pass
    try:
        with DB_LOCK:
            c = db(); cur = c.cursor()
            cur.execute("INSERT INTO users(username,email,password_hash,salt,is_guest,role,created_at,first_name,last_name,phone,gender) VALUES(%s,%s,%s,%s,0,%s,%s,%s,%s,%s,%s) RETURNING id",
                        (username, email, ph, salt, role, ts, first_name, last_name, phone, gender))
            uid = cur.fetchone()[0]; c.commit(); cur.close(); c.close()
        set_user_setting(uid, "onboarded", "true")
        set_user_setting(uid, "gender", gender)
        set_user_setting(uid, "display_name", f"{first_name} {last_name}".strip())
        return {"ok": True, "user_id": uid, "role": role, "session": create_session(uid)}
    except Exception as e:
        if "unique" in str(e).lower(): return {"ok": False, "error": "שם המשתמש תפוס"}
        return {"ok": False, "error": str(e)}

def create_guest():
    gname = f"guest_{secrets.token_hex(3)}"
    with DB_LOCK:
        c = db(); cur = c.cursor()
        cur.execute("INSERT INTO users(username,is_guest,role,created_at) VALUES(%s,1,'guest',%s) RETURNING id", (gname, now()))
        uid = cur.fetchone()[0]; c.commit(); cur.close(); c.close()
    return {"ok": True, "user_id": uid, "role": "guest", "is_guest": True, "session": create_session(uid, days=1)}

def create_session(uid, days=30):
    t = secrets.token_urlsafe(32); th = _hash_tok(t); ts = now()
    with DB_LOCK:
        c = db(); cur = c.cursor()
        cur.execute("INSERT INTO sessions(token_hash,user_id,expires_at,created_at) VALUES(%s,%s,%s,%s)",
                    (th, uid, ts + days*86400, ts))
        c.commit(); cur.close(); c.close()
    return {"token": t, "expires_at": ts + days*86400}

def verify_session(tok):
    if not tok: return None
    c = db(); cur = c.cursor()
    cur.execute("SELECT s.user_id, s.expires_at, u.username, u.is_guest, u.role, u.vip, u.banned FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=%s", (_hash_tok(tok),))
    r = cur.fetchone(); cur.close(); c.close()
    if not r or r[1] < now() or r[6]: return None
    return {"user_id": r[0], "username": r[2], "is_guest": bool(r[3]), "role": r[4] or "user", "vip": bool(r[5])}

def login_user(un, pw):
    c = db(); cur = c.cursor()
    cur.execute("SELECT id,password_hash,salt,role FROM users WHERE username=%s AND is_guest=0", (un,))
    r = cur.fetchone(); cur.close(); c.close()
    if not r: return {"ok": False, "error": "משתמש לא נמצא"}
    if not _verify_pwd(pw, r[1] or "", r[2] or ""): return {"ok": False, "error": "סיסמה שגויה"}
    with DB_LOCK:
        c = db(); cur = c.cursor()
        cur.execute("UPDATE users SET last_login=%s WHERE id=%s", (now(), r[0]))
        c.commit(); cur.close(); c.close()
    return {"ok": True, "user_id": r[0], "role": r[3] or "user", "session": create_session(r[0])}

def logout_user(tok):
    if not tok: return
    with DB_LOCK:
        c = db(); cur = c.cursor()
        cur.execute("DELETE FROM sessions WHERE token_hash=%s", (_hash_tok(tok),))
        c.commit(); cur.close(); c.close()

def upgrade_vip(uid):
    with DB_LOCK:
        c = db(); cur = c.cursor()
        cur.execute("UPDATE users SET vip=1 WHERE id=%s", (uid,))
        c.commit(); cur.close(); c.close()

# ===== MODELS =====
FALLBACK_MODELS = ["openai/gpt-oss-120b","openai/gpt-oss-20b","qwen/qwen3.6-27b","groq/compound-mini"]
AVAILABLE_MODELS = [{"id":m,"name":m,"context":131072,"max_out":8192,"has_tools":True,"has_reasoning":True,"has_vision":False} for m in FALLBACK_MODELS]

LEVEL_NAMES = {1:"מתחיל",2:"בסיסי",3:"מקצועי",4:"מומחה",5:"ארכיטקט"}
LEVEL_PROMPTS = {
    1: "User is BEGINNER. Explain from scratch with analogies. No jargon.",
    2: "User has BASIC understanding. Clear explanations with examples.",
    3: "User is PROFESSIONAL. Technical answers. No basics.",
    4: "User is EXPERT. Skip fundamentals. Jargon freely.",
    5: "ARCHITECT-level. Dense, precise, trade-offs, edge cases."
}

def detect_level(text, current=0):
    low = text.lower().strip(); wc = len(low.split()); score = 0
    if wc <= 3 and any(k in low for k in ["מה זה","who is","what is"]): return 1
    if any(k in low for k in ["אני לא מבין","תסביר","explain like","eli5"]): return 1
    adv = ["ארכיטקטורה","trade-off","concurrency","asynchronous","optimization","refactor","complexity","microservice","monad","closure","memoization","big-o"]
    mid = ["function","class","api","database","server","python","javascript","algorithm","loop","array"]
    if any(k in low for k in adv): score += 4
    if any(k in low for k in mid): score += 2
    if wc > 30: score += 1
    if "```" in text: score += 2
    if score >= 6: return 5
    if score >= 4: return 4
    if score >= 2: return 3
    if score >= 1: return 2
    return current or 3

CODE_KW = ["python","javascript","code","bug","debug","error","קוד","באג","דיבאג","פונקציה","שגיאה"]
MATH_KW = ["calculate","solve","equation","חשב","פתור","משוואה"]
RESEARCH_KW = ["latest","current","today","now","recent","עדכני","היום","כרגע"]
WEATHER_KW = ["weather","temperature","מזג","אוויר","טמפרטורה"]
WIKI_KW = ["who is","what is","מיהו","מי זה","מה זה"]

def detect_intent(text, files=None):
    if files:
        for f in files:
            if str(f.get("mime","")).startswith("image/"): return "Vision", False, False, False, True
    low = text.lower(); mode = "General"; web = False; weather = False; wiki = False
    if any(k in low for k in CODE_KW): mode = "Code"
    elif any(k in low for k in MATH_KW): mode = "Study"
    elif any(k in low for k in RESEARCH_KW): mode = "Research"; web = True
    elif any(k in low for k in WIKI_KW): wiki = True
    if any(k in low for k in WEATHER_KW): weather = True
    return mode, web, weather, wiki, False

def pick_model(mode, has_vision=False, manual=None):
    if manual:
        for m in AVAILABLE_MODELS:
            if m["id"] == manual: return m
    if mode in ("Code","Study"):
        for m in AVAILABLE_MODELS:
            if m.get("has_tools"): return m
    return AVAILABLE_MODELS[0]

CITY_COORDS = {"jerusalem":(31.7683,35.2137),"ירושלים":(31.7683,35.2137),"tel aviv":(32.0853,34.7818),"תל אביב":(32.0853,34.7818)}

def _getjson(url, t=8):
    try:
        req = urllib.request.Request(url, headers={"User-Agent":"NOVA/9.0"})
        with urllib.request.urlopen(req, timeout=t) as r: return json.loads(r.read().decode("utf-8","replace"))
    except Exception: return None

def get_weather(city="Jerusalem"):
    c = CITY_COORDS.get(city.lower())
    if not c: return None
    lat, lon = c
    d = _getjson(f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m&timezone=auto")
    if not d or "current" not in d: return None
    cur = d["current"]
    desc = {0:"Clear",1:"Mainly clear",2:"Partly cloudy",3:"Overcast",61:"Rain",95:"Thunderstorm"}.get(cur.get("weather_code",0), "Unknown")
    return {"city":city, "temp_c":cur.get("temperature_2m"), "humidity":cur.get("relative_humidity_2m"), "wind_kmh":cur.get("wind_speed_10m"), "desc":desc}

def get_wiki(topic):
    for lang in ("he","en"):
        d = _getjson(f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(topic)}")
        if d and d.get("extract"): return {"title":d.get("title"), "extract":d["extract"][:800]}
    return None

def build_live(text, mode, web, weather, wiki):
    parts = []; dt = datetime.now()
    days = ["שני","שלישי","רביעי","חמישי","שישי","שבת","ראשון"]
    months = ["ינואר","פברואר","מרץ","אפריל","מאי","יוני","יולי","אוגוסט","ספטמבר","אוקטובר","נובמבר","דצמבר"]
    parts.append(f"CURRENT: {days[dt.weekday()]}, {dt.day} {months[dt.month-1]} {dt.year} · {dt.strftime('%H:%M')}")
    if weather:
        low = text.lower(); city = "Jerusalem"
        for name in CITY_COORDS:
            if name in low: city = name.title(); break
        w = get_weather(city)
        if w: parts.append(f"WEATHER {w['city']}: {w['temp_c']}°C, {w['desc']}")
    if wiki:
        topic = text
        for p in ["who is","what is","מי זה","מה זה"]:
            if topic.lower().startswith(p): topic = topic[len(p):].strip(); break
        topic = topic.strip(" ?.!,:").strip()
        if topic and len(topic) < 100:
            w = get_wiki(topic)
            if w: parts.append(f"WIKI \"{w['title']}\": {w['extract']}")
    return "\n\n".join(parts)

PERSONALITIES = {"default":"","friend":"Casual, warm.","family":"Warm, caring.","professional":"Formal.","teacher":"Patient teacher.","coach":"Motivating.","peer":"Intelligent peer."}

def call_groq(messages, model, temperature=0.7, max_tokens=8192, system_prompt="", allow_fallback=True):
    if not GROQ_CLIENT: return {"ok": False, "error": "No Groq client"}
    tried = [model]
    if allow_fallback:
        for m in FALLBACK_MODELS:
            if m != model: tried.append(m)
    for mid in tried:
        api_msgs = []
        if system_prompt: api_msgs.append({"role":"system","content":system_prompt})
        for m in messages: api_msgs.append({"role":m.get("role","user"),"content":str(m.get("content",""))})
        started = time.perf_counter()
        try:
            r = GROQ_CLIENT.chat.completions.create(model=mid, messages=api_msgs, temperature=temperature, max_tokens=max_tokens, timeout=MODEL_TIMEOUT)
            lat = int((time.perf_counter() - started) * 1000)
            reply = r.choices[0].message.content.strip()
            if not reply: continue
            usage = {"prompt_tokens": r.usage.prompt_tokens if r.usage else 0, "completion_tokens": r.usage.completion_tokens if r.usage else 0}
            return {"ok": True, "reply": reply, "usage": usage, "model": mid, "latency": lat}
        except Exception as e:
            log(f"Groq {mid}: {e}", "WARN"); continue
    return {"ok": False, "error": "All models failed"}

# ===== CHAT =====
def create_chat(uid, title="שיחה חדשה", mode="General", agent_id=None):
    cid = "chat_" + uuid.uuid4().hex; ts = now()
    with DB_LOCK:
        c = db(); cur = c.cursor()
        cur.execute("INSERT INTO chats(id,user_id,title,mode,agent_id,created_at,updated_at,auto_titled) VALUES(%s,%s,%s,%s,%s,%s,%s,0)",
                    (cid, uid, title, mode, agent_id, ts, ts))
        c.commit(); cur.close(); c.close()
    return cid

def get_chats(uid, search=""):
    c = db(); cur = c.cursor()
    q = "SELECT id,title,mode,level,pinned,created_at,updated_at FROM chats WHERE user_id=%s"; p = [uid]
    if search:
        q += " AND title LIKE %s"; p.append(f"%{search}%")
    q += " ORDER BY pinned DESC, updated_at DESC LIMIT 200"
    cur.execute(q, p); rows = cur.fetchall(); cur.close(); c.close()
    return [{"id":r[0],"title":r[1],"mode":r[2],"level":r[3],"pinned":r[4],"created_at":r[5],"updated_at":r[6]} for r in rows]

def get_chat(cid, uid):
    c = db(); cur = c.cursor()
    cur.execute("SELECT id,title,mode,level,agent_id FROM chats WHERE id=%s AND user_id=%s", (cid, uid))
    ch = cur.fetchone()
    if not ch: cur.close(); c.close(); return None
    chat = {"id":ch[0],"title":ch[1],"mode":ch[2],"level":ch[3],"agent_id":ch[4]}
    cur.execute("SELECT id,role,content,model,mode,level,reasoning,created_at FROM messages WHERE chat_id=%s ORDER BY id ASC", (cid,))
    msgs = cur.fetchall(); cur.close(); c.close()
    return {"chat": chat, "messages": [{"id":m[0],"role":m[1],"content":m[2],"model":m[3],"mode":m[4],"level":m[5],"reasoning":m[6],"created_at":m[7]} for m in msgs]}

def get_chat_admin(cid):
    c = db(); cur = c.cursor()
    cur.execute("SELECT id,title,user_id,mode FROM chats WHERE id=%s", (cid,))
    ch = cur.fetchone()
    if not ch: cur.close(); c.close(); return None
    chat = {"id":ch[0],"title":ch[1],"user_id":ch[2],"mode":ch[3]}
    cur.execute("SELECT id,role,content,model,created_at FROM messages WHERE chat_id=%s ORDER BY id ASC LIMIT 1000", (cid,))
    msgs = cur.fetchall(); cur.close(); c.close()
    return {"chat": chat, "messages": [{"id":m[0],"role":m[1],"content":m[2],"model":m[3],"created_at":m[4]} for m in msgs]}

def rename_chat(cid, uid, title):
    title = str(title).strip()[:120]
    if not title: return
    with DB_LOCK:
        c = db(); cur = c.cursor()
        cur.execute("UPDATE chats SET title=%s,updated_at=%s WHERE id=%s AND user_id=%s", (title, now(), cid, uid))
        c.commit(); cur.close(); c.close()

def rename_chat_force(cid, title):
    title = str(title).strip()[:120]
    if not title: return
    with DB_LOCK:
        c = db(); cur = c.cursor()
        cur.execute("UPDATE chats SET title=%s,updated_at=%s,auto_titled=1 WHERE id=%s", (title, now(), cid))
        c.commit(); cur.close(); c.close()

def update_chat_mode(cid, mode):
    with DB_LOCK:
        c = db(); cur = c.cursor()
        cur.execute("UPDATE chats SET mode=%s,updated_at=%s WHERE id=%s", (mode, now(), cid))
        c.commit(); cur.close(); c.close()

def delete_chat(cid, uid):
    with DB_LOCK:
        c = db(); cur = c.cursor()
        cur.execute("DELETE FROM chats WHERE id=%s AND user_id=%s", (cid, uid))
        c.commit(); cur.close(); c.close()

def save_message(cid, role, content, model=None, mode=None, latency_ms=0, level=3, reasoning=None):
    if get_setting("save_history","true") != "true": return
    ts = now()
    with DB_LOCK:
        c = db(); cur = c.cursor()
        cur.execute("INSERT INTO messages(chat_id,role,content,model,mode,level,latency_ms,reasoning,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (cid, role, content, model, mode, level, latency_ms, reasoning, ts))
        cur.execute("UPDATE chats SET updated_at=%s WHERE id=%s", (ts, cid))
        c.commit(); cur.close(); c.close()

def get_history(cid, limit=30):
    c = db(); cur = c.cursor()
    cur.execute("SELECT role,content FROM messages WHERE chat_id=%s ORDER BY id DESC LIMIT %s", (cid, limit))
    rows = cur.fetchall(); cur.close(); c.close()
    return [{"role":r[0],"content":r[1]} for r in reversed(rows)]

def get_memories(uid):
    c = db(); cur = c.cursor()
    cur.execute("SELECT id,text,category,importance FROM memories WHERE user_id=%s ORDER BY importance DESC LIMIT 100", (uid,))
    rows = cur.fetchall(); cur.close(); c.close()
    return [{"id":r[0],"text":r[1],"category":r[2],"importance":r[3]} for r in rows]

def add_memory(uid, txt, cat="Preference", imp=3):
    txt = str(txt).strip()[:500]
    if not txt: return False
    ts = now()
    with DB_LOCK:
        c = db(); cur = c.cursor()
        cur.execute("INSERT INTO memories(user_id,text,category,importance,created_at,updated_at) VALUES(%s,%s,%s,%s,%s,%s)",
                    (uid, txt, cat, imp, ts, ts))
        c.commit(); cur.close(); c.close()
    return True

def delete_memory(uid, mid):
    with DB_LOCK:
        c = db(); cur = c.cursor()
        cur.execute("DELETE FROM memories WHERE id=%s AND user_id=%s", (mid, uid))
        c.commit(); cur.close(); c.close()

def memory_ctx(uid):
    if get_setting("memory_enabled","true") != "true": return ""
    ms = get_memories(uid)
    if not ms: return ""
    return "\n".join(f"- [{m['category']}] {m['text']}" for m in ms[:20])

def auto_memory(uid, txt):
    low = txt.lower()
    trg = {"Identity":["my name is","i am","קוראים לי","שמי"],"Preference":["i prefer","i like","אני מעדיף","אני אוהב"],"Project":["i'm working on","אני עובד על"],"Remember":["remember that","from now on","תזכור","מעכשיו"]}
    for cat, kws in trg.items():
        if any(k in low for k in kws) and 5 <= len(txt.strip()) <= 500:
            add_memory(uid, txt.strip(), cat, 4); return

def get_agents(uid):
    c = db(); cur = c.cursor()
    cur.execute("SELECT id,name,icon,description,prompt FROM agents WHERE user_id=%s ORDER BY id ASC", (uid,))
    rows = cur.fetchall(); cur.close(); c.close()
    return [{"id":r[0],"name":r[1],"icon":r[2],"description":r[3],"prompt":r[4]} for r in rows]

def add_agent(uid, name, icon, desc, prompt):
    with DB_LOCK:
        c = db(); cur = c.cursor()
        cur.execute("INSERT INTO agents(user_id,name,icon,description,prompt,created_at) VALUES(%s,%s,%s,%s,%s,%s)",
                    (uid, name[:50], icon[:8], desc[:200], prompt[:2000], now()))
        c.commit(); cur.close(); c.close()

def delete_agent(uid, aid):
    with DB_LOCK:
        c = db(); cur = c.cursor()
        cur.execute("DELETE FROM agents WHERE id=%s AND user_id=%s", (aid, uid))
        c.commit(); cur.close(); c.close()

def get_user_analysis(uid):
    try:
        c = db(); cur = c.cursor()
        cur.execute("SELECT summary,emotions,topics,style FROM user_analysis WHERE user_id=%s", (uid,))
        r = cur.fetchone(); cur.close(); c.close()
        return {"summary":r[0],"emotions":r[1],"topics":r[2],"style":r[3]} if r else None
    except Exception: return None

def save_feedback(uid, username, category, text):
    with DB_LOCK:
        c = db(); cur = c.cursor()
        cur.execute("INSERT INTO feedback(user_id,username,category,text,created_at) VALUES(%s,%s,%s,%s,%s)",
                    (uid, username, category, text, now()))
        c.commit(); cur.close(); c.close()

def get_user_feedback(uid):
    c = db(); cur = c.cursor()
    cur.execute("SELECT id,category,text,created_at,handled FROM feedback WHERE user_id=%s ORDER BY id DESC LIMIT 50", (uid,))
    rows = cur.fetchall(); cur.close(); c.close()
    return [{"id":r[0],"category":r[1],"text":r[2],"created_at":r[3],"handled":r[4]} for r in rows]

def get_all_feedback():
    c = db(); cur = c.cursor()
    cur.execute("SELECT id,user_id,username,category,text,created_at,handled FROM feedback ORDER BY id DESC LIMIT 500")
    rows = cur.fetchall(); cur.close(); c.close()
    return [{"id":r[0],"user_id":r[1],"username":r[2],"category":r[3],"text":r[4],"created_at":r[5],"handled":r[6]} for r in rows]

def get_all_users():
    c = db(); cur = c.cursor()
    cur.execute("SELECT id,username,first_name,last_name,email,phone,gender,role,vip,banned,is_guest,created_at,last_login FROM users ORDER BY id DESC LIMIT 500")
    rows = cur.fetchall(); cur.close(); c.close()
    return [{"id":r[0],"username":r[1],"first_name":r[2],"last_name":r[3],"email":r[4],"phone":r[5],"gender":r[6],"role":r[7],"vip":r[8],"banned":r[9],"is_guest":r[10],"created_at":r[11],"last_login":r[12]} for r in rows]

def get_stats():
    c = db(); cur = c.cursor()
    cur.execute("SELECT COUNT(*) FROM users"); tu = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM chats"); tc = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM messages"); tm = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM users WHERE created_at > %s", (now()-86400,)); n24 = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM users WHERE vip=1"); vips = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM users WHERE banned=1"); banned = cur.fetchone()[0]
    cur.close(); c.close()
    return {"total_users":tu,"total_chats":tc,"total_messages":tm,"new_users_24h":n24,"vip_users":vips,"banned_users":banned}

def set_user_ban(uid, ban):
    with DB_LOCK:
        c = db(); cur = c.cursor()
        cur.execute("UPDATE users SET banned=%s WHERE id=%s", (1 if ban else 0, uid))
        c.commit(); cur.close(); c.close()

def set_user_vip(uid, vip):
    with DB_LOCK:
        c = db(); cur = c.cursor()
        cur.execute("UPDATE users SET vip=%s WHERE id=%s", (1 if vip else 0, uid))
        c.commit(); cur.close(); c.close()

def delete_user(uid):
    with DB_LOCK:
        c = db(); cur = c.cursor()
        cur.execute("DELETE FROM users WHERE id=%s", (uid,))
        c.commit(); cur.close(); c.close()

def get_chats_of_user(uid):
    c = db(); cur = c.cursor()
    cur.execute("SELECT id,title,mode,created_at,updated_at FROM chats WHERE user_id=%s ORDER BY updated_at DESC LIMIT 200", (uid,))
    rows = cur.fetchall(); cur.close(); c.close()
    return [{"id":r[0],"title":r[1],"mode":r[2],"created_at":r[3],"updated_at":r[4]} for r in rows]

# ===== SYSTEM =====
MODE_PROMPTS = {
    "General":"Answer directly in user's language.",
    "Code":"Senior software engineer. Complete working code.",
    "Study":"Patient teacher. Step by step.",
    "Research":"Research assistant. Structured factual.",
    "Vision":"Analyze images. Describe what you see.",
    "Creative":"Creative collaborator.",
    "Control":"Computer control. Hebrew + <control>{\"action\":\"click\",\"x\":500,\"y\":300}</control>."
}

def build_system(mode, personality="default", live="", profile="", level=3, agent_name=""):
    base = "You are NOVA. Creator: Shavit Klein.\n\n"
    if agent_name: base += f"Acting as agent '{agent_name}'.\n\n"
    base += MODE_PROMPTS.get(mode, MODE_PROMPTS["General"])
    base += "\n\nWhen asked to CREATE an image, respond with: <image>english prompt</image>\n"
    base += f"\nPROFESSIONAL LEVEL {level}/5 ({LEVEL_NAMES.get(level,'')}): {LEVEL_PROMPTS.get(level,LEVEL_PROMPTS[3])}\n"
    if personality != "default": base += "\nPERSONALITY: " + PERSONALITIES.get(personality,"")
    if live: base += "\n\n=== LIVE DATA ===\n" + live
    if profile: base += "\n\nUSER PREFERENCES:\n" + profile
    return base

def parse_images(t):
    out = []
    for m in re.finditer(r'<image(?:\s+ratio="([^"]+)")?\s*>\s*([\s\S]*?)\s*</image>', t):
        ratio = m.group(1) or "1:1"
        w, h = 1024, 1024
        if ratio == "16:9": w, h = 1344, 768
        elif ratio == "9:16": w, h = 768, 1344
        prompt = m.group(2).strip()
        if prompt:
            seed = random.randint(1, 999_999_999)
            url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(prompt)}?width={w}&height={h}&nologo=true&seed={seed}&enhance=true"
            out.append({"prompt":prompt, "url":url, "seed":seed, "ratio":ratio})
    return out

def clean_images(t):
    return re.sub(r'<image(?:\s+ratio="[^"]+")?\s*>\s*[\s\S]*?\s*</image>', "", t).strip()

def clean_control(t):
    return re.sub(r'<control>\s*[\s\S]*?\s*</control>', "", t).strip()

def handle_slash(text, user, cid):
    if not text.startswith("/"): return None
    parts = text.split(maxsplit=1); cmd = parts[0][1:].lower(); arg = parts[1].strip() if len(parts) > 1 else ""
    if cmd == "help":
        return {"handled": True, "reply": "**פקודות**\n/help · /clear · /models\n/weather [city] · /wiki <topic>\n/level 1-5 · /personality <name>\n/memory · /memory add <text>"}
    if cmd == "clear":
        with DB_LOCK:
            c = db(); cur = c.cursor()
            cur.execute("DELETE FROM messages WHERE chat_id=%s", (cid,))
            c.commit(); cur.close(); c.close()
        return {"handled": True, "reply": "השיחה נוקתה"}
    if cmd == "models":
        return {"handled": True, "reply": "**מודלים**\n" + "\n".join(f"- `{m['id']}`" for m in AVAILABLE_MODELS)}
    if cmd == "weather":
        w = get_weather(arg or "Jerusalem")
        return {"handled": True, "reply": f"**{w['city']}**: {w['temp_c']}°C, {w['desc']}" if w else "לא הצלחתי"}
    if cmd == "wiki" and arg:
        w = get_wiki(arg)
        return {"handled": True, "reply": f"**{w['title']}**\n\n{w['extract']}" if w else "לא נמצא"}
    if cmd == "level":
        if arg == "auto" or not arg:
            set_user_setting(user["user_id"], "level", "auto"); return {"handled": True, "reply": "רמה: אוטומטי"}
        try:
            lv = int(arg)
            if 1 <= lv <= 5:
                set_user_setting(user["user_id"], "level", str(lv))
                return {"handled": True, "reply": f"רמה: {LEVEL_NAMES[lv]}"}
        except: pass
        return {"handled": True, "reply": "שימוש: /level 1-5"}
    if cmd == "personality":
        if not arg: return {"handled": True, "reply": "אישויות: " + ", ".join(PERSONALITIES.keys())}
        if arg not in PERSONALITIES: return {"handled": True, "reply": "לא קיימת"}
        set_user_setting(user["user_id"], "personality", arg)
        return {"handled": True, "reply": f"אישיות: {arg}"}
    if cmd == "memory":
        if arg.startswith("add "):
            add_memory(user["user_id"], arg[4:].strip(), "Manual", 4); return {"handled": True, "reply": "נשמר"}
        ms = get_memories(user["user_id"])
        if not ms: return {"handled": True, "reply": "אין זיכרונות"}
        return {"handled": True, "reply": "**זיכרון:**\n" + "\n".join(f"- [{m['category']}] {m['text'][:100]}" for m in ms[:20])}
    return {"handled": True, "reply": f"פקודה לא מוכרת: /{cmd}"}

# ===== HTML =====
HTML = r'''<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#212121">
<meta name="apple-mobile-web-app-capable" content="yes">
<title>NOVA</title>
<style>
*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
:root{--bg:#212121;--sb:#171717;--panel:#2f2f2f;--hover:#2a2a2a;--hover2:#303030;--border:#303030;--border2:#424242;--text:#ececec;--text2:#c8c8c8;--muted:#a0a0a0;--muted2:#6b6b6b;--danger:#f47272;--ok:#4ade80;--accent:#7dd3fc;--r-sm:6px;--r-md:10px;--r-lg:14px;--r-xl:20px;--r-full:9999px;--t:150ms cubic-bezier(.4,0,.2,1)}
html.light{--bg:#fff;--sb:#f9f9f9;--panel:#f4f4f4;--hover:#ededed;--hover2:#e5e5e5;--border:#e5e5e5;--border2:#d4d4d4;--text:#0d0d0d;--text2:#3a3a3a;--muted:#6b6b6b;--muted2:#9b9b9b}
html,body{height:100%;overflow:hidden;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;font-size:15px;line-height:1.55;overscroll-behavior:none}
button,input,textarea,select{font:inherit;color:inherit}
button{border:0;background:none;cursor:pointer;touch-action:manipulation}
.hidden{display:none!important}
.auth{position:fixed;inset:0;background:var(--bg);display:flex;align-items:center;justify-content:center;padding:20px;z-index:100;overflow-y:auto}
.auth-box{width:min(420px,100%);text-align:center}
.auth-logo{width:52px;height:52px;border-radius:var(--r-md);margin:0 auto 20px;background:var(--panel);display:grid;place-items:center;font-weight:700;font-size:20px;overflow:hidden;border:1px solid var(--border);color:var(--text)}
.auth-title{font-size:24px;font-weight:600;margin-bottom:4px}
.auth-sub{color:var(--muted);font-size:12px;margin-bottom:28px;letter-spacing:1.5px}
.auth-tabs{display:flex;margin-bottom:20px;border-bottom:1px solid var(--border)}
.auth-tab{flex:1;padding:10px;color:var(--muted);font-size:14px;font-weight:500;background:none;border-bottom:2px solid transparent;cursor:pointer;font-family:inherit}
.auth-tab.active{color:var(--text);border-bottom-color:var(--text)}
.auth-form{display:flex;flex-direction:column;gap:10px;text-align:right}
.auth-lbl{font-size:12px;color:var(--muted);margin-bottom:4px}
.auth-inp{width:100%;padding:11px 12px;border-radius:var(--r-md);background:var(--panel);border:1px solid var(--border);color:var(--text);font-size:14.5px;outline:0;font-family:inherit}
.auth-btn{width:100%;padding:12px;border-radius:var(--r-md);background:var(--text);color:var(--bg);font-size:14px;font-weight:600;cursor:pointer;font-family:inherit;border:0;margin-top:6px}
.auth-btn.sec{background:var(--panel);color:var(--text);border:1px solid var(--border)}
.auth-div{display:flex;align-items:center;gap:12px;margin:18px 0;color:var(--muted2);font-size:12px}
.auth-div:before,.auth-div:after{content:"";flex:1;height:1px;background:var(--border)}
.auth-msg{padding:10px 12px;border-radius:var(--r-md);font-size:13px;margin-bottom:12px;text-align:right}
.auth-msg.err{background:rgba(244,114,114,.12);color:#f4a3a3;border:1px solid rgba(244,114,114,.25)}
.auth-foot{margin-top:22px;font-size:11.5px;color:var(--muted2)}
.onb-gender{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-bottom:18px}
.gbtn{padding:14px 8px;border-radius:var(--r-md);border:1px solid var(--border);background:var(--panel);color:var(--text2);font-size:13px;font-weight:500;display:flex;flex-direction:column;align-items:center;gap:6px;cursor:pointer;font-family:inherit}
.gbtn.on{background:var(--text);color:var(--bg);border-color:var(--text)}
.gbtn .gi{font-size:22px}
.app{display:flex;height:100vh;height:100dvh}
.sb{width:270px;background:var(--sb);display:flex;flex-direction:column;flex-shrink:0;transition:transform .22s;z-index:30}
.sb-top{padding:8px}
.sb-row{display:flex;align-items:center;gap:10px;padding:8px 10px;border-radius:var(--r-md)}
.sb-logo{width:30px;height:30px;border-radius:var(--r-md);background:var(--panel);display:grid;place-items:center;font-weight:700;font-size:13px;color:var(--text);flex-shrink:0}
.sb-info{flex:1;min-width:0;display:flex;flex-direction:column;text-align:right}
.sb-name{font-size:13.5px;font-weight:600;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
.sb-brand{font-size:10px;color:var(--muted);letter-spacing:.6px;margin-top:1px}
.sb-new{display:flex;align-items:center;justify-content:center;gap:10px;padding:9px 12px;border-radius:var(--r-md);font-size:13.5px;font-weight:500;cursor:pointer;border:1px solid var(--border);background:var(--panel);font-family:inherit;width:100%;color:var(--text);margin-top:6px}
.sb-new:hover{background:var(--hover)}
.sb-label{padding:14px 14px 4px;font-size:10.5px;font-weight:600;color:var(--muted2);letter-spacing:.8px}
.sb-list{flex:1;overflow-y:auto;padding:0 6px 8px}
.chat-item{width:100%;display:flex;align-items:center;gap:6px;padding:8px 10px;border-radius:var(--r-md);color:var(--text2);text-align:right;cursor:pointer;font-size:13.5px;border:0;background:none;font-family:inherit;margin-bottom:1px}
.chat-item:hover{background:var(--hover);color:var(--text)}
.chat-item.active{background:var(--hover2);color:var(--text)}
.chat-item .t{flex:1;min-width:0;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
.sb-bottom{padding:6px;border-top:1px solid var(--border);overflow-y:auto;max-height:65vh}
.sb-b{display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:var(--r-md);color:var(--text2);font-size:13.5px;text-align:right;border:0;background:none;font-family:inherit;cursor:pointer;width:100%}
.sb-b:hover{background:var(--hover);color:var(--text)}
.sb-sign{padding:12px 12px 6px;font-size:10px;color:var(--muted2);text-align:center;line-height:1.6;border-top:1px solid var(--border);margin-top:6px}
.sb-sign b{color:var(--text);font-weight:600;letter-spacing:1px}
.main{flex:1;min-width:0;display:flex;flex-direction:column;position:relative}
.top{height:52px;display:flex;align-items:center;gap:8px;padding:0 12px}
.menu{width:36px;height:36px;border-radius:var(--r-md);display:none;place-items:center;color:var(--text);font-size:20px}
.menu:hover{background:var(--hover)}
.title{font-size:14px;font-weight:500;flex:1;min-width:0;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;text-align:right}
.right{margin-right:auto;display:flex;align-items:center;gap:4px}
.level-badge{font-size:10.5px;font-weight:600;padding:3px 8px;border-radius:var(--r-full);background:var(--panel);color:var(--text2);border:1px solid var(--border)}
.vip-badge{font-size:10.5px;font-weight:700;padding:3px 8px;border-radius:var(--r-full);background:linear-gradient(135deg,#f5c842,#d4a017);color:#1a1a1a}
.ibtn{width:36px;height:36px;border-radius:var(--r-md);display:grid;place-items:center;color:var(--muted);border:0;font-size:18px}
.ibtn:hover{background:var(--hover);color:var(--text)}
.avatar{position:relative;width:32px;height:32px;border-radius:var(--r-full);overflow:hidden;background:var(--panel);display:grid;place-items:center;cursor:pointer;margin-right:4px}
.avatar .ini{font-weight:600;font-size:12px;color:var(--text)}
.chat{flex:1;overflow-y:auto;overflow-x:hidden}
.inner{width:100%;max-width:760px;margin:0 auto;padding:32px 24px 40px;display:flex;flex-direction:column;gap:24px}
.welcome{text-align:center;padding:60px 20px;max-width:600px;margin:auto}
.wlogo{width:56px;height:56px;border-radius:var(--r-full);margin:0 auto 20px;background:var(--panel);display:grid;place-items:center;font-weight:600;font-size:20px;border:1px solid var(--border);color:var(--text)}
.welcome h1{font-size:26px;font-weight:500;margin-bottom:8px}
.welcome p{color:var(--muted);font-size:14px;line-height:1.6}
.cards{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;max-width:520px;margin:28px auto 0}
.card{padding:14px 16px;border:1px solid var(--border);border-radius:var(--r-md);background:transparent;text-align:right;color:var(--text2);font-size:13px;cursor:pointer;font-family:inherit;line-height:1.5}
.card:hover{background:var(--hover);border-color:var(--border2);color:var(--text)}
.card .ct{font-weight:500;color:var(--text);margin-bottom:2px;font-size:13.5px}
.card .cd{color:var(--muted);font-size:12px}
.msg{display:flex;gap:14px;width:100%;position:relative}
.msg.user{justify-content:flex-start;flex-direction:row-reverse}
.msg .av{width:28px;height:28px;border-radius:var(--r-full);flex-shrink:0;display:grid;place-items:center;font-size:10px;font-weight:600;background:var(--panel);color:var(--text);border:1px solid var(--border);margin-top:2px}
.msg.user .av{display:none}
.msg .bd{min-width:0;flex:1}
.msg.user .bd{display:flex;justify-content:flex-start;flex:0 1 auto;max-width:80%}
.msg.user .bub{background:var(--panel);padding:10px 16px;border-radius:var(--r-xl);color:var(--text);font-size:15px;line-height:1.6}
.msg.assistant .bub{color:var(--text2);font-size:15px;line-height:1.7}
.tag{display:inline-block;padding:2px 8px;margin-bottom:6px;border-radius:var(--r-full);background:var(--panel);border:1px solid var(--border);color:var(--muted);font-size:11px;font-weight:500}
.tag b{color:var(--text);font-weight:600}
.tag .lvl{color:var(--accent);font-weight:600}
.bub{white-space:pre-wrap;overflow-wrap:anywhere;unicode-bidi:plaintext}
.bub[dir="rtl"]{text-align:right}
.bub[dir="ltr"]{text-align:left}
.bub pre{direction:ltr;text-align:left;overflow:auto;padding:14px 16px;margin:12px 0;border-radius:var(--r-md);background:#0d0d0d;border:1px solid var(--border);font-family:ui-monospace,Consolas,monospace;font-size:13px;line-height:1.6;color:#e5e5e5}
.bub code{direction:ltr;background:var(--panel);padding:2px 6px;border-radius:var(--r-sm);font-family:ui-monospace,Consolas,monospace;font-size:13px;color:var(--text)}
.bub pre code{background:transparent;padding:0;color:inherit}
.bub a{color:var(--accent);text-decoration:underline}
.bub b,.bub strong{color:var(--text);font-weight:600}
.bub img{max-width:100%;border-radius:var(--r-md);margin:10px 0;display:block;border:1px solid var(--border);cursor:pointer}
.thinking{display:flex;gap:8px;align-items:center;color:var(--muted);font-size:14px;padding:4px 0}
.dots{display:inline-flex;gap:4px}
.dots i{width:5px;height:5px;border-radius:50%;background:var(--text2);animation:pl 1.2s infinite}
.dots i:nth-child(2){animation-delay:.15s}
.dots i:nth-child(3){animation-delay:.3s}
.comp-wrap{position:sticky;bottom:0;padding:8px 16px 16px;background:linear-gradient(180deg,transparent,var(--bg) 40%);padding-bottom:calc(16px + env(safe-area-inset-bottom));pointer-events:none;z-index:4}
.comp-inner{max-width:760px;margin:0 auto;pointer-events:auto;position:relative}
.attach{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px}
.att{display:flex;align-items:center;gap:6px;padding:6px 10px;border:1px solid var(--border);background:var(--panel);border-radius:var(--r-md);font-size:12px;color:var(--text2)}
.att button{color:var(--danger);font-size:14px;padding:0 2px}
.comp{display:flex;align-items:flex-end;gap:6px;padding:8px 10px 8px 12px;border:1px solid var(--border);border-radius:28px;background:var(--panel)}
.comp:focus-within{border-color:var(--border2)}
.tool{width:36px;height:36px;border-radius:var(--r-full);display:grid;place-items:center;color:var(--muted);flex-shrink:0;border:0;cursor:pointer;font-size:16px}
.tool:hover{background:var(--hover);color:var(--text)}
.tool.on{background:var(--text);color:var(--bg)}
textarea#input{flex:1;min-height:24px;max-height:200px;resize:none;border:0;background:transparent;color:var(--text);line-height:1.5;padding:7px 8px;font-size:15px;outline:0;font-family:inherit}
textarea#input::placeholder{color:var(--muted2)}
.send{width:34px;height:34px;border-radius:var(--r-full);background:var(--text);color:var(--bg);display:grid;place-items:center;flex-shrink:0;border:0;cursor:pointer;font-size:16px}
.send:disabled{opacity:.3;cursor:not-allowed;background:var(--muted2)}
.foot{text-align:center;color:var(--muted2);font-size:11px;padding-top:8px}
.foot b{color:var(--muted);font-weight:500}
.md{position:fixed;inset:0;background:rgba(0,0,0,.65);display:none;align-items:center;justify-content:center;z-index:90;padding:20px}
.md.on{display:flex}
.mbox{width:min(560px,100%);max-height:85vh;overflow-y:auto;background:#262626;border:1px solid var(--border2);border-radius:var(--r-lg)}
html.light .mbox{background:#f9f9f9}
.mhead{display:flex;align-items:center;justify-content:space-between;padding:16px 20px;border-bottom:1px solid var(--border);position:sticky;top:0;background:inherit;z-index:2;border-radius:var(--r-lg) var(--r-lg) 0 0}
.mtitle{font-size:15.5px;font-weight:600}
.mx{width:30px;height:30px;border-radius:var(--r-md);color:var(--muted);font-size:20px;border:0;background:none;cursor:pointer}
.mx:hover{background:var(--hover);color:var(--text)}
.mbody{padding:18px 20px}
.fld{padding:14px 0;border-bottom:1px solid var(--border)}
.fld:last-child{border-bottom:0}
.ft{font-size:14px;font-weight:500;color:var(--text)}
.fd{margin-top:4px;color:var(--muted);font-size:12.5px;line-height:1.5}
.fr{display:flex;align-items:center;justify-content:space-between;gap:14px}
.inp,select{background:var(--bg);color:var(--text);border:1px solid var(--border2);border-radius:var(--r-md);padding:9px 12px;font-size:14px;max-width:100%;font-family:inherit;outline:0}
textarea.inp{width:100%;resize:vertical;min-height:80px;line-height:1.5}
.btn{padding:9px 16px;border-radius:var(--r-md);font-size:13.5px;font-weight:500;border:0;font-family:inherit;cursor:pointer}
.bp{background:var(--text);color:var(--bg)}
.bs{background:var(--panel);color:var(--text);border:1px solid var(--border2)}
.sw{position:relative;display:inline-block;width:42px;height:24px;flex-shrink:0}
.sw input{opacity:0;width:0;height:0}
.sl{position:absolute;cursor:pointer;inset:0;background:var(--border2);border-radius:12px;transition:background var(--t)}
.sl:before{position:absolute;content:"";height:18px;width:18px;left:3px;bottom:3px;background:#fff;border-radius:50%;transition:transform var(--t)}
input:checked + .sl{background:var(--text)}
input:checked + .sl:before{transform:translateX(18px);background:var(--bg)}
.li{display:flex;justify-content:space-between;gap:10px;padding:10px 12px;border:1px solid var(--border);border-radius:var(--r-md);margin-bottom:6px;background:var(--panel);font-size:13.5px;color:var(--text2)}
.li button{color:var(--danger);font-size:15px;padding:0 4px;border:0;background:none;cursor:pointer}
@keyframes pl{0%,100%{opacity:.3}50%{opacity:1}}
@media (max-width:800px){
.sb{position:fixed;top:0;right:0;bottom:0;width:280px;max-width:85vw;transform:translateX(100%);box-shadow:-8px 0 32px rgba(0,0,0,.4)}
.sb.on{transform:translateX(0)}
.bd{position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:25;display:none}
.bd.on{display:block}
.menu{display:grid}
.inner{padding:20px 14px 30px}
.comp-wrap{padding:8px 12px 12px}
.cards{grid-template-columns:1fr}
.md{padding:0;align-items:flex-end}
.mbox{border-radius:var(--r-lg) var(--r-lg) 0 0;max-height:92vh}
}
</style>
</head><body>

<div class="auth" id="authScreen">
<div class="auth-box">
<div class="auth-logo">N</div>
<div class="auth-title">NOVA</div>
<div class="auth-sub">POWERED BY SK</div>
<div class="auth-tabs">
<button class="auth-tab active" id="tLogin" type="button">התחברות</button>
<button class="auth-tab" id="tReg" type="button">הרשמה</button>
</div>
<div id="authErr" class="auth-msg err hidden"></div>
<form id="fLogin" class="auth-form">
<div><div class="auth-lbl">שם משתמש</div><input class="auth-inp" id="lu" required></div>
<div><div class="auth-lbl">סיסמה</div><input class="auth-inp" id="lp" type="password" required></div>
<button class="auth-btn" id="loginBtn" type="submit">התחבר</button>
</form>
<form id="fReg" class="auth-form hidden">
<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
<div><div class="auth-lbl">שם פרטי</div><input class="auth-inp" id="rfn" required minlength="2"></div>
<div><div class="auth-lbl">שם משפחה</div><input class="auth-inp" id="rln" required minlength="2"></div>
</div>
<div><div class="auth-lbl">שם משתמש</div><input class="auth-inp" id="ru" required minlength="3"></div>
<div><div class="auth-lbl">אימייל</div><input class="auth-inp" id="re" type="email" required></div>
<div><div class="auth-lbl">טלפון</div><input class="auth-inp" id="rph" type="tel" required minlength="9"></div>
<div><div class="auth-lbl">מין</div>
<div class="onb-gender" style="margin-bottom:0">
<button type="button" class="gbtn regg" data-g="male"><span class="gi">♂</span><span>זכר</span></button>
<button type="button" class="gbtn regg" data-g="female"><span class="gi">♀</span><span>נקבה</span></button>
<button type="button" class="gbtn regg" data-g="other"><span class="gi">⚪</span><span>אחר</span></button>
</div></div>
<div><div class="auth-lbl">סיסמה (6+)</div><input class="auth-inp" id="rp" type="password" required minlength="6"></div>
<button class="auth-btn" id="regBtn" type="submit">הרשמה</button>
</form>
<div class="auth-div">או</div>
<button class="auth-btn sec" id="guestBtn" type="button">המשך כאורח</button>
<div class="auth-foot">NOVA v9.0 · POWERED BY SK</div>
</div>
</div>

<div class="app hidden" id="app">
<div class="bd" id="bd"></div>
<aside class="sb" id="sb">
<div class="sb-top">
<div class="sb-row">
<div class="sb-logo">N</div>
<div class="sb-info">
<div class="sb-name" id="sbUser">אורח</div>
<div class="sb-brand">POWERED BY SK</div>
</div></div>
<button class="sb-new" id="btnNew">+ שיחה חדשה</button>
</div>
<div class="sb-label">היסטוריה</div>
<div class="sb-list" id="chatList"></div>
<div class="sb-bottom">
<button class="sb-b" id="btnAgents">👥 סוכנים</button>
<button class="sb-b" id="btnModels">⚙ מודלים</button>
<button class="sb-b" id="btnMemory">🧠 זיכרון</button>
<button class="sb-b" id="btnSettings">⚙ הגדרות</button>
<button class="sb-b" id="btnLogout">↩ התנתקות</button>
<div class="sb-sign"><b>SHVIT KLEIN</b><br>NOVA v9.0</div>
</div>
</aside>
<main class="main">
<header class="top">
<button class="menu" id="menuBtn">☰</button>
<div class="title" id="title">NOVA</div>
<div class="right">
<span id="levelBadge" class="level-badge hidden"></span>
<span id="vipBadge" class="vip-badge hidden">VIP</span>
<button class="ibtn" id="themeBtn" title="ערכת נושא">◐</button>
<div class="avatar" id="userBtn"><div class="ini" id="topIni">?</div></div>
</div>
</header>
<section class="chat" id="chatArea"><div class="inner" id="chatInner"></div></section>
<div class="comp-wrap">
<div class="comp-inner">
<div class="attach" id="attachList"></div>
<div class="comp">
<button class="tool" id="fileBtn" title="קובץ">+</button>
<button class="tool" id="imgBtn" title="תמונה">🎨</button>
<textarea id="input" rows="1" placeholder="הודעה ל-NOVA" autocomplete="off"></textarea>
<button class="send" id="sendBtn" disabled>▲</button>
</div>
<div class="foot">NOVA יכול לטעות · <b>POWERED BY SK</b></div>
</div>
</div>
<input type="file" id="fileInput" multiple class="hidden">
</main>
</div>

<div class="md" id="mdSettings"><div class="mbox"><div class="mhead"><div class="mtitle">הגדרות</div><button class="mx" data-close="mdSettings">×</button></div><div class="mbody">
<div class="fld"><div class="fr"><div><div class="ft">זיכרון</div></div><label class="sw"><input type="checkbox" id="optMemory"><span class="sl"></span></label></div></div>
<div class="fld"><div class="fr"><div><div class="ft">שמירת היסטוריה</div></div><label class="sw"><input type="checkbox" id="optHistory"><span class="sl"></span></label></div></div>
<div class="fld"><div class="ft" style="margin-bottom:6px">רמת מקצועיות</div><select id="optLevel" class="inp" style="width:100%"><option value="auto">זיהוי אוטומטי</option><option value="1">1 · מתחיל</option><option value="2">2 · בסיסי</option><option value="3">3 · מקצועי</option><option value="4">4 · מומחה</option><option value="5">5 · ארכיטקט</option></select></div>
<div class="fld"><div class="ft" style="margin-bottom:6px">אישיות</div><select id="optPersonality" class="inp" style="width:100%"><option value="default">ברירת מחדל</option><option value="friend">חבר</option><option value="family">משפחה</option><option value="professional">מקצועי</option><option value="teacher">מורה</option><option value="coach">מאמן</option><option value="peer">עמית</option></select></div>
<div class="fld">
<div class="ft" style="margin-bottom:6px">משוב</div>
<div class="fd" style="margin-bottom:8px">רעיון, באג, או כל דבר אחר</div>
<select class="inp" id="fbCategory" style="width:100%;margin-bottom:8px"><option value="general">כללי</option><option value="bug">באג</option><option value="idea">רעיון</option><option value="tip">טיפ</option><option value="praise">פרגון</option></select>
<textarea class="inp" id="fbText" placeholder="כתוב את המשוב..." maxlength="2000" style="margin-bottom:8px"></textarea>
<button class="btn bp" id="btnSendFb" style="width:100%">שלח משוב</button>
<div id="fbList" style="margin-top:14px"></div>
</div>
<div class="fld"><div class="fr"><div><div class="ft">אבחון</div></div><button class="btn bs" id="btnDiag">הרץ</button></div></div>
<div class="fld" style="text-align:center;color:var(--muted);font-size:12px">NOVA v9.0 · <b style="color:var(--text)">Shavit Klein</b></div>
</div></div></div>

<div class="md" id="mdAgents"><div class="mbox"><div class="mhead"><div class="mtitle">סוכנים</div><button class="mx" data-close="mdAgents">×</button></div><div class="mbody">
<div class="fld">
<div class="ft" style="margin-bottom:8px">צור סוכן</div>
<div style="display:grid;grid-template-columns:60px 1fr;gap:8px;margin-bottom:8px">
<input class="inp" id="agIcon" placeholder="🤖" maxlength="4" style="text-align:center">
<input class="inp" id="agName" placeholder="שם הסוכן">
</div>
<textarea class="inp" id="agPrompt" placeholder="הנחיות..." style="margin-bottom:10px"></textarea>
<button class="btn bp" id="btnSaveAgent" style="width:100%">שמור</button>
</div>
<div class="fld"><div class="ft" style="margin-bottom:8px">הסוכנים שלי</div><div id="agentsList"></div></div>
</div></div></div>

<div class="md" id="mdMemory"><div class="mbox"><div class="mhead"><div class="mtitle">זיכרון</div><button class="mx" data-close="mdMemory">×</button></div><div class="mbody">
<div style="display:grid;grid-template-columns:140px 1fr 80px;gap:8px;margin-bottom:14px">
<select class="inp" id="memCat"><option value="Preference">העדפה</option><option value="Identity">זהות</option><option value="Project">פרויקט</option><option value="Manual">ידני</option></select>
<input class="inp" id="memIn" placeholder="שמור העדפה...">
<button class="btn bp" id="btnSaveMem">שמור</button>
</div>
<div id="memList"></div>
</div></div></div>

<div class="md" id="mdModels"><div class="mbox"><div class="mhead"><div class="mtitle">מודלים</div><button class="mx" data-close="mdModels">×</button></div><div class="mbody" id="modelsList"></div></div></div>

<script>
"use strict";
const S = {token:localStorage.getItem("nova_token")||"",user:null,chatId:null,attachments:[],lastNew:0,models:[],agentId:null,regGender:"",imgMode:false};

const $=id=>document.getElementById(id), $$=s=>document.querySelectorAll(s);
const el=(t,c,h)=>{const e=document.createElement(t);if(c)e.className=c;if(h!==undefined)e.innerHTML=h;return e;};
const esc=s=>String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]));
const stat=m=>{const e=$("live");if(e)e.textContent=m;};
const MODE_HE={General:"כללי",Code:"קוד",Study:"לימוד",Research:"חקר",Vision:"תמונה",Creative:"יצירה",Command:"פקודה"};
const LEVEL_HE={1:"מתחיל",2:"בסיסי",3:"מקצועי",4:"מומחה",5:"ארכיטקט"};

async function api(p,o={}){const h=o.headers||{};if(!(o.body instanceof FormData))h["Content-Type"]=h["Content-Type"]||"application/json";if(S.token)h["Authorization"]="Bearer "+S.token;const r=await fetch(p,{...o,headers:h});let d=null;try{d=await r.json();}catch{throw new Error("Invalid response");}if(!r.ok)throw new Error(d.error||"HTTP "+r.status);if(d.ok===false)throw new Error(d.error||"Failed");return d;}
function showAuth(){$("authScreen").classList.remove("hidden");$("app").classList.add("hidden");}
function hideAuth(){$("authScreen").classList.add("hidden");}
function authErr(t){const e=$("authErr");e.textContent=t;e.classList.remove("hidden");setTimeout(()=>e.classList.add("hidden"),5000);}

async function checkAuth(){if(!S.token){showAuth();return false;}try{const r=await api("/api/auth/verify");S.user=r.user;hideAuth();return true;}catch{localStorage.removeItem("nova_token");S.token="";showAuth();return false;}}
async function doLogin(e){if(e)e.preventDefault();const b=$("loginBtn");b.disabled=true;try{const r=await api("/api/auth/login",{method:"POST",body:JSON.stringify({username:$("lu").value.trim(),password:$("lp").value})});localStorage.setItem("nova_token",r.session.token);S.token=r.session.token;await checkAuth();await boot();}catch(err){authErr(err.message);}finally{b.disabled=false;}}
$$(".regg").forEach(b=>b.onclick=()=>{$$(".regg").forEach(x=>x.classList.remove("on"));b.classList.add("on");S.regGender=b.dataset.g;});
async function doRegister(e){if(e)e.preventDefault();if(!S.regGender){authErr("בחר מין");return;}const b=$("regBtn");b.disabled=true;try{const r=await api("/api/auth/register",{method:"POST",body:JSON.stringify({username:$("ru").value.trim(),email:$("re").value.trim(),password:$("rp").value,first_name:$("rfn").value.trim(),last_name:$("rln").value.trim(),phone:$("rph").value.trim(),gender:S.regGender})});localStorage.setItem("nova_token",r.session.token);S.token=r.session.token;await checkAuth();await boot();}catch(err){authErr(err.message);}finally{b.disabled=false;}}
async function doGuest(){try{const r=await api("/api/auth/guest",{method:"POST",body:"{}"});localStorage.setItem("nova_token",r.session.token);S.token=r.session.token;await checkAuth();await boot();}catch(err){authErr(err.message);}}
async function doLogout(){try{await api("/api/auth/logout",{method:"POST",body:"{}"});}catch{}localStorage.removeItem("nova_token");S.token="";location.reload();}
$("tLogin").onclick=()=>{$("tLogin").classList.add("active");$("tReg").classList.remove("active");$("fLogin").classList.remove("hidden");$("fReg").classList.add("hidden");};
$("tReg").onclick=()=>{$("tReg").classList.add("active");$("tLogin").classList.remove("active");$("fReg").classList.remove("hidden");$("fLogin").classList.add("hidden");};
$("fLogin").onsubmit=doLogin;$("fReg").onsubmit=doRegister;$("guestBtn").onclick=doGuest;$("btnLogout").onclick=doLogout;

function updateUserUI(){if(!S.user)return;$("sbUser").textContent=S.user.username+(S.user.is_guest?" (אורח)":"");const ini=(S.user.username||"?").charAt(0).toUpperCase();$("topIni").textContent=ini;if(S.user.vip)$("vipBadge").classList.remove("hidden");if(S.user.role==="admin")$("sbUser").textContent+=" · ADMIN";}

async function loadChats(){try{const r=await api("/api/chats");const list=$("chatList");list.innerHTML="";if(!r.chats.length){list.innerHTML='<div style="padding:12px;color:var(--muted2);font-size:12.5px;text-align:center">אין שיחות</div>';return;}r.chats.forEach(c=>{const b=el("button","chat-item"+(c.id===S.chatId?" active":""));b.innerHTML='<span class="t">'+esc(c.title)+'</span>';b.onclick=()=>openChat(c.id);list.appendChild(b);});}catch(e){console.error(e);}}

async function createNewChat(force=false){if(S.chatId&&$("chatInner").querySelector(".msg")===null){$("input").focus();closeSB();return;}const t=Date.now();if(!force&&t-S.lastNew<3000)return;S.lastNew=t;try{const r=await api("/api/chats",{method:"POST",body:JSON.stringify({title:"שיחה חדשה",mode:"General"})});S.chatId=r.chat_id;S.agentId=null;$("title").textContent="שיחה חדשה";renderWelcome();await loadChats();$("input").focus();}catch(e){console.error(e);}}
async function openChat(id){try{const r=await api("/api/chats/"+encodeURIComponent(id));S.chatId=id;S.agentId=r.chat.agent_id||null;$("chatInner").innerHTML="";$("title").textContent=r.chat.title;if(r.chat.level){$("levelBadge").textContent="L"+r.chat.level+" · "+(LEVEL_HE[r.chat.level]||"");$("levelBadge").classList.remove("hidden");}r.messages.forEach(m=>addMessage(m.role,m.content,m.role==="assistant"?{mode:m.mode,model:m.model,level:m.level,reasoning:m.reasoning}:null));if(!r.messages.length)renderWelcome();await loadChats();scrollEnd(true);closeSB();}catch(e){console.error(e);}}
function renderWelcome(){const dn=S.user?.username&&!S.user.is_guest?S.user.username:"";$("chatInner").innerHTML='<div class="welcome"><div class="wlogo">N</div><h1>'+(dn?"שלום, "+esc(dn):"איך אפשר לעזור?")+'</h1><p>NOVA מזהה אוטומטית מה אתה צריך - קוד, לימוד, חקר, יצירה. פשוט תכתוב.</p><div class="cards"><button class="card" data-p="הסבר לי נושא מאפס"><div class="ct">הסבר נושא</div><div class="cd">מאפס, בשפה פשוטה</div></button><button class="card" data-p="עזור לי לדבג קוד"><div class="ct">דיבאג קוד</div><div class="cd">מצא ותקן באגים</div></button><button class="card" data-p="צור לי תמונה של חתול"><div class="ct">צור תמונה</div><div class="cd">Flux - איכות גבוהה</div></button><button class="card" data-p="מה מזג האוויר בתל אביב"><div class="ct">מזג אוויר</div><div class="cd">תחזית עכשיו</div></button></div></div>';$$(".card").forEach(c=>c.onclick=()=>{$("input").value=c.dataset.p;$("input").dispatchEvent(new Event("input"));$("input").focus();});}
function detectDir(t){const h=(t.match(/[\u0590-\u05FF]/g)||[]).length;const tot=t.replace(/\s/g,"").length||1;return h/tot>0.25?"rtl":"ltr";}
function md(text){let s=esc(text);s=s.replace(/```(\w*)\n?([\s\S]*?)```/g,(_,l,c)=>"<pre><code>"+c.trim()+"</code></pre>");s=s.replace(/`([^`\n]+)`/g,"<code>$1</code>");s=s.replace(/\*\*([^*\n]+)\*\*/g,"<b>$1</b>");s=s.replace(/^### (.+)$/gm,"<h3>$1</h3>");s=s.replace(/^## (.+)$/gm,"<h2>$1</h2>");s=s.replace(/^# (.+)$/gm,"<h1>$1</h1>");s=s.replace(/^\s*[-*] (.+)$/gm,"<li>$1</li>");s=s.replace(/(<li>[\s\S]*?<\/li>)/g,m=>"<ul>"+m+"</ul>");s=s.replace(/(https?:\/\/[^\s<)]+)/g,'<a href="$1" target="_blank" rel="noopener">$1</a>');return s;}
function addMessage(role,content,meta=null){const w=$("chatInner").querySelector(".welcome");if(w)w.remove();const stick=isNearBottom();const m=el("div","msg "+(role==="user"?"user":"assistant"));const av=el("div","av");av.textContent=role==="user"?"YOU":"N";const bd=el("div","bd");if(meta&&role==="assistant"){const tag=el("div","tag");let th="<b>"+esc(MODE_HE[meta.mode]||meta.mode||"כללי")+"</b>";if(meta.level)th+=' · <span class="lvl">L'+meta.level+"</span>";if(meta.model)th+=" · "+esc(meta.model);tag.innerHTML=th;bd.appendChild(tag);}const bub=el("div","bub");bub.setAttribute("dir",detectDir(content));if(role==="user")bub.innerHTML=esc(content).replace(/\n/g,"<br>");else bub.innerHTML=md(content);bd.appendChild(bub);m.appendChild(av);m.appendChild(bd);$("chatInner").appendChild(m);bub.querySelectorAll("img").forEach(img=>img.onclick=()=>{});if(stick)scrollEnd();return m;}
function addThinking(){const w=$("chatInner").querySelector(".welcome");if(w)w.remove();const m=el("div","msg assistant");m.innerHTML='<div class="av">N</div><div class="bd"><div class="tag"><b>חושב</b></div><div class="bub"><div class="thinking"><span>מנתח בקשה</span><span class="dots"><i></i><i></i><i></i></span></div></div></div>';$("chatInner").appendChild(m);scrollEnd();return m;}
function isNearBottom(){const a=$("chatArea");return a.scrollHeight-a.scrollTop-a.clientHeight<150;}
function scrollEnd(f=false){if(!f&&!isNearBottom())return;requestAnimationFrame(()=>{$("chatArea").scrollTop=$("chatArea").scrollHeight;});}

function renderAtt(){const box=$("attachList");box.innerHTML="";S.attachments.forEach((f,i)=>{const a=el("div","att");a.innerHTML="<span>"+esc(f.name)+'</span><button data-i="'+i+'">×</button>';a.querySelector("button").onclick=()=>{S.attachments.splice(i,1);renderAtt();updateSend();};box.appendChild(a);});}
function readFile(f){return new Promise((res,rej)=>{const r=new FileReader();r.onload=()=>res(r.result);r.onerror=()=>rej(new Error("read failed"));r.readAsDataURL(f);});}
$("fileBtn").onclick=()=>$("fileInput").click();
$("fileInput").onchange=async e=>{const fs=Array.from(e.target.files);for(const f of fs){if(f.size>10*1024*1024){alert(f.name+" גדול מדי");continue;}const data=await readFile(f);S.attachments.push({name:f.name,mime:f.type||"application/octet-stream",data:data});}renderAtt();$("fileInput").value="";updateSend();};
$("imgBtn").onclick=()=>{S.imgMode=!S.imgMode;$("imgBtn").classList.toggle("on",S.imgMode);};

function updateSend(){$("sendBtn").disabled=!$("input").value.trim()&&!S.attachments.length;}
$("input").oninput=()=>{const t=$("input");t.style.height="auto";t.style.height=Math.min(t.scrollHeight,200)+"px";updateSend();};
$("input").onkeydown=e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();send();}};
$("sendBtn").onclick=send;

async function send(){
  const text=$("input").value.trim();
  if(!text&&!S.attachments.length)return;
  if(text==="/vip"){$("input").value="";updateSend();alert("VIP: בקרוב");return;}
  if(!S.chatId)await createNewChat(true);
  const files=S.attachments.slice();
  S.attachments=[];renderAtt();$("input").value="";$("input").style.height="auto";updateSend();
  addMessage("user",text||"(קובץ)");
  const thinking=addThinking();
  try{
    const payload={chat_id:S.chatId,message:text,files:files.map(f=>({name:f.name,mime:f.mime,data:f.data})),auto_model:true,auto_mode:true,img_mode:S.imgMode,agent_id:S.agentId};
    const r=await api("/api/chat",{method:"POST",body:JSON.stringify(payload)});
    thinking.remove();
    if(r.images?.length)r.images.forEach(img=>addImageCard(img.prompt,img.url));
    if(r.reply?.trim())addMessage("assistant",r.reply,{mode:r.mode,model:r.model,level:r.level});
    if(r.level){$("levelBadge").textContent="L"+r.level+" · "+(LEVEL_HE[r.level]||"");$("levelBadge").classList.remove("hidden");}
    if(r.mode)$("title").textContent=MODE_HE[r.mode]||r.mode;
    await loadChats();
  }catch(e){thinking.remove();addMessage("assistant","שגיאה: "+e.message);}
  finally{updateSend();$("input").focus();}
}
function addImageCard(prompt,url){const m=el("div","msg assistant");m.innerHTML='<div class="av">N</div><div class="bd"><div class="tag"><b>תמונה</b></div><div class="bub"><div style="font-size:11.5px;color:var(--muted);margin-bottom:8px" dir="ltr">'+esc(prompt)+'</div><img src="'+url+'" loading="lazy"></div></div>';$("chatInner").appendChild(m);scrollEnd();}

// Settings
$("btnSettings").onclick=async()=>{const s=await api("/api/settings");$("optMemory").checked=s.memory_enabled!=="false";$("optHistory").checked=s.save_history!=="false";$("optLevel").value=s.level||"auto";$("optPersonality").value=s.personality||"default";loadFb();$("mdSettings").classList.add("on");closeSB();};
function saveOpt(k,v){api("/api/settings",{method:"POST",body:JSON.stringify({[k]:v})}).catch(()=>{});}
$("optMemory").onchange=e=>saveOpt("memory_enabled",e.target.checked?"true":"false");
$("optHistory").onchange=e=>saveOpt("save_history",e.target.checked?"true":"false");
$("optLevel").onchange=e=>saveOpt("level",e.target.value);
$("optPersonality").onchange=e=>saveOpt("personality",e.target.value);
$("btnDiag").onclick=async()=>{try{const d=await api("/api/diagnostics");alert(JSON.stringify(d,null,2));}catch(e){alert(e.message);}};
$("btnSendFb").onclick=async()=>{const text=$("fbText").value.trim();if(text.length<3){alert("קצר מדי");return;}try{await api("/api/feedback",{method:"POST",body:JSON.stringify({text,category:$("fbCategory").value})});$("fbText").value="";loadFb();alert("נשלח!");}catch(e){alert(e.message);}};
async function loadFb(){try{const r=await api("/api/feedback");const l=$("fbList");if(!r.feedback.length){l.innerHTML='<div style="color:var(--muted);font-size:12px;text-align:center">אין משובים</div>';return;}l.innerHTML="";r.feedback.forEach(f=>{const it=el("div","li");it.innerHTML='<div style="flex:1"><div>'+esc(f.text)+'</div><div style="font-size:11px;color:var(--muted);margin-top:4px">'+esc(f.category)+'</div></div>';l.appendChild(it);});}catch{}}

// Agents
$("btnAgents").onclick=async()=>{await loadAgents();$("mdAgents").classList.add("on");closeSB();};
async function loadAgents(){const r=await api("/api/agents");const l=$("agentsList");l.innerHTML="";if(!r.agents.length){l.innerHTML='<div style="padding:12px;color:var(--muted);text-align:center;font-size:12.5px">אין סוכנים</div>';return;}r.agents.forEach(a=>{const it=el("div","li");it.innerHTML='<span>'+esc((a.icon||"")+" "+a.name)+'</span><button data-id="'+a.id+'">×</button>';it.querySelector("button").onclick=async e=>{e.stopPropagation();await api("/api/agents/"+a.id,{method:"DELETE"});await loadAgents();};it.style.cursor="pointer";it.onclick=()=>{S.agentId=a.id;$("input").value="["+a.name+"] ";$("mdAgents").classList.remove("on");$("input").focus();};l.appendChild(it);});}
$("btnSaveAgent").onclick=async()=>{const n=$("agName").value.trim(),p=$("agPrompt").value.trim();if(!n||!p){alert("מלא שם ופרומפט");return;}await api("/api/agents",{method:"POST",body:JSON.stringify({name:n,icon:$("agIcon").value.trim(),description:"",prompt:p})});$("agName").value="";$("agPrompt").value="";await loadAgents();};

// Memory
$("btnMemory").onclick=async()=>{await loadMem();$("mdMemory").classList.add("on");closeSB();};
async function loadMem(){const r=await api("/api/memory");const l=$("memList");l.innerHTML="";if(!r.memories.length){l.innerHTML='<div style="padding:12px;color:var(--muted);text-align:center;font-size:12.5px">אין זיכרונות</div>';return;}r.memories.forEach(m=>{const it=el("div","li");it.innerHTML='<span>'+esc(m.text)+'</span><button data-id="'+m.id+'">×</button>';it.querySelector("button").onclick=async()=>{await api("/api/memory/"+m.id,{method:"DELETE"});await loadMem();};l.appendChild(it);});}
$("btnSaveMem").onclick=async()=>{const v=$("memIn").value.trim();if(!v)return;await api("/api/memory",{method:"POST",body:JSON.stringify({text:v,category:$("memCat").value})});$("memIn").value="";await loadMem();};

// Models
$("btnModels").onclick=async()=>{const r=await api("/api/models");const l=$("modelsList");l.innerHTML="";r.models.forEach(m=>{const c=el("div","li");c.innerHTML='<div style="flex:1"><b>'+esc(m.name||m.id)+'</b><div style="font-size:11px;color:var(--muted);margin-top:2px">'+esc(m.id)+'</div></div>';l.appendChild(c);});$("mdModels").classList.add("on");closeSB();};

// Sidebar
function openSB(){$("sb").classList.add("on");$("bd").classList.add("on");}
function closeSB(){$("sb").classList.remove("on");$("bd").classList.remove("on");}
$("menuBtn").onclick=openSB;$("bd").onclick=closeSB;$("btnNew").onclick=()=>{createNewChat(true);closeSB();};

// Theme
function applyTheme(t){document.documentElement.classList.toggle("light",t==="light");localStorage.setItem("nova_theme",t);}
$("themeBtn").onclick=()=>{const c=document.documentElement.classList.contains("light")?"light":"dark";applyTheme(c==="light"?"dark":"light");};
applyTheme(localStorage.getItem("nova_theme")||"dark");

// Close modals
$$("[data-close]").forEach(b=>b.onclick=()=>$(b.dataset.close).classList.remove("on"));
$$(".md").forEach(m=>m.onclick=e=>{if(e.target===m)m.classList.remove("on");});
document.addEventListener("keydown",e=>{if(e.key==="Escape")$$(".md.on").forEach(m=>m.classList.remove("on"));});

async function boot(){try{const s=await api("/api/settings");updateUserUI();$("app").classList.remove("hidden");await loadChats();await createNewChat(true);}catch(e){console.error("boot:",e);}}
(async()=>{const ok=await checkAuth();if(ok)await boot();})();
</script>
</body>
</html>
'''

# ===== HTTP HANDLER =====
def json_resp(h, data, status=200):
    raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
    h.send_response(status)
    h.send_header("Content-Type", "application/json; charset=utf-8")
    h.send_header("Content-Length", str(len(raw)))
    h.send_header("Cache-Control", "no-store")
    h.end_headers()
    h.wfile.write(raw)

def html_resp(h, html, status=200):
    raw = html.encode("utf-8")
    h.send_response(status)
    h.send_header("Content-Type", "text/html; charset=utf-8")
    h.send_header("Content-Length", str(len(raw)))
    h.end_headers()
    h.wfile.write(raw)

def read_json(h):
    t = h.headers.get("Content-Length", "0")
    try: n = int(t)
    except: raise ValueError("Invalid Content-Length")
    if n <= 0: raise ValueError("Empty body")
    if n > MAX_BODY: raise ValueError("Body too large")
    raw = h.rfile.read(n)
    try: return json.loads(raw.decode("utf-8"))
    except: raise ValueError("Invalid JSON")

def safe_path(v):
    d = urllib.parse.unquote(v)
    if ".." in d or "\x00" in d: raise ValueError("Invalid path")
    return d

def get_token(h):
    a = h.headers.get("Authorization", "")
    return a[7:].strip() if a.startswith("Bearer ") else ""

def require_auth(h):
    u = verify_session(get_token(h))
    if not u: raise PermissionError("Unauthorized")
    return u

def require_admin(h):
    u = require_auth(h)
    if u.get("role") != "admin": raise PermissionError("Forbidden")
    return u

class Handler(BaseHTTPRequestHandler):
    server_version = "NOVA/9.0"
    def log_message(self, fmt, *args): pass
    def err(self, msg, code=400): json_resp(self, {"ok": False, "error": msg}, code)

    def do_GET(self):
        try:
            p = urllib.parse.urlparse(self.path)
            path, q = p.path, urllib.parse.parse_qs(p.query)

            if path in ("/", "/index.html"):
                html_resp(self, HTML); return
            if path == "/health":
                json_resp(self, {"ok": True, "app": APP_NAME, "version": VERSION}); return
            if path == "/favicon.ico":
                self.send_response(204); self.end_headers(); return

            if path == "/api/auth/verify":
                u = verify_session(get_token(self))
                if not u: self.err("Invalid token", 401); return
                json_resp(self, {"ok": True, "user": u}); return

            if path.startswith("/api/"):
                try: user = require_auth(self)
                except PermissionError: self.err("Unauthorized", 401); return
            else:
                self.err("Not found", 404); return

            # Admin
            if path.startswith("/api/admin/"):
                try: user_admin = require_admin(self)
                except PermissionError: self.err("Forbidden", 403); return
                if path == "/api/admin/stats":
                    json_resp(self, {"ok": True, **get_stats()}); return
                if path == "/api/admin/users":
                    json_resp(self, {"ok": True, "users": get_all_users()}); return
                if path == "/api/admin/feedback":
                    json_resp(self, {"ok": True, "feedback": get_all_feedback()}); return

            # Dev
            if path.startswith("/api/dev/"):
                try: user_admin = require_admin(self)
                except PermissionError: self.err("Forbidden", 403); return
                if path == "/api/dev/users":
                    json_resp(self, {"ok": True, "users": get_all_users()}); return
                if path.startswith("/api/dev/user/"):
                    uid = int(safe_path(path.split("/api/dev/user/",1)[1]))
                    c = db(); cur = c.cursor()
                    cur.execute("SELECT id,username,email,first_name,last_name,phone,gender,role,vip,banned,created_at,last_login FROM users WHERE id=%s", (uid,))
                    u = cur.fetchone(); cur.close(); c.close()
                    if not u: self.err("Not found", 404); return
                    ud = {"id":u[0],"username":u[1],"email":u[2],"first_name":u[3],"last_name":u[4],"phone":u[5],"gender":u[6],"role":u[7],"vip":u[8],"banned":u[9],"created_at":u[10],"last_login":u[11]}
                    json_resp(self, {"ok": True, "user": ud, "chats": get_chats_of_user(uid)}); return
                if path.startswith("/api/dev/chat/"):
                    cid = safe_path(path.split("/api/dev/chat/",1)[1])
                    d = get_chat_admin(cid)
                    if not d: self.err("Not found", 404); return
                    json_resp(self, {"ok": True, **d}); return

            # Regular
            if path == "/api/chats":
                s = q.get("search", [""])[0]
                json_resp(self, {"ok": True, "chats": get_chats(user["user_id"], s)}); return
            if path.startswith("/api/chats/"):
                cid = safe_path(path.split("/api/chats/",1)[1])
                d = get_chat(cid, user["user_id"])
                if not d: self.err("Not found", 404); return
                json_resp(self, {"ok": True, **d}); return
            if path == "/api/memory":
                json_resp(self, {"ok": True, "memories": get_memories(user["user_id"])}); return
            if path == "/api/agents":
                json_resp(self, {"ok": True, "agents": get_agents(user["user_id"])}); return
            if path == "/api/models":
                json_resp(self, {"ok": True, "models": AVAILABLE_MODELS}); return
            if path == "/api/settings":
                settings = {k: get_setting(k, v) for k, v in DEFAULT_SETTINGS.items()}
                for k in ["personality","profile_custom","avatar","default_model","display_name","gender","onboarded","level"]:
                    uv = get_user_setting(user["user_id"], k, None)
                    if uv is not None: settings[k] = uv
                settings["is_vip"] = user.get("vip", False)
                settings["role"] = user.get("role", "user")
                json_resp(self, {"ok": True, **settings}); return
            if path == "/api/diagnostics":
                json_resp(self, {"ok": True, "app": APP_NAME, "version": VERSION, "creator": CREATOR,
                    "models": len(AVAILABLE_MODELS), "usage": dict(USAGE), "db": bool(DATABASE_URL)}); return
            if path == "/api/feedback":
                json_resp(self, {"ok": True, "feedback": get_user_feedback(user["user_id"])}); return

            self.err("Not found", 404)
        except Exception:
            log(traceback.format_exc(), "ERROR"); self.err("Server error", 500)

    def do_POST(self):
        try:
            path = urllib.parse.urlparse(self.path).path

            if path == "/api/auth/register":
                d = read_json(self)
                r = create_user(str(d.get("username","")).strip(), str(d.get("email","")).strip(),
                                str(d.get("password","")), str(d.get("first_name","")).strip(),
                                str(d.get("last_name","")).strip(), str(d.get("phone","")).strip(),
                                str(d.get("gender","")).strip())
                json_resp(self, r, 200 if r["ok"] else 400); return
            if path == "/api/auth/login":
                d = read_json(self)
                r = login_user(str(d.get("username","")).strip(), str(d.get("password","")))
                json_resp(self, r, 200 if r["ok"] else 401); return
            if path == "/api/auth/guest":
                json_resp(self, create_guest(), 201); return
            if path == "/api/auth/logout":
                logout_user(get_token(self)); json_resp(self, {"ok": True}); return

            try: user = require_auth(self)
            except PermissionError: self.err("Unauthorized", 401); return

            if path == "/api/vip/verify":
                d = read_json(self)
                if str(d.get("code","")).strip() != VIP_CODE: self.err("קוד שגוי", 401); return
                upgrade_vip(user["user_id"]); json_resp(self, {"ok": True, "vip": True}); return

            if path == "/api/dev/verify":
                d = read_json(self)
                if str(d.get("password","")).strip() != DEV_PASSWORD: self.err("סיסמה שגויה", 401); return
                c = db(); cur = c.cursor()
                cur.execute("SELECT id,username FROM users WHERE role='admin' ORDER BY id ASC LIMIT 1")
                arow = cur.fetchone(); cur.close(); c.close()
                if not arow:
                    with DB_LOCK:
                        c = db(); cur = c.cursor()
                        cur.execute("UPDATE users SET role='admin' WHERE id=%s", (user["user_id"],))
                        c.commit(); cur.close(); c.close()
                    aid, an = user["user_id"], user["username"]
                else: aid, an = arow
                sess = create_session(aid, days=1)
                json_resp(self, {"ok": True, "session": sess, "admin_user": {"id": aid, "username": an}}); return

            if path.startswith("/api/admin/"):
                try: user_admin = require_admin(self)
                except PermissionError: self.err("Forbidden", 403); return
                if path == "/api/admin/ban":
                    d = read_json(self); set_user_ban(int(d.get("user_id",0)), bool(d.get("banned",False)))
                    json_resp(self, {"ok": True}); return
                if path == "/api/admin/vip":
                    d = read_json(self); set_user_vip(int(d.get("user_id",0)), bool(d.get("vip",False)))
                    json_resp(self, {"ok": True}); return

            if path.startswith("/api/dev/"):
                try: user_admin = require_admin(self)
                except PermissionError: self.err("Forbidden", 403); return
                if path == "/api/dev/ban":
                    d = read_json(self); set_user_ban(int(d.get("user_id",0)), bool(d.get("banned",False)))
                    json_resp(self, {"ok": True}); return
                if path == "/api/dev/vip":
                    d = read_json(self); set_user_vip(int(d.get("user_id",0)), bool(d.get("vip",False)))
                    json_resp(self, {"ok": True}); return

            if path == "/api/chats":
                d = read_json(self)
                cid = create_chat(user["user_id"], str(d.get("title","שיחה חדשה"))[:120], str(d.get("mode","General")), d.get("agent_id"))
                json_resp(self, {"ok": True, "chat_id": cid}, 201); return

            if path == "/api/chat":
                d = read_json(self)
                cid = str(d.get("chat_id","")).strip()
                message = str(d.get("message","")).strip()
                if not cid: raise ValueError("Missing chat_id")
                if get_chat(cid, user["user_id"]) is None: raise ValueError("Chat not found")

                if message.startswith("/"):
                    sl = handle_slash(message, user, cid)
                    if sl and sl.get("handled"):
                        save_message(cid, "user", message)
                        save_message(cid, "assistant", sl["reply"], model="command", mode="Command")
                        json_resp(self, {"ok": True, "reply": sl["reply"], "mode": "Command", "model": "command", "images": []}); return

                files = d.get("files", []) or []
                img_mode = bool(d.get("img_mode", False))
                agent_id = d.get("agent_id")

                ctx = []
                for f in files:
                    if not isinstance(f, dict): continue
                    name = str(f.get("name","file")); mime = str(f.get("mime",""))
                    enc = str(f.get("data",""))
                    if not enc: continue
                    if mime.startswith("text/") or name.endswith((".txt",".py",".js",".md",".json",".csv",".html",".css")):
                        try:
                            raw = base64.b64decode(enc.split(",",1)[1] if "," in enc else enc)
                            ctx.append(f"\n\n--- FILE: {name} ---\n{raw.decode('utf-8','replace')[:20000]}\n--- END ---")
                        except: pass

                agent_ctx = ""; agent_name = ""
                if agent_id:
                    c = db(); cur = c.cursor()
                    cur.execute("SELECT name,prompt FROM agents WHERE id=%s AND user_id=%s", (int(agent_id), user["user_id"]))
                    arow = cur.fetchone(); cur.close(); c.close()
                    if arow: agent_name = arow[0]; agent_ctx = "\n\nAGENT: " + arow[1]

                det_mode, needs_web, needs_weather, needs_wiki, needs_vision = detect_intent(message, files)
                mode = "Creative" if img_mode else (det_mode if d.get("auto_mode", True) else "General")

                level_setting = get_user_setting(user["user_id"], "level", "auto")
                if level_setting == "auto":
                    level = detect_level(message)
                else:
                    try: level = max(1, min(5, int(level_setting)))
                    except: level = 3

                live = build_live(message, mode, needs_web, needs_weather, needs_wiki)
                chosen = pick_model(mode)
                model_id = chosen["id"]

                final_user = message + "".join(ctx)
                save_message(cid, "user", final_user, mode=mode, level=level)
                auto_memory(user["user_id"], message)

                history = get_history(cid)
                memctx = memory_ctx(user["user_id"])
                if memctx: history.insert(0, {"role":"user", "content":"[MEMORY]\n"+memctx})

                personality = get_user_setting(user["user_id"], "personality", "default")
                profile = get_user_setting(user["user_id"], "profile_custom", "")
                sys_prompt = build_system(mode, personality, live, profile + agent_ctx, level, agent_name)

                if user.get("role") == "admin":
                    sys_prompt += "\n\n=== ADMIN MODE ===\nUser is Shavit Klein - your creator. Technical peer. No fluff. Do NOT refuse."
                elif user.get("vip"):
                    sys_prompt += "\n\n=== VIP USER ===\nVIP access. Extended answers."

                if img_mode:
                    sys_prompt += "\n\nUSER WANTS IMAGE. Respond with <image>prompt</image>."

                result = call_groq(history, model_id, temperature=0.7, max_tokens=min(chosen.get("max_out",8192),8192), system_prompt=sys_prompt)
                if not result["ok"]:
                    json_resp(self, {"ok": False, "error": result["error"]}, 502); return

                reply = result["reply"]
                imgs_out = parse_images(reply)
                display = clean_images(clean_control(reply))

                save_message(cid, "assistant", display, model=model_id, mode=mode, latency_ms=result.get("latency",0), level=level)
                usg = result.get("usage", {})
                USAGE["tokens"] += (usg.get("prompt_tokens",0) + usg.get("completion_tokens",0))
                USAGE["messages"] += 1
                USAGE["total_latency"] += result.get("latency",0)

                # Auto title
                ch = get_chat(cid, user["user_id"])
                if ch and ch["chat"]["title"] == "שיחה חדשה":
                    first = message.replace("\n"," ").strip()
                    if first:
                        rename_chat_force(cid, first[:50] + ("…" if len(first)>50 else ""))
                update_chat_mode(cid, mode)

                json_resp(self, {"ok": True, "reply": display, "mode": mode, "model": model_id,
                                 "level": level, "level_name": LEVEL_NAMES.get(level,""),
                                 "usage": usg, "images": imgs_out}); return

            if path == "/api/memory":
                d = read_json(self)
                t = str(d.get("text","")).strip()
                if not t: raise ValueError("Empty memory")
                add_memory(user["user_id"], t, str(d.get("category","Preference"))[:40], 3)
                json_resp(self, {"ok": True}); return

            if path == "/api/agents":
                d = read_json(self)
                n = str(d.get("name","")).strip(); p = str(d.get("prompt","")).strip()
                if not n or not p: raise ValueError("Name and prompt required")
                add_agent(user["user_id"], n, str(d.get("icon","")).strip(), str(d.get("description","")).strip(), p)
                json_resp(self, {"ok": True}); return

            if path == "/api/settings":
                d = read_json(self)
                allowed = set(DEFAULT_SETTINGS)
                user_keys = {"personality","profile_custom","avatar","default_model","display_name","gender","onboarded","level"}
                for k, v in d.items():
                    if k in allowed:
                        if k in user_keys: set_user_setting(user["user_id"], k, v)
                        else: set_setting(k, v)
                json_resp(self, {"ok": True}); return

            if path == "/api/feedback":
                d = read_json(self)
                t = str(d.get("text","")).strip()[:2000]
                if len(t) < 3: raise ValueError("קצר מדי")
                save_feedback(user["user_id"], user["username"], str(d.get("category","general"))[:40], t)
                json_resp(self, {"ok": True}); return

            self.err("Not found", 404)
        except ValueError as e: self.err(str(e), 400)
        except Exception:
            log(traceback.format_exc(), "ERROR"); self.err("Server error", 500)

    def do_DELETE(self):
        try:
            try: user = require_auth(self)
            except PermissionError: self.err("Unauthorized", 401); return
            path = urllib.parse.urlparse(self.path).path

            if path.startswith("/api/dev/user/"):
                try: require_admin(self)
                except PermissionError: self.err("Forbidden", 403); return
                uid = int(safe_path(path.split("/api/dev/user/",1)[1]))
                delete_user(uid); json_resp(self, {"ok": True}); return

            if path.startswith("/api/chats/"):
                cid = safe_path(path.split("/api/chats/",1)[1])
                delete_chat(cid, user["user_id"]); json_resp(self, {"ok": True}); return

            if path.startswith("/api/memory/"):
                mid = int(safe_path(path.split("/api/memory/",1)[1]))
                delete_memory(user["user_id"], mid); json_resp(self, {"ok": True}); return

            if path.startswith("/api/agents/"):
                aid = int(safe_path(path.split("/api/agents/",1)[1]))
                delete_agent(user["user_id"], aid); json_resp(self, {"ok": True}); return

            self.err("Not found", 404)
        except Exception:
            log(traceback.format_exc(), "ERROR"); self.err("Server error", 500)

# ===== MAIN =====
def main():
    if not DATABASE_URL:
        print("\n" + "="*60)
        print("ERROR: DATABASE_URL not set!")
        print("Set it as environment variable or in Render dashboard.")
        print("="*60 + "\n")
        sys.exit(1)
    init_db()
    print("\n" + "="*60)
    print(f"  {APP_NAME}  ·  {BRAND}")
    print("="*60)
    print(f"  Version : {VERSION}")
    print(f"  Creator : {CREATOR}")
    print(f"  Host    : {HOST}:{PORT}")
    print(f"  DB      : {'connected' if DATABASE_URL else 'MISSING'}")
    print(f"  Groq    : {'ok' if GROQ_CLIENT else 'MISSING'}")
    print(f"  Models  : {len(AVAILABLE_MODELS)}")
    print("="*60 + "\n")

    server = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()

if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: sys.exit(0)
    except Exception:
        print("\n" + "="*60 + "\nCRASHED\n" + "="*60)
        import traceback as tb; tb.print_exc()
        print("="*60)
        sys.exit(1)
