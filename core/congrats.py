"""
Kalendar tabriklari — admin "DD-MM matn" ko'rinishida sana+matn qo'shadi, bot o'sha kuni
soat 09:00 (Toshkent) da guruhga avtomatik yuboradi (har yili takrorlanadi).

ESLATMA: bu "avto-tabriklash"ning TUG'ILGAN KUN emas, KALENDAR (bayram/muhim sana) versiyasi —
loyihada foydalanuvchilarning tug'ilgan sanasi haqida ma'lumot yo'q. Agar aynan tug'ilgan kunlarni
tabriklash kerak bo'lsa, buni alohida aytib bering (manbasini ko'rsatib) — alohida qilib beraman.
"""
import re

import core.tgdb as tgdb

MAX_ITEMS = 50
MAX_TEXT = 500
_DATE_RE = re.compile(r"^(\d{1,2})-(\d{1,2})\s+(.+)$", re.DOTALL)


def _bucket(chat_id: int) -> list:
    return tgdb.get().setdefault("congrats", {}).setdefault(str(chat_id), [])


def get(chat_id: int) -> list[dict]:
    return _bucket(chat_id)


async def add(bot, chat_id: int, raw: str) -> tuple[bool, str]:
    m = _DATE_RE.match(raw.strip())
    if not m:
        return False, "Format: <code>DD-MM matn</code> (masalan: <code>08-03 Xotin-qizlar bayrami bilan!</code>)"
    day, month, text = int(m.group(1)), int(m.group(2)), " ".join(m.group(3).split())[:MAX_TEXT]
    if not (1 <= day <= 31 and 1 <= month <= 12):
        return False, "Sana noto'g'ri."
    items = _bucket(chat_id)
    if len(items) >= MAX_ITEMS:
        return False, f"Eng ko'pi {MAX_ITEMS} ta tabrik qo'shish mumkin."
    items.append({"day": day, "month": month, "text": text})
    await tgdb.save(bot, force=True)
    return True, ""


async def remove(bot, chat_id: int, index: int) -> bool:
    items = _bucket(chat_id)
    if 0 <= index < len(items):
        items.pop(index)
        await tgdb.save(bot, force=True)
        return True
    return False


def all_chats() -> list[int]:
    return [int(cid) for cid in tgdb.get().get("congrats", {})]


def for_date(chat_id: int, day: int, month: int) -> list[str]:
    return [it["text"] for it in get(chat_id) if it["day"] == day and it["month"] == month]
