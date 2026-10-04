"""
Tariflar — joriy holat va Telegram Stars (XTR) bilan sotib olish. BUYRUQ YO'Q: hammasi inline tugmalar orqali —
/start menyusidagi "💳 Tariflar", limit/kvota tugaganda javob tagidagi tugma, eslatma xabarlaridagi tugma (shaxsiy chatda callback
`tariff:menu`; guruhdan deep-link `?start=tariff` — handlers/start.py). Superadmin narx/limitlarni /panel → 💳 Tariflar'da boshqaradi.

Oqim: "💳 Tariflar" → tugma (tariff:buy:<tier>) → send_invoice (XTR) → pre_checkout_query (qat'iy tekshiruv, 10 soniya ichida
javob) → successful_payment (idempotent hisoblash) → tarif yoqiladi. To'lov bo'yicha murojaat: handlers/support.py (inline tugma).
Faqat SHAXSIY chatda ishlaydi.
"""
import datetime
import html
import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, Message,
                           PreCheckoutQuery)

import config
import core.roles as roles
import core.tariffs as tariffs
import handlers.support as support

logger = logging.getLogger("tariff")
router = Router()


def _feature_line(t: tariffs.Tier) -> str:
    bits = []
    if t.daily_limit:
        bits.append(f"{t.daily_limit} so'rov/kun")
    bits.append(f"fayl yaratish {t.files}/kun")
    bits.append(f"rasm o'qish {t.vision}/kun")
    bits.append("story izohi bor" if t.caption else "story izohisiz")
    return ", ".join(bits)


def _usage_line(user_id: int) -> str:
    parts = []
    for kind, label in ((tariffs.KIND_FILES, "fayl"), (tariffs.KIND_VISION, "rasm")):
        limit = tariffs.quota_limit(user_id, kind)
        parts.append(f"{label}: {tariffs.quota_used(user_id, kind)}/{'∞' if limit is None else limit}")
    return "Bugun ishlatildi — " + ", ".join(parts)


def render_plans(user_id: int) -> tuple[str, InlineKeyboardMarkup | None]:
    free = tariffs.tiers()["free"]
    cur = tariffs.active_tier(user_id)
    lines = ["💳 <b>Tariflar</b>\n"]
    if roles.is_superadmin(user_id) or roles.is_admin(user_id):
        lines.append("Siz adminsiz: hamma imkoniyat doim ochiq, tarif kerak emas.\n")
    elif cur.id == "free":
        lines.append(f"Joriy tarif: <b>{free.name}</b> — {roles.effective_daily_limit(user_id)} so'rov/kun, "
                     f"bugun qoldi: {roles.remaining_requests(user_id)}\n{_usage_line(user_id)}\n")
    else:
        until = datetime.datetime.fromtimestamp(tariffs.until_ts(user_id)).strftime("%d.%m.%Y")
        lines.append(f"Joriy tarif: <b>{cur.name}</b> — {tariffs.days_left(user_id)} kun qoldi ({until} gacha)\n"
                     f"Bugun qoldi: {roles.remaining_requests(user_id)} so'rov\n{_usage_line(user_id)}\n")
    lines.append(f"🆓 <b>{free.name}</b> — kunlik so'rov limiti (standart {roles.DEFAULT_DAILY_LIMIT}), "
                 f"fayl yaratish {free.files}/kun, rasm o'qish {free.vision}/kun, story izohisiz")
    rows = []
    for t in tariffs.paid_tiers():
        lines.append(f"{t.name} — {_feature_line(t)}\n   <b>{t.stars} ⭐ / {tariffs.DURATION_DAYS} kun</b>")
        ok, _ = tariffs.can_purchase(user_id, t.id)
        if ok:
            label = f"{'🔄 Uzaytirish' if cur.id == t.id else '⭐ Olish'}: {t.name} — {t.stars} ⭐"
            rows.append([InlineKeyboardButton(text=label, callback_data=f"tariff:buy:{t.id}")])
    lines.append("\n«Fayl yaratish» — docx/xlsx/pptx/pdf/html/py va boshqa har qanday fayl, taqdimot, diagramma. "
                 "Story qo'yish hamma uchun cheksiz, faqat story izohi (caption) Plus/Pro'da.\n"
                 "To'lov Telegram Stars bilan, bot ichida. Muddat tugagach avtomatik Bepul tarifga qaytasiz "
                 "(tugashidan oldin eslatma keladi). To'lov bo'yicha savol: «📨 Adminga murojaat» tugmasi.")
    rows.append([InlineKeyboardButton(text="📨 To'lov bo'yicha murojaat", callback_data=support.CALLBACK)])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


