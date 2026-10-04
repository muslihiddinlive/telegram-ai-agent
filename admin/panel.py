"""
Boshqaruv paneli — StokerDownloader patternidan, lekin sizning ierarxiyangizga
moslashtirilgan:
  - superadmin: "Adminlar" + "Foydalanuvchilar" ikkalasini ham ko'radi/boshqaradi
  - admin: FAQAT "Foydalanuvchilar"ni ko'radi — "Adminlar" bo'limi umuman
    ko'rsatilmaydi (superadmin identligi/adminlar ro'yxati adminlardan yashirin)
"""
import asyncio
import html
import time

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command

import core.bot_commands as bot_commands
import core.tgdb as tgdb
import core.roles as roles
import core.pending_input as pending_input
import core.shared_keys as shared_keys
import core.ai_persona as ai_persona
import core.global_blacklist as global_blacklist
import core.admin_messaging as admin_messaging
import core.tariffs as tariffs

router = Router()


def main_menu_kb(user_id: int) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="👤 Foydalanuvchilar", callback_data="panel:users:0")]]
    if roles.is_superadmin(user_id):
        rows.append([InlineKeyboardButton(text="🛡 Adminlar", callback_data="panel:admins:0")])
        rows.append([InlineKeyboardButton(text="🔑 AI kalitlar", callback_data="panel:keys")])
        rows.append([InlineKeyboardButton(text="🎭 AI shaxsiyati", callback_data="panel:persona")])
        rows.append([InlineKeyboardButton(text="🌐 Global qora ro'yxat", callback_data="panel:qora")])
        rows.append([InlineKeyboardButton(text="📢 Hammaga xabar (broadcast)", callback_data="panel:bc")])
        rows.append([InlineKeyboardButton(text="💳 Tariflar", callback_data="panel:tariffs")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("panel"))
async def open_panel(message: Message):
    if not (roles.is_superadmin(message.from_user.id) or roles.is_admin(message.from_user.id)):
        return  # oddiy/tasdiqlangan userlar panelni ko'rmaydi
    pending_input.clear(message.from_user.id)  # yarim qolgan oqim (xabar yozish, broadcast...) bekor bo'ladi
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
        icon = "🚫" if rec.get("role") == "blocked" else "✅"
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
    buttons.append([InlineKeyboardButton(text="🔍 Qidirish (ID yoki ism)", callback_data="panel:search_users")])
    buttons.append([InlineKeyboardButton(text="📥 CSV yuklab olish", callback_data="panel:export_csv")])
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
    role = "🚫 Bloklangan" if rec.get("role") == "blocked" else "✅ Faol"
    notes_count = len(rec.get("notes", []))
    text = (
        f"👤 {rec.get('name') or uid} (ID: <code>{uid}</code>)\n"
        f"Holat: {role}\n"
        f"Kunlik limit: {rec.get('daily_limit')}\n"
        f"Bugun ishlatilgan: {rec.get('requests_today', 0)}\n"
        f"🧠 Eslab qolingan narsalar: {notes_count} ta\n"
        f"💳 Tarif: {_tariff_line(int(uid)) if uid.lstrip('-').isdigit() else '-'}\n"
        f"📊 {_usage_text(int(uid)) if uid.lstrip('-').isdigit() else '-'}"
    )

    kb_rows = []
    if rec.get("role") != "blocked":
        kb_rows.append([InlineKeyboardButton(text="✏️ Limitni o'zgartirish", callback_data=f"panel:setlimit:{uid}")])
        # Faqat superadmin bloklay oladi
        if roles.is_superadmin(caller):
            kb_rows.append([InlineKeyboardButton(text="🚫 Bloklash", callback_data=f"panel:revoke:{uid}")])
    else:
        kb_rows.append([InlineKeyboardButton(text="✅ Blokdan chiqarish", callback_data=f"panel:approve:{uid}")])
    kb_rows.append([InlineKeyboardButton(text="✉️ Xabar yozish", callback_data=f"panel:msg:{uid}")])
    if roles.is_superadmin(caller):  # tarifni faqat superadmin boshqaradi
        kb_rows.append([
            InlineKeyboardButton(text="🎁 Plus 30 kun", callback_data=f"panel:tgrant:plus:{uid}"),
            InlineKeyboardButton(text="🎁 Pro 30 kun", callback_data=f"panel:tgrant:pro:{uid}"),
        ])
        kb_rows.append([
            InlineKeyboardButton(text="❌ Tarifni bekor qilish", callback_data=f"panel:trevoke:{uid}"),
            InlineKeyboardButton(text="💸 Oxirgi to'lovni qaytarish", callback_data=f"panel:trefund:{uid}"),
        ])
    # Xotira/maxfiylik nazorati — superadmin va admin ikkalasi ham ko'ra oladi
    # (admin va superadmin uchun)
    if notes_count:
        kb_rows.append([InlineKeyboardButton(text="🧠 Xotirani ko'rish", callback_data=f"panel:notes:{uid}")])
    kb_rows.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="panel:users:0")])

    await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))


