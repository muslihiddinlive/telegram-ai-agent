"""
Entry point — webhook mode (Render uchun), StokerDownloader / KanalKotibRobot /
mafia_host_bot repolaringizdagi umumiy deploy patterniga mos.
"""
import logging
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiogram.client.default import DefaultBotProperties

import config
import core.tgdb as tgdb
from core.channels import on_bot_added_to_chat
from admin.panel import router as panel_router
from handlers.start import router as start_router
from handlers.topics import router as topics_router
from handlers.userbot_commands import router as userbot_commands_router
from handlers.pending_text import router as pending_text_router
from handlers.ai_chat import router as ai_chat_router

logging.basicConfig(level=logging.INFO)

bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

dp.include_router(panel_router)
dp.include_router(start_router)
dp.include_router(topics_router)
dp.include_router(userbot_commands_router)
dp.include_router(pending_text_router)  # MUHIM: ai_chat'dan OLDIN — aks holda pending matnlar AI'ga ketadi
dp.include_router(ai_chat_router)

dp.my_chat_member.register(on_bot_added_to_chat)


async def on_startup(bot: Bot):
    await tgdb.load(bot)  # DB'ni pin qilingan xabardan tiklaydi (agar bo'lsa)
    if config.WEBHOOK_URL:
        await bot.set_webhook(f"{config.WEBHOOK_URL}/webhook")


async def on_shutdown(bot: Bot):
    await tgdb.force_flush()  # qoldiq (hali flush qilinmagan) o'zgarishlarni yo'qotmaslik uchun


def main():
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path="/webhook")
    setup_application(app, dp, bot=bot)

    web.run_app(app, host="0.0.0.0", port=config.PORT)


if __name__ == "__main__":
    main()
