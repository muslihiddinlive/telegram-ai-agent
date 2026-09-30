"""
Guruhdagi HAR BIR xabarni (bot tag qilinmasa ham) kuzatib boruvchi middleware:
  1) yozuvchi / reply qilingan / text_mention / yangi qo'shilgan a'zolarni indeksga yozadi
     (keyin "@username ga mute ber" ishlashi uchun — Bot API username'ni o'zi hal qila olmaydi);
  2) matnli xabarni guruh umumiy xotirasiga jimgina qo'shadi (core/group_memory.py).
Javob bermaydi va handler'lar ishini o'zgartirmaydi. Xato bo'lsa ham xabar oqimini to'xtatmaydi.

DIQQAT: bot guruhdagi barcha xabarlarni FAQAT (a) guruh admini bo'lsa yoki
(b) BotFather'da Group Privacy o'chirilgan bo'lsa oladi.
"""
import logging

from aiogram import BaseMiddleware
from aiogram.types import Message

import core.group_memory as group_memory
import core.tgdb as tgdb

logger = logging.getLogger("group_observer")

_seeded_chats: set[int] = set()  # jarayon davomida har guruh uchun admin-ro'yxat bir marta olinadi


def mem_thread(message: Message) -> int | None:
    """Faqat HAQIQIY forum topic'lari alohida xotira; oddiy guruhdagi reply-thread'lar emas."""
    return message.message_thread_id if getattr(message, "is_topic_message", False) else None


class GroupObserver(BaseMiddleware):
    async def __call__(self, handler, event: Message, data: dict):
        try:
            if event.chat.type in ("group", "supergroup") and event.from_user:
                await self._observe(event)
        except Exception:  # noqa: BLE001 — kuzatuv hech qachon asosiy oqimni buzmasin
            logger.exception("Guruh kuzatuvida xatolik")
        return await handler(event, data)

    async def _observe(self, m: Message):
        chat_id = m.chat.id
        changed = group_memory.record_member(chat_id, m.from_user)

        if m.reply_to_message and m.reply_to_message.from_user:
            changed |= group_memory.record_member(chat_id, m.reply_to_message.from_user)
        for u in (m.new_chat_members or []):
            changed |= group_memory.record_member(chat_id, u)
        for ent in (m.entities or m.caption_entities or []):
            if ent.type == "text_mention" and ent.user:
                changed |= group_memory.record_member(chat_id, ent.user)

        if chat_id not in _seeded_chats:
            _seeded_chats.add(chat_id)
            try:
                for adm in await m.bot.get_chat_administrators(chat_id):
                    changed |= group_memory.record_member(chat_id, adm.user)
            except Exception:  # noqa: BLE001
                logger.info("Guruh %s adminlari ro'yxatini olib bo'lmadi", chat_id)

        text = m.text or m.caption or ""
        if text and not text.startswith("/"):
            await group_memory.record_human(m.bot, chat_id, mem_thread(m), m.message_id, m.from_user, text)
        elif changed:
            await tgdb.save(m.bot)