@router.callback_query(F.data.startswith("panel:notes:"))
async def show_user_notes(call: CallbackQuery):
    caller = call.from_user.id
    if not (roles.is_superadmin(caller) or roles.is_admin(caller)):
        await call.answer("Ruxsat yo'q", show_alert=True)
        return
    uid = call.data.split(":")[-1]
    import core.ai_tools as ai_tools
    notes = ai_tools.get_user_notes(int(uid))

    text = f"🧠 Foydalanuvchi {uid} haqida AI eslab qolgan narsalar:\n\n"
    text += "\n".join(f"{i+1}. {n}" for i, n in enumerate(notes)) if notes else "(bo'sh)"

    kb_rows = []
    if notes:
        kb_rows.append([InlineKeyboardButton(text="🗑 Hammasini tozalash", callback_data=f"panel:notes_clear:{uid}")])
    kb_rows.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data=f"panel:user_detail:{uid}")])

    await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))


@router.callback_query(F.data.startswith("panel:notes_clear:"))
async def clear_user_notes_cb(call: CallbackQuery, bot: Bot):
    caller = call.from_user.id
    if not (roles.is_superadmin(caller) or roles.is_admin(caller)):
        await call.answer("Ruxsat yo'q", show_alert=True)
        return
    uid = call.data.split(":")[-1]
    import core.ai_tools as ai_tools
    await ai_tools.clear_user_notes(bot, int(uid))
    await call.answer("Tozalandi 🗑")
    await user_detail(call)  # tafsilot oynasiga qaytamiz (yangilangan notes_count bilan)


@router.callback_query(F.data.startswith("panel:approve:"))
async def approve_user_cb(call: CallbackQuery, bot: Bot):
    caller = call.from_user.id
    if not (roles.is_superadmin(caller) or roles.is_admin(caller)):
        await call.answer("Ruxsat yo'q", show_alert=True)
        return
    uid = int(call.data.split(":")[-1])
    await roles.approve_user(bot, uid, approved_by=caller)
    await call.answer("Blokdan chiqarildi ✅")
    try:
        await bot.send_message(uid, "✅ Botdan foydalanish qayta ochildi.")
    except Exception:
        pass


@router.callback_query(F.data.startswith("panel:revoke:"))
async def revoke_user_cb(call: CallbackQuery, bot: Bot):
    if not roles.is_superadmin(call.from_user.id):
        await call.answer("Faqat superadmin bloklay oladi", show_alert=True)
        return
    uid = int(call.data.split(":")[-1])
    await roles.revoke_user(bot, uid)
    await call.answer("Bloklandi 🚫")


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


def _usage_text(uid: int) -> str:
    parts = []
    for kind, label in ((tariffs.KIND_FILES, "Fayl"), (tariffs.KIND_VISION, "Rasm")):
        limit = tariffs.quota_limit(uid, kind)
        parts.append(f"{label}: {tariffs.quota_used(uid, kind)}/{'∞' if limit is None else limit}")
    return "Bugun — " + ", ".join(parts)


def _tariff_line(uid: int) -> str:
    cur = tariffs.active_tier(uid)
    if cur.id == "free":
        return "Bepul"
    return f"{cur.name} ({tariffs.days_left(uid)} kun qoldi)"


# ── Tariflar (FAQAT superadmin): statistika + qo'lda berish/bekor qilish/refund ──

@router.callback_query(F.data == "panel:tariffs")
async def show_tariffs(call: CallbackQuery):
    if not roles.is_superadmin(call.from_user.id):
        await call.answer("Faqat superadmin", show_alert=True)
        return
    st = tariffs.stats()
    lines = ["💳 <b>Tariflar</b>\n"]
    for t in tariffs.paid_tiers():
        lines.append(f"{t.name}: {t.stars} ⭐ / {tariffs.DURATION_DAYS} kun, {t.daily_limit} so'rov/kun — "
                     f"faol: <b>{st['active'][t.id]}</b>")
    lines.append(f"\nJami tushum (qaytarilganlarsiz): <b>{st['stars_total']} ⭐</b>, xaridorlar: {st['subscribers']}")
    lines.append("Narx va limitlarni o'zgartirish: pastdagi tarif tugmasi. Foydalanuvchiga berish/bekor qilish/refund: "
                 "Foydalanuvchilar → foydalanuvchi.")
    rows = [[InlineKeyboardButton(text=f"✏️ {t.name}", callback_data=f"panel:tcfg:{t.id}")] for t in tariffs.tiers().values()]
    rows.append([InlineKeyboardButton(text="🔙 Menyu", callback_data="panel:main")])
    await call.message.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


def tariff_config_view(tier_id: str) -> tuple[str, InlineKeyboardMarkup]:
    t = tariffs.tiers()[tier_id]
    over = tariffs._overrides().get(tier_id, {})
    mark = lambda f: " ✱" if f in over else ""  # ✱ — standartdan o'zgartirilgan
    lines = [f"✏️ <b>{t.name}</b> sozlamalari\n"]
    rows = []
    for field, (_, _, paid_only) in tariffs.FIELDS.items():
        if paid_only and tier_id == "free":
            continue
        lines.append(f"{tariffs.FIELD_LABELS[field]}: <b>{getattr(t, field)}</b>{mark(field)}")
        rows.append([InlineKeyboardButton(text=f"✏️ {tariffs.FIELD_LABELS[field]}", callback_data=f"panel:tset:{tier_id}:{field}")])
    if tier_id == "free":
        lines.append("So'rov/kun: har bir foydalanuvchi uchun alohida (Foydalanuvchilar → Limitni o'zgartirish).")
    lines.append("\n✱ — standart qiymatdan o'zgartirilgan. O'zgarish hammaga darhol amal qiladi; mavjud obunachilarning "
                 "muddati va to'lagan narxi o'zgarmaydi.")
    if over:
        rows.append([InlineKeyboardButton(text="↩️ Standartga qaytarish", callback_data=f"panel:treset:{tier_id}")])
    rows.append([InlineKeyboardButton(text="🔙 Tariflar", callback_data="panel:tariffs")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data.startswith("panel:tcfg:"))
async def tariff_config_open(call: CallbackQuery):
    if not roles.is_superadmin(call.from_user.id):
        await call.answer("Faqat superadmin", show_alert=True)
        return
    tier_id = call.data.split(":")[-1]
    if tier_id not in tariffs.tiers():
        await call.answer("Bunday tarif yo'q", show_alert=True)
        return
    text, kb = tariff_config_view(tier_id)
    await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data.startswith("panel:tset:"))
