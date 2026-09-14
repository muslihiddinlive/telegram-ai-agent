"""
Live "o'ylab olay..." status indikatori — ekranda ko'rgan skrinshotingizdagi
"Думаю... 0c" effekti (odatda Telegram AI-botlarida uchraydigan pattern).

Ishlash tartibi:
  1. AI so'roviga ketishdan oldin "🤔 O'ylab olay... 0s" xabari yuboriladi.
  2. Background task har ~1-2 soniyada shu xabarni "...Ns" ga edit qiladi.
  3. AI javobi tayyor bo'lgach, background task to'xtatiladi va xabar
     yakuniy javob matni bilan almashtiriladi (edit_message_text).

Forum-topic (superguruh topics) qo'llab-quvvatlash: message_thread_id bo'lsa,
status xabari ham javob ham O'SHA topic ichida yuboriladi/edit qilinadi —
shuning uchun barcha chaqiruvlarda thread_id ni uzatib turing.
"""
import asyncio
import time
from aiogram import Bot
from aiogram.types import Message


class ThinkingIndicator:
    def __init__(self, bot: Bot, chat_id: int, thread_id: int | None = None, label: str = "🤔 O'ylab olay"):
        self.bot = bot
        self.chat_id = chat_id
        self.thread_id = thread_id
        self.label = label
        self._msg: Message | None = None
        self._task: asyncio.Task | None = None
        self._start = 0.0

    async def start(self):
        self._start = time.monotonic()
        self._msg = await self.bot.send_message(
            self.chat_id, f"{self.label}... 0s", message_thread_id=self.thread_id
        )
        self._task = asyncio.create_task(self._tick())
        return self

    async def _tick(self):
        try:
            while True:
                await asyncio.sleep(1.5)
                elapsed = int(time.monotonic() - self._start)
                await self.bot.edit_message_text(
                    f"{self.label}... {elapsed}s",
                    chat_id=self.chat_id,
                    message_id=self._msg.message_id,
                )
        except asyncio.CancelledError:
            pass
        except Exception:
            pass  # edit ba'zan "message not modified" xatosi berishi mumkin — e'tiborsiz qoldiramiz

    async def finish(self, final_text: str):
        if self._task:
            self._task.cancel()
        try:
            await self.bot.edit_message_text(
                final_text, chat_id=self.chat_id, message_id=self._msg.message_id
            )
        except Exception:
            await self.bot.send_message(self.chat_id, final_text, message_thread_id=self.thread_id)
