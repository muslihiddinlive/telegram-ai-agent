"""
Dinamik kanal aniqlash + admin-based ruxsat — KanalKotibRobot patternidan.

- Bot biror kanal/guruhga admin qilib qo'shilganda (my_chat_member update),
  o'sha kanal avtomatik DB'ga ro'yxatga olinadi — .env'da qo'lda yozish shart emas.
- Foydalanuvchi faqat O'ZI admin bo'lgan kanallarga amal (post, va h.k.) qila oladi —
  bu get_chat_member orqali tekshiriladi.
"""
from aiogram import Bot
from aiogram.types import ChatMemberUpdated
import core.tgdb as tgdb


async def on_bot_added_to_chat(update: ChatMemberUpdated, bot: Bot):
    """main.py'da my_chat_member handler sifatida ro'yxatdan o'tkaziladi."""
    new_status = update.new_chat_member.status
    db = tgdb.get()
    chat_id = str(update.chat.id)

    if new_status in ("administrator", "member"):
        db["channels"][chat_id] = {
            "title": update.chat.title,
            "added_by": update.from_user.id if update.from_user else None,
            "type": update.chat.type,
        }
    elif new_status in ("left", "kicked"):
        db["channels"].pop(chat_id, None)

    await tgdb.save(bot)


async def user_admin_channels(bot: Bot, user_id: int) -> list[dict]:
    """Foydalanuvchi ADMIN bo'lgan, botga ma'lum kanallar ro'yxati."""
    db = tgdb.get()
    result = []
    for chat_id, info in db["channels"].items():
        try:
            member = await bot.get_chat_member(int(chat_id), user_id)
            if member.status in ("administrator", "creator"):
                result.append({"chat_id": int(chat_id), **info})
        except Exception:
            continue
    return result
