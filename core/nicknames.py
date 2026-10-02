"""
Foydalanuvchilarning maxsus taxalluslari — AI va guruh xabarlarida ism o'rniga shu ishlatiladi.
Masalan: ID 8054272729 -> "Omirbayev aka" (standart, birinchi ishga tushishda bir marta o'rnatiladi).
Foydalanuvchining o'zi /laqab buyrug'i bilan o'z taxallusini istalgan vaqt o'zgartira yoki o'chira oladi.
"""
import core.tgdb as tgdb

MAX_LEN = 40
# Standart taxalluslar: birinchi ishga tushishda bir marta o'rnatiladi (keyin foydalanuvchi o'zgartirsa, qayta yozilmaydi)
_DEFAULT_SEED = {8054272729: "Omirbayev aka"}


def _bucket() -> dict:
    return tgdb.get().setdefault("nicknames", {})


def get(user_id: int) -> str | None:
    return _bucket().get(str(user_id))


async def set(bot, user_id: int, nickname: str | None):
    bucket = _bucket()
    nickname = (nickname or "").strip()[:MAX_LEN]
    if nickname:
        bucket[str(user_id)] = nickname
    else:
        bucket.pop(str(user_id), None)
    await tgdb.save(bot, force=True)


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
