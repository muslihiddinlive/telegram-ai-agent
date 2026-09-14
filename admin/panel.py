"""
Boshqaruv paneli — StokerDownloader patternidan, lekin sizning ierarxiyangizga
moslashtirilgan:
  - superadmin: "Adminlar" + "Foydalanuvchilar" ikkalasini ham ko'radi/boshqaradi
  - admin: FAQAT "Foydalanuvchilar"ni ko'radi — "Adminlar" bo'limi umuman
    ko'rsatilmaydi (superadmin identligi/adminlar ro'yxati adminlardan yashirin)
"""
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command

import core.tgdb as tgdb
import core.roles as roles
import core.pending_input as pending_input

router = Router()


def main_menu_kb(user_id: int) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="👤 Foydalanuvchilar", callback_data="panel:users:0")]]
    if roles.is_superadmin(user_id):
        rows.append([InlineKeyboardButton(text="🛡 Adminlar", callback_data="panel:admins:0")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("panel"))
async def open_panel(message: Message):
    if not (roles.is_superadmin(message.from_user.id) or roles.is_admin(message.from_user.id)):
        return  # oddiy/tasdiqlangan userlar panelni ko'rmaydi
    await message.answer("🛠 Boshqaruv paneli:", reply_markup=main_menu_kb(message.from_user.id))


# ── Foydalanuvchilar (admin + superadmin ikkalasi ham ko'radi) ──

@router.callback_query(F.data.startswith("panel:users:"))
async def show_users(call: CallbackQuery):
    caller = call.from_user.id
    if not (roles.is_superadmin(caller) or roles.is_admin(caller)):
        await call.answer("Ruxsat yo'q", show_alert=True)
        return

    page = int(call.data.split(":")[-1])
    db = tgdb.get()
    user_ids = list(db["users"].keys())
    page_size = 10
    chunk = user_ids[page * page_size:(page + 1) * page_size]

    def label(uid: str) -> str:
        rec = db["users"][uid]
        icon = "✅" if rec.get("role") == "approved" else "⏳"
        return f"{icon} {rec.get('name') or uid}"

    buttons = [
        [InlineKeyboardButton(text=label(uid), callback_data=f"panel:user_detail:{uid}")]
        for uid in chunk
    ]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"panel:users:{page-1}"))
    if (page + 1) * page_size < len(user_ids):
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"panel:users:{page+1}"))
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton(text="🔙 Menyu", callback_data="panel:main")])

    await call.message.edit_text(
        f"Foydalanuvchilar ({len(user_ids)} ta):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(F.data.startswith("panel:user_detail:"))
async def user_detail(call: CallbackQuery):
    caller = call.from_user.id
    if not (roles.is_superadmin(caller) or roles.is_admin(caller)):
        await call.answer("Ruxsat yo'q", show_alert=True)
        return

    uid = call.data.split(":")[-1]
    db = tgdb.get()
    rec = db["users"].get(uid, {})
    role = "✅ Tasdiqlangan" if rec.get("role") == "approved" else "⏳ Kutilmoqda"
    text = (
        f"👤 {rec.get('name') or uid} (ID: <code>{uid}</code>)\n"
        f"Holat: {role}\n"
        f"Kunlik limit: {rec.get('daily_limit')}\n"
        f"Bugun ishlatilgan: {rec.get('requests_today', 0)}"
    )

    kb_rows = []
    if rec.get("role") == "approved":
        kb_rows.append([InlineKeyboardButton(text="✏️ Limitni o'zgartirish", callback_data=f"panel:setlimit:{uid}")])
        # Faqat superadmin ISTALGAN vaqt bekor qila oladi (kim tasdiqlaganidan qat'iy nazar)
        if roles.is_superadmin(caller):
            kb_rows.append([InlineKeyboardButton(text="🚫 Ruxsatni bekor qilish", callback_data=f"panel:revoke:{uid}")])
    else:
        kb_rows.append([InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"panel:approve:{uid}")])
    kb_rows.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="panel:users:0")])

    await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))


@router.callback_query(F.data.startswith("panel:approve:"))
async def approve_user_cb(call: CallbackQuery, bot: Bot):
    caller = call.from_user.id
    if not (roles.is_superadmin(caller) or roles.is_admin(caller)):
        await call.answer("Ruxsat yo'q", show_alert=True)
        return
    uid = int(call.data.split(":")[-1])
    await roles.approve_user(bot, uid, approved_by=caller)
    await call.answer("Tasdiqlandi ✅")
    try:
        await bot.send_message(uid, "✅ So'rovingiz tasdiqlandi! Endi botdan foydalanishingiz mumkin.")
    except Exception:
        pass


@router.callback_query(F.data.startswith("panel:revoke:"))
async def revoke_user_cb(call: CallbackQuery, bot: Bot):
    if not roles.is_superadmin(call.from_user.id):
        await call.answer("Faqat superadmin bekor qila oladi", show_alert=True)
        return
    uid = int(call.data.split(":")[-1])
    await roles.revoke_user(bot, uid)
    await call.answer("Ruxsat bekor qilindi 🚫")


@router.callback_query(F.data.startswith("panel:setlimit:"))
async def set_limit_start(call: CallbackQuery):
    caller = call.from_user.id
    if not (roles.is_superadmin(caller) or roles.is_admin(caller)):
        await call.answer("Ruxsat yo'q", show_alert=True)
        return
    uid = call.data.split(":")[-1]
    pending_input.set(caller, "set_user_limit", {"target_uid": uid})
    await call.message.answer(f"Foydalanuvchi {uid} uchun yangi kunlik limitni yuboring (raqam):")
    await call.answer()


# ── Adminlar (FAQAT superadmin ko'radi) ──

@router.callback_query(F.data.startswith("panel:admins:"))
async def show_admins(call: CallbackQuery):
    if not roles.is_superadmin(call.from_user.id):
        await call.answer("Ruxsat yo'q", show_alert=True)
        return
    admins = roles.list_admins()
    lines = [f"🛡 {info.get('name') or uid} (ID: {uid})" for uid, info in admins.items()] or ["Hozircha admin yo'q."]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Admin qo'shish", callback_data="panel:add_admin")],
        [InlineKeyboardButton(text="🔙 Menyu", callback_data="panel:main")],
    ])
    await call.message.edit_text("\n".join(lines), reply_markup=kb)


@router.callback_query(F.data == "panel:add_admin")
async def add_admin_start(call: CallbackQuery):
    if not roles.is_superadmin(call.from_user.id):
        await call.answer("Ruxsat yo'q", show_alert=True)
        return
    pending_input.set(call.from_user.id, "add_admin_wait_id")
    await call.message.answer("Yangi admin qilinadigan foydalanuvchi ID'sini yuboring:")
    await call.answer()


@router.callback_query(F.data == "panel:main")
async def back_to_main(call: CallbackQuery):
    await call.message.edit_text("🛠 Boshqaruv paneli:", reply_markup=main_menu_kb(call.from_user.id))
