"""
Entry point — webhook mode (Render uchun), StokerDownloader / KanalKotibRobot /
mafia_host_bot repolaringizdagi umumiy deploy patterniga mos.
"""
import asyncio
import logging
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiogram.client.default import DefaultBotProperties
from aiogram.types import BotCommandScopeDefault
import core.bot_commands as bot_commands
import core.instagram_media as instagram_media
import core.instagram_oauth as instagram_oauth
import core.instagram_scheduler as instagram_scheduler
import core.instagram_webhook as instagram_webhook

import config
import core.tgdb as tgdb
import core.roles as roles
from core.channels import on_bot_added_to_chat
from admin.panel import router as panel_router
from handlers.start import router as start_router
from handlers.tariff import router as tariff_router
from handlers.support import router as support_router
from handlers.command_guard import router as command_guard_router
from handlers.topics import router as topics_router
from handlers.group_settings import router as group_settings_router
from handlers.group_tools import router as group_tools_router
from handlers.api_integration import router as api_integration_router
from handlers.instagram import router as instagram_router
from handlers.group_mod import router as group_mod_router
from handlers.github import router as github_router
from handlers.site import router as site_router
from handlers.profile import router as profile_router
from handlers.story_tools import router as story_tools_router
from handlers.pending_text import router as pending_text_router
from handlers.admin_terminal import router as admin_terminal_router
from handlers.ai_chat import router as ai_chat_router
from handlers.slide_preview import router as slide_preview_router
from core.legacy_cleanup import purge_userbot_data
import core.nicknames as nicknames
import core.scheduler as scheduler
from core.group_observer import GroupObserver
import core.file_cleanup as file_cleanup
import core.github_sandbox as github_sandbox
import core.bot_identity as bot_identity
import core.userbot as userbot
from tools.file_tools import USER_FILES_ROOT

logging.basicConfig(level=logging.INFO)

bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()
dp.message.outer_middleware(GroupObserver())  # guruhdagi HAR BIR xabarni kuzatadi (xotira + a'zolar indeksi)

dp.include_router(support_router)  # BIRINCHI: murojaat sessiyasi paytidagi xabarlar/komandalar boshqa handler'larga (start, panel, AI...) ketmasin
dp.include_router(group_mod_router)  # .ban/.mute/... — botga tag shart EMAS, shuning uchun ai_chat'dan (va boshqalardan) oldin
dp.include_router(site_router)  # /site — sayt frontend'ini o'qish/ko'chirish
dp.include_router(github_router)  # /gh + token ushlagich: token yozilgan xabar AI/xotira/boshqa handler'larga HECH QACHON yetmasin
dp.include_router(panel_router)
dp.include_router(start_router)
dp.include_router(tariff_router)  # ai_chat'dan OLDIN: tariflar tugmasi, to'lov (pre_checkout/successful_payment) AI'ga ketib qolmasin
dp.include_router(topics_router)
dp.include_router(instagram_router)  # /instagram — ai_chat'dan OLDIN (komanda AI'ga ketib qolmasin)
dp.include_router(group_settings_router)
dp.include_router(group_tools_router)
dp.include_router(api_integration_router)
dp.include_router(story_tools_router)  # story tahriri/sozlamalari — profile_router bilan birga, ai_chat'dan oldin
dp.include_router(profile_router)  # ai_chat'dan OLDIN — story uchun yuborilgan rasm/video AI-suhbatga ketib qolmasin
dp.include_router(admin_terminal_router)  # ai_chat'dan OLDIN — "exec:" AI'ga ketmasin
dp.include_router(slide_preview_router)
dp.include_router(command_guard_router)  # xato yozilgan komandalar AI'ga ketib "bajardim" demasin
dp.include_router(pending_text_router)  # MUHIM: ai_chat'dan OLDIN — aks holda pending matnlar AI'ga ketadi
dp.include_router(ai_chat_router)

dp.my_chat_member.register(on_bot_added_to_chat)


