"""
GitHub: token ushlagich va tasdiq tugmalari. BUYRUQLAR YO'Q — GitHub bilan hamma ish AI orqali, oddiy suhbatda
(tool'lar: core/github_tools.py → core/github_ops.run()).

Bu router faqat ikki xavfsizlik vazifasi uchun kerak:
  * Token ushlagich: GitHub tokeni yozilgan xabar DARHOL o'chiriladi va AI/xotira/boshqa handler'larga HECH QACHON yetmaydi
    (ai_chat'dan oldin ulanadi). Shaxsiy chatda token avtomatik ulanadi; guruhda — o'chirishga urinamiz va revoke qilishni eslatamiz.
  * Tasdiq tugmalari: push/PR/merge/... uchun faqat shu foydalanuvchi, faqat shaxsiy chat, bir martalik, 10 daqiqa.
"""
from __future__ import annotations

import html
import logging

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, Message

import core.github_backup as backup
import core.github_ops as ops
import core.github_sandbox as sb
from core.github_sandbox import GitHubError

logger = logging.getLogger("handlers.github")
router = Router()


# ── Token ushlagich: ai_chat va boshqa hamma narsadan OLDIN ─────────────────────
@router.message(F.chat.type == "private", F.text.func(lambda t: bool(sb.find_token(t))))
async def private_token(message: Message):
    token = sb.find_token(message.text)
    deleted = True
    try:
        await message.delete()
    except Exception:  # noqa: BLE001
        deleted = False
    try:
        me = await ops.connect(message.bot, message.from_user.id, token)
    except GitHubError as e:
        await message.answer("❌ " + html.escape(sb.redact(str(e), token), quote=False)
                             + ("" if deleted else "\n⚠️ Tokenli xabarni o'zingiz o'chirib qo'ying."))
        return
    lines = [f"✅ GitHub ulandi: <b>{html.escape(me['login'])}</b> ({'classic' if me['classic'] else 'fine-grained'} token). "
             f"Token shifrlab saqlandi, men uni ko'rmayman."]
    lines += ["⚠️ " + html.escape(w) for w in me["warnings"]]
    if not deleted:
        lines.append("⚠️ Tokenli xabarni o'chira olmadim — uni o'zingiz o'chirib qo'ying.")
    if len(message.text.strip()) > len(token) + 8:
        lines.append("ℹ️ Xabaringizda token bor edi, shuning uchun u AI'ga yuborilmadi. Gapingizning boshqa qismini qayta yozing.")
    lines.append("📦 " + html.escape(backup.disclosure()))
    lines.append("\n💬 Endi menga oddiy yozing, masalan: «repolarimni ko'rsat», «<i>repo</i>ni klon qil», «<i>repo</i>dagi xatoni tuzat va push qil», "
                 "«falonchining GitHub profili haqida ma'lumot ber». Yozuvchi amallar (push, PR, merge...) uchun tasdiq tugmasi chiqadi. "
                 "GitHub'dan chiqish uchun «GitHub'dan chiq» deng.")
    await message.answer("\n".join(lines))


@router.message(F.chat.type.in_({"group", "supergroup"}), F.text.func(lambda t: bool(sb.find_token(t))))
async def group_token(message: Message):
    try:
        await message.delete()
        gone = "Xabarni o'chirdim."
    except Exception:  # noqa: BLE001
        gone = "Xabarni o'chira olmadim — o'zingiz o'chiring."
    await message.answer(f"🚨 Guruhga GitHub token yuborildi! {gone} Token OSHKOR bo'ldi hisoblanadi: darhol GitHub → Settings → "
                         f"Developer settings'dan uni o'chirib (revoke) yangisini yarating. Tokenni faqat menga SHAXSIY chatda yuboring.")


# ── Tasdiq tugmalari ───────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("gh:"))
async def confirm_cb(call: CallbackQuery, bot: Bot):
    parts = (call.data or "").split(":", 2)
    if len(parts) != 3 or parts[1] not in ("ok", "no"):
        await call.answer("Noto'g'ri so'rov", show_alert=True)
        return
    _, act, pid = parts
    uid = call.from_user.id
    if call.message is None or call.message.chat.type != "private" or call.message.chat.id != uid:
        await call.answer("Faqat shaxsiy chatda.", show_alert=True)
        return
    p = ops.pop_pending(pid, uid)      # bir martalik; faqat egasi; muddati o'tmagan
    if p is None:
        await call.answer("Bu so'rov eskirgan yoki allaqachon ishlatilgan.", show_alert=True)
        try:
            await call.message.edit_reply_markup(reply_markup=None)
        except Exception:  # noqa: BLE001
            pass
        return
    if act == "no":
        await call.message.edit_text(f"{p.summary}\n\n❌ <b>Bekor qilindi.</b>")
        await call.answer("Bekor qilindi")
        return
    await call.answer("Bajarilmoqda…")
    await call.message.edit_text(f"{p.summary}\n\n⏳ <i>Bajarilmoqda…</i>")
    res = await ops.execute_pending(bot, uid, p)
    outcome = ("❌ " + html.escape(str(res["error"]), quote=False)) if res.get("error") else \
        "✅ " + html.escape(sb.clip(str(res.get("text") or "Bajarildi."), 1500), quote=False)
    await call.message.edit_text(f"{p.summary}\n\n{outcome}")
