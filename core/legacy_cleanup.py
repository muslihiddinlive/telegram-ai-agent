"""
Userbot funksiyasi butunlay olib tashlandi — uning DB'da qolgan ma'lumotlarini tozalaydi.

NEGA KERAK: eski userbot Telegram SESSION STRING'ini (hisobga to'liq kirish huquqi) shifrlab
db["ai_sessions"][user_id] ichida saqlagan edi. Kod o'chirilsa ham bu ma'lumot DB'da qolib ketardi.
Faqat userbot kalitlari o'chiriladi; foydalanuvchilarning shaxsiy AI API kalitlariga (/apikalit) TEGILMAYDI.

Ishga tushganda har safar chaqiriladi; tozalanadigan narsa qolmagan bo'lsa hech narsa qilmaydi.
"""
import logging

import core.tgdb as tgdb

logger = logging.getLogger("legacy_cleanup")

_USERBOT_SECRET_KEYS = ("telegram_session", "api_id", "api_hash")


async def purge_userbot_data(bot) -> int:
    """O'chirilgan yozuvlar sonini qaytaradi."""
    db = tgdb.get()
    removed = 0
    for secrets in db.get("ai_sessions", {}).values():
        for key in _USERBOT_SECRET_KEYS:
            if key in secrets:
                del secrets[key]
                removed += 1
    if db.pop("auto_reply", None) is not None:  # userbot auto-reply (kalit-so'z / away) qoidalari
        removed += 1
    if removed:
        await tgdb.save(bot, force=True)
        logger.info("Eski userbot ma'lumotlari tozalandi: %s ta yozuv", removed)
    return removed
