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

import core.ai_reaction as ai_reaction
import core.antispam as antispam
import core.banned_words as banned_words
import core.global_blacklist as global_blacklist
import core.group_memory as group_memory
import core.moderation as moderation
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
                if await self._observe(event):
                    return  # taqiqlangan so'z uchun xabar o'chirildi — AI/boshqa handler'larga yubormaymiz
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
            is_global = global_blacklist.find_match(text) is not None
            is_local = banned_words.find_match(chat_id, text) is not None
            if is_global or is_local:
                if await self._delete_banned(m, escalate=is_global):
                    return True

            access = await moderation.get_access(m.bot, chat_id, m.from_user.id)
            if access is None and antispam.is_enabled(chat_id):
                if antispam.register_and_check(chat_id, m.from_user.id, text):
                    await self._handle_flood(m)

            await group_memory.record_human(m.bot, chat_id, mem_thread(m), m.message_id, m.from_user, text)
            if ai_reaction.is_enabled(chat_id):
                ai_reaction.react_in_background(m.bot, chat_id, m.message_id, text, m.from_user.id)
        elif changed:
            await tgdb.save(m.bot)
        return False

    async def _handle_flood(self, m: Message):
        ctx = {"bot": m.bot, "chat_id": m.chat.id, "is_group": True, "mod": moderation.ModAccess(0, is_owner=True)}
        r = await moderation.dispatch(m.bot, "mute_user", {"user_id": m.from_user.id, "minutes": antispam.MUTE_MINUTES}, ctx)
        if r.get("ok"):
            name = group_memory.label(m.from_user.full_name, m.from_user.username, m.from_user.id)
            try:
                await m.bot.send_message(m.chat.id, f"🚫 {name} — flood (juda tez-tez yozish) uchun {antispam.MUTE_MINUTES} daqiqaga mute qilindi.")
            except Exception:  # noqa: BLE001
                pass

    async def _delete_banned(self, m: Message, escalate: bool = False) -> bool:
        """Taqiqlangan so'z: guruh/bot adminlari TEKSHIRILMAYDI. O'chirish muvaffaqiyatli bo'lsagina True.
        escalate=True (GLOBAL qora ro'yxat) bo'lsa — strike hisoblanadi va 3/5-chisida mute/ban qo'llanadi."""
        access = await moderation.get_access(m.bot, m.chat.id, m.from_user.id)
        if access is not None:
            return False
        if await moderation.bot_rights_error(m.bot, m.chat.id, "delete_message") is not None:
            logger.info("Taqiqlangan so'z topildi, lekin botda o'chirish huquqi yo'q (chat=%s)", m.chat.id)
            return False
        result = await moderation.get_toolkit(m.bot).call("delete_message", chat_id=m.chat.id, message_id=m.message_id)
        if not result.ok:
            logger.info("Taqiqlangan so'z xabarini o'chirib bo'lmadi: %s", result.message)
            return False
        name = group_memory.label(m.from_user.full_name, m.from_user.username, m.from_user.id)
        note = ""
        if escalate:
            n = global_blacklist.register_strike(m.chat.id, m.from_user.id)
            ctx = {"bot": m.bot, "chat_id": m.chat.id, "is_group": True, "mod": moderation.ModAccess(0, is_owner=True)}
            if n >= global_blacklist.BAN_AT:
                r = await moderation.dispatch(m.bot, "ban_user", {"user_id": m.from_user.id}, ctx)
                if r.get("ok"):
                    note = " Takroriy buzilish tufayli guruhdan ban qilindi."
            elif n >= global_blacklist.MUTE_AT:
                r = await moderation.dispatch(m.bot, "mute_user", {"user_id": m.from_user.id, "minutes": global_blacklist.MUTE_MINUTES}, ctx)
                if r.get("ok"):
                    note = f" Takroriy buzilish tufayli {global_blacklist.MUTE_MINUTES} daqiqaga mute qilindi."
        try:
            await m.bot.send_message(m.chat.id, f"🚫 {name} xabari o'chirildi — taqiqlangan so'z ishlatilgan.{note}")
        except Exception:  # noqa: BLE001
            pass
        return True
