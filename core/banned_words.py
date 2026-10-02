"""
Guruhda taqiqlangan so'zlar — avtomatik nazorat: so'z uchrasa, xabar o'chiriladi (bot admin bo'lsa).
Har bir guruh uchun alohida ro'yxat; birinchi marta tekshirilganda standart ro'yxat ("dnx") bilan boshlanadi.
Guruh adminlari, bot adminlari va superadmin TEKSHIRILMAYDI (ularning xabari o'chirilmaydi).
"""
import re

import core.tgdb as tgdb

MAX_WORDS = 100
_DEFAULT_SEED = ["dnx"]


def _bucket() -> dict:
    return tgdb.get().setdefault("banned_words", {})


def get(chat_id: int) -> list[str]:
    bucket = _bucket()
    key = str(chat_id)
    if key not in bucket:
        bucket[key] = list(_DEFAULT_SEED)
    return bucket[key]


async def add(bot, chat_id: int, word: str) -> bool:
    word = word.strip().lower()
    if not word:
        return False
    words = get(chat_id)
    if word in words or len(words) >= MAX_WORDS:
        return False
    words.append(word)
    await tgdb.save(bot, force=True)
    return True


async def remove(bot, chat_id: int, word: str) -> bool:
    words = get(chat_id)
    word = word.strip().lower()
    if word not in words:
        return False
    words.remove(word)
    await tgdb.save(bot, force=True)
    return True


def find_match(chat_id: int, text: str) -> str | None:
    """Matnda taqiqlangan so'z (so'z o'zagi sifatida) uchrasa — o'sha so'zni qaytaradi."""
    low = (text or "").lower()
    for word in get(chat_id):
        if re.search(rf"(?<![a-zA-Z0-9'’ʻ]){re.escape(word)}", low):
            return word
    return None
