"""
Doimiy DB qatlami — mafia_host_bot/src/tgdb.py patternidan.

Nega bu yechim tanlandi (userbot-ai/db_store.py'dagi oddiy matn-blob o'rniga):
  - Butun DB bitta JSON fayl (data/db.json) sifatida RAM+disk'da saqlanadi —
    Telegram xabar belgi limitiga (4096) hech qachon urilmaymiz.
  - Har o'zgarishdan keyin fayl DB_GROUP_ID guruhiga DOCUMENT sifatida
    yuboriladi/yangilanadi (edit_message_media — xabar ID o'zgarmaydi) va PIN qilinadi.
  - Disk tozalansa ham (masalan Render qayta deploy qilganda), bot pin qilingan
    xabardan faylni qayta yuklab, hech narsa yo'qotmasdan davom etadi.

# TODO: agar concurrency yuqori bo'lsa, asyncio.Lock() qo'shing (StokerDownloader
# repodagi _state_lock namunasiga qarang).
"""
from __future__ import annotations
import json
import os
import asyncio
from aiogram import Bot
from aiogram.types import BufferedInputFile

import config

LOCAL_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "db.json")

DEFAULT_DB = {
    "users": {},            # user_id(str) -> {"role": "pending"/"approved", "daily_limit":..., ...} (core/roles.py)
    "admins": {},           # user_id(str) -> {"name": str} — faqat superadmin tayinlagan adminlar
    "channels": {},         # chat_id(str) -> {"title": str, "added_by": int}
    "ai_sessions": {},      # user_id(str) -> {"encrypted_session": str}  (crypto_store orqali)
    "topics": {},           # user_id(str) -> {thread_id(str): {"title":, "history": []}}
    "auto_reply": {},       # owner_id(str) -> {"keywords": [...], "away_delay":, "last_owner_activity": {}}
    "settings": {},
}

_cache: dict | None = None
_pinned_msg_id: int | None = None
_dirty: bool = False
_flush_lock = None  # asyncio.Lock() — birinchi save() chaqirilganda yaratiladi
_flusher_task = None
_bot_ref: Bot | None = None
FLUSH_INTERVAL_SECONDS = 5


async def _find_pinned_db_message(bot: Bot) -> int | None:
    chat = await bot.get_chat(config.DB_GROUP_ID)
    if chat.pinned_message:
        return chat.pinned_message.message_id
    return None


async def load(bot: Bot) -> dict:
    global _cache, _pinned_msg_id, _bot_ref, _flush_lock, _flusher_task
    _bot_ref = bot
    if _flush_lock is None:
        _flush_lock = asyncio.Lock()
    os.makedirs(os.path.dirname(LOCAL_FILE), exist_ok=True)

    if os.path.exists(LOCAL_FILE):
        with open(LOCAL_FILE, "r", encoding="utf-8") as f:
            _cache = json.load(f)
    else:
        pinned_id = await _find_pinned_db_message(bot)
        if pinned_id:
            file = await bot.get_file((await bot.forward_message(
                chat_id=config.SUPERADMIN_ID, from_chat_id=config.DB_GROUP_ID, message_id=pinned_id
            )).document.file_id)
            downloaded = await bot.download_file(file.file_path)
            _cache = json.loads(downloaded.read())
            _pinned_msg_id = pinned_id
            with open(LOCAL_FILE, "w", encoding="utf-8") as f:
                json.dump(_cache, f, ensure_ascii=False, indent=2)
        else:
            _cache = dict(DEFAULT_DB)

    if _flusher_task is None:
        _flusher_task = asyncio.create_task(_background_flusher())

    return _cache


async def _background_flusher():
    """
    StokerDownloader/_state_flusher_loop patternidan — tez-tez ketma-ket
    yozishlarni bittalashtiradi: har FLUSH_INTERVAL_SECONDS'da faqat
    "dirty" bo'lsa bitta marta Telegram'ga yozadi (rate-limit'dan qochish).
    Kritik amallar uchun save(force=True) chaqirib, darhol yozdirish mumkin.
    """
    global _dirty
    while True:
        await asyncio.sleep(FLUSH_INTERVAL_SECONDS)
        if _dirty:
            await _flush_now()


async def _flush_now():
    global _dirty, _pinned_msg_id
    async with _flush_lock:
        if not _dirty or _cache is None or _bot_ref is None:
            return
        os.makedirs(os.path.dirname(LOCAL_FILE), exist_ok=True)
        with open(LOCAL_FILE, "w", encoding="utf-8") as f:
            json.dump(_cache, f, ensure_ascii=False, indent=2)

        data_bytes = json.dumps(_cache, ensure_ascii=False, indent=2).encode("utf-8")
        doc = BufferedInputFile(data_bytes, filename="db.json")

        if _pinned_msg_id is None:
            _pinned_msg_id = await _find_pinned_db_message(_bot_ref)

        if _pinned_msg_id:
            try:
                from aiogram.types import InputMediaDocument
                await _bot_ref.edit_message_media(
                    chat_id=config.DB_GROUP_ID,
                    message_id=_pinned_msg_id,
                    media=InputMediaDocument(media=doc),
                )
                _dirty = False
                return
            except Exception:
                pass

        sent = await _bot_ref.send_document(config.DB_GROUP_ID, doc, caption="#DB backup")
        await _bot_ref.pin_chat_message(config.DB_GROUP_ID, sent.message_id, disable_notification=True)
        _pinned_msg_id = sent.message_id
        _dirty = False


async def save(bot: Bot, force: bool = False):
    """
    Odatiy holda faqat "dirty" belgisini qo'yadi — haqiqiy yozish
    background flusher orqali bir necha soniyadan keyin bajariladi.
    Kritik amallar (masalan pul/ruxsat berish) uchun force=True bering —
    o'sha zahoti Telegram'ga yozadi.
    """
    global _dirty, _bot_ref
    if _cache is None:
        raise RuntimeError("DB yuklanmagan — avval load() chaqiring")
    _bot_ref = bot
    _dirty = True
    if force:
        await _flush_now()


async def force_flush():
    """Bot to'xtatilishidan oldin (shutdown) qoldiq o'zgarishlarni yozib qo'yish uchun."""
    if _dirty:
        await _flush_now()


def get() -> dict:
    if _cache is None:
        raise RuntimeError("DB yuklanmagan — avval load(bot) chaqiring (main.py startup'da)")
    return _cache
