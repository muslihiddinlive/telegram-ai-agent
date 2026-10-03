"""
Foydalanuvchilarning maxsus taxalluslari — AI va guruh xabarlarida ism o'rniga shu ishlatiladi.
Masalan: ID 8054272729 -> "Omirbayev aka" (standart, birinchi ishga tushishda bir marta o'rnatiladi).
Foydalanuvchining o'zi /laqab buyrug'i bilan o'z taxallusini istalgan vaqt o'zgartira yoki o'chira oladi.

IKKI MANBA (ustuvorlik tartibida):
  1) ANIQ taxallus — /laqab bilan o'zi o'rnatgan (db["nicknames"]). Har doim ustun.
  2) AVTOMATIK taxallus — foydalanuvchi chatda "meni X deb chaqir" desa va /laqab ishlatmagan bo'lsa
     (db["auto_nicknames"], AI tool `set_my_nickname` orqali). U foydalanuvchiga bog'langan, ya'ni HAMMA
     guruhda ishlaydi — shuning uchun reklama/soxtalashtirishga yo'l qo'ymaslik uchun SERVER tomonida qattiq
     filtrlanadi (validate_auto): qisqa, faqat harf, havola/@/raqam-ko'p/reklama so'zlari/admin-bot
     so'zlari yo'q, kuniga 3 martadan ko'p almashtirib bo'lmaydi. /laqab -o'chir ikkalasini ham o'chiradi.
"""
import re
import time
import unicodedata

import core.tgdb as tgdb

MAX_LEN = 40
# Standart taxalluslar: birinchi ishga tushishda bir marta o'rnatiladi (keyin foydalanuvchi o'zgartirsa, qayta yozilmaydi)
_DEFAULT_SEED = {8054272729: "Omirbayev aka"}


AUTO_MAX_LEN = 24
AUTO_MAX_WORDS = 3
AUTO_MAX_DIGITS = 2
AUTO_MAX_CHANGES_PER_DAY = 3

# Reklama / tijorat / yo'naltirish — token ANIQ mos kelsa (qisqa so'zlar, "bet" "Betty"ga tegmasin)
_BLOCKED_EXACT = {
    "bet", "vip", "bot", "ai", "shop", "store", "market", "sale", "free", "promo", "ads", "ad", "pro", "official",
    "tg", "tme", "bonus", "kurs", "narx", "pul", "sotuv", "kanal", "chat", "guruh", "group", "channel", "link",
    "admin", "owner", "support", "moderator", "mod", "claude", "chatgpt", "gpt",
    "реклама", "админ", "бот", "канал", "казино", "бонус", "курс", "магазин",
}
# Reklama / tijorat / soxtalashtirish — token shu bilan BOSHLANSA (uzun o'zak)
_BLOCKED_STEMS = (
    "reklam", "advert", "kripto", "crypto", "bitcoin", "casino", "kazino", "stavka", "obuna", "subscri", "follow",
    "sotam", "sotil", "sotib", "chegirma", "aksiya", "discount", "daromad", "invest", "zayom", "kredit", "loan",
    "magazin", "dokon", "do'kon", "dukon", "premium", "rasmiy", "official", "administr", "moderat", "egasi",
    "paradoks", "telegram", "support", "xizmat", "service", "kanal", "channel",
    "реклам", "крипт", "казин", "магазин", "официал", "модератор", "администр",
)
_ALLOWED_RE = re.compile(r"^[^\W\d_](?:[^\W_]|['’ʻʼ`\- ])*$", re.UNICODE)  # harf bilan boshlanadi; harf/raqam/'/-/bo'shliq
_APOS = "'’ʻʼ`"


def _bucket() -> dict:
    return tgdb.get().setdefault("nicknames", {})


def _auto_bucket() -> dict:
    return tgdb.get().setdefault("auto_nicknames", {})


def get(user_id: int) -> str | None:
    """Aniq (/laqab) taxallus, bo'lmasa avtomatik (chatda aytilgan). Hammasi foydalanuvchi bo'yicha — barcha guruhlarda bir xil."""
    explicit = _bucket().get(str(user_id))
    if explicit:
        return explicit
    auto = _auto_bucket().get(str(user_id))
    return auto["n"] if auto else None


def source(user_id: int) -> str | None:
    """"explicit" | "auto" | None — /laqab javobida ko'rsatish uchun."""
    if _bucket().get(str(user_id)):
        return "explicit"
    return "auto" if _auto_bucket().get(str(user_id)) else None


