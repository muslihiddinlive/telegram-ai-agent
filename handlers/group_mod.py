"""
Guruh moderatsiyasi: .ban .unban .kick .mute .unmute .del (+ .modhelp).

Nega alohida router: ai_chat guruhda botga TAG qilinmagan / botning o'z xabariga REPLY bo'lmagan har qanday xabarni
e'tiborsiz qoldiradi — shuning uchun "foydalanuvchi xabariga reply + ban qil" yoki ".ban" botga yetib kelmasdi.
Bu router ai_chat'dan OLDIN turadi va tag shart emas. (Bot guruhda admin bo'lishi kerak — shunda barcha xabarlarni oladi.)

Sintaksis va muddat tahlili: core/dot_mod.py (StokerDownloader'dan). Ruxsat va bajarish — mavjud tekshiruvli yadro:
moderation.get_access (Telegram admin huquqi HAR AMAL uchun alohida) va moderation.dispatch (botning huquqi, adminlarni
himoyalash, natijani qayta o'qib tasdiqlash). Moderator bo'lmaganlarga bot JIM turadi (spam yo'q).
"""
import html
import logging

from aiogram import F, Router
from aiogram.types import Message

import config
import core.bot_identity as bot_identity
import core.dot_mod as dot_mod
import core.duration as duration
import core.mod_commands as mod_commands
import core.moderation as moderation
import core.roles as roles

logger = logging.getLogger("group_mod")
router = Router()

ANON_ADMIN_ID = 1087968824      # GroupAnonymousBot — anonim admin xabarlari
TELEGRAM_SERVICE_ID = 777000    # kanaldan avtomatik forward qilingan postlar

_TOOL = {"ban": "ban_user", "unban": "unban_user", "kick": "kick_user", "mute": "mute_user",
         "unmute": "unmute_user", "del": "delete_message"}
_LABEL = {"ban": "Ban", "unban": "Unban", "kick": "Kick", "mute": "Mute", "unmute": "Unmute", "del": "O'chirish"}
_PROTECTED_TOOLS = {"ban_user", "kick_user", "mute_user"}   # bot egasi/adminlariga qarshi guruh moderatori ishlata olmaydi


def _is_dot_command(message: Message) -> bool:
    return bool(message.text and dot_mod.COMMAND_PATTERN.match(message.text))


def _real_reply(message: Message):
    """Haqiqiy reply (forum mavzusida har xabar mavzu ildiziga 'reply' bo'lib ko'rinadi — u reply emas)."""
    r = message.reply_to_message
    if r is None:
        return None
    if getattr(message, "message_thread_id", None) and r.message_id == message.message_thread_id:
        return None
    return r


def _is_bot_staff(user_id: int) -> bool:
    return user_id == config.SUPERADMIN_ID or roles.is_superadmin(user_id) or roles.is_admin(user_id)


async def _resolve(bot, message: Message, parsed: dot_mod.Parsed):
    """Nishon: (user_id, ism_html, None) yoki (None, None, xato). Reply va aniq ko'rsatma bir-biriga zid bo'lsa — so'raydi."""
    explicit = None
    for e in (message.entities or []):
        if e.type == "text_mention" and e.user:
            explicit = (e.user.id, mod_commands._name(e.user.id, e.user.full_name, e.user.username))
            break
    if explicit is None and parsed.target:
        if parsed.target.startswith("@"):
            uid, name, err = await mod_commands.resolve_username(bot, message.chat.id, parsed.target[1:])
            if err:
                return None, None, err
            explicit = (uid, name)
        else:
            uid = int(parsed.target)
            explicit = (uid, f"<code>{uid}</code>")

    reply = None
    r = _real_reply(message)
    if r is not None:
        u = r.from_user
        if u is not None and u.id not in (ANON_ADMIN_ID, TELEGRAM_SERVICE_ID):
            reply = (u.id, mod_commands._name(u.id, u.full_name, u.username))
        elif explicit is None:
            return None, None, ("Bu xabar kanal yoki anonim admin nomidan yozilgan — foydalanuvchi emas. "
                                "Odamning o'z xabariga reply qiling yoki @username yozing.")
    if explicit and reply and explicit[0] != reply[0]:
        return None, None, "Reply ham, @user ham berdingiz va ular turli odam — bittasini ishlating."
    chosen = explicit or reply
    if chosen is None:
        return None, None, "Kimga? Uning xabariga <b>reply</b> qiling yoki <b>@username</b> / ID yozing."
    return chosen[0], chosen[1], None