async def tariff_config_ask(call: CallbackQuery):
    caller = call.from_user.id
    if not roles.is_superadmin(caller):
        await call.answer("Faqat superadmin", show_alert=True)
        return
    _, _, tier_id, field = call.data.split(":")
    _, err = tariffs.validate_value(tier_id, field, "1")  # tarif/maydon mosligini tekshiradi (qiymatni emas)
    if err and "son" not in err and "gacha" not in err:
        await call.answer(err, show_alert=True)
        return
    lo, hi, _ = tariffs.FIELDS[field]
    pending_input.set(caller, "tariff_value", {"tier": tier_id, "field": field})
    await call.message.answer(f"✏️ {tariffs.tiers()[tier_id].name} — <b>{tariffs.FIELD_LABELS[field]}</b>: yangi qiymatni "
                              f"yozing ({lo}–{hi}). Bekor qilish: /panel")
    await call.answer()


@router.callback_query(F.data.startswith("panel:treset:"))
async def tariff_config_reset(call: CallbackQuery, bot: Bot):
    if not roles.is_superadmin(call.from_user.id):
        await call.answer("Faqat superadmin", show_alert=True)
        return
    tier_id = call.data.split(":")[-1]
    if tier_id not in tariffs.tiers():
        await call.answer("Bunday tarif yo'q", show_alert=True)
        return
    await tariffs.reset_config(bot, tier_id)
    text, kb = tariff_config_view(tier_id)
    await call.message.edit_text(text, reply_markup=kb)
    await call.answer("↩️ Standart qiymatlar tiklandi")


@router.callback_query(F.data.startswith("panel:tgrant:"))
async def tariff_grant_cb(call: CallbackQuery, bot: Bot):
    if not roles.is_superadmin(call.from_user.id):
        await call.answer("Faqat superadmin", show_alert=True)
        return
    _, _, tier_id, uid = call.data.split(":")
    if tier_id not in ("plus", "pro") or not uid.lstrip("-").isdigit():
        await call.answer("Noto'g'ri so'rov", show_alert=True)
        return
    await tariffs.grant(bot, int(uid), tier_id)
    await call.answer(f"✅ {tariffs.tiers()[tier_id].name} 30 kunga berildi", show_alert=True)


@router.callback_query(F.data.startswith("panel:trevoke:"))
async def tariff_revoke_cb(call: CallbackQuery, bot: Bot):
    if not roles.is_superadmin(call.from_user.id):
        await call.answer("Faqat superadmin", show_alert=True)
        return
    uid = call.data.split(":")[-1]
    done = uid.lstrip("-").isdigit() and await tariffs.revoke(bot, int(uid))
    await call.answer("✅ Tarif bekor qilindi" if done else "Faol tarif yo'q", show_alert=True)


@router.callback_query(F.data.startswith("panel:trefund:"))
async def tariff_refund_cb(call: CallbackQuery, bot: Bot):
    """Oxirgi Stars to'lovini Telegram orqali QAYTARADI (refundStarPayment) va tarifni bekor qiladi."""
    if not roles.is_superadmin(call.from_user.id):
        await call.answer("Faqat superadmin", show_alert=True)
        return
    uid = call.data.split(":")[-1]
    charge = tariffs.last_refundable_charge(int(uid)) if uid.lstrip("-").isdigit() else None
    if not charge:
        await call.answer("Qaytariladigan to'lov yo'q", show_alert=True)
        return
    try:
        await bot.refund_star_payment(user_id=int(uid), telegram_payment_charge_id=charge["id"])
    except Exception as e:  # noqa: BLE001
        await call.answer(f"Refund bajarilmadi: {type(e).__name__}", show_alert=True)
        return
    await tariffs.mark_refunded(bot, int(uid), charge["id"])
    try:
        await bot.send_message(int(uid), "💸 To'lovingiz qaytarildi (Stars hisobingizga), tarif bekor qilindi.")
    except Exception:  # noqa: BLE001
        pass
    await call.answer(f"✅ {charge['stars']} ⭐ qaytarildi", show_alert=True)


