import os, re, json, uuid, sqlite3, logging, asyncio, threading
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = "8977741740:AAEhHQSYw0ODjXs85fRuGomcAZrgIjWO6FQ"
DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(DIR, "users.db")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder=None)

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL DEFAULT '',
                nickname TEXT DEFAULT '',
                avatar TEXT DEFAULT '',
                token TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS saves (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                game TEXT NOT NULL,
                data TEXT DEFAULT '{}',
                updated_at TEXT DEFAULT (datetime('now')),
                UNIQUE(user_id, game),
                FOREIGN KEY(user_id) REFERENCES users(id)
            );
        """)
        for col in ['nickname', 'avatar']:
            try:
                conn.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass
    logger.info("DB initialized")

def token_required(req):
    auth = req.headers.get("Authorization", "")
    token = auth.replace("Bearer ", "").strip()
    if not token:
        return None
    with get_db() as conn:
        row = conn.execute("SELECT id, email, nickname, avatar FROM users WHERE token = ?", (token,)).fetchone()
    return dict(row) if row else None

@app.route("/api/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        return jsonify({"error": "РќРµРІРµСЂРЅС‹Р№ С„РѕСЂРјР°С‚ email"}), 400
    token = str(uuid.uuid4())
    try:
        with get_db() as conn:
            conn.execute("INSERT INTO users (email, password, token, nickname, avatar) VALUES (?, ?, ?, ?, ?)", (email, "", token, "", ""))
        return jsonify({"ok": True, "token": token, "email": email, "nickname": "", "avatar": ""})
    except sqlite3.IntegrityError:
        return jsonify({"error": "Email СѓР¶Рµ Р·Р°СЂРµРіРёСЃС‚СЂРёСЂРѕРІР°РЅ"}), 409

@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    with get_db() as conn:
        row = conn.execute("SELECT id, email, nickname, avatar FROM users WHERE email = ?", (email,)).fetchone()
    if not row:
        return jsonify({"error": "Email РЅРµ РЅР°Р№РґРµРЅ. РЎРЅР°С‡Р°Р»Р° Р·Р°СЂРµРіРёСЃС‚СЂРёСЂСѓР№С‚РµСЃСЊ."}), 404
    token = str(uuid.uuid4())
    with get_db() as conn:
        conn.execute("UPDATE users SET token = ? WHERE id = ?", (token, row["id"]))
    return jsonify({"ok": True, "token": token, "email": row["email"], "nickname": row["nickname"] or "", "avatar": row["avatar"] or ""})

@app.route("/api/save", methods=["POST"])
def save():
    user = token_required(request)
    if not user:
        return jsonify({"error": "РўСЂРµР±СѓРµС‚СЃСЏ Р°РІС‚РѕСЂРёР·Р°С†РёСЏ"}), 401
    data = request.get_json(silent=True) or {}
    game = data.get("game", "").strip()
    game_data = json.dumps(data.get("data", {}), ensure_ascii=False)
    if not game:
        return jsonify({"error": "РЈРєР°Р¶РёС‚Рµ РёРіСЂСѓ"}), 400
    with get_db() as conn:
        conn.execute("""
            INSERT INTO saves (user_id, game, data, updated_at)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(user_id, game) DO UPDATE SET
                data = excluded.data,
                updated_at = excluded.updated_at
        """, (user["id"], game, game_data))
    return jsonify({"ok": True})

@app.route("/api/load", methods=["GET"])
def load():
    user = token_required(request)
    if not user:
        return jsonify({"error": "РўСЂРµР±СѓРµС‚СЃСЏ Р°РІС‚РѕСЂРёР·Р°С†РёСЏ"}), 401
    game = request.args.get("game", "").strip()
    if not game:
        return jsonify({"error": "РЈРєР°Р¶РёС‚Рµ РёРіСЂСѓ"}), 400
    with get_db() as conn:
        row = conn.execute("SELECT data FROM saves WHERE user_id = ? AND game = ?", (user["id"], game)).fetchone()
    return jsonify({"ok": True, "data": json.loads(row["data"]) if row else None})

@app.route("/api/me", methods=["GET"])
def me():
    user = token_required(request)
    if not user:
        return jsonify({"error": "РўСЂРµР±СѓРµС‚СЃСЏ Р°РІС‚РѕСЂРёР·Р°С†РёСЏ"}), 401
    return jsonify({"ok": True, "email": user["email"], "nickname": user["nickname"] or "", "avatar": user["avatar"] or ""})

@app.route("/api/profile", methods=["PUT"])
def update_profile():
    user = token_required(request)
    if not user:
        return jsonify({"error": "РўСЂРµР±СѓРµС‚СЃСЏ Р°РІС‚РѕСЂРёР·Р°С†РёСЏ"}), 401
    data = request.get_json(silent=True) or {}
    nickname = (data.get("nickname") or "").strip()[:15]
    avatar = (data.get("avatar") or "").strip()[:500000]
    with get_db() as conn:
        conn.execute("UPDATE users SET nickname = ?, avatar = ? WHERE id = ?", (nickname, avatar, user["id"]))
    return jsonify({"ok": True, "nickname": nickname, "avatar": avatar})

@app.route("/", defaults={"path": "index.html"})
@app.route("/<path:path>")
def static_files(path):
    filepath = os.path.join(DIR, path)
    if not os.path.exists(filepath) or not os.path.isfile(filepath):
        return "Not found", 404
    return send_from_directory(DIR, path)

async def bot_start(update: Update, ctx):
    webapp_url = os.environ.get("WEBAPP_URL", f"https://{os.environ.get('KOYEB_SERVICE_URL', 'localhost')}")
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("рџЋ® РћС‚РєСЂС‹С‚СЊ РёРіСЂС‹", web_app=WebAppInfo(url=webapp_url))
    ]])
    msg = (
        "рџЋ®вњЁ <b>SpikeGod</b> вњЁрџЋ®\n\n"
        "рџ‘‹ <i>Р”РѕР±СЂРѕ РїРѕР¶Р°Р»РѕРІР°С‚СЊ! РќР°СЃР»Р°Р¶РґР°Р№СЃСЏ РёРіСЂРѕР№</i>\n\n"
        "в¬‡пёЏ <b>РќР°Р¶РјРё РєРЅРѕРїРєСѓ РЅРёР¶Рµ, С‡С‚РѕР±С‹ РЅР°С‡Р°С‚СЊ</b>"
    )
    await update.message.reply_text(msg, reply_markup=kb, parse_mode="HTML")

def run_bot():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    tg_app = Application.builder().token(TOKEN).build()
    tg_app.add_handler(CommandHandler("start", bot_start))
    logger.info("Bot started polling")
    tg_app.run_polling()

if __name__ == "__main__":
    init_db()
    t = threading.Thread(target=run_bot, daemon=True)
    t.start()
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Server running on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
