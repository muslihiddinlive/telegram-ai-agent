"""
AI'ning "shaxsiyati" (system prompt) — FAQAT superadmin tomonidan
belgilanadi (/panel -> 🎭 AI shaxsiyati). Bu matn HAR BIR suhbatga
(barcha foydalanuvchilar, barcha topic'lar uchun) avtomatik qo'shiladi —
AI o'zini kim deb tanishtirishi, qaysi community/kanalga tegishli
ekanini shu orqali "biladi".
"""
import core.tgdb as tgdb

DEFAULT_SYSTEM_PROMPT = (
    "Siz foydalanuvchilarga yordam beradigan AI agentisiz. Savollarga aniq, "
    "foydali va samimiy javob bering."
)


def get_system_prompt() -> str:
    db = tgdb.get()
    return db.get("settings", {}).get("system_prompt") or DEFAULT_SYSTEM_PROMPT


async def set_system_prompt(bot, text: str):
    db = tgdb.get()
    db.setdefault("settings", {})["system_prompt"] = text
    await tgdb.save(bot, force=True)


async def reset_system_prompt(bot):
    db = tgdb.get()
    db.setdefault("settings", {}).pop("system_prompt", None)
    await tgdb.save(bot, force=True)
