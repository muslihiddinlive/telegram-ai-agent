"""
/instagram — foydalanuvchi o'z Instagram akkauntini ulaydi / holatini ko'radi / uzadi.

Ulash tugmasi — Meta'ning rasmiy kirish sahifasiga olib boradigan havola (parol botga HECH QACHON berilmaydi).
Faqat shaxsiy chatda. Imkoniyatlar tarif bo'yicha: core/instagram_plans.py.
"""
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import core.instagram_accounts as accounts
import core.instagram_api as ig
import core.instagram_common as common
import core.instagram_context as ictx
import core.instagram_media as media
import core.instagram_oauth as oauth
import core.instagram_plans as plans
import core.instagram_store as store
import core.roles as roles
import core.tariffs as tariffs

router = Router()


def _limit(v, unit: str = "") -> str:
    return "cheksiz" if v is None else (f"{v}{unit}" if v else "yo'q")


def _plan_lines(user_id: int, acct, plan: plans.Plan) -> str:
    """Tarif imkoniyatlari + hozirgi foydalanish (joriy akkaunt kontekstida)."""
    with ictx.use(acct, plan):
        sched, trig, banned = store.pending_count(), len(store.list_triggers()), len(store.banned_words())
    rows = ["• Joylash, statistika, izohlar: " + ("cheksiz (Instagram limiti ichida)" if plan.publish else "yo'q")]
    rows.append("• Rejalashtirish: " + ("yo'q" if plan.max_scheduled == 0 else
                f"{sched}/{plan.max_scheduled}" if plan.max_scheduled is not None else f"{sched} (cheksiz)"))
    rows.append("• Avtomatik qoidalar (kalit so'z → DM, spam): " + ("yo'q" if plan.max_triggers == 0 else
                f"{trig}/{plan.max_triggers}" if plan.max_triggers is not None else f"{trig} (cheksiz)"))
    rows.append("• DM'da AI yordamchi: " + ("yo'q" if not plan.dm else
                f"kuniga {plan.dm_daily} ta javob" if plan.dm_daily is not None else "cheksiz"))
    return "\n".join(rows)


def _kb(user_id: int, state: str) -> InlineKeyboardMarkup:
    rows = []
    ok, _ = oauth.can_connect(user_id)
    if state in ("none", "reauth") and ok:
        try:
            link = oauth.authorize_url(user_id)
        except media.MediaError:      # ommaviy manzil (IG_PUBLIC_BASE_URL / WEBHOOK_URL) sozlanmagan
            link = None
        if link:
            rows.append([InlineKeyboardButton(text="🔗 Instagram'ni ulash" if state == "none" else "🔄 Qayta ulash",
                                              url=link)])
    if state in ("ok", "reauth"):
        rows.append([InlineKeyboardButton(text="🔌 Uzish", callback_data="ig:disc")])
    rows.append([InlineKeyboardButton(text=tariffs.PLANS_BUTTON_TEXT, callback_data=tariffs.PLANS_CALLBACK)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _status_text(user_id: int) -> tuple[str, str]:
    """(matn, holat) — holat: none | ok | reauth | owner."""
    if ig.is_configured() and common.allowed(user_id):
        return ("✅ Siz bot egasisiz — Instagram akkauntingiz serverda sozlangan (barcha imkoniyatlar ochiq).\n"
                "Menga \"postga rasm qo'y\", \"statistika\" kabi yozing."), "owner"
    state = accounts.status(user_id)
    if state == "none":
        ok, why = oauth.can_connect(user_id)
        if not ok:
            return f"📸 Instagram\n\n{why}", "none"
        plan = plans.plan_for(user_id)
        if plan.code in ("plus", "pro"):
            head = f"Tarifingiz: {plan.label}."
        else:
            head = f"🎁 Yangi foydalanuvchi uchun {accounts.TRIAL_DAYS} kunlik bepul sinov (bir martalik) — ulanganda boshlanadi."
        return (f"📸 Instagram akkauntingizni ulang — bot sizning nomingizdan post/reel/story joylaydi, statistika "
                f"va izohlarni boshqaradi.\n\n{head}\nFaqat Instagram Business yoki Creator akkaunt ulanadi. "
                f"Parolni bot ko'rmaydi: kirish Instagram'ning o'z sahifasida."), "none"
    rec = accounts.record(user_id) or {}
    if state == "reauth":
        return (f"⚠️ @{rec.get('username', '')}: ulanish eskirgan yoki bekor qilingan. Rejalashtirilgan postlar va "
                f"avtomatik javoblar to'xtatilgan. Qayta ulang."), "reauth"
    acct = accounts.account_for(user_id)
    plan = plans.plan_for(user_id, acct)
    head = f"✅ Ulangan: @{rec.get('username', '')}\nTarif: {plan.label}"
    if plan.code == "trial":
        head += f" — qolgan vaqt: {plans.trial_text(accounts.trial_seconds_left(user_id))}"
    if plan.code == "none":
        return f"{head}\n\n{plans.deny_text(plan, 'publish')}", "ok"
    return f"{head}\n\n{_plan_lines(user_id, acct, plan)}", "ok"


async def _show(message: Message, user_id: int) -> None:
    text, state = _status_text(user_id)
    if state == "owner":
        await message.answer(text)
        return
    try:
        media.public_base()
    except media.MediaError:
        await message.answer("Instagram ulash hozircha sozlanmagan (administrator IG_PUBLIC_BASE_URL / WEBHOOK_URL "
                             "ni o'rnatishi kerak). Keyinroq urinib ko'ring.")
        return
    await message.answer(text, reply_markup=_kb(user_id, state))


@router.message(Command("instagram"))
async def cmd_instagram(message: Message):
    if not roles.can_use_bot(message.from_user.id):
        return
    if message.chat.type != "private":
        await message.reply("Instagram'ni ulash faqat shaxsiy chatda: botga shaxsiy xabar yozing.")
        return
    if not ictx.multi_enabled() and not (ig.is_configured() and common.allowed(message.from_user.id)):
        await message.answer("Instagram ulash hozircha yoqilmagan.")
        return
    await _show(message, message.from_user.id)


@router.callback_query(F.data == "ig:disc")
async def ask_disconnect(call: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Ha, uzish", callback_data="ig:disc:yes"),
        InlineKeyboardButton(text="↩️ Bekor", callback_data="ig:disc:no")]])
    await call.message.answer("Instagram'ni uzasizmi? Token va shu akkauntning barcha ma'lumotlari (rejalashtirilgan "
                              "postlar, avtomatik qoidalar, DM suhbatlari) o'chadi. Bepul sinov qaytmaydi.", reply_markup=kb)
    await call.answer()


@router.callback_query(F.data == "ig:disc:yes")
async def do_disconnect(call: CallbackQuery):
    done = accounts.disconnect(call.from_user.id)
    await call.message.edit_text("🔌 Instagram uzildi, ma'lumotlar o'chirildi." if done else "Ulangan akkaunt yo'q.")
    await call.answer()


@router.callback_query(F.data == "ig:disc:no")
async def cancel_disconnect(call: CallbackQuery):
    await call.message.edit_text("Bekor qilindi.")
    await call.answer()