@router.callback_query(F.data.startswith("panel:msg:"))
async def message_user_start(call: CallbackQuery):
    caller = call.from_user.id
    if not admin_messaging.can_message_user(caller):
        await call.answer("Ruxsat yo'q", show_alert=True)
        return
    uid = call.data.split(":")[-1]
    if not uid.lstrip("-").isdigit():
        await call.answer("Noto'g'ri foydalanuvchi", show_alert=True)
        return
    pending_input.set(caller, "msg_user_text", {"target_uid": int(uid)})
    await call.message.answer(
        f"✉️ {uid} ga yuboriladigan xabar matnini yozing.\n"
        f"Xabar sizning ismingizsiz, \"Admin xabari\" sifatida boradi. Bekor qilish: /panel"
    )
    await call.answer()


# ── Broadcast (FAQAT superadmin): matn → oldindan ko'rish → tasdiqlash → yuborish ──

_bg_tasks: set = set()  # create_task'ni GC yeb qo'ymasligi uchun


@router.callback_query(F.data == "panel:bc")
async def broadcast_start(call: CallbackQuery):
    caller = call.from_user.id
    if not admin_messaging.can_broadcast(caller):
        await call.answer("Faqat superadmin", show_alert=True)
        return
    if admin_messaging.is_broadcast_active():
        await call.answer("Boshqa broadcast hozir ishlayapti", show_alert=True)
        return
    pending_input.set(caller, "broadcast_text")
    count = len(admin_messaging.recipients(caller))
    await call.message.answer(
        f"📢 Hamma foydalanuvchilarga ({count} ta, bloklanmaganlar) yuboriladigan xabar matnini yozing.\n"
        f"Yuborishdan oldin ko'rib, tasdiqlaysiz. Bekor qilish: /panel"
    )
    await call.answer()


async def _run_broadcast(bot: Bot, caller: int, text: str):
    try:
        res = await admin_messaging.broadcast(bot, caller, text)
        if "error" in res:
            report = f"⚠️ {res['error']}"
        else:
            reasons = ", ".join(f"{k}: {v}" for k, v in res["reasons"].items())
            report = (f"📢 Broadcast tugadi.\nYetkazildi: {res['sent']} / {res['total']}"
                      + (f"\nYetkazilmadi: {res['failed']} ({reasons})" if res["failed"] else ""))
    except Exception as e:  # noqa: BLE001
        report = f"⚠️ Broadcast xatolik bilan to'xtadi: {type(e).__name__}"
    try:
        await bot.send_message(caller, report)
    except Exception:  # noqa: BLE001
        pass


@router.callback_query(F.data == "panel:bc_yes")
async def broadcast_confirm(call: CallbackQuery, bot: Bot):
    caller = call.from_user.id
    if not admin_messaging.can_broadcast(caller):
        await call.answer("Faqat superadmin", show_alert=True)
        return
    state = pending_input.get(caller)
    if not state or state["action"] != "broadcast_confirm":
        await call.answer("Muddati o'tgan — qaytadan boshlang", show_alert=True)
        return
    text = state["data"]["text"]
    pending_input.clear(caller)  # ikki marta bosilsa ikki marta yuborilmasin
    task = asyncio.create_task(_run_broadcast(bot, caller, text))
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    await call.message.edit_text("📤 Yuborilmoqda... tugagach hisobot keladi.")
    await call.answer()


@router.callback_query(F.data == "panel:bc_no")
async def broadcast_cancel(call: CallbackQuery):
    pending_input.clear(call.from_user.id)
    await call.message.edit_text("❌ Broadcast bekor qilindi.")
    await call.answer()


def render_search_results(matches: dict) -> InlineKeyboardMarkup:
    if not matches:
        return None
    buttons = [
        [InlineKeyboardButton(
            text=f"{'🚫' if rec.get('role') == 'blocked' else '✅'} {rec.get('name') or uid} (ID: {uid})",
            callback_data=f"panel:user_detail:{uid}",
        )]
        for uid, rec in list(matches.items())[:15]  # ko'p mos kelsa — birinchi 15 tasi
    ]
    buttons.append([InlineKeyboardButton(text="🔙 Menyu", callback_data="panel:main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.callback_query(F.data == "panel:search_users")
async def search_users_start(call: CallbackQuery):
    caller = call.from_user.id
    if not (roles.is_superadmin(caller) or roles.is_admin(caller)):
        await call.answer("Ruxsat yo'q", show_alert=True)
        return
    pending_input.set(caller, "search_users_query")
    await call.message.answer("🔍 Qidirish uchun foydalanuvchi ID'sini yoki ismini (bir qismini) yuboring:")
    await call.answer()


@router.callback_query(F.data == "panel:export_csv")
async def export_csv(call: CallbackQuery, bot: Bot):
    caller = call.from_user.id
    if not (roles.is_superadmin(caller) or roles.is_admin(caller)):
        await call.answer("Ruxsat yo'q", show_alert=True)
        return

    from aiogram.types import BufferedInputFile
    csv_text = roles.build_users_csv()
    doc = BufferedInputFile(csv_text.encode("utf-8-sig"), filename="foydalanuvchilar.csv")
    await bot.send_document(caller, doc, caption="📥 Foydalanuvchilar ro'yxati")
    await call.answer()


# ── AI kalitlar (FAQAT superadmin) — .env O'RNIGA panel orqali boshqariladi ──

@router.callback_query(F.data == "panel:keys")
async def show_key_sections(call: CallbackQuery):
    """AI kalitlar: ikki alohida to'plam — suhbat uchun va rasm o'qish uchun."""
    if not roles.is_superadmin(call.from_user.id):
        await call.answer("Ruxsat yo'q", show_alert=True)
        return
    chat_total = sum(shared_keys.key_count(p) for p in shared_keys.PROVIDERS)
    vis_total = sum(shared_keys.key_count(p, "vision") for p in shared_keys.VISION_PROVIDERS)
    await call.message.edit_text(
        "🔑 <b>AI API kalitlari</b>\n\n"
        "• <b>💬 Chat</b> — oddiy suhbat uchun (avval kiritilgan barcha kalitlar shu yerda).\n"
        "• <b>👁 Rasm o'qish</b> — rasm/videoni «ko'rish» uchun alohida kalitlar. "
        "Ular doim rasm qabul qiladigan modelga yo'naltiriladi (masalan Groq kaliti → Llama 4 vision).\n\n"
        "Ikkala to'plam bir-biriga ta'sir qilmaydi.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"💬 Chat kalitlari ({chat_total})", callback_data="panel:keys_chat")],
            [InlineKeyboardButton(text=f"👁 Rasm o'qish kalitlari ({vis_total})", callback_data="panel:vkeys")],
            [InlineKeyboardButton(text="🔙 Menyu", callback_data="panel:main")],
        ]),
    )


@router.callback_query(F.data == "panel:keys_chat")
async def show_key_providers(call: CallbackQuery):
    if not roles.is_superadmin(call.from_user.id):
        await call.answer("Ruxsat yo'q", show_alert=True)
        return
    rows = []
    for provider in shared_keys.PROVIDERS:
        label = shared_keys.PROVIDER_LABELS[provider]
        count = shared_keys.key_count(provider)
        rows.append([InlineKeyboardButton(text=f"{label} ({count} ta kalit)", callback_data=f"panel:keys_p:{provider}")])
    rows.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="panel:keys")])
    await call.message.edit_text(
        "💬 Chat kalitlari — provayderni tanlang:\n"
        "(Har biriga 1 dan 10 tagacha kalit qo'shish mumkin, Round-Robin ishlaydi)",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data.startswith("panel:keys_p:"))
