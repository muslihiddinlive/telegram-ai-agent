"""
Guruhda bot javobini FAQAT tanlangan foydalanuvchilarga cheklash —
guruh egasi/admini (bizning superadmin/admin tizimimizdan MUSTAQIL —
bu Telegram darajasidagi guruh adminligi) buni o'rnatadi.

Agar biror guruh uchun ro'yxat o'rnatilmagan bo'lsa — standart xatti-harakat
davom etadi (core/roles.py'dagi global ruxsat tizimi ishlaydi).
Ro'yxat o'rnatilgan bo'lsa — FAQAT shu username'lar javob oladi, qolganlar
uchun bot butunlay jim qoladi (shovqin qilmaslik uchun xato ham yozmaydi).
"""
import core.tgdb as tgdb


def _bucket(chat_id: int) -> dict:
    db = tgdb.get()
    return db.setdefault("group_settings", {}).setdefault(str(chat_id), {})


async def set_allowed_responders(bot, chat_id: int, usernames: list[str], set_by: int):
    """usernames — '@' belgisisiz, kichik harfda saqlanadi (Telegram username'lar case-insensitive)."""
    bucket = _bucket(chat_id)
    bucket["allowed_usernames"] = [u.lstrip("@").lower() for u in usernames]
    bucket["set_by"] = set_by
    await tgdb.save(bot, force=True)


async def clear_allowed_responders(bot, chat_id: int):
    bucket = _bucket(chat_id)
    bucket.pop("allowed_usernames", None)
    await tgdb.save(bot, force=True)


def get_allowed_responders(chat_id: int) -> list[str] | None:
    db = tgdb.get()
    bucket = db.get("group_settings", {}).get(str(chat_id), {})
    return bucket.get("allowed_usernames")  # None = cheklov yo'q


def is_allowed_in_group(chat_id: int, username: str | None) -> bool:
    """
    True qaytaradi agar: (a) shu guruh uchun ro'yxat o'rnatilmagan bo'lsa
    (cheklov yo'q), YOKI (b) foydalanuvchi ro'yxatda bo'lsa.
    """
    allowed = get_allowed_responders(chat_id)
    if allowed is None:
        return True  # cheklov yo'q — standart (global rol) tizimi ishlaydi
    if not username:
        return False  # username'i yo'q foydalanuvchi ro'yxatga kira olmaydi
    return username.lower() in allowed
