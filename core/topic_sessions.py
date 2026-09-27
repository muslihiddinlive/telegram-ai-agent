"""
Shaxsiy chatdagi Topics (Bot API 9.4, 2026-02-09) — har bir topic mustaqil
AI-suhbat sessiyasi sifatida ishlaydi.

Muhim: bu funksiya ishlashi uchun BotFather'da bot sozlamalarida
"Private Chat Topics" (yoki shunga o'xshash) yoqilgan bo'lishi kerak —
shundagina foydalanuvchi User.has_topics_enabled = true bo'ladi va
o'zi ham topic yarata oladi (agar allows_users_to_create_topics
cheklanmagan bo'lsa).

Har bir (user_id, thread_id) juftligi — alohida suhbat tarixi.
thread_id = None bo'lsa — "General" (topic tashqarisidagi asosiy chat).
"""
from aiogram import Bot
import core.tgdb as tgdb

MAX_HISTORY = 50  # oxirgi N ta xabar saqlanadi (AI kontekst uchun) — avval 20 edi,
# AI suhbatni "unutib qo'yayotgani" uchun kengaytirildi. Zamonaviy modellarning
# kontekst oynasi (odatda 32k-200k token) buni bemalol ko'taradi — 50 ta oddiy
# matn xabar odatda bir necha ming tokendan oshmaydi.


def _key(thread_id: int | None) -> str:
    return str(thread_id) if thread_id is not None else "general"


def get_history(user_id: int, thread_id: int | None) -> list[dict]:
    db = tgdb.get()
    topics = db.setdefault("topics", {}).setdefault(str(user_id), {})
    session = topics.setdefault(_key(thread_id), {"title": None, "history": []})
    return session["history"]


async def append_and_save(bot: Bot, user_id: int, thread_id: int | None, role: str, content: str):
    db = tgdb.get()
    topics = db.setdefault("topics", {}).setdefault(str(user_id), {})
    session = topics.setdefault(_key(thread_id), {"title": None, "history": []})
    session["history"].append({"role": role, "content": content})
    session["history"] = session["history"][-MAX_HISTORY:]
    await tgdb.save(bot)


async def set_title(bot: Bot, user_id: int, thread_id: int, title: str):
    db = tgdb.get()
    topics = db.setdefault("topics", {}).setdefault(str(user_id), {})
    session = topics.setdefault(_key(thread_id), {"title": None, "history": []})
    session["title"] = title
    await tgdb.save(bot)


async def create_topic(bot: Bot, user_id: int, name: str) -> int:
    """Bot tomonidan foydalanuvchi uchun yangi topic ochish (Bot API 9.4)."""
    topic = await bot.create_forum_topic(chat_id=user_id, name=name)
    await set_title(bot, user_id, topic.message_thread_id, name)
    return topic.message_thread_id


async def list_topics(user_id: int) -> dict:
    db = tgdb.get()
    return db.get("topics", {}).get(str(user_id), {})
