"""
Profil boshqaruvi: botni foydalanuvchining Telegram profiliga (Business) AI-yordamchi sifatida
ulash va u orqali story qo'yish.

Oqim:  /start -> "👤 Profil boshqaruvi" -> "📸 Story qo'yish" -> rasm/video yuboriladi
       (izoh yozilsa — story matni bo'ladi) -> muddat tanlanadi -> story profilga joylanadi.

MUHIM: bu router main.py'da handlers.ai_chat'dan OLDIN ro'yxatdan o'tishi kerak — aks holda
yuborilgan rasm/video oddiy AI-suhbat fayli sifatida ketib qoladi.
"""
import html
import logging
import os
import time

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import BusinessConnection, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import core.bot_identity as bot_identity
import core.roles as roles
import core.stories as stories
import core.story_caption as story_caption

logger = logging.getLogger("profile")
router = Router()

WAIT_TTL = 15 * 60  # soniya — story jarayoni shundan keyin bekor bo'ladi
MAX_REGEN = 3  # «Boshqacha yozish» ko'pi bilan shuncha marta (har biri AI so'rovi hisoblanadi)
# user_id -> {"step": "media"|"period", "t": vaqt, "path", "kind", "caption", "entities", "duration", "anim", "src"}
_waiting: dict[int, dict] = {}


def _state(user_id: int) -> dict | None:
    st = _waiting.get(user_id)
    if st and time.time() - st["t"] > WAIT_TTL:
        _drop(user_id)
        return None
    return st


def _drop(user_id: int):
    st = _waiting.pop(user_id, None)
    if st:
        stories.cleanup(st.get("path"), st.get("src"))


def _kb(*rows: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t, callback_data=d) for t, d in row] for row in rows
    ])


def _connect_help() -> str:
    uname = bot_identity.get_username() or "bot"
    return (
        "Botni profilingizga ulash:\n"
        "1️⃣ Hisobingizda <b>Telegram Premium</b> bo'lishi kerak (Business funksiyalari uchun).\n"
        "2️⃣ Telegram → <b>Sozlamalar → Telegram Business → Chatbotlar</b> (menyu nomi versiyaga qarab biroz farq qilishi mumkin).\n"
        f"3️⃣ <code>@{html.escape(uname)}</code> ni tanlab qo'shing.\n"
        "4️⃣ Bot ruxsatlarida <b>story'larni boshqarish</b> ruxsatini yoqing. "
        "Faqat story kerak bo'lsa, botning chatlarga kirishini minimal qilib qo'ying.\n\n"
        "Ulangach, shu yerga qaytib <b>«🔄 Holatni tekshirish»</b> ni bosing."
    )


def _menu(user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    st = stories.status(user_id)
    refresh = ("🔄 Holatni tekshirish", "profile:menu")
    back = ("🔙 Orqaga", "profile:home")
    if st == "ready":
        return (
            "👤 <b>Profil boshqaruvi</b>\n✅ Bot profilingizga ulangan, story qo'yish yoqilgan.",
            _kb([("📸 Story qo'yish", "profile:story")], [back]),
        )
    if st == "no_rights":
        return (
            "👤 <b>Profil boshqaruvi</b>\n⚠️ Bot ulangan, lekin <b>story'larni boshqarish</b> ruxsati berilmagan.\n\n"
            "Sozlamalar → Telegram Business → Chatbotlar → botingiz → ruxsatlardan story'ni yoqing.",
            _kb([refresh], [back]),
        )
    if st == "disabled":
        return ("👤 <b>Profil boshqaruvi</b>\n🔌 Ulanish o'chirilgan.\n\n" + _connect_help(), _kb([refresh], [back]))
    return ("👤 <b>Profil boshqaruvi</b>\n❌ Bot hali profilingizga ulanmagan.\n\n" + _connect_help(), _kb([refresh], [back]))


async def _edit(call: CallbackQuery, text: str, kb: InlineKeyboardMarkup | None):
    try:
        await call.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest as e:  # "message is not modified" va h.k.
        if "not modified" not in str(e).lower():
            await call.message.answer(text, reply_markup=kb)


# ───────────────────────── menyu ─────────────────────────

@router.message(Command("profil"), F.chat.type == "private")
async def profile_cmd(message: Message):
    if not roles.can_use_bot(message.from_user.id):
        return
    text, kb = _menu(message.from_user.id)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "profile:menu")
