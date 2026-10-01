"""
Har bir foydalanuvchining shaxsiy AI API-key'ini shifrlangan holda
saqlaydi — userbot-ai/accounts_store.py g'oyasi, lekin endi alohida Telegram
xabarlar o'rniga bitta tgdb.py ichida ("ai_sessions" bo'limida) saqlanadi,
chunki tgdb.py belgi limitidan xoli (fayl sifatida saqlanadi).

Bu orqali: foydalanuvchilar o'z AI API kalitini berib, botni shaxsiy rejimda ishlatishi mumkin.
Telegram session SAQLANMAYDI (userbot olib tashlangan); profilga ulash faqat Telegram Business orqali.
"""
from aiogram import Bot
import core.tgdb as tgdb
from core.crypto_store import encrypt, decrypt


async def save_user_secret(bot: Bot, user_id: int, key: str, value: str):
    """key masalan: 'own_groq_key' va h.k."""
    db = tgdb.get()
    bucket = db["ai_sessions"].setdefault(str(user_id), {})
    bucket[key] = encrypt(value)
    await tgdb.save(bot, force=True)  # kritik ma'lumot — darhol yozamiz, kechiktirmaymiz


def get_user_secret(user_id: int, key: str) -> str | None:
    db = tgdb.get()
    bucket = db["ai_sessions"].get(str(user_id), {})
    enc = bucket.get(key)
    return decrypt(enc) if enc else None


async def remove_user_secret(bot: Bot, user_id: int, key: str):
    db = tgdb.get()
    bucket = db["ai_sessions"].get(str(user_id))
    if bucket and key in bucket:
        del bucket[key]
        await tgdb.save(bot, force=True)
