"""
USERBOT_SESSION (Telethon StringSession) yaratish — LOKAL kompyuteringizda bir marta ishga tushiring:

    pip install telethon
    python gen_userbot_session.py

API_ID/API_HASH: https://my.telegram.org -> API development tools.
Chiqqan satrni Render'da USERBOT_SESSION env'iga qo'ying. Uni hech qayerga commit qilmang va
boshqa joyda bir vaqtda ISHLATMANG (Telegram bekor qiladi). Kerak bo'lmay qolsa:
Telegram -> Sozlamalar -> Qurilmalar -> sessiyani tugatish.
"""
import asyncio

from telethon import TelegramClient
from telethon.sessions import StringSession


async def main():
    api_id = int(input("API_ID: ").strip())
    api_hash = input("API_HASH: ").strip()
    async with TelegramClient(StringSession(), api_id, api_hash) as client:
        print("\nUSERBOT_SESSION=" + client.session.save())


if __name__ == "__main__":
    asyncio.run(main())
