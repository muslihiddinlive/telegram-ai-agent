"""
Admin panel xabarlari.

  - BITTA foydalanuvchiga xabar: superadmin VA bot adminlari (send_dm).
  - HAMMAGA xabar (broadcast): FAQAT superadmin (broadcast) — ruxsat bu yerda SERVER tomonida tekshiriladi,
    panel tugmasining yashirinligiga tayanilmaydi.

Qarorlar:
  - Xabar jo'natuvchi nomisiz ketadi ("Admin xabari" / "E'lon"): panel superadmin identligini adminlardan ataylab
    yashiradi (admin/panel.py), xabar orqali ochilib qolmasin.
  - Matn HTML-escape qilinadi: admin yozgan `<` `&` aynan o'zi ko'rinadi, buzuq teg yetkazishni to'xtatmaydi.
  - Broadcast: bloklangan foydalanuvchilar va jo'natuvchining o'zi chiqarib tashlanadi; ~16 xabar/s (Telegram limitidan past),
    FloodWait'da kutib 1 marta qayta uriniladi; botni bloklaganlar/hech qachon /start bosmaganlar "yetkazilmadi" deb sanaladi
    (db["users"]ga guruhdagi faollikdan ham tushadi, shuning uchun bu normal). Bir vaqtda faqat bitta broadcast.
  - Oddiy adminlarga soatiga ADMIN_MSG_PER_HOUR ta xabar limiti (spam/suiiste'molga qarshi). Superadminga limit yo'q.
  - Har bir yuborish logga yoziladi (kim, kimga, uzunligi) — matnning o'zi emas.
"""
from __future__ import annotations

import asyncio
import html
import logging
import time
from collections import defaultdict, deque

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter

import core.roles as roles
import core.tgdb as tgdb

logger = logging.getLogger("admin_messaging")

MAX_TEXT = 3500  # Telegram limiti 4096; sarlavha va escape uchun zaxira
ADMIN_MSG_PER_HOUR = 30
BROADCAST_DELAY = 0.06
MAX_RETRY_AFTER = 60

_admin_sent: dict[int, deque] = defaultdict(deque)
_broadcast_active = False


def can_message_user(user_id: int) -> bool:
    return roles.is_superadmin(user_id) or roles.is_admin(user_id)


def can_broadcast(user_id: int) -> bool:
    return roles.is_superadmin(user_id)


def format_dm(text: str) -> str:
    return f"📩 <b>Admin xabari</b>\n\n{html.escape(text)}"


def format_broadcast(text: str) -> str:
    return f"📢 <b>E'lon</b>\n\n{html.escape(text)}"


def validate_text(text: str | None) -> str | None:
    """Xato matnini qaytaradi yoki None (yaroqli)."""
    if not text or not text.strip():
        return "Xabar matni bo'sh."
    if len(text.strip()) > MAX_TEXT:
        return f"Xabar juda uzun ({len(text.strip())} belgi). Eng ko'pi {MAX_TEXT}."
    return None


def admin_rate_wait(user_id: int, now: float | None = None) -> int:
    """Oddiy admin uchun limit oshgan bo'lsa kutish soniyalari, bo'lmasa 0 (va hisoblaydi). Superadmin — har doim 0."""
    if roles.is_superadmin(user_id):
        return 0
    now = time.time() if now is None else now
    q = _admin_sent[user_id]
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) >= ADMIN_MSG_PER_HOUR:
        return int(3600 - (now - q[0])) + 1
    q.append(now)
    return 0


def recipients(sender_id: int) -> list[int]:
    """Broadcast qabul qiluvchilari: bloklanmagan hamma foydalanuvchi, jo'natuvchining o'zisiz."""
    ids = []
    for uid, rec in tgdb.get()["users"].items():
        if rec.get("role") == "blocked" or not str(uid).lstrip("-").isdigit():
            continue
        if int(uid) != sender_id:
            ids.append(int(uid))
    return ids


async def send_one(bot, chat_id: int, html_text: str) -> tuple[bool, str | None]:
    """(yetkazildi, sabab). FloodWait'da bir marta kutib qayta urinadi."""
    for attempt in range(2):
        try:
            await bot.send_message(chat_id, html_text)
            return True, None
        except TelegramRetryAfter as e:
            if attempt == 0 and e.retry_after <= MAX_RETRY_AFTER:
                await asyncio.sleep(e.retry_after + 1)
                continue
            return False, "flood"
        except TelegramForbiddenError:
            return False, "bot bloklangan"
        except TelegramBadRequest:
            return False, "chat topilmadi"
        except Exception as e:  # noqa: BLE001
            return False, type(e).__name__
    return False, "flood"


async def send_dm(bot, sender_id: int, target_id: int, text: str) -> tuple[bool, str]:
    """Bitta foydalanuvchiga xabar. (ok, foydalanuvchiga ko'rsatiladigan matn)."""
    if not can_message_user(sender_id):
        return False, "Ruxsat yo'q."
    if err := validate_text(text):
        return False, err
    wait = admin_rate_wait(sender_id)
    if wait:
        return False, f"Xabar limiti tugadi (soatiga {ADMIN_MSG_PER_HOUR} ta). Taxminan {wait // 60 + 1} daqiqadan keyin urinib ko'ring."
    ok, reason = await send_one(bot, target_id, format_dm(text.strip()))
    logger.info("admin_msg by=%s to=%s len=%d ok=%s", sender_id, target_id, len(text.strip()), ok)
    if ok:
        return True, f"✅ Xabar {target_id} ga yuborildi."
    return False, f"⚠️ Yetkazilmadi ({reason}). Foydalanuvchi botni /start qilmagan yoki bloklagan bo'lishi mumkin."


async def broadcast(bot, sender_id: int, text: str) -> dict:
    """Hammaga xabar (FAQAT superadmin). {"total","sent","failed","reasons":{sabab: soni}} qaytaradi yoki {"error": ...}."""
    global _broadcast_active
    if not can_broadcast(sender_id):
        return {"error": "Ruxsat yo'q: broadcast faqat superadmin uchun."}
    if err := validate_text(text):
        return {"error": err}
    if _broadcast_active:
        return {"error": "Boshqa broadcast hozir ishlayapti — tugashini kuting."}
    _broadcast_active = True
    try:
        msg = format_broadcast(text.strip())
        targets = recipients(sender_id)
        sent, reasons = 0, defaultdict(int)
        for chat_id in targets:
            ok, reason = await send_one(bot, chat_id, msg)
            if ok:
                sent += 1
            else:
                reasons[reason or "?"] += 1
            await asyncio.sleep(BROADCAST_DELAY)
        logger.info("broadcast by=%s total=%d sent=%d len=%d", sender_id, len(targets), sent, len(text.strip()))
        return {"total": len(targets), "sent": sent, "failed": len(targets) - sent, "reasons": dict(reasons)}
    finally:
        _broadcast_active = False


def is_broadcast_active() -> bool:
    return _broadcast_active