async def profile_menu(call: CallbackQuery):
    if not roles.can_use_bot(call.from_user.id):
        await call.answer("Ruxsat yo'q", show_alert=True)
        return
    _drop(call.from_user.id)
    text, kb = _menu(call.from_user.id)
    await _edit(call, text, kb)
    await call.answer()


@router.callback_query(F.data == "profile:home")
async def profile_home(call: CallbackQuery):
    _drop(call.from_user.id)
    await _edit(
        call,
        "Bosh menyu. Menga xabar yozing yoki quyidagilardan birini tanlang:",
        _kb([("👤 Profil boshqaruvi", "profile:menu")], [("🔑 AI API integratsiya", "apikey:menu")]),
    )
    await call.answer()


@router.callback_query(F.data == "profile:story")
async def story_start(call: CallbackQuery):
    uid = call.from_user.id
    if not roles.can_use_bot(uid):
        await call.answer("Ruxsat yo'q", show_alert=True)
        return
    if stories.status(uid) != "ready":
        text, kb = _menu(uid)
        await _edit(call, text, kb)
        await call.answer("Avval botni profilga ulang", show_alert=True)
        return
    _drop(uid)
    _waiting[uid] = {"step": "media", "t": time.time()}
    await _edit(
        call,
        "📸 Story uchun <b>rasm yoki video</b> yuboring.\n\n"
        "• Izoh (caption) yozsangiz: oddiy matn bo'lsa — <b>aynan shunday</b> story matni bo'ladi; "
        "AI'ga buyruq bo'lsa (masalan «shunga jiddiy izoh yoz») — AI uni bajarib matnni <b>o'zi yozadi</b>.\n"
        "• Fayl 20 MB dan oshmasin (videoni bot o'zi Story formatiga o'tkazadi, eng ko'pi 60 soniya).\n"
        "• «Fayl sifatida» yuborsangiz ham bo'ladi.",
        _kb([("❌ Bekor qilish", "profile:menu")]),
    )
    await call.answer()


# ───────────────────────── media qabul qilish ─────────────────────────

def _extract(message: Message):
    """(kind, file_id, size, is_animation, name) yoki None"""
    if message.photo:
        p = message.photo[-1]
        return "photo", p.file_id, p.file_size or 0, False, "photo.jpg"
    if message.video:
        v = message.video
        return "video", v.file_id, v.file_size or 0, False, v.file_name or "video.mp4"
    if message.animation:
        a = message.animation
        return "video", a.file_id, a.file_size or 0, True, a.file_name or "animation.mp4"
    if message.document:
        d = message.document
        kind = stories.kind_of(d.file_name or "")
        mime = d.mime_type or ""
        if kind is None and mime.startswith("image/"):
            kind = "photo"
        elif kind is None and mime.startswith("video/"):
            kind = "video"
        if kind:
            return kind, d.file_id, d.file_size or 0, False, d.file_name or ("file.jpg" if kind == "photo" else "file.mp4")
    return None


def _waiting_media(message: Message) -> bool:
    if message.chat.type != "private" or not message.from_user:
        return False
    st = _state(message.from_user.id)
    return bool(st and st["step"] == "media" and (_extract(message) or (message.text and not message.text.startswith("/"))))


