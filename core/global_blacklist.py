"""
GLOBAL qora ro'yxat — HAMMA guruhlarda ishlaydi (faqat superadmin boshqaradi, chunki
butun botga tegishli). core/banned_words.py'dan farqi: bu — bitta umumiy ro'yxat
(bot joylashgan har bir guruhga baravar qo'llanadi), ikkinchisi — har bir guruh o'zi
sozlaydigan, shu guruhga xos ro'yxat. Ikkalasi ham tekshiriladi.

Eskalatsiya: bir xabarda taqiqlangan so'z topilsa — xabar o'chiriladi va foydalanuvchining
shu guruhdagi "strike"i +1 bo'ladi (oynasi 24 soat). 3-strike — 1 soatga mute,
5-strike — ban. Guruh/bot adminlari TEKSHIRILMAYDI.
"""
import re
import time

import core.tgdb as tgdb

MAX_WORDS = 300
STRIKE_WINDOW = 24 * 3600
MUTE_AT, MUTE_MINUTES = 3, 60
BAN_AT = 5


def _words() -> list[str]:
    return tgdb.get().setdefault("global_blacklist", [])


def get() -> list[str]:
    return list(_words())


async def add(bot, word: str) -> bool:
    word = word.strip().lower()
    words = _words()
    if not word or word in words or len(words) >= MAX_WORDS:
        return False
    words.append(word)
    await tgdb.save(bot, force=True)
    return True


async def remove(bot, word: str) -> bool:
    word = word.strip().lower()
    words = _words()
    if word not in words:
        return False
    words.remove(word)
    await tgdb.save(bot, force=True)
    return True


def find_match(text: str) -> str | None:
    low = (text or "").lower()
    for word in _words():
        if re.search(rf"(?<![a-zA-Z0-9'’ʻ]){re.escape(word)}", low):
            return word
    return None


def _strikes_bucket(chat_id: int) -> dict:
    return tgdb.get().setdefault("blacklist_strikes", {}).setdefault(str(chat_id), {})


def register_strike(chat_id: int, user_id: int) -> int:
    """Strike +1 qo'shadi (24 soatlik oyna) va joriy sonini qaytaradi."""
    bucket = _strikes_bucket(chat_id)
    rec = bucket.setdefault(str(user_id), {"n": 0, "t": 0.0})
    now = time.time()
    if now - rec.get("t", 0) > STRIKE_WINDOW:
        rec["n"] = 0
    rec["n"] += 1
    rec["t"] = now
    return rec["n"]
