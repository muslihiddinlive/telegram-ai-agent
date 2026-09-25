"""
Botning o'z username'i va ID'sini saqlab turadi — main.py on_startup'da
bot.get_me() orqali bir marta o'qiladi, keyin butun kod bo'ylab (fayl
nomlarida "by @BotUsername", yoki guruhda "botga reply qilinganmi?"
tekshiruvi uchun) shu yerdan olinadi.
"""
_username: str | None = None
_id: int | None = None


def set_username(username: str):
    global _username
    _username = username


def get_username() -> str | None:
    return _username


def set_id(bot_id: int):
    global _id
    _id = bot_id


def get_id() -> int | None:
    return _id
