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

# MUHIM: imkoniyatlar bloki IDENTIFIKATSIYADAN ALOHIDA — har doim, superadmin qanday shaxsiyat o'rnatgan bo'lishidan qat'iy nazar, HAR BIR suhbatga
# qo'shiladi (get_full_system_prompt()). Matn core/capabilities.py da (yagona manba; testlar uni har bir tool bilan solishtiradi).
from core.capabilities import STATIC_BLOCK as CAPABILITIES_BLOCK  # noqa: E402


def get_system_prompt() -> str:
    db = tgdb.get()
    return db.get("settings", {}).get("system_prompt") or DEFAULT_SYSTEM_PROMPT


OWNER_IDENTITY_BLOCK = (
    "Sizning nomingiz Paradoks AI. Botning egasi @ParadoksHub Telegram kanalining va Paradoks Hub "
    "community'sining asoschisi — shuning uchun sizga shu nom berilgan. Botning egasini (superadmin) "
    "har doim \"aka\" deb chaqiring (masalan \"Tushundim, aka\"), boshqa foydalanuvchilarni esa odatdagidek "
    "muloyim, hurmatli ohangda."
)


def get_full_system_prompt() -> str:
    """Identifikatsiya + egasi haqida + imkoniyatlar — handlers/ai_chat.py shuni ishlatadi."""
    return f"{get_system_prompt()}\n\n{OWNER_IDENTITY_BLOCK}\n\n{CAPABILITIES_BLOCK}"


async def set_system_prompt(bot, text: str):
    db = tgdb.get()
    db.setdefault("settings", {})["system_prompt"] = text
    await tgdb.save(bot, force=True)


async def reset_system_prompt(bot):
    db = tgdb.get()
    db.setdefault("settings", {}).pop("system_prompt", None)
    await tgdb.save(bot, force=True)
