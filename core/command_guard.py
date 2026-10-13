"""
Noto'g'ri yozilgan komandalar (masalan "/vipchaatmode: on") AI-suhbatga tushib qolmasin.

Muammo: komanda hech bir handler'ga mos kelmasa, matn oddiy xabar sifatida AI'ga ketadi va AI "VIP rejim yoqildi" deb YOLG'ON
yozadi (u sozlamalarni o'zgartira olmaydi). Bu yerda: harf xatosi bo'lsa — to'g'ri komandani taklif qilamiz va AI'ga yubormaymiz.

Qoidalar:
  - Taklif faqat foydalanuvchi O'ZI ishlata oladigan komandalardan (superadminga xos /vipchatmode oddiy userga ko'rsatilmaydi).
  - Boshqa botga mo'ljallangan komanda ("/cmd@BoshqaBot") — jim yutiladi (bizniki emas, AI'ga ham bormasin).
  - Hech narsaga o'xshamaydigan, @bizning_bot siz komanda (masalan boshqa bot uchun "/help") — tegilmaydi (avvalgidek).
  - Komanda to'g'ri, lekin noto'g'ri chatda (masalan guruhda /profil) — qaysi chatda ishlashini aytamiz.
"""
from __future__ import annotations

import difflib
import re

import core.bot_identity as bot_identity
import core.roles as roles

_CMD_RE = re.compile(r"^/([A-Za-z0-9_]{1,32})(?:@(\w+))?(?=\s|$|:)")

PRIVATE_ONLY = {"profil", "start", "instagram", "gh"}
GROUP_ONLY = {"guruh_ruxsat", "guruh_ruxsat_ochirish", "chatmode", "qoida_qoshish", "qoidalar", "qoida_ochir", "taqiq_qoshish",
              "taqiq_ochir", "taqiqlar", "statistika", "top_faollar", "aireakmode", "antispam"}
EVERYWHERE = {"yangi_mavzu", "mavzular", "apikalit", "laqab", "site"}
STAFF_ONLY = {"panel"}
SUPERADMIN_ONLY = {"vipchatmode"}
KNOWN = PRIVATE_ONLY | GROUP_ONLY | EVERYWHERE | STAFF_ONLY | SUPERADMIN_ONLY | {"vipchatmode"}
CUTOFF = 0.75


def parse(text: str | None) -> tuple[str, str | None] | None:
    """("komanda", "@bot_nomi"|None) yoki None (komanda emas)."""
    m = _CMD_RE.match((text or "").strip())
    if not m:
        return None
    return m.group(1).lower(), (m.group(2).lower() if m.group(2) else None)


def visible_commands(user_id: int, chat_type: str) -> set[str]:
    """Shu foydalanuvchiga TAKLIF qilsa bo'ladigan komandalar (u ishlata oladiganlar, shu chat turida)."""
    in_group = chat_type in ("group", "supergroup")
    pool = set(EVERYWHERE) | (GROUP_ONLY if in_group else PRIVATE_ONLY)
    if roles.is_superadmin(user_id):
        pool |= STAFF_ONLY | SUPERADMIN_ONLY
    elif roles.is_admin(user_id):
        pool |= STAFF_ONLY
    return pool


def suggest(cmd: str, user_id: int, chat_type: str) -> str | None:
    matches = difflib.get_close_matches(cmd, sorted(visible_commands(user_id, chat_type)), n=1, cutoff=CUTOFF)
    return matches[0] if matches else None


def classify(text: str | None, user_id: int, chat_type: str) -> tuple[str, str | None] | None:
    """Qaror: None — tegmaymiz; ("foreign", None) — boshqa botniki, jim yutamiz; ("typo", to'g'ri_komanda);
    ("unknown", None) — bizga @ bilan yozilgan, lekin noma'lum; ("wrong_chat", "private"|"group")."""
    parsed = parse(text)
    if parsed is None:
        return None
    cmd, target = parsed
    mine = bot_identity.get_username()
    if target and mine and target != mine.lower():
        return "foreign", None
    in_group = chat_type in ("group", "supergroup")
    if cmd in KNOWN:
        if cmd in PRIVATE_ONLY and in_group:
            return "wrong_chat", "private"
        if cmd in GROUP_ONLY and not in_group:
            return "wrong_chat", "group"
        return None  # to'g'ri komanda va to'g'ri chat — o'z handler'iga ishlaydi (bu yerga odatda yetib kelmaydi)
    fix = suggest(cmd, user_id, chat_type)
    if fix:
        return "typo", fix
    if target:
        return "unknown", None  # "/narsa@bizning_bot" — aniq bizga
    return None


def reply_text(kind: str, cmd: str, extra: str | None) -> str:
    if kind == "typo":
        return f"❓ <code>/{cmd}</code> degan komanda yo'q. Balki <code>/{extra}</code> ni nazarda tutgandirsiz?"
    if kind == "wrong_chat":
        return ("ℹ️ Bu komanda faqat shaxsiy chatda ishlaydi." if extra == "private"
                else "ℹ️ Bu komanda faqat guruhda ishlaydi.")
    return f"❓ <code>/{cmd}</code> degan komanda yo'q."
