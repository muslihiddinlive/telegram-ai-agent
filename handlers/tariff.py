"""
/tarif — tariflar, joriy holat va Telegram Stars (XTR) bilan sotib olish.

Oqim: /tarif → tugma (tariff:buy:<tier>) → send_invoice (XTR) → pre_checkout_query (qat'iy tekshiruv, 10 soniya ichida
javob) → successful_payment (idempotent hisoblash) → tarif yoqiladi. /paysupport — Telegram talab qiladigan to'lov murojaati.
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

logger = logging.getLogger("tariff")
router = Router()


def _feature_line(t: tariffs.Tier) -> str:
    bits = []
    if t.daily_limit:
        bits.append(f"{t.daily_limit} so'rov/kun")
    if tariffs.FEATURE_VISION in t.features:
        bits.append("rasm o'qish")
    if tariffs.FEATURE_FILES in t.features:
        bits.append("fayl/hujjat yaratish (docx, xlsx, pptx, pdf, taqdimot, diagramma)")
    return ", ".join(bits)


def render_plans(user_id: int) -> tuple[str, InlineKeyboardMarkup | None]:
    free = tariffs.tiers()["free"]
    cur = tariffs.active_tier(user_id)
    lines = ["💳 <b>Tariflar</b>\n"]
    if roles.is_superadmin(user_id) or roles.is_admin(user_id):
        lines.append("Siz adminsiz: hamma imkoniyat doim ochiq, tarif kerak emas.\n")
    elif cur.id == "free":
        lines.append(f"Joriy tarif: <b>{free.name}</b> — {roles.effective_daily_limit(user_id)} so'rov/kun, "
                     f"bugun qoldi: {roles.remaining_requests(user_id)}\n")
    else:
        until = datetime.datetime.fromtimestamp(tariffs.until_ts(user_id)).strftime("%d.%m.%Y")
        lines.append(f"Joriy tarif: <b>{cur.name}</b> — {tariffs.days_left(user_id)} kun qoldi ({until} gacha)\n"
                     f"Bugun qoldi: {roles.remaining_requests(user_id)} so'rov\n")
    lines.append(f"🆓 <b>{free.name}</b> — kunlik limit (standart {roles.DEFAULT_DAILY_LIMIT}), rasm/fayl yo'q")
    rows = []
    for t in tariffs.paid_tiers():
        lines.append(f"{t.name} — {_feature_line(t)}\n   <b>{t.stars} ⭐ / {tariffs.DURATION_DAYS} kun</b>")
        ok, _ = tariffs.can_purchase(user_id, t.id)
        if ok:
            label = f"{'🔄 Uzaytirish' if cur.id == t.id else '⭐ Olish'}: {t.name} — {t.stars} ⭐"
            rows.append([InlineKeyboardButton(text=label, callback_data=f"tariff:buy:{t.id}")])
    lines.append("\nTo'lov Telegram Stars bilan, bot ichida. Muddat tugagach avtomatik Bepul tarifga qaytasiz. "
                 "To'lov bo'yicha savol: /paysupport")
    return "\n".join(lines), (InlineKeyboardMarkup(inline_keyboard=rows) if rows else None)


@router.message(Command("tarif"))
async def tarif_cmd(message: Message):
    if message.chat.type != "private":
        await message.reply("💳 Tariflar bilan shaxsiy chatda ishlang: botga to'g'ridan-to'g'ri /tarif yozing.")
        return
    text, kb = render_plans(message.from_user.id)
    await message.answer(text, reply_markup=kb)


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
        await message.answer("⚠️ To'lov qabul qilindi, lekin tarifni avtomatik yoqib bo'lmadi. Admin ko'rib chiqadi: /paysupport")
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


@router.message(Command("paysupport"), F.chat.type == "private")
async def paysupport(message: Message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.answer("💬 To'lov bo'yicha muammoni shunday yozing: <code>/paysupport muammo tavsifi</code>\n"
                             "Xabaringiz adminga yetkaziladi. To'lovni qaytarish (refund) ham shu orqali so'raladi.")
        return
    text = parts[1].strip()[:1000]
    await _notify_superadmin(message.bot, f"💬 To'lov murojaati\nUser: <code>{message.from_user.id}</code> "
                                          f"({html.escape(message.from_user.full_name)})\n\n{html.escape(text)}")
    await message.answer("✅ Murojaatingiz adminga yuborildi. Javobni shu botda olasiz.")
