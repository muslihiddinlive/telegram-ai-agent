"""
Haqiqiy Dispatcher (main.dp, hamma router va middleware) orqali o'tkazadigan integratsion test yordamchisi.
Bot API chaqiruvlari yozib boriladi (tarmoqsiz): feed() — soxta Update yuboradi, qaytaradi: yuborilgan so'rovlar ro'yxati.
"""
import asyncio
import datetime as dt

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import (GetChatMember, GetChatAdministrators, GetMe, SendMessage, TelegramMethod)
from aiogram.types import (Chat, ChatMemberAdministrator, ChatMemberMember, ChatMemberOwner, Message, Update, User)

NOW = dt.datetime(2026, 10, 4, 12, 0)
BOT_ID = 777
BOT_USERNAME = "paradoks_ai_bot"


class RecordingSession(BaseSession):
    def __init__(self, admins=()):
        super().__init__()
        self.calls: list[tuple[str, dict]] = []
        self.admins = set(admins)
        self._mid = 1000

    async def close(self):
        pass

    async def stream_content(self, *a, **k):  # pragma: no cover
        raise NotImplementedError

    async def make_request(self, bot, method: TelegramMethod, timeout=None):
        data = method.model_dump(exclude_none=True)
        self.calls.append((type(method).__name__, data))
        if isinstance(method, SendMessage):
            self._mid += 1
            return Message(message_id=self._mid, date=NOW, chat=Chat(id=method.chat_id, type="supergroup"),
                           text=method.text, from_user=User(id=BOT_ID, is_bot=True, first_name="Bot"))
        if isinstance(method, GetChatMember):
            u = User(id=method.user_id, is_bot=False, first_name="U")
            if method.user_id in self.admins:
                fields = {n: False for n, f in ChatMemberAdministrator.model_fields.items()
                          if f.is_required() and n not in ("status", "user")}
                return ChatMemberAdministrator(user=u, **fields)

            return ChatMemberMember(user=u)
        if isinstance(method, GetChatAdministrators):
            return []
        if isinstance(method, GetMe):
            return User(id=BOT_ID, is_bot=True, first_name="Bot", username=BOT_USERNAME)
        return True

    def texts(self, chat_id=None):
        return [d["text"] for n, d in self.calls if n == "SendMessage" and (chat_id is None or d["chat_id"] == chat_id)]


def make_bot(admins=()):
    return Bot(token="123456:TEST", session=RecordingSession(admins))


def message_update(update_id, chat_id, user_id, text=None, chat_type="supergroup", message_id=1, reply_to_bot=False, **extra):
    chat = Chat(id=chat_id, type=chat_type, title="G" if chat_type != "private" else None)
    user = User(id=user_id, is_bot=False, first_name="Ali", username=f"u{user_id}")
    kwargs = dict(message_id=message_id, date=NOW, chat=chat, from_user=user, text=text, **extra)
    if text and text.startswith("/"):
        from aiogram.types import MessageEntity
        word = text.split()[0]
        kwargs["entities"] = [MessageEntity(type="bot_command", offset=0, length=len(word))]
    return Update(update_id=update_id, message=Message(**kwargs))


async def feed(dp, bot, update):
    await dp.feed_update(bot, update)


def press_callback(dp, bot, user_id, data, update_id=1, message_id=50):
    """Shaxsiy chatda inline tugma bosilishini haqiqiy Dispatcher orqali yuboradi."""
    from aiogram.types import CallbackQuery
    user = User(id=user_id, is_bot=False, first_name="Ali", username=f"u{user_id}")
    msg = Message(message_id=message_id, date=NOW, chat=Chat(id=user_id, type="private"),
                  from_user=User(id=BOT_ID, is_bot=True, first_name="Bot"), text="panel")
    cq = CallbackQuery(id=str(update_id), from_user=user, chat_instance="x", message=msg, data=data)
    return dp.feed_update(bot, Update(update_id=update_id, callback_query=cq))  # coroutine — run() bilan bajariladi
