"""
Userbot login (Telethon) — StokerDownloader/_userbot_send_code va
_userbot_sign_in_code/_userbot_sign_in_password patternidan.

Oqim: /userbot komandasi -> telefon raqam so'raladi -> Telegram SMS/ilova orqali
kod yuboradi -> foydalanuvchi kodni yozadi -> (agar 2FA yoqilgan bo'lsa) parol
so'raladi -> session_string olinadi -> shifrlab accounts_store'ga saqlanadi.

Login jarayoni tugagunча TelegramClient xotirada (_pending_clients) ushlab
turiladi — negaki ketma-ket bir nechta xabar (kod, parol) kerak bo'ladi.
"""
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError

from aiogram import Bot
from core.accounts_store import save_user_secret
import core.pending_input as pending_input

_pending_clients: dict[int, dict] = {}  # user_id -> {"client":, "phone":, "phone_code_hash":}


async def start_login(user_id: int, api_id: int, api_hash: str, phone: str) -> str:
    """Kod yuborishni boshlaydi. Muvaffaqiyatli bo'lsa 'code_sent' qaytaradi."""
    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.connect()
    sent = await client.send_code_request(phone)

    _pending_clients[user_id] = {
        "client": client,
        "phone": phone,
        "phone_code_hash": sent.phone_code_hash,
        "api_id": api_id,
        "api_hash": api_hash,
    }
    pending_input.set(user_id, "userbot_wait_code")
    return "code_sent"


async def submit_code(user_id: int, code: str) -> str:
    """Kodni tasdiqlaydi. Qaytaradi: 'success' | 'need_password'."""
    entry = _pending_clients.get(user_id)
    if not entry:
        return "no_session"

    client: TelegramClient = entry["client"]
    try:
        await client.sign_in(
            phone=entry["phone"], code=code, phone_code_hash=entry["phone_code_hash"]
        )
    except SessionPasswordNeededError:
        pending_input.set(user_id, "userbot_wait_password")
        return "need_password"
    except PhoneCodeInvalidError:
        return "invalid_code"

    return "success"


async def submit_password(user_id: int, password: str) -> str:
    entry = _pending_clients.get(user_id)
    if not entry:
        return "no_session"
    client: TelegramClient = entry["client"]
    try:
        await client.sign_in(password=password)
    except Exception:
        return "invalid_password"
    return "success"


async def finalize_login(bot: Bot, user_id: int) -> str:
    """Session string'ni chiqarib, shifrlab saqlaydi va clientni yopadi."""
    entry = _pending_clients.pop(user_id, None)
    if not entry:
        return ""
    client: TelegramClient = entry["client"]
    session_string = client.session.save()
    await save_user_secret(bot, user_id, "telegram_session", session_string)
    # api_id/api_hash ham saqlanadi — bot qayta ishga tushganda userbot'ni
    # avtomatik qayta ulash uchun kerak (core/userbot_runtime.py)
    await save_user_secret(bot, user_id, "api_id", str(entry["api_id"]))
    await save_user_secret(bot, user_id, "api_hash", entry["api_hash"])
    await client.disconnect()
    pending_input.clear(user_id)
    return session_string


def cancel_login(user_id: int):
    entry = _pending_clients.pop(user_id, None)
    if entry:
        import asyncio
        asyncio.create_task(entry["client"].disconnect())
    pending_input.clear(user_id)
