"""
Moderatsiya buyruqlarining AI'siz (deterministik) yo'li.

Nega: oddiy "mute ber" LLM zanjiridan o'tsa — limit sarflanadi, tool tanlash/ID taxmini xato bo'lishi va, eng
yomoni, AI amal bajarilmagan bo'lsa ham "bajardim" deyishi mumkin edi. Aniq buyruqlar uchun bu yerda:
  buyruq turi + nishon + muddat KODDA aniqlanadi -> tekshiruvli moderation.dispatch -> javob ham kodda yoziladi.
Aniq buyruq bo'lmasa (savol, inkor, o'tgan zamon, nishon yo'q...) — hech narsa qilmaydi, xabar odatdagidek AI'ga ketadi.

Faqat xabar yozuvchi shu guruhda moderatsiya huquqiga ega bo'lsa ishlaydi (moderation.get_access).
"""
import html
import logging
import re

import core.bot_identity as bot_identity
import core.duration as duration
import core.group_memory as group_memory
import core.moderation as moderation

logger = logging.getLogger("mod_commands")

_AP = r"['’ʻ`]?"  # apostrof variantlari (qo'y / qoʻy / qoy)
# Buyruq (amr) shakllari: "ber", "qil", "qo'y", "et" ... — o'tgan zamon ("qildim") va inkor ("qilma") ularga TO'G'RI KELMAYDI
_IMP = rf"(?:ber(?:ing)?|qil(?:ing)?|qo{_AP}y(?:ing)?|et(?:ing)?|bo{_AP}lsin)\b"

# Tartib MUHIM: avval teskari amallar (unmute/unban), keyin ban/kick/mute
_ACTIONS: list[tuple[str, re.Pattern]] = [
    ("unmute", re.compile(rf"\bunmute\b|\bmute\s*(?:ni|{_AP}ni)?\s*(?:ol|oling|olib\s*tashla|olib\s*tashlang|bekor\s*qil|bekor\s*qiling)\b|\bovoz(?:ini)?\s*(?:och|oching|qaytar)\b")),
    ("unban", re.compile(rf"\bunban\b|\bban\s*(?:ni|{_AP}ni)?\s*(?:ol|oling|olib\s*tashla|olib\s*tashlang|bekor\s*qil|bekor\s*qiling)\b|\bblokdan\s*(?:chiqar|chiqaring|ol|oling)\b")),
    ("kick", re.compile(rf"\bkick\s*{_IMP}|\bkick\b$|\bhayda(?:ng)?\b|\bhaydab\s*(?:yubor|yuboring|tashla|tashlang)\b|\bchiqarib\s*(?:yubor|yuboring)\b")),
    ("ban", re.compile(rf"\bban\s*{_IMP}|\bban\b$|\bblokla(?:ng)?\b|\bbloklab\s*qo{_AP}y(?:ing)?\b")),
    ("mute", re.compile(rf"\bmute\s*{_IMP}|\bmute\b$|\bjim\s*(?:qil|qiling|qo{_AP}y|qo{_AP}ying|bo{_AP}l)\b|\bovozsiz\s*{_IMP}")),
]
_TOOL = {"mute": "mute_user", "unmute": "unmute_user", "ban": "ban_user", "unban": "unban_user", "kick": "kick_user"}
_TIMED = {"mute", "ban"}

# Savol, inkor, o'tgan/kelasi zamon — bular buyruq EMAS
_NOT_A_COMMAND = re.compile(
    rf"\?|\b(?:nima|nega|nimaga|qanday|qaysi|qachon|kim)\b|\bqil(?:ma|mang|maylik|ay|aman|amiz|di|dim|dik|gan|sa|sak|sam|ar|ib)\b"
    rf"|\bber(?:ma|mang|maylik|ay|aman|amiz|di|dim|dik|gan|sa|sak|sam|ar)\b|\bkerak\s*emas\b|\bbo{_AP}lmaydi\b|\bmumkin\s*emas\b"
)
_MENTION_RE = re.compile(r"@\w+")
_LEFTOVER_FILLER = {"ga", "ni", "ning", "dan", "ka", "qa", "bu", "shu", "uni", "buni", "ushbu", "odamni", "odam", "foydalanuvchini", "foydalanuvchi", "iltimos", "plz", "pls", "ber", "qil", "qo'y", "bering", "qiling", "et", "xohlaysan", "mumkin"}

_OK_TEXT = {
    "mute": "🔇 {name} mute qilindi ({dur}).",
    "unmute": "🔊 {name}ning ovozi ochildi (mute olindi).",
    "ban": "⛔ {name} ban qilindi ({dur}).",
    "unban": "✅ {name} blokdan chiqarildi.",
    "kick": "👢 {name} guruhdan haydaldi.",
}
_LABEL = {"mute": "Mute", "unmute": "Unmute", "ban": "Ban", "unban": "Unban", "kick": "Kick"}


def _norm(text: str) -> str:
    low = (text or "").lower()
    for ch in ("’", "ʻ", "ʼ", "`", "‘"):
        low = low.replace(ch, "'")
    return " ".join(low.split())


def detect_action(text: str) -> str | None:
    """Matn aniq moderatsiya BUYRUG'IMI? ('mute'|'unmute'|'ban'|'unban'|'kick') yoki None."""
    low = _norm(text)
    if not low or len(low) > 160 or _NOT_A_COMMAND.search(low):
        return None
    for action, pattern in _ACTIONS:
        if pattern.search(low):
            return action
    return None