async def show_provider_keys(call: CallbackQuery):
    if not roles.is_superadmin(call.from_user.id):
        await call.answer("Ruxsat yo'q", show_alert=True)
        return
    provider = call.data.split(":")[-1]
    label = shared_keys.PROVIDER_LABELS[provider]
    keys = shared_keys.list_keys(provider)

    rows = [
        [InlineKeyboardButton(text=f"❌ {shared_keys.masked(k)}", callback_data=f"panel:keys_rm:{provider}:{i}")]
        for i, k in enumerate(keys)
    ]
    if len(keys) < shared_keys.MAX_KEYS_PER_PROVIDER:
        rows.append([InlineKeyboardButton(text="➕ Kalit qo'shish", callback_data=f"panel:keys_add:{provider}")])
    if provider == "xkiro":
        rows.append([InlineKeyboardButton(text="🧠 Modelni o'zgartirish", callback_data="panel:keys_model")])
    rows.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="panel:keys_chat")])

    extra = f"\nJoriy model: <code>{shared_keys.get_xkiro_model()}</code>" if provider == "xkiro" else ""
    text = f"🔑 {label} — {len(keys)}/{shared_keys.MAX_KEYS_PER_PROVIDER} ta kalit{extra}"
    if not keys:
        text += "\n\nHali kalit qo'shilmagan."

    await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("panel:keys_add:"))
async def add_key_start(call: CallbackQuery):
    if not roles.is_superadmin(call.from_user.id):
        await call.answer("Ruxsat yo'q", show_alert=True)
        return
    provider = call.data.split(":")[-1]
    pending_input.set(call.from_user.id, "add_shared_key", {"provider": provider})
    label = shared_keys.PROVIDER_LABELS[provider]
    await call.message.answer(f"{label} uchun yangi API kalitni yuboring:")
    await call.answer()


@router.callback_query(F.data.startswith("panel:keys_rm:"))
async def remove_key_cb(call: CallbackQuery, bot: Bot):
    if not roles.is_superadmin(call.from_user.id):
        await call.answer("Ruxsat yo'q", show_alert=True)
        return
    _, _, provider, index = call.data.split(":")
    await shared_keys.remove_key(bot, provider, int(index))
    await call.answer("O'chirildi 🗑")
    await show_provider_keys(call)  # ro'yxatni yangilab qayta chizamiz


@router.callback_query(F.data == "panel:keys_model")
async def set_model_start(call: CallbackQuery):
    if not roles.is_superadmin(call.from_user.id):
        await call.answer("Ruxsat yo'q", show_alert=True)
        return
    pending_input.set(call.from_user.id, "set_xkiro_model")
    await call.message.answer(
        f"Joriy model: <code>{shared_keys.get_xkiro_model()}</code>\n\n"
        "Yangi model ID'sini yuboring (masalan: <code>qwen/qwen3.8-max:free</code>):"
    )
    await call.answer()


# ── 👁 Rasm o'qish (vision) kalitlari (FAQAT superadmin) ──

def _vision_model_line(provider: str) -> str:
    model = shared_keys.get_vision_model(provider)
    if provider == "groq":
        return (f"Groq kaliti rasm uchun avtomatik <b>vision modeliga</b> yo'naltiriladi: <code>{model}</code>\n"
                "(model eskirsa, zaxira nomzodlarga o'tadi va Groq ro'yxatidan o'zi topadi)")
    if not model:
        return "⚠️ Rasm o'qiy oladigan <b>model tanlanmagan</b> — «🧠 Modelni o'zgartirish»ni bosing."
    return f"Vision modeli: <code>{model}</code>"


