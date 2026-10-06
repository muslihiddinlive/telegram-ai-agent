"""
Telegram "/" menyu komandalari ro'yxati — bitta markazlashgan joyda,
main.py (ishga tushishda) va handlers/pending_text.py (yangi admin
qo'shilganda, darhol) ikkalasi ham shu yerdan foydalanadi.
"""
from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeAllGroupChats, BotCommandScopeDefault

GROUP_COMMANDS = [
    BotCommand(command="guruh_ruxsat", description="🔒 Bot javobini tanlangan userlarga cheklash"),
    BotCommand(command="guruh_ruxsat_ochirish", description="🔓 Cheklovni bekor qilish"),
    BotCommand(command="chatmode", description="💬 Chat rejimi: on / off (guruh admini)"),
    BotCommand(command="qoida_qoshish", description="📋 AI uchun doimiy qoida qo'shish (admin)"),
    BotCommand(command="qoidalar", description="📋 Guruh qoidalarini ko'rish"),
    BotCommand(command="taqiqlar", description="🚫 Taqiqlangan so'zlar (admin)"),
    BotCommand(command="statistika", description="📊 Guruh statistikasi"),
    BotCommand(command="top_faollar", description="🏆 Eng faol a'zolarni belgilash (admin)"),
    BotCommand(command="aireakmode", description="😁 AI avto-reaksiya: on/off (admin)"),
    BotCommand(command="antispam", description="🛡 Anti-spam: on/off (admin)"),
]

def _ig_multi() -> bool:
    import core.instagram_context as ictx
    return ictx.multi_enabled()


_BASE_COMMANDS = [
    BotCommand(command="start", description="Botni ishga tushirish"),
    BotCommand(command="yangi_mavzu", description="🗂 Yangi mustaqil mavzu ochish"),
    BotCommand(command="mavzular", description="🗂 Mavzularim ro'yxati"),
    BotCommand(command="apikalit", description="🔑 O'z AI API kalitimni ulash"),
    BotCommand(command="profil", description="👤 Profil boshqaruvi (story qo'yish)"),
    BotCommand(command="laqab", description="🏷 Guruhda ishlatiladigan taxallusingiz"),
]
_IG_COMMAND = BotCommand(command="instagram", description="📸 Instagram akkauntimni ulash")


def general_commands() -> list:
    """Hamma uchun menyu. /instagram faqat Instagram ulash yoqilgan bo'lsa (paneldan keyin yoqilishi mumkin)."""
    return _BASE_COMMANDS + ([_IG_COMMAND] if _ig_multi() else [])


def admin_commands() -> list:
    return general_commands() + [BotCommand(command="panel", description="🛠 Boshqaruv paneli")]


# Orqaga moslik (ishga tushish payti surati); dinamik variantlar — general_commands()/admin_commands()
GENERAL_COMMANDS = general_commands()
ADMIN_COMMANDS = admin_commands()


async def refresh_commands(bot: Bot) -> None:
    """Menyuni hozirgi holatga moslaydi (masalan, superadmin paneldan Instagram'ni yoqqach /instagram paydo bo'ladi)."""
    import config
    import core.roles as roles
    await bot.set_my_commands(general_commands(), scope=BotCommandScopeDefault())
    for admin_id in {config.SUPERADMIN_ID} | {int(u) for u in roles.list_admins()}:
        try:
            await register_admin_commands(bot, admin_id)
        except Exception:  # noqa: BLE001
            pass


async def register_admin_commands(bot: Bot, chat_id: int):
    """Bitta admin/superadmin uchun /panel'ni ularning shaxsiy '/'' menyusiga qo'shadi."""
    await bot.set_my_commands(admin_commands(), scope=BotCommandScopeChat(chat_id=chat_id))


async def unregister_admin_commands(bot: Bot, chat_id: int):
    """Adminlikdan olingan odamning shaxsiy '/' menyusidan /panel'ni olib tashlaydi (umumiy menyuga qaytadi)."""
    await bot.delete_my_commands(scope=BotCommandScopeChat(chat_id=chat_id))


async def register_group_commands(bot: Bot):
    """/guruh_ruxsat va /guruh_ruxsat_ochirish — FAQAT guruh chatlarida ko'rinadi."""
    await bot.set_my_commands(GROUP_COMMANDS, scope=BotCommandScopeAllGroupChats())
