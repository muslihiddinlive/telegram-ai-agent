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
  C) `sendChatAction(action="typing")` — hech biri ishlamasa (eng oxirgi
     chora). Bu — Telegram'ning eski/klassik "<Bot> yozmoqda..." indikatori
     (foydalanuvchi terayotganda chiqadigan xabar bilan bir xil turkum),
     HECH QANDAY xabar yubormaydi — shuning uchun guruhda "Miyamni ishga
     solyapman..." kabi matn ko'rinib qolmaydi. ~5 soniyada bir marta
     avtomatik o'chadi, shuning uchun tayyor bo'lgunicha davriy ravishda
     qayta yuborib turiladi.

Manba: https://core.telegram.org/bots/api#sendrichmessagedraft
       https://core.telegram.org/bots/api#sendmessagedraft
"""
import asyncio
import logging
import random
import time
from aiogram import Bot
from aiogram.types import InputRichMessage

logger = logging.getLogger("thinking_indicator")

DRAFT_REFRESH_SECONDS = 20  # draft 30s'da tugaydi — shundan oldin yangilaymiz
CHAT_ACTION_REFRESH_SECONDS = 4  # "typing" holati ~5s'da tugaydi — shundan oldin yangilaymiz

FUNNY_THINKING_PHRASES = [
    "Miyamni ishga solyapman...",
    "Fikr yuritayapman...",
    "Bir oz sabr, g'oyalar pishmoqda...",
    "Neyronlarni uyg'otyapman...",
    "Aql bovar qilmas javob tayyorlanmoqda...",
    "Kerakli so'zlarni termoqdaman...",
]


class ThinkingIndicator:
    def __init__(self, bot: Bot, chat_id: int, thread_id: int | None = None):
        self.bot = bot
        self.chat_id = chat_id
        self.thread_id = thread_id
        self._draft_id = random.randint(1, 2**31 - 1)
        self._mode = "fallback"  # "rich" | "native" | "fallback"
        self._task: asyncio.Task | None = None
        self._start = 0.0
        self._phrase_index = 0

    async def start(self):
        self._start = time.monotonic()

        # sendRichMessageDraft/sendMessageDraft — rasmiy Bot API bo'yicha
        # FAQAT shaxsiy (private) chatlar uchun ishlaydi (guruh/supergroup/
        # kanalda umuman qo'llab-quvvatlanmaydi). Telegram'da guruh/kanal
        # chat_id'lari doim MANFIY son, shaxsiy chat_id'lar esa MUSBAT —
        # shu bilan guruhda A/B'ni bekorga urinib ko'rmasdan, to'g'ridan-to'g'ri
        # C (typing) ga o'tamiz.
        is_private_chat = self.chat_id > 0

        # A) Eng yaxshisi — sendRichMessageDraft + <tg-thinking>: logo + o'z matnimiz
        if is_private_chat:
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

        # C) Eng oxirgi chora (yoki guruh/kanal bo'lsa — TO'G'RIDAN-TO'G'RI shu
        # yerdan boshlanadi) — hech qanday xabar yubormasdan, native
        # "<Bot> yozmoqda..." (typing) holatini ko'rsatamiz
        self._mode = "fallback"
        try:
            await self.bot.send_chat_action(
                self.chat_id, action="typing", message_thread_id=self.thread_id
            )
        except Exception as e:
            logger.warning("send_chat_action ishlamadi: %s", e)
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
                await asyncio.sleep(CHAT_ACTION_REFRESH_SECONDS)
                await self.bot.send_chat_action(
                    self.chat_id, action="typing", message_thread_id=self.thread_id
                )
        except asyncio.CancelledError:
            pass
        except Exception:
            pass  # tarmoq/limit xatolari — e'tiborsiz qoldiramiz

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

        # "native" va "fallback" (typing) rejimlarida ko'rinadigan xabar
        # yaratilmagan — ikkalasida ham yakuniy javobni oddiy yangi xabar
        # sifatida yuboramiz.
        await self.bot.send_message(self.chat_id, final_text, message_thread_id=self.thread_id)
