"""
📨 Adminga murojaat — inline tugma bilan boshlanadi, BUYRUQ-matn yo'q.

Oqim: tugma (support:start) → reply-klaviatura ["✅ Yuborish", "❌ Bekor qilish"] chiqadi → foydalanuvchi xohlagancha xabar yozadi
(matn, rasm, video, stiker, GIF, ovozli, fayl, emoji...) — HAR BIRI alohida xabar bo'lib saqlanadi, hali HECH QAYERGA YUBORILMAYDI →
faqat «✅ Yuborish» bosilganda hammasi (har biri alohida, o'z turida: copy_message) superadminga boradi; oldidan murojaat sarlavhasi
(kim, tarifi) va "✉️ Javob yozish" tugmasi. «❌ Bekor qilish» — hammasi bekor.

Qarorlar:
  - Yig'ilgan xabarlar faqat message_id sifatida saqlanadi (xotirada); yuborishda copy_message ishlatiladi, shuning uchun HAR QANDAY tur
    (stiker, GIF, video_note, kontakt, lokatsiya, fayl...) o'z holicha boradi.
  - Sessiya xotirada, 30 daqiqa harakatsizlikdan keyin tugaydi; 20 tagacha xabar; soatiga 5 ta murojaat (spamga qarshi).
  - Sessiya paytida komanda (masalan /start) yozilsa — murojaat bekor bo'ladi va komanda odatdagidek bajariladi.
  - Telegram to'lov qabul qiladigan botlardan /paysupport talab qiladi — u yerda faqat shu tugmani ochadi (matn argumenti yo'q).
"""
import html
import logging
import time
from collections import defaultdict, deque

from aiogram import Router, F
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.filters import Command
from aiogram.types import (CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, Message,
                           ReplyKeyboardMarkup, ReplyKeyboardRemove)

import config
import core.pending_input as pending_input
import core.roles as roles
import core.tariffs as tariffs

logger = logging.getLogger("support")
router = Router()

SEND_TEXT = "✅ Yuborish"
CANCEL_TEXT = "❌ Bekor qilish"
CALLBACK = "support:start"
BUTTON_TEXT = "📨 Adminga murojaat"
MAX_ITEMS = 20
SESSION_TTL = 1800
SUBMISSIONS_PER_HOUR = 5

_sessions: dict[int, dict] = {}   # user_id -> {"items": [message_id...], "t": oxirgi harakat}
_submitted: dict[int, deque] = defaultdict(deque)


def markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=BUTTON_TEXT, callback_data=CALLBACK)]])


def _keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=SEND_TEXT), KeyboardButton(text=CANCEL_TEXT)]],
                               resize_keyboard=True, input_field_placeholder="Xabar yozing, so'ng «✅ Yuborish» ni bosing")


def _active(user_id: int, now: float | None = None) -> dict | None:
    s = _sessions.get(user_id)
    if s is None:
        return None
    if (time.time() if now is None else now) - s["t"] > SESSION_TTL:
        _sessions.pop(user_id, None)
        return None
    return s


def _rate_wait(user_id: int, now: float | None = None) -> int:
    now = time.time() if now is None else now
    q = _submitted[user_id]
    while q and now - q[0] > 3600:
        q.popleft()
    return int(3600 - (now - q[0])) + 1 if len(q) >= SUBMISSIONS_PER_HOUR else 0


# ── boshlash ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == CALLBACK)
async def start_cb(call: CallbackQuery):
    if call.message is None or call.message.chat.type != "private":
        await call.answer("Murojaat faqat shaxsiy chatda", show_alert=True)
        return
    uid = call.from_user.id
    if roles.is_blocked(uid):
        await call.answer("Sizga botdan foydalanish cheklangan", show_alert=True)
        return
    wait = _rate_wait(uid)
    if wait:
        await call.answer(f"Murojaatlar limiti tugadi. Taxminan {wait // 60 + 1} daqiqadan keyin urinib ko'ring.", show_alert=True)
        return
    pending_input.clear(uid)  # boshqa yarim qolgan oqim (API kalit, story...) bilan aralashmasin
    _sessions[uid] = {"items": [], "t": time.time()}
    await call.message.answer(
        "📨 <b>Adminga murojaat</b>\n\n"
        "Xabaringizni yozing: matn, rasm, video, stiker, GIF, ovozli xabar, fayl — istalgancha. "
        "Har biri alohida xabar bo'lib adminga boradi, lekin <b>faqat «✅ Yuborish» ni bosganingizdan keyin</b>.\n"
        f"Bekor qilish: «❌ Bekor qilish». (Eng ko'pi {MAX_ITEMS} ta xabar.)",
        reply_markup=_keyboard(),
    )
    await call.answer()


# ── yig'ish / yuborish / bekor ───────────────────────────────────────────

