"""
Telegram "/" menyu komandalari ro'yxati — bitta markazlashgan joyda,
main.py (ishga tushishda) va handlers/pending_text.py (yangi admin
qo'shilganda, darhol) ikkalasi ham shu yerdan foydalanadi.
"""
from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeAllGroupChats

GROUP_COMMANDS = [
    BotCommand(command="guruh_ruxsat", description="🔒 Bot javobini tanlangan userlarga cheklash"),
    BotCommand(command="guruh_ruxsat_ochirish", description="🔓 Cheklovni bekor qilish"),
    BotCommand(command="chatmode", description="💬 Chat rejimi: on / off (guruh admini)"),
]

GENERAL_COMMANDS = [
    BotCommand(command="start", description="Botni ishga tushirish"),
    BotCommand(command="yangi_mavzu", description="🗂 Yangi mustaqil mavzu ochish"),
    BotCommand(command="mavzular", description="🗂 Mavzularim ro'yxati"),
    BotCommand(command="apikalit", description="🔑 O'z AI API kalitimni ulash"),
    BotCommand(command="profil", description="👤 Profil boshqaruvi (story qo'yish)"),
]

ADMIN_COMMANDS = GENERAL_COMMANDS + [
    BotCommand(command="panel", description="🛠 Boshqaruv paneli"),
]


async def register_admin_commands(bot: Bot, chat_id: int):
    """Bitta admin/superadmin uchun /panel'ni ularning shaxsiy '/'' menyusiga qo'shadi."""
    await bot.set_my_commands(ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=chat_id))


async def register_group_commands(bot: Bot):
    """/guruh_ruxsat va /guruh_ruxsat_ochirish — FAQAT guruh chatlarida ko'rinadi."""
    await bot.set_my_commands(GROUP_COMMANDS, scope=BotCommandScopeAllGroupChats())
