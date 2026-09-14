"""
Userbot'ni ishga tushirish — saqlangan session orqali Telethon clientni
background'da ulaydi va kiruvchi shaxsiy xabarlarni tinglaydi:
  - Agar EGASI o'zi yozsa -> mark_owner_activity (u band emasligini bildiradi)
  - Agar BOSHQA odam yozsa -> should_auto_reply() true bo'lsa va kalit-so'zga
    mos kelsa -> avtomatik javob yuboradi (StokerDownloader/away-mode patterni)

# TODO: bir nechta eganing userbot'ini bir vaqtda ishga tushirish uchun
# _running_clients lug'atida kuzatib, restart/health-check qo'shing.
"""
import asyncio
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from aiogram import Bot

from core.accounts_store import get_user_secret
import core.auto_reply as auto_reply

_running_clients: dict[int, TelegramClient] = {}


async def start_userbot_for_owner(bot: Bot, owner_id: int, api_id: int, api_hash: str):
    session_string = get_user_secret(owner_id, "telegram_session")
    if not session_string:
        return False

    client = TelegramClient(StringSession(session_string), api_id, api_hash)
    await client.connect()

    @client.on(events.NewMessage(incoming=True, outgoing=False))
    async def on_incoming(event):
        if not event.is_private:
            return
        chat_id = event.chat_id
        text = event.raw_text or ""

        if auto_reply.should_auto_reply(owner_id, chat_id):
            response = auto_reply.find_keyword_response(owner_id, text)
            if response:
                await event.reply(response)

    @client.on(events.NewMessage(incoming=False, outgoing=True))
    async def on_outgoing(event):
        if not event.is_private:
            return
        await auto_reply.mark_owner_activity(bot, owner_id, event.chat_id)

    _running_clients[owner_id] = client
    asyncio.create_task(client.run_until_disconnected())
    return True


async def stop_userbot_for_owner(owner_id: int):
    client = _running_clients.pop(owner_id, None)
    if client:
        await client.disconnect()