@router.callback_query(F.data == "panel:vkeys")
async def show_vision_providers(call: CallbackQuery):
    if not roles.is_superadmin(call.from_user.id):
        await call.answer("Ruxsat yo'q", show_alert=True)
        return
    rows = [
        [InlineKeyboardButton(
            text=f"{shared_keys.PROVIDER_LABELS[p]} ({shared_keys.key_count(p, 'vision')} ta kalit)",
            callback_data=f"panel:vkeys_p:{p}",
        )]
        for p in shared_keys.VISION_PROVIDERS
    ]
    rows.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="panel:keys")])
    await call.message.edit_text(
        "👁 <b>Rasm o'qish kalitlari</b> — provayderni tanlang.\n"
        "Bu kalitlar FAQAT rasm/videoni tushunish uchun ishlatiladi (suhbat kalitlaridan alohida). "
        "DeepSeek'ning rasm API'si yo'q, shuning uchun ro'yxatda yo'q.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data.startswith("panel:vkeys_p:"))
async def show_vision_provider_keys(call: CallbackQuery):
    if not roles.is_superadmin(call.from_user.id):
        await call.answer("Ruxsat yo'q", show_alert=True)
        return
    provider = call.data.split(":")[-1]
    if provider not in shared_keys.VISION_PROVIDERS:
        await call.answer("Noma'lum provayder", show_alert=True)
        return
    label = shared_keys.PROVIDER_LABELS[provider]
    keys = shared_keys.list_keys(provider, "vision")
    rows = [
        [InlineKeyboardButton(text=f"❌ {shared_keys.masked(k)}", callback_data=f"panel:vkeys_rm:{provider}:{i}")]
        for i, k in enumerate(keys)
    ]
    if len(keys) < shared_keys.MAX_KEYS_PER_PROVIDER:
        rows.append([InlineKeyboardButton(text="➕ Kalit qo'shish", callback_data=f"panel:vkeys_add:{provider}")])
    rows.append([InlineKeyboardButton(text="🧠 Modelni o'zgartirish", callback_data=f"panel:vkeys_model:{provider}")])
    rows.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="panel:vkeys")])
    text = f"👁 {label} — {len(keys)}/{shared_keys.MAX_KEYS_PER_PROVIDER} ta rasm kaliti\n\n{_vision_model_line(provider)}"
    if not keys:
        text += "\n\nHali kalit qo'shilmagan."
    await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("panel:vkeys_add:"))
async def add_vision_key_start(call: CallbackQuery):
    if not roles.is_superadmin(call.from_user.id):
        await call.answer("Ruxsat yo'q", show_alert=True)
        return
    provider = call.data.split(":")[-1]
    pending_input.set(call.from_user.id, "add_vision_key", {"provider": provider})
    label = shared_keys.PROVIDER_LABELS[provider]
    await call.message.answer(f"👁 {label} uchun <b>rasm o'qish</b> API kalitini yuboring (kichik test rasm bilan tekshiriladi):")
    await call.answer()


@router.callback_query(F.data.startswith("panel:vkeys_rm:"))
async def remove_vision_key_cb(call: CallbackQuery, bot: Bot):
    if not roles.is_superadmin(call.from_user.id):
        await call.answer("Ruxsat yo'q", show_alert=True)
        return
    _, _, provider, index = call.data.split(":")
    await shared_keys.remove_key(bot, provider, int(index), purpose="vision")
    await call.answer("O'chirildi 🗑")
    await show_vision_provider_keys(call)


@router.callback_query(F.data.startswith("panel:vkeys_model:"))
async def set_vision_model_start(call: CallbackQuery):
    if not roles.is_superadmin(call.from_user.id):
        await call.answer("Ruxsat yo'q", show_alert=True)
        return
    provider = call.data.split(":")[-1]
    pending_input.set(call.from_user.id, "set_vision_model", {"provider": provider})
    cur = shared_keys.get_vision_model(provider) or "(tanlanmagan)"
    await call.message.answer(
        f"Joriy vision modeli: <code>{cur}</code>\n\n"
        f"{shared_keys.PROVIDER_LABELS[provider]} uchun <b>rasm qabul qiladigan</b> model ID'sini yuboring "
        "(masalan Groq: <code>meta-llama/llama-4-scout-17b-16e-instruct</code>):"
    )
    await call.answer()


# ── AI shaxsiyati / system prompt (FAQAT superadmin) ──

