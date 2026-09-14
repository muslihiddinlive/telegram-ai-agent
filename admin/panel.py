"""
Superadmin panel — StokerDownloader/sticker_bot_webhook.py patternidan
(8000+ qatorli production bot, 283 funksiya, panel atrofida qurilgan).

Bu yerda soddalashtirilgan skelet: asosiy menyu + foydalanuvchilar/kanallar
ro'yxati + drill-down. StokerDownloader'dagi kabi to'liq bosqichma-bosqich
(FSM) limit/premium berish logikasi TODO sifatida qoldirilgan — kengaytirish
kerak bo'lsa aynan o'sha repoga qarang.
"""
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command

import config
import core.tgdb as tgdb

router = Router()


def _is_superadmin(user_id: int) -> bool:
    return user_id == config.SUPERADMIN_ID


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Foydalanuvchilar", callback_data="panel:users:0")],
        [InlineKeyboardButton(text="📢 Kanallar", callback_data="panel:channels:0")],
        [InlineKeyboardButton(text="📊 Statistika", callback_data="panel:stats")],
    ])


@router.message(Command("panel"))
async def open_panel(message, bot: Bot):
    if not _is_superadmin(message.from_user.id):
        return
    await message.answer("🛠 Superadmin panel:", reply_markup=main_menu_kb())


@router.callback_query(F.data.startswith("panel:users:"))
async def show_users(call: CallbackQuery):
    if not _is_superadmin(call.from_user.id):
        await call.answer("Ruxsat yo'q", show_alert=True)
        return

    page = int(call.data.split(":")[-1])
    db = tgdb.get()
    user_ids = list(db["users"].keys())
    page_size = 10
    chunk = user_ids[page * page_size:(page + 1) * page_size]

    buttons = [
        [InlineKeyboardButton(text=f"👤 {uid}", callback_data=f"panel:user_detail:{uid}")]
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
    if not _is_superadmin(call.from_user.id):
        await call.answer("Ruxsat yo'q", show_alert=True)
        return
    uid = call.data.split(":")[-1]
    db = tgdb.get()
    info = db["users"].get(uid, {})
    text = f"👤 User {uid}\n" + "\n".join(f"{k}: {v}" for k, v in info.items())
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Tasdiqlash (approve)", callback_data=f"panel:approve:{uid}")],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="panel:users:0")],
    ])
    await call.message.edit_text(text or "Ma'lumot yo'q", reply_markup=kb)


@router.callback_query(F.data.startswith("panel:approve:"))
async def approve_user(call: CallbackQuery, bot: Bot):
    if not _is_superadmin(call.from_user.id):
        await call.answer("Ruxsat yo'q", show_alert=True)
        return
    uid = call.data.split(":")[-1]
    db = tgdb.get()
    db["users"].setdefault(uid, {})["approved"] = True
    await tgdb.save(bot, force=True)  # kritik amal — darhol yoziladi (StokerDownloader patterni)
    await call.answer("Tasdiqlandi ✅")


@router.callback_query(F.data == "panel:main")
async def back_to_main(call: CallbackQuery):
    await call.message.edit_text("🛠 Superadmin panel:", reply_markup=main_menu_kb())

# TODO: panel:channels:*, panel:stats — StokerDownloader'dagi tegishli
# bo'limlarga qarab xuddi shu naqshda qo'shing.
