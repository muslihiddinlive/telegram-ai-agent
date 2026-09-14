"""
Foydalanuvchi shaxsiy chatda o'zi Telegram interfeysidan (📎 yonidagi yoki
chat sarlavhasidan) ham topic ochishi mumkin (agar BotFather'da ruxsat
berilgan bo'lsa) — u holda bot buni oddiy xabar sifatida qabul qiladi va
core/topic_sessions.py o'sha thread_id uchun avtomatik yangi sessiya ochadi.

Bu yerda qo'shimcha ravishda BOT orqali ham topic yaratish komandasi bor —
masalan foydalanuvchi tugma/AI orqali "yangi mavzu och" desa ham ishlaydi.
"""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

import core.topic_sessions as topic_sessions
import core.roles as roles

router = Router()


@router.message(Command("yangi_mavzu"))
async def new_topic(message: Message):
    """/yangi_mavzu <nom> — bot nomidan yangi topic yaratadi (Bot API 9.4)."""
    if not roles.can_use_bot(message.from_user.id):
        return
    name = message.text.replace("/yangi_mavzu", "", 1).strip() or "Yangi mavzu"
    try:
        thread_id = await topic_sessions.create_topic(message.bot, message.from_user.id, name)
        await message.answer(
            f"✅ \"{name}\" nomli yangi mavzu ochildi. Shu yerga yozgan xabarlaringiz "
            f"boshqa mavzulardan mustaqil suhbat sifatida saqlanadi.",
            message_thread_id=thread_id,
        )
    except Exception as e:
        await message.answer(
            "⚠️ Topic yarata olmadim — BotFather'da botingiz uchun "
            "\"Private Chat Topics\" yoqilganiga ishonch hosil qiling.\n"
            f"Xato: {e}"
        )


@router.message(Command("mavzular"))
async def list_topics(message: Message):
    """/mavzular — foydalanuvchining barcha ochiq mavzulari ro'yxati."""
    if not roles.can_use_bot(message.from_user.id):
        return
    topics = await topic_sessions.list_topics(message.from_user.id)
    if not topics:
        await message.answer("Hozircha alohida mavzular yo'q. /yangi_mavzu <nom> bilan oching.")
        return
    lines = [f"• {info.get('title') or tid} — {len(info['history'])} ta xabar" for tid, info in topics.items()]
    await message.answer("🗂 Sizning mavzularingiz:\n" + "\n".join(lines))