@router.callback_query(F.data == "panel:qora")
async def show_global_blacklist(call: CallbackQuery):
    """GLOBAL qora ro'yxat (barcha guruhda ishlaydi) — faqat superadmin ko'radi/boshqaradi."""
    if not roles.is_superadmin(call.from_user.id):
        await call.answer("Ruxsat yo'q", show_alert=True)
        return
    words = global_blacklist.get()
    rows = [
        [InlineKeyboardButton(text=f"❌ {w}", callback_data=f"panel:qora_rm:{i}")]
        for i, w in enumerate(words)
    ]
    if len(words) < global_blacklist.MAX_WORDS:
        rows.append([InlineKeyboardButton(text="➕ So'z qo'shish", callback_data="panel:qora_add")])
    rows.append([InlineKeyboardButton(text="🔙 Menyu", callback_data="panel:main")])
    text = (
        "🌐 <b>Global qora ro'yxat</b> — barcha guruhda birdek ishlaydi, so'z uchrasa xabar o'chiriladi.\n"
        f"Eskalatsiya: {global_blacklist.MUTE_AT}-marta — {global_blacklist.MUTE_MINUTES} daqiqa mute, "
        f"{global_blacklist.BAN_AT}-marta — ban (24 soatlik oyna).\n\n"
        + (f"{len(words)} ta so'z bor." if words else "Hali so'z qo'shilmagan.")
    )
    await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data == "panel:qora_add")
async def global_blacklist_add_start(call: CallbackQuery):
    if not roles.is_superadmin(call.from_user.id):
        await call.answer("Ruxsat yo'q", show_alert=True)
        return
    pending_input.set(call.from_user.id, "add_global_blacklist_word", {})
    await call.message.answer("Qo'shmoqchi bo'lgan so'zni yozing:")
    await call.answer()


@router.callback_query(F.data.startswith("panel:qora_rm:"))
async def global_blacklist_remove_cb(call: CallbackQuery, bot: Bot):
    if not roles.is_superadmin(call.from_user.id):
        await call.answer("Ruxsat yo'q", show_alert=True)
        return
    index = int(call.data.split(":")[-1])
    words = global_blacklist.get()
    if 0 <= index < len(words):
        await global_blacklist.remove(bot, words[index])
        await call.answer("O'chirildi 🗑")
    await show_global_blacklist(call)


@router.callback_query(F.data == "panel:persona")
async def show_persona(call: CallbackQuery):
    if not roles.is_superadmin(call.from_user.id):
        await call.answer("Ruxsat yo'q", show_alert=True)
        return
    current = ai_persona.get_system_prompt()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ O'zgartirish", callback_data="panel:persona_edit")],
        [InlineKeyboardButton(text="↩️ Standartga qaytarish", callback_data="panel:persona_reset")],
        [InlineKeyboardButton(text="🔙 Menyu", callback_data="panel:main")],
    ])
    await call.message.edit_text(
        f"🎭 <b>AI shaxsiyati</b> (system prompt)\n\n"
        f"Bu matn AI'ning HAR BIR suhbatiga (barcha foydalanuvchilar uchun) "
        f"avtomatik qo'shiladi — AI o'zini kim deb tanishtirishini shu belgilaydi.\n\n"
        f"ℹ️ Bu yerga botning imkoniyatlarini (fayl yaratish, prezentatsiya va h.k.) "
        f"yozib o'tirish shart EMAS — ular alohida, avtomatik ravishda har doim "
        f"qo'shiladi. Bu yerda faqat <b>kim ekanligini</b> (ism, community, kanal) "
        f"yozing.\n\n"
        f"<b>Joriy:</b>\n<i>{current}</i>",
        reply_markup=kb,
    )


@router.callback_query(F.data == "panel:persona_edit")
async def persona_edit_start(call: CallbackQuery):
    if not roles.is_superadmin(call.from_user.id):
        await call.answer("Ruxsat yo'q", show_alert=True)
        return
    pending_input.set(call.from_user.id, "set_system_prompt")
    await call.message.answer(
        "Yangi system prompt'ni yuboring. Masalan:\n\n"
        "<i>Sen Paradoks AI san, Paradoks Hub community'ning AI agentisan. "
        "Seni yaratgan community'ning Telegram kanali: @ParadoksHub. "
        "Foydalanuvchilarga shu ruhda, do'stona va foydali javob ber.</i>"
    )
    await call.answer()


@router.callback_query(F.data == "panel:persona_reset")
async def persona_reset_cb(call: CallbackQuery, bot: Bot):
    if not roles.is_superadmin(call.from_user.id):
        await call.answer("Ruxsat yo'q", show_alert=True)
        return
    await ai_persona.reset_system_prompt(bot)
    await call.answer("Standart holatga qaytarildi ✅")
    await show_persona(call)


# ── Adminlar (FAQAT superadmin ko'radi) ──

ADMIN_DEL_TTL = 120  # soniya: tasdiqlash bosqichlari shu vaqt ichida bajarilishi kerak
_admin_del: dict[int, dict] = {}  # superadmin_id -> {"uid": admin_id, "step": 1|2, "t": vaqt}


async def _admin_label(bot: Bot, uid: str, info: dict) -> str:
    """Ro'yxatda tanib olish uchun ism: saqlangan bo'lmasa Telegram'dan so'raymiz va eslab qolamiz (xato bo'lsa — ID)."""
    if not info.get("name"):
        try:
            chat = await bot.get_chat(int(uid))
            name = getattr(chat, "full_name", None) or getattr(chat, "first_name", None) or getattr(chat, "title", None)
            username = getattr(chat, "username", None)
            if isinstance(name, str) and name:
                info["name"] = name + (f" (@{username})" if isinstance(username, str) and username else "")
        except Exception:  # noqa: BLE001
            pass
    return info.get("name") or uid


