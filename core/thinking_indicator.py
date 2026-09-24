"""
"O'ylayapti..." status indikatori — 3 bosqichli fallback zanjiri bilan.

MUHIM KASHFIYOT (foydalanuvchi bilan birga aniqlandi): Telegram'da ikkita
yaqin, lekin FARQLI metod bor:

1. `sendRichMessageDraft` + `<tg-thinking>MATN</tg-thinking>` tegi — BOY
   (rich) draft. Bu YAGONA yo'l — matnни O'ZINGIZ moslashtirib, SHU BILAN
   BIRGA native yulduzcha-logo+taymerni saqlab qolish mumkin. Rasmiy hujjat
   maxsus emoji-ikonkalar tavsiya qiladi (https://t.me/addemoji/AIActions).
2. `sendMessageDraft` (oddiy, rich emas) + text="" — faqat BO'SH matn
   bilan native logo chiqadi; istalgan MATN berilsa, logo yo'qolib, oddiy
   yuborilgan xabarga aylanadi (bu holatni skrinshot bilan tasdiqladik).

Shuning uchun ustuvorlik tartibi:
  A) sendRichMessageDraft + <tg-thinking>kulgili ibora</tg-thinking> —
     ENG YAXSHISI: logo HAM, o'zimizning matn HAM birga
  B) sendMessageDraft (text="") — logo bor, lekin matn moslashtirib
     bo'lmaydi (agar A ishlamasa, masalan aiogram/Bot API versiyasi eski)
  C) Oddiy xabar + qo'lda edit qilish — hech biri ishlamasa (eng oxirgi chora)

Manba: https://core.telegram.org/bots/api#sendrichmessagedraft
       https://core.telegram.org/bots/api#sendmessagedraft
"""
import asyncio
import logging
import random
import time
from aiogram import Bot
from aiogram.types import Message, InputRichMessage

logger = logging.getLogger("thinking_indicator")

DRAFT_REFRESH_SECONDS = 20  # draft 30s'da tugaydi — shundan oldin yangilaymiz

FUNNY_THINKING_PHRASES = [
    "Miyamni ishga solyapman...",
    "Fikr yuritayapman...",
    "Bir oz sabr, g'oyalar pishmoqda...",
    "Neyronlarni uyg'otyapman...",
    "Aql bovar qilmas javob tayyorlanmoqda...",
    "Kerakli so'zlarni termoqdaman...",
]


class ThinkingIndicator:
    def __init__(self, bot: Bot, chat_id: int, thread_id: int | None = None, label: str | None = None):
        self.bot = bot
        self.chat_id = chat_id
        self.thread_id = thread_id
        self.label = label or random.choice(FUNNY_THINKING_PHRASES)
        self._draft_id = random.randint(1, 2**31 - 1)
        self._mode = "fallback"  # "rich" | "native" | "fallback"
        self._msg: Message | None = None  # faqat "fallback" rejimida ishlatiladi
        self._task: asyncio.Task | None = None
        self._start = 0.0
        self._phrase_index = 0

    async def start(self):
        self._start = time.monotonic()

        # A) Eng yaxshisi — sendRichMessageDraft + <tg-thinking>: logo + o'z matnimiz
        try:
            await self.bot.send_rich_message_draft(
                chat_id=self.chat_id,
                draft_id=self._draft_id,
                message_thread_id=self.thread_id,
                rich_message=InputRichMessage(html=f"<tg-thinking>{FUNNY_THINKING_PHRASES[0]}</tg-thinking>"),
            )
            self._mode = "rich"
            self._task = asyncio.create_task(self._refresh_rich_loop())
            return self
        except Exception as e:
            logger.info("sendRichMessageDraft ishlamadi (%s) — oddiy draft'ga o'tildi", e)

        # B) O'rtacha — sendMessageDraft (text="" — logo bor, matn yo'q)
        try:
            await self.bot.send_message_draft(
                chat_id=self.chat_id, draft_id=self._draft_id,
                message_thread_id=self.thread_id, text="",
            )
            self._mode = "native"
            self._task = asyncio.create_task(self._refresh_native_loop())
            return self
        except Exception as e:
            logger.info("sendMessageDraft ham ishlamadi (%s) — matnli fallback'ga o'tildi", e)

        # C) Eng oxirgi chora — oddiy xabar + qo'lda edit
        self._mode = "fallback"
        self._msg = await self.bot.send_message(
            self.chat_id, f"🌀 {self.label}", message_thread_id=self.thread_id
        )
        self._task = asyncio.create_task(self._tick_fallback())
        return self

    async def _refresh_rich_loop(self):
        try:
            while True:
                await asyncio.sleep(DRAFT_REFRESH_SECONDS)
                self._phrase_index = (self._phrase_index + 1) % len(FUNNY_THINKING_PHRASES)
                await self.bot.send_rich_message_draft(
                    chat_id=self.chat_id, draft_id=self._draft_id,
                    message_thread_id=self.thread_id,
                    rich_message=InputRichMessage(
                        html=f"<tg-thinking>{FUNNY_THINKING_PHRASES[self._phrase_index]}</tg-thinking>"
                    ),
                )
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    async def _refresh_native_loop(self):
        try:
            while True:
                await asyncio.sleep(DRAFT_REFRESH_SECONDS)
                await self.bot.send_message_draft(
                    chat_id=self.chat_id, draft_id=self._draft_id,
                    message_thread_id=self.thread_id, text="",
                )
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    async def _tick_fallback(self):
        try:
            while True:
                await asyncio.sleep(1.5)
                elapsed = int(time.monotonic() - self._start)
                await self.bot.edit_message_text(
                    f"🌀 {self.label} ({elapsed}s)",
                    chat_id=self.chat_id,
                    message_id=self._msg.message_id,
                )
        except asyncio.CancelledError:
            pass
        except Exception:
            pass  # "message not modified" kabi xatolar — e'tiborsiz qoldiramiz

    async def finish(self, final_text: str):
        if self._task:
            self._task.cancel()

        if self._mode == "rich":
            # Rich draft'ni yopish uchun rasmiy hujjat sendRichMessage'ni
            # tavsiya qiladi (oddiy sendMessage emas).
            try:
                await self.bot.send_rich_message(
                    chat_id=self.chat_id,
                    message_thread_id=self.thread_id,
                    rich_message=InputRichMessage(html=final_text),
                )
                return
            except Exception as e:
                logger.warning("send_rich_message muvaffaqiyatsiz (%s) — oddiy send_message bilan", e)

        if self._mode in ("rich", "native"):
            await self.bot.send_message(self.chat_id, final_text, message_thread_id=self.thread_id)
        else:
            try:
                await self.bot.edit_message_text(
                    final_text, chat_id=self.chat_id, message_id=self._msg.message_id
                )
            except Exception:
                await self.bot.send_message(self.chat_id, final_text, message_thread_id=self.thread_id)