async def on_startup(bot: Bot):
    me = await bot.get_me()
    bot_identity.set_username(me.username)  # fayl nomlarida "by @username" uchun
    bot_identity.set_id(me.id)  # guruhda "botga reply qilinganmi?" tekshiruvi uchun

    file_cleanup.cleanup_stale_files(USER_FILES_ROOT)  # oldingi sessiyadan qolgan qoldiqlar
    github_sandbox.cleanup_idle(0)  # restartdan qolgan GitHub ish nusxalari/yarim klonlar — hammasi o'chadi (ish nusxasi vaqtinchalik)
    asyncio.create_task(github_sandbox.sweeper())  # bo'sh turgan ish nusxalarini har 5 daqiqada o'chiradi
    db = await tgdb.load(bot)  # DB'ni pin qilingan xabardan tiklaydi (agar bo'lsa) — _register_commands'dan OLDIN kerak (roles.list_admins() DB'ni talab qiladi)
    await _register_commands(bot)

    if config.WEBHOOK_URL:
        # business_connection update'i kelishi uchun allaqachon ro'yxatdan o'tgan handler turlari so'raladi
        await bot.set_webhook(f"{config.WEBHOOK_URL}/webhook", allowed_updates=dp.resolve_used_update_types())

    # Userbot olib tashlangan: eski sessiya (hisobga kirish huquqi) ma'lumotlarini DB'dan o'chiramiz
    await purge_userbot_data(bot)
    await nicknames.seed_defaults(bot)  # standart taxalluslar (masalan 8054272729 -> "Omirbayev aka")
    await userbot.start()  # sozlanmagan/xato bo'lsa bot yiqilmaydi — funksiya shunchaki o'chiq qoladi
    asyncio.create_task(scheduler.run_forever(bot))  # kunlik top-faollar (20:00) va tabriklar (09:00)
    asyncio.create_task(instagram_scheduler.run_forever(bot))  # rejalashtirilgan Instagram postlari


async def _register_commands(bot: Bot):
    """
    Telegram'ning "/" menyu tugmasida komandalar KO'RINISHI uchun shart —
    aks holda ular kodda ishlab tursa ham, foydalanuvchi ularni qo'lda
    yozib bilishi shart bo'lib qolardi (masalan /yangi_mavzu — Topics
    funksiyasi "yo'q" deb ko'rinishining asosiy sababi shu edi).
    """
    await bot.set_my_commands(bot_commands.general_commands(), scope=BotCommandScopeDefault())
    await bot_commands.register_group_commands(bot)

    # Superadmin va barcha adminlarga qo'shimcha /panel komandasi — faqat
    # ULARNING shaxsiy chatida ko'rinadi (oddiy userlarga chiqmaydi)
    admin_ids = [config.SUPERADMIN_ID] + [int(uid) for uid in roles.list_admins()]
    for admin_id in set(admin_ids):
        try:
            await bot_commands.register_admin_commands(bot, admin_id)
        except Exception as e:
            logging.warning("Admin (%s) uchun maxsus komandalar o'rnatilmadi: %s", admin_id, e)


async def on_shutdown(bot: Bot):
    await userbot.stop()
    await tgdb.force_flush()  # qoldiq (hali flush qilinmagan) o'zgarishlarni yo'qotmaslik uchun


def main():
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path="/webhook")
    setup_application(app, dp, bot=bot)
    instagram_media.register(app)  # Instagram uchun vaqtinchalik media URL (/ig-media/...)
    instagram_oauth.register(app, bot)  # foydalanuvchilar o'z Instagramini ulashi (IG_APP_ID/IG_APP_SECRET bo'lsa)
    instagram_webhook.register(app, bot)  # izoh webhook'i (faqat IG_WEBHOOK_ENABLED=1 bo'lsa)

    web.run_app(app, host="0.0.0.0", port=config.PORT)


if __name__ == "__main__":
    main()