async def send_plans(message: Message):
    """Tariflar sahifasini yangi xabar sifatida yuboradi (shaxsiy chat)."""
    text, kb = render_plans(message.chat.id)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == tariffs.PLANS_CALLBACK)
async def plans_cb(call: CallbackQuery):
    if call.message is None or call.message.chat.type != "private":
        await call.answer("Tariflar faqat shaxsiy chatda ochiladi", show_alert=True)
        return
    text, kb = render_plans(call.from_user.id)
    await call.message.answer(text, reply_markup=kb)  # yangi xabar: asl xabar (menyu/eslatma) joyida qoladi
    await call.answer()


@router.callback_query(F.data.startswith("tariff:buy:"))
async def buy_cb(call: CallbackQuery):
    if call.message is None or call.message.chat.type != "private":
        await call.answer("Faqat shaxsiy chatda", show_alert=True)
        return
    user_id = call.from_user.id
    tier_id = call.data.split(":")[-1]
    ok, why = tariffs.can_purchase(user_id, tier_id)
    if not ok:
        await call.answer(why or "Mumkin emas", show_alert=True)
        return
    if roles.is_blocked(user_id):
        await call.answer("Sizga botdan foydalanish cheklangan", show_alert=True)
        return
    tier = tariffs.tiers()[tier_id]
    desc = _feature_line(tier) + f". Muddat: {tariffs.DURATION_DAYS} kun."
    warn = tariffs.upgrade_warning(user_id, tier_id)
    if warn:
        desc += " " + warn
    await call.message.answer_invoice(
        title=f"{tier.name.split()[0]} tarifi — {tariffs.DURATION_DAYS} kun",
        description=desc[:255],
        payload=tariffs.make_payload(user_id, tier_id),
        currency="XTR",
        prices=[LabeledPrice(label=f"{tier.name.split()[0]} / {tariffs.DURATION_DAYS} kun", amount=tier.stars)],
        provider_token="",  # Telegram Stars uchun bo'sh
    )
    await call.answer()


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    tier_id, err = tariffs.check_payment(query.invoice_payload, query.from_user.id, query.currency,
                                         query.total_amount, strict_price=True)
    if tier_id is None:
        logger.warning("pre_checkout rad: uid=%s payload=%r sabab=%s", query.from_user.id, query.invoice_payload, err)
        await query.answer(ok=False, error_message=err or "To'lovni qabul qilib bo'lmadi.")
        return
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def successful_payment(message: Message):
    pay = message.successful_payment
    user_id = message.from_user.id
    tier_id, err = tariffs.check_payment(pay.invoice_payload, user_id, pay.currency, pay.total_amount, strict_price=False)
    if tier_id is None:
        # Pul yechilgan, lekin to'lov tanib bo'lmadi — jimgina yutib yubormaymiz: superadminga xabar (refund qo'lda)
        logger.error("successful_payment tanilmadi: uid=%s payload=%r charge=%s sabab=%s",
                     user_id, pay.invoice_payload, pay.telegram_payment_charge_id, err)
        await message.answer("⚠️ To'lov qabul qilindi, lekin tarifni avtomatik yoqib bo'lmadi. Admin ko'rib chiqadi — pastdagi tugma orqali yozing:",
                             reply_markup=support.markup())
        await _notify_superadmin(message.bot, f"⚠️ Tanilmagan to'lov!\nUser: <code>{user_id}</code>\n"
                                              f"Summa: {pay.total_amount} {pay.currency}\n"
                                              f"Charge: <code>{html.escape(pay.telegram_payment_charge_id)}</code>\n"
                                              f"Payload: <code>{html.escape(pay.invoice_payload)}</code>")
        return
    status = await tariffs.apply_payment(message.bot, user_id, tier_id, pay.total_amount, pay.telegram_payment_charge_id)
    tier = tariffs.tiers()[tier_id]
    if status == "duplicate":
        await message.answer("✅ Bu to'lov allaqachon hisobga olingan.")
        return
    until = datetime.datetime.fromtimestamp(tariffs.until_ts(user_id)).strftime("%d.%m.%Y")
    logger.info("tarif sotib olindi: uid=%s tier=%s stars=%s", user_id, tier_id, pay.total_amount)
    await message.answer(f"🎉 Rahmat! <b>{tier.name}</b> tarifi yoqildi — {until} gacha ({tariffs.days_left(user_id)} kun).\n"
                         f"{_feature_line(tier)}")


async def _notify_superadmin(bot, text: str):
    try:
        await bot.send_message(config.SUPERADMIN_ID, text)
    except Exception:  # noqa: BLE001
        logger.exception("Superadminga xabar yuborib bo'lmadi")
