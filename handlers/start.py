"""
/start — yangi foydalanuvchini avtomatik ro'yxatga oladi (admin tasdig'i KERAK EMAS)
va darrov botdan foydalanishga ruxsat beradi. Faqat superadmin bloklagan userlar
(role="blocked") kira olmaydi.
"""
from aiogram import Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

import core.tgdb as tgdb
import core.roles as roles
import core.tariffs as tariffs
from handlers.tariff import send_plans

router = Router()


@router.message(CommandStart())
async def start(message: Message, command: CommandObject):
    user_id = message.from_user.id
    db = tgdb.get()
    uid = str(user_id)

    if uid not in db["users"]:
        db["users"][uid] = {
            "role": "approved",
            "approved_by": "auto",
            "daily_limit": roles.DEFAULT_DAILY_LIMIT,
            "requests_today": 0,
            "last_reset": roles.today_str(),
            "name": message.from_user.full_name,
            "username": message.from_user.username,
        }
        await tgdb.save(message.bot, force=True)

    if roles.get_role(user_id) == "blocked":
        await message.answer("🚫 Sizga botdan foydalanish cheklangan.")
        return

    if (command.args or "").strip() == tariffs.PLANS_DEEPLINK and message.chat.type == "private":
        await send_plans(message)  # guruhdagi "💳 Tariflar" tugmasidan keldi (deep-link)
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Profil boshqaruvi", callback_data="profile:menu")],
        [InlineKeyboardButton(text=tariffs.PLANS_BUTTON_TEXT, callback_data=tariffs.PLANS_CALLBACK)],
        [InlineKeyboardButton(text="🔑 AI API integratsiya", callback_data="apikey:menu")],
    ])
    await message.answer(
        "Salom! Men sizning shaxsiy AI agentingizman.\n"
        "Menga xabar yozing — kerak bo'lsa fayl yarataman, kanalga post qilaman "
        "yoki eslatma saqlab qo'yaman.\n\n"
        "Xohlasangiz, o'zingizning AI API kalitingizni ulab, botni cheksiz "
        "ishlatishingiz mumkin:",
        reply_markup=kb,
    )
