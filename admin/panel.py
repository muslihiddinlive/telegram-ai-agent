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
import core.shared_keys as shared_keys
import core.ai_persona as ai_persona

router = Router()


def main_menu_kb(user_id: int) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="👤 Foydalanuvchilar", callback_data="panel:users:0")]]
    if roles.is_superadmin(user_id):
        rows.append([InlineKeyboardButton(text="🛡 Adminlar", callback_data="panel:admins:0")])
        rows.append([InlineKeyboardButton(text="🔑 AI kalitlar", callback_data="panel:keys")])
        rows.append([InlineKeyboardButton(text="🎭 AI shaxsiyati", callback_data="panel:persona")])
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
        f"🧠 Eslab qolingan narsalar: {notes_count} ta"
    )

    kb_rows = []
    if rec.get("role") != "blocked":
        kb_rows.append([InlineKeyboardButton(text="✏️ Limitni o'zgartirish", callback_data=f"panel:setlimit:{uid}")])
        # Faqat superadmin bloklay oladi
        if roles.is_superadmin(caller):
            kb_rows.append([InlineKeyboardButton(text="🚫 Bloklash", callback_data=f"panel:revoke:{uid}")])
    else:
        kb_rows.append([InlineKeyboardButton(text="✅ Blokdan chiqarish", callback_data=f"panel:approve:{uid}")])
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
