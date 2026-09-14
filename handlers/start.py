"""
/start — yangi foydalanuvchini "pending" sifatida ro'yxatga oladi va
superadmin + barcha adminlarga tasdiqlash so'rovini tugma bilan yuboradi.
"""
from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

import config
import core.tgdb as tgdb
import core.roles as roles

router = Router()


@router.message(CommandStart())
async def start(message: Message):
    user_id = message.from_user.id
    db = tgdb.get()
    uid = str(user_id)

    is_new = uid not in db["users"]
    if is_new:
        db["users"][uid] = {
            "role": "pending",
            "approved_by": None,
            "daily_limit": roles.DEFAULT_DAILY_LIMIT,
            "requests_today": 0,
            "last_reset": roles.today_str(),
            "name": message.from_user.full_name,
        }
        await tgdb.save(message.bot, force=True)

    role = roles.get_role(user_id)

    if role == "pending":
        await message.answer(
            "👋 Salom! Sizning so'rovingiz ko'rib chiqilmoqda — admin tasdiqlagach "
            "botdan foydalana olasiz."
        )
        if is_new:
            await _notify_approvers(message)
    else:
        await message.answer(
            "Salom! Men sizning shaxsiy AI agentingizman.\n"
            "Menga xabar yozing — kerak bo'lsa fayl yarataman, kanalga post qilaman "
            "yoki eslatma saqlab qo'yaman."
        )


async def _notify_approvers(message: Message):
    """Superadmin + barcha adminlarga yangi so'rov haqida xabar yuboradi."""
    user_id = message.from_user.id
    text = (
        f"🆕 Yangi foydalanuvchi so'rovi:\n"
        f"👤 {message.from_user.full_name} (ID: <code>{user_id}</code>)"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"panel:approve:{user_id}")],
    ])

    recipients = [config.SUPERADMIN_ID] + [int(uid) for uid in roles.list_admins()]
    for admin_id in set(recipients):
        try:
            await message.bot.send_message(admin_id, text, reply_markup=kb)
        except Exception:
            pass  # admin botni bloklagan bo'lishi mumkin
