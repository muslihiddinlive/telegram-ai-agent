"""
Noma'lum/xato yozilgan komandalar — ai_chat'dan OLDIN (main.py'da), hamma haqiqiy komanda handler'laridan KEYIN.
Mantiq core/command_guard.py da.
"""
from aiogram import Router, F
from aiogram.types import Message

import core.command_guard as command_guard

router = Router()


@router.message(F.text.startswith("/"))
async def guard(message: Message):
    if message.from_user is None:
        return
    verdict = command_guard.classify(message.text, message.from_user.id, message.chat.type)
    if verdict is None:
        from aiogram.dispatcher.event.bases import SkipHandler
        raise SkipHandler  # bu komanda bizniki emas/oddiy xabar — keyingi handler'ga (ai_chat) o'tsin
    kind, extra = verdict
    if kind == "foreign":
        return  # boshqa botga mo'ljallangan — jim, AI'ga ham bormasin
    parsed = command_guard.parse(message.text)
    await message.reply(command_guard.reply_text(kind, parsed[0], extra))