@router.message(_waiting_media)
async def story_media(message: Message, bot: Bot):
    uid = message.from_user.id
    info = _extract(message)
    if info is None:  # matn yozibdi
        await message.answer("Story uchun <b>rasm yoki video</b> yuboring (matn emas). Bekor qilish: /profil")
        return
    kind, file_id, size, is_anim, name = info
    if size > stories.TG_DOWNLOAD_LIMIT:
        await message.answer("⚠️ Fayl 20 MB dan katta — Telegram botlarga bunday fayllarni yuklab olishga ruxsat bermaydi. "
                             "Kichikroq/qisqaroq qilib qayta yuboring.")
        return

    wd = stories.work_dir(uid)
    src = os.path.join(wd, f"src_{int(time.time())}_{os.path.basename(name)}")
    status_msg = await message.answer("⏳ Fayl Story formatiga tayyorlanmoqda…" + (" (video biroz vaqt olishi mumkin)" if kind == "video" else ""))
    try:
        await bot.download(file_id, destination=src)
        prepared, duration = await stories.prepare(kind, src, wd)
    except stories.StoryError as e:
        stories.cleanup(src)
        await status_msg.edit_text(f"❌ {html.escape(str(e))}")
        return
    except Exception as e:  # noqa: BLE001
        logger.exception("Story tayyorlashda xatolik")
        stories.cleanup(src)
        await status_msg.edit_text(f"❌ Xatolik: {html.escape(str(e))}")
        return

    _waiting[uid] = {
        "step": "period", "t": time.time(), "path": prepared, "src": src, "kind": kind,
        "duration": duration, "anim": is_anim,
        "orig_caption": message.caption, "orig_entities": message.caption_entities, "regen": 0,
    }
    if (message.caption or "").strip():
        await status_msg.edit_text("✍️ Izoh tekshirilmoqda…")
    await _apply_caption(bot, uid)
    text, kb = _period_view(_waiting[uid])
    await status_msg.edit_text(text, reply_markup=kb)


async def _apply_caption(bot: Bot, uid: int):
    """Izohni AI bilan hal qiladi (oddiy matn -> aynan shunday; buyruq -> AI yozadi) va holatga yozadi."""
    st = _waiting[uid]
    caption, mode, reason = await story_caption.resolve(bot, uid, st["orig_caption"], st["kind"], photo_path=st["src"])
    st["caption"], st["mode"], st["reason"] = caption, mode, reason
    # AI yozgan matnda asl izohning entity'lari (offsetlari) mos kelmaydi
    st["entities"] = None if mode == story_caption.AI else st["orig_entities"]
    st["t"] = time.time()


def _period_view(st: dict) -> tuple[str, InlineKeyboardMarkup]:
    cap = st.get("caption") or ""
    shown = f"«{html.escape(cap[:400])}{'…' if len(cap) > 400 else ''}»"
    mode = st.get("mode")
    if mode == story_caption.AI:
        caption_line = f"✍️ Izohingizdagi buyruqni bajardim. Story matni:\n{shown}"
    elif mode == story_caption.LITERAL:
        caption_line = f"📝 Story matni (aynan shunday chiqadi):\n{shown}"
    elif mode == story_caption.FALLBACK:
        why = {
            story_caption.R_LIMIT: "kunlik so'rov limitingiz tugagan",
            story_caption.R_ERROR: "AI xizmati hozir javob bermadi",
            story_caption.R_FORMAT: "AI javobi tushunarsiz bo'ldi",
        }.get(st.get("reason"), "noma'lum sabab")
        caption_line = (
            f"⚠️ Izohni AI bilan tekshirib bo'lmadi ({why}), shuning uchun u <b>so'zma-so'z</b> qo'yiladi:\n"
            f"{shown}\nBuyruq yozgan bo'lsangiz — «AI bilan qayta tekshirish»ni bosing yoki bekor qiling."
        )
    else:
        caption_line = "📝 Story matnsiz chiqadi (izoh yozilmagan)."
    rows = [
        [("⚡ 24 soat (tavsiya)", "profile:post:24")],
        [("6 soat", "profile:post:6"), ("12 soat", "profile:post:12"), ("48 soat", "profile:post:48")],
    ]
    if st.get("regen", 0) < MAX_REGEN:
        if mode == story_caption.AI:
            rows.append([("🔁 Boshqacha yozish", "profile:regen")])
        elif mode == story_caption.FALLBACK and st.get("reason") != story_caption.R_LIMIT:
            rows.append([("🔁 AI bilan qayta tekshirish", "profile:regen")])
    rows.append([("❌ Bekor qilish", "profile:menu")])
    text = (
        "✅ Tayyor. Story qancha vaqt <b>hammaga ko'rinib</b> turadi?\n\n"
        f"{caption_line}\n\n<i>Muddati tugagach ham profilingizda saqlanib qoladi (o'zingiz o'chirmaguningizcha).</i>"
    )
    return text, _kb(*rows)