def _leftover_words(low: str) -> list[str]:
    """Buyruq so'zi, nishon va muddat olib tashlangach qolgan 'begona' so'zlar — ko'p bo'lsa bu oddiy gap."""
    low = _MENTION_RE.sub(" ", low)
    for _, pat in _ACTIONS:
        low = pat.sub(" ", low)
    low = re.sub(r"\d+(?:[.,]\d+)?\s*[^\W\d_]*", " ", low)  # raqam + birlik ("14 daqiqaga")
    return [w for w in re.findall(r"[\w']+", low) if w not in _LEFTOVER_FILLER]


def _name(user_id: int, full_name: str | None, username: str | None = None) -> str:
    label = full_name or (f"@{username}" if username else str(user_id))
    return f"<b>{html.escape(label)}</b>"


async def _resolve_target(bot, message, text: str):
    """Nishon: (user_id, ism_html, None) yoki (None, None, xato_matni)."""
    chat_id = message.chat.id
    me = bot_identity.get_id()
    bot_un = (bot_identity.get_username() or "").lower()
    raw = message.text or message.caption or ""
    ents = message.entities or message.caption_entities or []

    # 1) Aniq odam tanlangan (text_mention)
    for e in ents:
        if e.type == "text_mention" and e.user and not e.user.is_bot:
            return e.user.id, _name(e.user.id, e.user.full_name, e.user.username), None

    # 2) @username — botning o'z indeksi (Bot API oddiy userni @username bo'yicha topa olmaydi)
    for e in ents:
        if e.type != "mention":
            continue
        uname = e.extract_from(raw).lstrip("@")
        if uname.lower() == bot_un:
            continue  # botning o'zi tag qilingan — nishon emas
        found = group_memory.find_user_id(chat_id, uname)
        if found:
            return found[0], _name(found[0], found[1], uname), None
        try:
            chat = await bot.get_chat(f"@{uname}")
            if chat.type == "private":
                return chat.id, _name(chat.id, getattr(chat, "full_name", None), uname), None
        except Exception:  # noqa: BLE001
            pass
        return None, None, (f"@{html.escape(uname)} ni topa olmadim: bu odam guruhda hali hech narsa yozmagan va botga "
                            f"ko'rinmagan. Uning xabariga <b>reply</b> qilib yozing yoki u bitta xabar yozsin.")

    # 3) Reply qilingan xabar muallifi
    r = message.reply_to_message
    if r is not None and r.from_user is not None and not r.from_user.is_bot and r.from_user.id != me:
        u = r.from_user
        return u.id, _name(u.id, u.full_name, u.username), None

    # 4) Matnda ism aytilgan ("Jasurga mute ber") — faqat YAGONA moslik bo'lsa
    cands = group_memory.candidates_by_text(chat_id, text)
    if len(cands) == 1:
        uid, n, u = cands[0]
        return uid, _name(uid, n, u), None
    if len(cands) > 1:
        listed = ", ".join(f"{html.escape(n)}" + (f" (@{u})" if u else "") for _, n, u in cands)
        return None, None, f"Qaysi biri? {listed}. @username yozing yoki xabariga reply qiling."
    return None, None, "Kimga? Uning xabariga <b>reply</b> qiling yoki <b>@username</b> yozing."


async def try_handle(message, access, bot_username: str | None = None) -> bool:
    """Xabar aniq moderatsiya buyrug'i bo'lsa — bajaradi, javob yozadi va True qaytaradi.
    Aks holda False (xabar odatdagidek AI'ga ketadi). `access` — moderation.get_access natijasi."""
    if access is None or message.from_user is None:
        return False
    raw = message.text or ""
    text = raw
    if bot_username:
        text = re.sub(rf"@{re.escape(bot_username)}", " ", text, flags=re.IGNORECASE)
    action = detect_action(text)
    if action is None:
        return False
    low = _norm(text)
    # Oddiy gap emas, qisqa buyruq bo'lsin ("mute" so'zi uchragan har qanday xabar emas)
    if len(_leftover_words(low)) > (2 if action not in ("mute", "ban", "kick") else 3):
        return False
    tool = _TOOL[action]
    if not access.allows(tool):
        return False  # huquqi yo'q — AI/oddiy yo'l o'zi javob beradi

    bot = message.bot
    uid, name_html, error = await _resolve_target(bot, message, text)
    if error:
        await message.reply(f"⚠️ {error}")
        return True
    if uid == message.from_user.id:
        await message.reply("⚠️ O'zingizga bu amalni qila olmayman.")
        return True

    minutes = None
    if action in _TIMED:
        durations = duration.parse_all(text)
        if len(durations) > 1:
            await message.reply("⚠️ Bir nechta muddat aytildi — bittasini yozing (masalan: <code>14 daqiqaga mute ber</code>).")
            return True
        minutes = durations[0] if durations else None

    args = {"user_id": uid}
    if minutes:
        args["minutes"] = minutes
    ctx = {"bot": bot, "chat_id": message.chat.id, "is_group": True, "mod": access, "mod_minutes": minutes}
    result = await moderation.dispatch(bot, tool, args, ctx)

    if result.get("ok"):
        dur = duration.fmt(minutes) if minutes else "cheksiz"
        await message.reply(_OK_TEXT[action].format(name=name_html, dur=dur))
    else:
        reason = result.get("message") or result.get("error") or "noma'lum xato"
        logger.info("MOD buyruq bajarilmadi: %s user=%s: %s", action, uid, reason)
        await message.reply(f"⚠️ {_LABEL[action]} bajarilmadi: {reason}")
    return True