async def set(bot, user_id: int, nickname: str | None):
    """/laqab uchun. Bo'sh qiymat — taxallusni o'chirish: avtomatik taxallus ham o'chadi (aks holda
    foydalanuvchi "o'chirdim" desa ham eski avtomatik ism qaytib turardi)."""
    bucket = _bucket()
    nickname = (nickname or "").strip()[:MAX_LEN]
    if nickname:
        bucket[str(user_id)] = nickname
    else:
        bucket.pop(str(user_id), None)
        _auto_bucket().pop(str(user_id), None)
    await tgdb.save(bot, force=True)


def validate_auto(raw: str) -> tuple[str | None, str | None]:
    """Chatda aytilgan taxallusni tekshiradi -> (tozalangan_nom, None) yoki (None, rad etish sababi)."""
    name = unicodedata.normalize("NFKC", raw or "")
    name = name.strip().strip("\"«»“”„'’ʻʼ`").strip()
    name = " ".join(name.split())
    if len(name) < 2:
        return None, "taxallus juda qisqa"
    if len(name) > AUTO_MAX_LEN:
        return None, f"taxallus {AUTO_MAX_LEN} belgidan oshmasin"
    if len(name.split()) > AUTO_MAX_WORDS:
        return None, f"taxallus {AUTO_MAX_WORDS} so'zdan oshmasin"
    low = name.lower()
    if "http" in low or "www" in low or "t.me" in low:
        return None, "havola bo'lishi mumkin emas"
    if not _ALLOWED_RE.match(name):
        return None, "faqat harflar (va ' - belgilari) ruxsat etiladi — havola, @, emoji, maxsus belgilar mumkin emas"
    if sum(ch.isdigit() for ch in name) > AUTO_MAX_DIGITS:
        return None, "taxallusda raqamlar ko'p"
    if sum(ch.isalpha() for ch in name) < 2:
        return None, "taxallusda kamida 2 ta harf bo'lsin"
    plain = low
    for a in _APOS:
        plain = plain.replace(a, "")
    for token in re.split(r"[\s\-]+", plain):
        if token in _BLOCKED_EXACT or any(token.startswith(stem.replace("'", "")) for stem in _BLOCKED_STEMS):
            return None, "reklama, tijorat yoki admin/bot nomiga o'xshash so'zlar mumkin emas"
    if name.isupper() and len(name) > 3:
        name = name.title()  # "QICHQIRIQ" kabi baqiriq ko'rinishini yumshatamiz
    return name, None


async def set_auto(bot, user_id: int, raw: str, now: float | None = None) -> tuple[bool, str]:
    """Chatda aytilgan taxallusni FILTRDAN o'tkazib saqlaydi. (ok, nom yoki xato matni)."""
    if _bucket().get(str(user_id)):
        return False, "Siz /laqab bilan taxallus o'rnatgansiz — u ustun. O'zgartirish yoki o'chirish uchun /laqab buyrug'idan foydalaning."
    name, reason = validate_auto(raw)
    if name is None:
        return False, reason or "taxallus qabul qilinmadi"
    now = time.time() if now is None else now
    rec = _auto_bucket().get(str(user_id)) or {"n": None, "t": 0, "h": []}
    history = [t for t in rec.get("h", []) if now - t < 86400]
    if rec.get("n") != name and len(history) >= AUTO_MAX_CHANGES_PER_DAY:
        return False, f"Taxallusni kuniga {AUTO_MAX_CHANGES_PER_DAY} martadan ko'p almashtirib bo'lmaydi — keyinroq urinib ko'ring."
    if rec.get("n") != name:
        history.append(now)
    _auto_bucket()[str(user_id)] = {"n": name, "t": int(now), "h": history}
    await tgdb.save(bot, force=True)
    return True, name


async def clear_auto(bot, user_id: int) -> bool:
    removed = _auto_bucket().pop(str(user_id), None) is not None
    if removed:
        await tgdb.save(bot, force=True)
    return removed


async def seed_defaults(bot):
    """Ishga tushganda bir marta chaqiriladi — hali taxallus o'rnatilmagan standart yozuvlarni qo'shadi."""
    bucket = _bucket()
    changed = False
    for uid, nick in _DEFAULT_SEED.items():
        if str(uid) not in bucket:
            bucket[str(uid)] = nick
            changed = True
    if changed:
        await tgdb.save(bot, force=True)