async def render_admins(bot: Bot) -> tuple[str, InlineKeyboardMarkup]:
    admins = roles.list_admins()
    rows = []
    for uid, info in admins.items():
        label = await _admin_label(bot, uid, info)
        rows.append([InlineKeyboardButton(text=f"🛡 {label} · {uid}"[:60], callback_data=f"panel:adm:{uid}")])
    rows.append([InlineKeyboardButton(text="➕ Admin qo'shish", callback_data="panel:add_admin")])
    rows.append([InlineKeyboardButton(text="🔙 Menyu", callback_data="panel:main")])
    text = ("🛡 <b>Adminlar</b>\nAdminni olib tashlash uchun uning ustiga bosing."
            if admins else "🛡 <b>Adminlar</b>\nHozircha admin yo'q.")
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data.startswith("panel:admins:"))
async def show_admins(call: CallbackQuery, bot: Bot):
    if not roles.is_superadmin(call.from_user.id):
        await call.answer("Ruxsat yo'q", show_alert=True)
        return
    _admin_del.pop(call.from_user.id, None)
    text, kb = await render_admins(bot)
    await call.message.edit_text(text, reply_markup=kb)


def _del_state(caller: int, uid: str, step: int, now: float | None = None) -> bool:
    """Tasdiqlash bosqichi ketma-ket va o'z vaqtida bajarilganini tekshiradi (eski xabardagi tugmani qayta bosish o'tmaydi)."""
    st = _admin_del.get(caller)
    return bool(st and st["uid"] == uid and st["step"] == step and (time.time() if now is None else now) - st["t"] <= ADMIN_DEL_TTL)


async def _deny_unless_super(call: CallbackQuery) -> bool:
    if not roles.is_superadmin(call.from_user.id):
        await call.answer("Ruxsat yo'q", show_alert=True)
        return True
    return False


@router.callback_query(F.data.startswith("panel:adm:"))
async def admin_manage(call: CallbackQuery, bot: Bot):
    """1-tasdiq: admin ustiga bosildi → 'o'chirasizmi?'"""
    if await _deny_unless_super(call):
        return
    uid = call.data.split(":")[-1]
    info = roles.list_admins().get(uid)
    if info is None:
        await call.answer("Bu admin allaqachon ro'yxatda yo'q", show_alert=True)
        text, kb = await render_admins(bot)
        await call.message.edit_text(text, reply_markup=kb)
        return
    _admin_del[call.from_user.id] = {"uid": uid, "step": 1, "t": time.time()}
    label = await _admin_label(bot, uid, info)
    await call.message.edit_text(
        f"🛡 <b>{html.escape(label)}</b> (ID: <code>{uid}</code>)\n\nBu adminni adminlikdan olib tashlaysizmi?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚠️ Ha, davom etish", callback_data=f"panel:admdel1:{uid}")],
            [InlineKeyboardButton(text="❌ Yo'q, qoldirish", callback_data="panel:admins:0")],
        ]))
    await call.answer()


@router.callback_query(F.data.startswith("panel:admdel1:"))
async def admin_delete_step1(call: CallbackQuery, bot: Bot):
    """2-tasdiq: oxirgi ogohlantirish."""
    if await _deny_unless_super(call):
        return
    uid = call.data.split(":")[-1]
    if not _del_state(call.from_user.id, uid, 1):
        await call.answer("Tasdiqlash muddati tugagan — adminni qaytadan tanlang", show_alert=True)
        text, kb = await render_admins(bot)
        await call.message.edit_text(text, reply_markup=kb)
        return
    _admin_del[call.from_user.id] = {"uid": uid, "step": 2, "t": time.time()}
    info = roles.list_admins().get(uid, {})
    label = await _admin_label(bot, uid, info)
    await call.message.edit_text(
        f"⚠️ <b>OXIRGI TASDIQ</b>\n\n<b>{html.escape(label)}</b> (ID: <code>{uid}</code>) adminlikdan olib tashlanadi: "
        f"/panel va admin imkoniyatlari yo'qoladi. Keyin uni yana admin qilib qo'shish mumkin.\n\nRostdan ham o'chirilsinmi?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Ha, adminni o'chirish", callback_data=f"panel:admdel2:{uid}")],
            [InlineKeyboardButton(text="❌ Yo'q, bekor qilish", callback_data="panel:admins:0")],
        ]))
    await call.answer()


@router.callback_query(F.data.startswith("panel:admdel2:"))
async def admin_delete_step2(call: CallbackQuery, bot: Bot):
    if await _deny_unless_super(call):
        return
    uid = call.data.split(":")[-1]
    if not _del_state(call.from_user.id, uid, 2):
        await call.answer("Tasdiqlash muddati tugagan yoki bosqich o'tkazib yuborilgan — qaytadan boshlang", show_alert=True)
        text, kb = await render_admins(bot)
        await call.message.edit_text(text, reply_markup=kb)
        return
    _admin_del.pop(call.from_user.id, None)  # bir martalik: ikkinchi marta bosilsa o'tmaydi
    removed = await roles.remove_admin(bot, int(uid))
    try:
        await bot_commands.unregister_admin_commands(bot, int(uid))  # shaxsiy '/' menyusidan /panel ketadi
    except Exception:  # noqa: BLE001
        pass
    await call.answer("✅ Admin o'chirildi" if removed else "Bu admin allaqachon yo'q edi", show_alert=True)
    text, kb = await render_admins(bot)
    await call.message.edit_text(text, reply_markup=kb)


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
