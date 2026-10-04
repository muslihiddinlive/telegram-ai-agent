"""
Guruh ichida bot javobini boshqarish komandalari.
/guruh_ruxsat* — FAQAT o'sha GURUHNING Telegram-admini/egasi.
/chatmode — guruh egasi/adminlari + bot adminlari + superadmin.
/vipchatmode — FAQAT superadmin (cheksiz rejim).
"""
import logging
import re

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

import core.group_permissions as group_permissions
import core.chat_mode as chat_mode
import core.roles as roles

router = Router()


async def _is_group_admin(message: Message) -> bool:
    if message.chat.type not in ("group", "supergroup"):
        return False
    member = await message.bot.get_chat_member(message.chat.id, message.from_user.id)
    return member.status in ("creator", "administrator")


logger = logging.getLogger("group_settings")
_CHATMODE_RE = re.compile(r"(?is)^/(vip)?chatmode(?:@\w+)?\s*:?\s*(\w*)")


async def _can_manage_chatmode(message: Message) -> bool:
    """
    /chatmode on|off kim qila oladi: guruh egasi/adminlari (Telegram darajasida),
    botning adminlari va superadmin.
    """
    uid = message.from_user.id
    if roles.is_superadmin(uid) or roles.is_admin(uid):
        return True
    return await _is_group_admin(message)


@router.message(F.text.regexp(r"(?i)^/(vip)?chatmode\b"), F.chat.type.in_({"group", "supergroup"}))
async def toggle_chat_mode(message: Message):
    """
    /chatmode on|off|(holat)    — guruh egasi/adminlari, bot adminlari, superadmin.
        Hisob: avval yoqqan odamning limiti -> tugasa yozuvchining o'z limiti.
    /vipchatmode on|off|(holat) — FAQAT superadmin. Shu guruhda CHEKSIZ (hisoblanmaydi).
    """
    m = _CHATMODE_RE.match(message.text or "")
    is_vip_cmd = bool(m and m.group(1))
    arg = (m.group(2) if m else "").lower()
    uid = message.from_user.id
    chat_id = message.chat.id

    # Anonim admin (guruh nomidan yozish) — kim ekani noma'lum, hisob-kitob bo'lmaydi
    if message.sender_chat is not None or message.from_user.is_bot:
        await message.reply("⚠️ Anonim admin rejimida bu komandani ishlatib bo'lmaydi — o'z akkauntingizdan yozing.")
        return

    current = chat_mode.get(chat_id)

    if is_vip_cmd:
        if not roles.is_superadmin(uid):
            # Oddiy a'zoga jim (komanda mavjudligi sir qoladi), LEKIN logga yoziladi. Bot yoki guruh admini bo'lsa — sababi aytiladi
            # (aks holda egasi "komanda ishlamayapti" deb o'ylaydi, aslida akkaunt ID'si SUPERADMIN_ID'ga teng emas).
            logger.warning("/vipchatmode superadmin emas: uid=%s chat=%s", uid, chat_id)
            if roles.is_admin(uid) or await _is_group_admin(message):
                await message.reply(f"👑 /vipchatmode faqat superadmin uchun. Sizning Telegram ID'ingiz: <code>{uid}</code> — "
                                    f"u botning superadmin ID'siga teng emas.")
            return
        if arg == "on":
            await chat_mode.enable(message.bot, chat_id, owner_id=uid, vip=True)
            await message.reply(
                "👑 VIP chat rejimi YOQILDI — bot HAR BIR xabarga javob beradi va bu guruhda "
                "CHEKSIZ: hech kimning limiti tekshirilmaydi va hisoblanmaydi.\n\n"
                "O'chirish: <code>/vipchatmode off</code>"
            )
        elif arg == "off":
            if current and current.get("vip"):
                await chat_mode.disable(message.bot, chat_id)
                await message.reply("✅ VIP chat rejimi O'CHIRILDI.")
            else:
                await message.reply("VIP chat rejimi bu guruhda yoqilmagan.")
        else:
            status = "YOQILGAN 👑" if current and current.get("vip") else "O'CHIRILGAN ⛔"
            await message.reply(
                f"VIP holat: {status}\n\n"
                f"Yoqish: <code>/vipchatmode on</code>\nO'chirish: <code>/vipchatmode off</code>"
            )
        return

    # ── /chatmode (oddiy) ──
    if not await _can_manage_chatmode(message):
        await message.reply("⚠️ Bu komandani faqat guruh egasi/adminlari, bot adminlari yoki superadmin ishlata oladi.")
        return

    # VIP rejimni faqat superadmin o'zgartira oladi
    if current and current.get("vip") and not roles.is_superadmin(uid) and arg in ("on", "off"):
        await message.reply("👑 Bu guruhda VIP chat rejimi yoqilgan — uni faqat superadmin o'zgartira oladi.")
        return

    if arg == "on":
        await chat_mode.enable(message.bot, chat_id, owner_id=uid, vip=False)
        await message.reply(
            "✅ Chat rejimi YOQILDI — bot endi HAR BIR xabarga (tag/reply shart emas) javob beradi.\n"
            "So'rovlar avval sizning (shu komandani yozgan) limitingizdan ketadi; "
            "u tugagach — har bir xabar yozgan odamning o'z limitidan.\n\n"
            "O'chirish: <code>/chatmode off</code>"
        )
    elif arg == "off":
        await chat_mode.disable(message.bot, chat_id)
        await message.reply("✅ Chat rejimi O'CHIRILDI — bot endi yana faqat tag/reply qilinganda javob beradi.")
    else:
        if current and current.get("vip"):
            status = "YOQILGAN (VIP 👑)"
        elif current:
            status = "YOQILGAN ✅"
        else:
            status = "O'CHIRILGAN ⛔"
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
