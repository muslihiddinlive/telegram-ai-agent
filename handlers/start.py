from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

import core.tgdb as tgdb

router = Router()


@router.message(CommandStart())
async def start(message: Message):
    db = tgdb.get()
    uid = str(message.from_user.id)
    if uid not in db["users"]:
        db["users"][uid] = {"approved": False, "name": message.from_user.full_name}
        await tgdb.save(message.bot)

    await message.answer(
        "Salom! Men sizning shaxsiy AI agentingizman.\n"
        "Menga xabar yozing — kerak bo'lsa fayl yarataman, kanalga post qilaman "
        "yoki eslatma saqlab qo'yaman."
    )
