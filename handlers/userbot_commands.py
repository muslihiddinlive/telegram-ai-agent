"""
Userbot ulash + kalit-so'z auto-reply boshqaruv komandalari.
"""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

import core.pending_input as pending_input
import core.userbot_login as userbot_login
import core.auto_reply as auto_reply

router = Router()


@router.message(Command("userbot"))
async def userbot_start(message: Message):
    pending_input.set(message.from_user.id, "userbot_wait_api_id")
    await message.answer(
        "Userbot ulash uchun https://my.telegram.org dan API ID va API HASH oling.\n\n"
        "Avval <b>API ID</b>ni yuboring (faqat raqam):"
    )


@router.message(Command("kalitsoz_qoshish"))
async def keyword_add_start(message: Message):
    pending_input.set(message.from_user.id, "keyword_wait_trigger")
    await message.answer("Qaysi so'zga javob berilsin? (masalan: salom)")


@router.message(Command("kalitsozlar"))
async def keyword_list(message: Message):
    kws = auto_reply.get_keywords(message.from_user.id)
    if not kws:
        await message.answer("Hali kalit-so'z qo'shilmagan. /kalitsoz_qoshish bilan qo'shing.")
        return
    lines = [f"#{k['id']}: \"{k['trigger']}\" → {k['response']}" for k in kws]
    await message.answer("🔑 Kalit-so'zlaringiz:\n" + "\n".join(lines))


@router.message(Command("away"))
async def set_away(message: Message):
    pending_input.set(message.from_user.id, "away_wait_seconds")
    current = auto_reply.get_away_delay(message.from_user.id)
    await message.answer(
        f"Hozirgi 'band' vaqti: {current} soniya.\n"
        f"Necha soniyadan keyin avto-javob ishga tushsin? (masalan: 300)"
    )
