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
import core.history_summarizer as history_summarizer
import core.token_usage as token_usage

MAX_HISTORY = 50  # oxirida SO'Z-MA-SO'Z ushlab turiladigan "yaqin" xabarlar soni
SUMMARIZE_BATCH = 10  # shuncha ORTIQCHA xabar yig'ilgach, BIR YO'LA (kamroq AI-chaqiruv
# bilan) eski xulosaga QO'SHIB, yangilangan xulosaga aylantiriladi — har xabarda
# emas, har 10 ta ortiqcha xabarda BITTA qo'shimcha AI-chaqiruv (arzonroq).


def _key(thread_id: int | None) -> str:
    return str(thread_id) if thread_id is not None else "general"


def _get_session(user_id: int, thread_id: int | None) -> dict:
    db = tgdb.get()
    topics = db.setdefault("topics", {}).setdefault(str(user_id), {})
    session = topics.setdefault(_key(thread_id), {"title": None, "history": [], "summary": ""})
    session.setdefault("summary", "")  # eski (bu xususiyat qo'shilishidan oldingi) sessiyalarda yo'q bo'lishi mumkin
    return session


def get_history(user_id: int, thread_id: int | None) -> list[dict]:
    return _get_session(user_id, thread_id)["history"]


def get_summary(user_id: int, thread_id: int | None) -> str:
    """Suhbatning ESKI (endi so'z-ma-so'z saqlanmaydigan) qismining xulosasi —
    bo'sh qator qaytsa, hali xulosaga aylantiriladigan darajada uzun bo'lmagan."""
    return _get_session(user_id, thread_id)["summary"]


async def append_and_save(bot: Bot, user_id: int, thread_id: int | None, role: str, content: str):
    session = _get_session(user_id, thread_id)
    session["history"].append({"role": role, "content": content})

    # Xotira "cheksiz" his qilinishi uchun: MAX_HISTORY+SUMMARIZE_BATCH'dan
    # oshib ketsa, ENG ESKI SUMMARIZE_BATCH ta xabar butunlay TASHLAB
    # YUBORILMAYDI — avval ularning MAZMUNI xulosaga (eski xulosa bilan
    # birlashtirilib) qo'shib qo'yiladi, keyingina tarixdan olib tashlanadi.
    if len(session["history"]) > MAX_HISTORY + SUMMARIZE_BATCH:
        overflow = session["history"][:SUMMARIZE_BATCH]
        session["history"] = session["history"][SUMMARIZE_BATCH:]
        with token_usage.scope(purpose="summary"):
            session["summary"] = await history_summarizer.summarize(session["summary"], overflow)

    await tgdb.save(bot)


async def set_title(bot: Bot, user_id: int, thread_id: int, title: str):
    session = _get_session(user_id, thread_id)
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