def _in_session(message: Message) -> bool:
    return (message.chat.type == "private" and message.from_user is not None
            and _active(message.from_user.id) is not None
            and not (message.text or "").startswith("/"))


def _is_stale_button(message: Message) -> bool:
    return (message.chat.type == "private" and message.text in (SEND_TEXT, CANCEL_TEXT)
            and _active(message.from_user.id) is None)


def _is_command_in_session(message: Message) -> bool:
    return (message.chat.type == "private" and message.from_user is not None
            and (message.text or "").startswith("/") and _active(message.from_user.id) is not None)


@router.message(_is_command_in_session)
async def command_cancels(message: Message):
    _sessions.pop(message.from_user.id, None)
    await message.answer("❌ Murojaat bekor qilindi (yuborilmadi).", reply_markup=ReplyKeyboardRemove())
    raise SkipHandler  # komandaning o'zi odatdagidek bajarilsin


@router.message(_is_stale_button)
async def stale_buttons(message: Message):
    await message.answer("⌛ Murojaat sessiyasi tugagan. Qaytadan boshlash uchun «📨 Adminga murojaat» tugmasini bosing.",
                         reply_markup=ReplyKeyboardRemove())


@router.message(_in_session)
async def collect(message: Message):
    uid = message.from_user.id
    s = _active(uid)
    if message.text == CANCEL_TEXT:
        _sessions.pop(uid, None)
        await message.answer("❌ Murojaat bekor qilindi, hech narsa yuborilmadi.", reply_markup=ReplyKeyboardRemove())
        return
    if message.text == SEND_TEXT:
        await _submit(message, s)
        return
    if len(s["items"]) >= MAX_ITEMS:
        await message.reply(f"⚠️ Eng ko'pi {MAX_ITEMS} ta xabar. «✅ Yuborish» ni bosing yoki «❌ Bekor qilish».")
        return
    s["items"].append(message.message_id)
    s["t"] = time.time()
    await message.reply(f"📥 Qabul qilindi ({len(s['items'])}). Yana yozishingiz yoki «✅ Yuborish» ni bosishingiz mumkin.")


async def _submit(message: Message, s: dict):
    uid = message.from_user.id
    if not s["items"]:
        await message.reply("Avval kamida bitta xabar yozing, so'ng «✅ Yuborish» ni bosing.")
        return
    wait = _rate_wait(uid)
    if wait:
        await message.reply(f"⚠️ Murojaatlar limiti tugadi (soatiga {SUBMISSIONS_PER_HOUR} ta). "
                            f"Taxminan {wait // 60 + 1} daqiqadan keyin urinib ko'ring.")
        return
    u = message.from_user
    uname = f"@{u.username}" if u.username else "—"
    header = (f"📨 <b>Murojaat</b>\nUser: <code>{uid}</code> ({html.escape(u.full_name)}) {uname}\n"
              f"Tarif: {html.escape(tariffs.active_tier(uid).name)}\nXabarlar: {len(s['items'])} ta (quyida, har biri alohida)")
    reply_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✉️ Javob yozish", callback_data=f"panel:msg:{uid}")]])
    try:
        await message.bot.send_message(config.SUPERADMIN_ID, header, reply_markup=reply_kb)
    except Exception as e:  # noqa: BLE001
        logger.warning("Murojaat sarlavhasi yuborilmadi: %s", type(e).__name__)
        await message.reply("⚠️ Hozir adminga yetkazib bo'lmadi. Xabarlaringiz saqlanib turibdi — birozdan keyin «✅ Yuborish» ni qayta bosing.")
        return  # sessiya saqlanadi
    delivered = 0
    for mid in s["items"]:
        try:
            await message.bot.copy_message(chat_id=config.SUPERADMIN_ID, from_chat_id=message.chat.id, message_id=mid)
            delivered += 1
        except Exception as e:  # noqa: BLE001
            logger.info("Murojaat xabari ko'chirilmadi (mid=%s): %s", mid, type(e).__name__)
    _submitted[uid].append(time.time())
    _sessions.pop(uid, None)
    logger.info("murojaat: uid=%s xabarlar=%d/%d", uid, delivered, len(s["items"]))
    note = "" if delivered == len(s["items"]) else f" ({len(s['items']) - delivered} tasi o'chirilgan bo'lgani uchun yetmadi)"
    await message.answer(f"✅ Murojaatingiz adminga yuborildi: {delivered} ta xabar{note}. Javobni shu botda olasiz.",
                         reply_markup=ReplyKeyboardRemove())


# ── Telegram talabi: /paysupport (matn argumentisiz) ─────────────────────

@router.message(Command("paysupport"), F.chat.type == "private")
async def paysupport(message: Message):
    await message.answer("💬 To'lov bo'yicha savol yoki refund uchun adminga murojaat qiling:", reply_markup=markup())
