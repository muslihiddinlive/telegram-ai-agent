import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
SUPERADMIN_ID = int(os.environ["SUPERADMIN_ID"])
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
DB_GROUP_ID = int(os.environ["DB_GROUP_ID"])
PORT = int(os.environ.get("PORT", 8080))

# Bot adminlari + superadmin uchun kunlik limit (faqat /chatmode on guruhlarida ularning
# hisobidan ketadigan so'rovlarga tegishli; shaxsiy chatda ular baribir limitsiz).
ADMIN_DAILY_LIMIT = int(os.environ.get("ADMIN_DAILY_LIMIT", 100))

def _split_keys(env_name: str) -> list[str]:
    raw = os.environ.get(env_name, "")
    return [k.strip() for k in raw.split(",") if k.strip()]

GROQ_API_KEYS = _split_keys("GROQ_API_KEYS")
OPENAI_API_KEYS = _split_keys("OPENAI_API_KEYS")
ANTHROPIC_API_KEYS = _split_keys("ANTHROPIC_API_KEYS")
DEEPSEEK_API_KEYS = _split_keys("DEEPSEEK_API_KEYS")

# Tavily — AI-agentlar uchun maxsus qidiruv API'si (search_web tool uchun,
# core/ai_tools.py). IXTIYORIY: berilmasa, search_web avtomatik DuckDuckGo/
# Bing scraping'ga tushadi (kamroq ishonchli, lekin kalitsiz ham ishlaydi).
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")

ENCRYPTION_KEY = os.environ["ENCRYPTION_KEY"]  # Fernet.generate_key() bilan yarating

# ── Userbot (Telethon, FAQAT O'QISH) — core/userbot.py. IXTIYORIY: uchalasi berilmasa funksiya o'chiq.
# Session'ni gen_userbot_session.py bilan oling; ENV'dan boshqa joyga (DB, repo) QO'YMANG.
# DIQQAT: shu session boshqa joyda (boshqa userbot) bir vaqtda ishlatilsa Telegram uni bekor qiladi.
USERBOT_API_ID = int(os.environ.get("USERBOT_API_ID") or 0)
USERBOT_API_HASH = os.environ.get("USERBOT_API_HASH", "")
USERBOT_SESSION = os.environ.get("USERBOT_SESSION", "")
# "all" — hamma foydalanuvchi so'ray oladi (soatiga USERBOT_RATE_PER_HOUR limit bilan); "admins" — faqat adminlar
USERBOT_ACCESS = os.environ.get("USERBOT_ACCESS", "all").strip().lower()
if USERBOT_ACCESS not in ("all", "admins"):
    USERBOT_ACCESS = "admins"  # noto'g'ri qiymatda xavfsizroq tomonga
USERBOT_RATE_PER_HOUR = int(os.environ.get("USERBOT_RATE_PER_HOUR", 15))
