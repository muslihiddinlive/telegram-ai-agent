"""
"O'ylayapti..." status indikatori.

MUHIM YANGILANISH: Telegram Bot API 9.3+ (2025-12-31) rasmiy `sendMessageDraft`
metodini qo'shdi — bu AI-botlar uchun maxsus, NATIVE "Thinking…" ko'rsatkichi
(o'z ikonkasi/animatsiyasi bilan, Telegram klienti tomonidan chizilgan — oddiy
matn xabari emas). Manba: https://core.telegram.org/bots/api#sendmessagedraft

Ishlash tartibi (native, ustuvor):
  1. bot.send_message_draft(chat_id, draft_id, text="") — bo'sh matn native
     "Thinking…" placeholder'ni ko'rsatadi.
  2. Draft EFEMER (30 soniyalik vaqtinchalik preview) — shuning uchun har
     ~20 soniyada bir xil draft_id bilan qayta chaqirilib, "tirik" ushlab
     turiladi (bir xil draft_id — animatsiyali yangilanish beradi).
  3. Javob tayyor bo'lgach, oddiy bot.send_message() chaqiriladi — bu draft'ni
     avtomatik yopadi/almashtiradi (alohida o'chirish/edit shart emas).

FALLBACK: agar botingizda bu funksiya hali yoqilmagan bo'lsa (BotFather'da
"Private Chat Topics"/shunga bog'liq sozlama kerak bo'lishi mumkin) yoki
eski aiogram/Bot API muhitida ishlasa, avtomatik ravishda ESKI usulga
o'tiladi: oddiy xabar yuborilib, matn orqali "🌀 O'ylayapti... Ns" ko'rsatiladi
va edit qilinadi — funksionallik hech qachon butunlay singib qolmaydi.
"""
import asyncio
import logging
import random
import time
from aiogram import Bot
from aiogram.types import Message

logger = logging.getLogger("thinking_indicator")

DRAFT_REFRESH_SECONDS = 20  # draft 30s'da tugaydi — shundan oldin yangilaymiz

# Do'stona/kulgili iboralar — FAQAT fallback rejimida ishlatiladi (native
# draft'da matn har doim bo'sh bo'lishi SHART, aks holda maxsus ikonka
# yo'qoladi — pastdagi start() izohiga qarang).
FUNNY_THINKING_PHRASES = [
    "🌀 Miyamni ishga solyapman...",
    "🤔 Fikr yuritayapman...",
    "☕ Bir oz sabr, g'oyalar pishmoqda...",
    "⚡ Neyronlarni uyg'otyapman...",
    "🧠 Aql bovar qilmas javob tayyorlanmoqda...",
    "🔍 Kerakli so'zlarni termoqdaman...",
]


class ThinkingIndicator:
    def __init__(self, bot: Bot, chat_id: int, thread_id: int | None = None, label: str | None = None):
        self.bot = bot
        self.chat_id = chat_id
        self.thread_id = thread_id
        self.label = label or random.choice(FUNNY_THINKING_PHRASES)
        self._draft_id = random.randint(1, 2**31 - 1)
        self._use_native = False
        self._msg: Message | None = None  # faqat fallback rejimida ishlatiladi
        self._task: asyncio.Task | None = None
        self._start = 0.0

    async def start(self):
        self._start = time.monotonic()
        try:
            # MUHIM (amaliy kuzatuv, rasmiy hujjatda aniq yozilmagan): faqat
            # text="" (BO'SH) berilganda Telegram maxsus native "Thinking"
            # kartasini (o'z ikonkasi + animatsiyasi + hisoblagichi bilan)
            # ko'rsatadi. Har qanday MATN bersak (hatto qisqa bo'lsa ham),
            # bu maxsus UI yo'qoladi va oddiy "yuborilgan xabar"ga aylanib
            # qoladi (✓✓ belgisi bilan) — buni foydalanuvchi bilan birga
            # sinab, aniq tasdiqladik. Shuning uchun native yo'lda matnни
            # HAR DOIM bo'sh qoldiramiz.
            await self.bot.send_message_draft(
                chat_id=self.chat_id,
                draft_id=self._draft_id,
                message_thread_id=self.thread_id,
                text="",
            )
            self._use_native = True
            self._task = asyncio.create_task(self._refresh_draft_loop())
        except Exception as e:
            logger.info("Native 'Thinking' draft ishlamadi (%s) — matnli fallback'ga o'tildi", e)
            self._use_native = False
            self._msg = await self.bot.send_message(
                self.chat_id, f"{self.label}", message_thread_id=self.thread_id
            )
            self._task = asyncio.create_task(self._tick_fallback())
        return self

    async def _refresh_draft_loop(self):
        try:
            while True:
                await asyncio.sleep(DRAFT_REFRESH_SECONDS)
                await self.bot.send_message_draft(
                    chat_id=self.chat_id,
                    draft_id=self._draft_id,
                    message_thread_id=self.thread_id,
                    text="",  # bo'sh — native ikonka saqlanib qolishi uchun
                )
        except asyncio.CancelledError:
            pass
        except Exception:
            pass  # draft muddati tugagan yoki chat yopilgan bo'lishi mumkin — jim o'tkazamiz

    async def _tick_fallback(self):
        try:
            while True:
                await asyncio.sleep(1.5)
                elapsed = int(time.monotonic() - self._start)
                await self.bot.edit_message_text(
                    f"{self.label} ({elapsed}s)",
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

        if self._use_native:
            # sendMessage chaqirilishi bilan draft o'zi yopiladi/almashtiriladi —
            # alohida o'chirish yoki edit qilish shart emas.
            await self.bot.send_message(self.chat_id, final_text, message_thread_id=self.thread_id)
        else:
            try:
                await self.bot.edit_message_text(
                    final_text, chat_id=self.chat_id, message_id=self._msg.message_id
                )
            except Exception:
                await self.bot.send_message(self.chat_id, final_text, message_thread_id=self.thread_id)
