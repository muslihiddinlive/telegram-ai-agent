"""
Guruh ichida bot javobini cheklash komandalari — bularni FAQAT o'sha
GURUHNING Telegram-admini/egasi ishlatishi mumkin (bizning superadmin/admin
tizimimizdan mustaqil — bu guruhga xos, Telegram darajasidagi tekshiruv).
"""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

import core.group_permissions as group_permissions
import core.chat_mode as chat_mode

router = Router()


async def _is_group_admin(message: Message) -> bool:
    if message.chat.type not in ("group", "supergroup"):
        return False
    member = await message.bot.get_chat_member(message.chat.id, message.from_user.id)
    return member.status in ("creator", "administrator")


@router.message(F.text.regexp(r"(?i)^/chatmode\b"), F.chat.type.in_({"group", "supergroup"}))
async def toggle_chat_mode(message: Message):
    """
    /chatmode on  — bot HAR BIR xabarga (tag/reply shart emas) javob beradi;
                    so'rovlar shu komandani yozgan admin hisobidan ketadi.
    /chatmode off — standart holatga qaytadi (faqat tag/reply'ga javob beradi).
    /chatmode     — joriy holatni ko'rsatadi.
    """
    if not await _is_group_admin(message):
        await message.reply("⚠️ Bu komandani faqat guruh admin/egasi ishlata oladi.")
        return

    parts = message.text.split(None, 1)
    arg = parts[1].strip().lower().lstrip(":").strip() if len(parts) > 1 else ""

    if arg == "on":
        await chat_mode.enable(message.bot, message.chat.id, owner_id=message.from_user.id)
        await message.reply(
            "✅ Chat rejimi YOQILDI — bot endi HAR BIR xabarga (tag/reply shart emas) javob beradi.\n"
            "So'rovlar sizning (shu komandani yozgan) hisobingizdan hisoblanadi.\n\n"
            "O'chirish: <code>/chatmode off</code>"
        )
    elif arg == "off":
        await chat_mode.disable(message.bot, message.chat.id)
        await message.reply("✅ Chat rejimi O'CHIRILDI — bot endi yana faqat tag/reply qilinganda javob beradi.")
    else:
        current = chat_mode.get(message.chat.id)
        status = "YOQILGAN ✅" if current else "O'CHIRILGAN ⛔"
        await message.reply(
            f"Joriy holat: {status}\n\n"
            f"Yoqish: <code>/chatmode on</code>\nO'chirish: <code>/chatmode off</code>"
        )


@router.message(Command("guruh_ruxsat"), F.chat.type.in_({"group", "supergroup"}))
async def set_group_allowlist(message: Message):
    """/guruh_ruxsat @user1 @user2 @user3 — bot FAQAT shularga javob beradi."""
    if not await _is_group_admin(message):
        await message.reply("⚠️ Bu komandani faqat guruh admin/egasi ishlata oladi.")
        return

    usernames = [w for w in message.text.split() if w.startswith("@")]
    if not usernames:
        await message.reply(
            "Foydalanish: <code>/guruh_ruxsat @user1 @user2 @user3</code>\n"
            "Shundan keyin bot FAQAT shu foydalanuvchilarga javob beradi."
        )
        return

    await group_permissions.set_allowed_responders(
        message.bot, message.chat.id, usernames, set_by=message.from_user.id
    )
    await message.reply(
        f"✅ Endi bu guruhda bot FAQAT quyidagilarga javob beradi:\n"
        f"{', '.join(usernames)}\n\n"
        f"Bekor qilish uchun: /guruh_ruxsat_ochirish"
    )


@router.message(Command("guruh_ruxsat_ochirish"), F.chat.type.in_({"group", "supergroup"}))
async def clear_group_allowlist(message: Message):
    if not await _is_group_admin(message):
        await message.reply("⚠️ Bu komandani faqat guruh admin/egasi ishlata oladi.")
        return
    await group_permissions.clear_allowed_responders(message.bot, message.chat.id)
    await message.reply("✅ Cheklov olib tashlandi — bot endi barcha ruxsat berilgan foydalanuvchilarga javob beradi.")