@router.callback_query(F.data == "profile:regen")
async def story_regen(call: CallbackQuery, bot: Bot):
    uid = call.from_user.id
    st = _state(uid)
    if not st or st["step"] != "period" or st.get("mode") not in (story_caption.AI, story_caption.FALLBACK):
        await call.answer("Sessiya tugagan — qaytadan boshlang.", show_alert=True)
        return
    if st.get("regen", 0) >= MAX_REGEN:
        await call.answer("Qayta yozish limiti tugadi.", show_alert=True)
        return
    st["regen"] = st.get("regen", 0) + 1
    await call.answer("Qayta yozilmoqda…")
    await _edit(call, "✍️ Boshqacha yozilmoqda…", None)
    await _apply_caption(bot, uid)
    text, kb = _period_view(_waiting[uid])
    await _edit(call, text, kb)


@router.callback_query(F.data.startswith("profile:post:"))
async def story_post(call: CallbackQuery, bot: Bot):
    uid = call.from_user.id
    st = _state(uid)
    if not st or st["step"] != "period":
        await call.answer("Sessiya tugagan — qaytadan boshlang.", show_alert=True)
        return
    hours = int(call.data.split(":")[-1])
    await call.answer("Joylanmoqda…")
    await _edit(call, "⏳ Story joylanmoqda…", None)
    try:
        story = await stories.post(
            bot, uid, st["kind"], st["path"], hours=hours, caption=st["caption"],
            entities=st["entities"], duration=st["duration"], is_animation=st["anim"],
        )
    except stories.StoryError as e:
        _drop(uid)
        await _edit(call, f"❌ Story qo'yilmadi:\n{html.escape(str(e))}", _kb([("🔙 Profil boshqaruvi", "profile:menu")]))
        return
    _drop(uid)
    await _edit(
        call,
        f"✅ Story profilingizga qo'yildi.\n• {hours} soat hammaga ko'rinib turadi.\n"
        "• Undan keyin ham profilingizdagi story'lar bo'limida qoladi (o'zingiz o'chirmaguningizcha).",
        _kb([("🗑 O'chirish", f"profile:del:{story.id}")], [("📸 Yana story", "profile:story")], [("🔙 Profil boshqaruvi", "profile:menu")]),
    )


@router.callback_query(F.data.startswith("profile:del:"))
async def story_delete(call: CallbackQuery, bot: Bot):
    uid = call.from_user.id
    story_id = int(call.data.split(":")[-1])
    try:
        await stories.delete(bot, uid, story_id)
    except stories.StoryError as e:
        await call.answer(str(e)[:190], show_alert=True)
        return
    await _edit(call, "🗑 Story o'chirildi.", _kb([("📸 Yangi story", "profile:story")], [("🔙 Profil boshqaruvi", "profile:menu")]))
    await call.answer()


# ───────────────────────── Business ulanish yangilanishi ─────────────────────────

@router.business_connection()
async def on_business_connection(bc: BusinessConnection, bot: Bot):
    """Foydalanuvchi botni profiliga ulaganda/uzganda/ruxsatlarni o'zgartirganda Telegram yuboradi."""
    rec = await stories.save_connection(bot, bc)
    if not rec["enabled"]:
        text = "🔌 Bot profilingizdan uzildi."
    elif rec["stories"]:
        text = "✅ Bot profilingizga ulandi va story qo'yish ruxsati bor.\nStory qo'yish: /profil → «📸 Story qo'yish»."
    else:
        text = ("✅ Bot profilingizga ulandi, lekin <b>story'larni boshqarish</b> ruxsati berilmagan.\n"
                "Sozlamalar → Telegram Business → Chatbotlar → botingiz → ruxsatlardan story'ni yoqing.")
    try:
        await bot.send_message(bc.user_chat_id, text)
    except Exception:  # noqa: BLE001 — foydalanuvchi botni bloklagan bo'lishi mumkin
        logger.info("Business ulanish xabarini yuborib bo'lmadi (%s)", bc.user.id)
