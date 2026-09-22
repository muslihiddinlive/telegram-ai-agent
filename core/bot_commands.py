"""
Telegram "/" menyu komandalari ro'yxati — bitta markazlashgan joyda,
main.py (ishga tushishda) va handlers/pending_text.py (yangi admin
qo'shilganda, darhol) ikkalasi ham shu yerdan foydalanadi.
"""
from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeChat

GENERAL_COMMANDS = [
    BotCommand(command="start", description="Botni ishga tushirish"),
    BotCommand(command="yangi_mavzu", description="🗂 Yangi mustaqil mavzu ochish"),
    BotCommand(command="mavzular", description="🗂 Mavzularim ro'yxati"),
    BotCommand(command="apikalit", description="🔑 O'z AI API kalitimni ulash"),
    BotCommand(command="userbot", description="👤 Userbot ulash (auto-reply uchun)"),
    BotCommand(command="kalitsoz_qoshish", description="🔑 Auto-reply kalit-so'z qo'shish"),
    BotCommand(command="kalitsozlar", description="🔑 Kalit-so'zlarim ro'yxati"),
    BotCommand(command="away", description="⏱ 'Band' vaqtini sozlash"),
]

ADMIN_COMMANDS = GENERAL_COMMANDS + [
    BotCommand(command="panel", description="🛠 Boshqaruv paneli"),
]


async def register_admin_commands(bot: Bot, chat_id: int):
    """Bitta admin/superadmin uchun /panel'ni ularning shaxsiy '/'' menyusiga qo'shadi."""
    await bot.set_my_commands(ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=chat_id))