def _ok_text(parsed: dot_mod.Parsed, name: str) -> str:
    a, mins = parsed.action, parsed.minutes
    if a == "ban":
        text = f"🚫 {name} guruhdan ban qilindi" + (f" ({duration.fmt(mins)})." if mins else ".")
    elif a == "unban":
        text = f"✅ {name} ban'dan chiqarildi."
    elif a == "kick":
        text = f"👢 {name} guruhdan chiqarildi (qaytib kira oladi)."
    elif a == "mute":
        text = f"🔇 {name} " + (f"{duration.fmt(mins)}ga mute qilindi." if mins else "butunlay mute qilindi.")
    else:
        text = f"🔊 {name} mute'dan chiqarildi."
    if parsed.reason:
        text += f"\nSabab: {html.escape(parsed.reason)}"
    return text


async def _delete(message: Message, bot, ctx: dict) -> None:
    r = _real_reply(message)
    if r is None:
        await message.reply("O'chirmoqchi bo'lgan xabaringizga <b>reply</b> qilib <code>.del</code> yozing.")
        return
    result = await moderation.dispatch(bot, "delete_message", {"message_id": r.message_id}, ctx)
    if result.get("ok"):
        try:
            await message.delete()           # buyruqning o'zi ham tozalansin
        except Exception:  # noqa: BLE001
            pass
    else:
        reason = result.get("message") or result.get("error") or "noma'lum xato"
        await message.reply(f"⚠️ O'chirib bo'lmadi: {reason}")


async def execute(message: Message) -> None:
    user = message.from_user
    if user is None:
        return
    parsed = dot_mod.parse(message.text or "")
    if parsed is None:
        return
    bot, chat_id = message.bot, message.chat.id

    if user.id == ANON_ADMIN_ID:
        await message.reply("⚠️ Anonim admin nomidan buyruq bajarib bo'lmaydi (kim ekanligingizni aniqlay olmayman) — "
                            "guruh sozlamalarida anonimlikni o'chirib qayta yozing.")
        return
    access = await moderation.get_access(bot, chat_id, user.id)
    if access is None:
        return                                # moderator emas — jim (spam va "buyruqlar mavjudligi" oshkor bo'lmasin)
    if parsed.action == "modhelp":
        await message.reply(dot_mod.HELP)
        return

    tool = _TOOL[parsed.action]
    if not access.allows(tool):
        right = moderation._RIGHT_FOR_TOOL.get(tool)
        await message.reply(f"⚠️ Sizda «{moderation._BOT_RIGHT_HELP.get(right, right)}» admin huquqi yo'q — "
                            f"bu amalni bajara olmaysiz.")
        return

    ctx = {"bot": bot, "chat_id": chat_id, "is_group": True, "mod": access, "mod_minutes": parsed.minutes}
    if parsed.action == "del":
        await _delete(message, bot, ctx)
        return

    uid, name, err = await _resolve(bot, message, parsed)
    if err:
        await message.reply(f"⚠️ {err}")
        return
    if uid == user.id:
        await message.reply("⚠️ O'zingizga bu amalni qila olmayman.")
        return
    if uid == bot_identity.get_id():
        await message.reply("⚠️ Botning o'ziga bu amalni qo'llab bo'lmaydi.")
        return
    if tool in _PROTECTED_TOOLS and _is_bot_staff(uid) and not _is_bot_staff(user.id):
        await message.reply("⛔️ Bu foydalanuvchiga bu amalni qo'llab bo'lmaydi.")
        return

    args = {"user_id": uid}
    if parsed.action in dot_mod.TIMED and parsed.minutes:
        args["minutes"] = parsed.minutes
    result = await moderation.dispatch(bot, tool, args, ctx)
    if result.get("ok"):
        await message.reply(_ok_text(parsed, name))
    else:
        reason = result.get("message") or result.get("error") or "noma'lum xato"
        logger.info("MOD .%s bajarilmadi: user=%s: %s", parsed.action, uid, reason)
        await message.reply(f"⚠️ {_LABEL[parsed.action]} bajarilmadi: {reason}")


@router.message(F.chat.type.in_({"group", "supergroup"}), _is_dot_command)
async def on_dot_command(message: Message):
    await execute(message)
