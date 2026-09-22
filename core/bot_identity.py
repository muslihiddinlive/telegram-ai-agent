"""
Botning o'z username'ini saqlab turadi — main.py on_startup'da bot.get_me()
orqali bir marta o'qiladi, keyin butun kod bo'ylab (masalan fayl nomlarida
"by @BotUsername" qo'shish uchun) shu yerdan olinadi.
"""
_username: str | None = None


def set_username(username: str):
    global _username
    _username = username


def get_username() -> str | None:
    return _username
