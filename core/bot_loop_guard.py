"""
Bot-bot cheksiz tsiklidan himoya.

Telegram (BotFather -> Bot-to-Bot Communication Mode) o'zi ham ochiq
ogohlantiradi: "Bots can easily trigger infinite loops. You must prevent
this by implementing filtering or rate limits." Shu modul aynan shu talabni
bajaradi.

Yechim (RAM'da, oddiy va yetarli): har bir chat uchun ketma-ket necha marta
BOSHQA BOTDAN kelgan xabarga javob berilganini sanaymiz. Chatga haqiqiy
INSON yozishi bilan hisoblagich nolga tushadi. Ketma-ket bot-javoblar soni
MAX_CONSECUTIVE_BOT_REPLIES'dan oshsa — zanjir jimgina uziladi (javob
yuborilmaydi), va superadminga BIR martagina ogohlantirish yuboriladi
(inson aralashmaguncha qayta yubormaslik uchun).

Eslatma: bu hisoblagich process-xotirasida (RAM) saqlanadi, DB'ga yozilmaydi —
qayta ishga tushirilganda tozalanadi, bu tabiiy va yetarli (maqsad — faqat
bitta suhbat sessiyasi ichidagi runaway tsiklni to'xtatish).
"""
import logging

logger = logging.getLogger("bot_loop_guard")

MAX_CONSECUTIVE_BOT_REPLIES = 4

_chain_counts: dict[int, int] = {}       # chat_id -> ketma-ket bot-javoblar soni
_warned_chats: set[int] = set()          # bu chatda allaqachon ogohlantirish yuborilganmi


def register_incoming(chat_id: int, is_from_bot: bool) -> bool:
    """
    Botga murojaat qilingan HAR bir xabar uchun chaqiriladi (mention/reply
    filtridan o'tgandan keyin, lekin AI'ga so'rov yuborishdan OLDIN).

    True -> javob berish mumkin.
    False -> zanjir MAX_CONSECUTIVE_BOT_REPLIES'dan oshdi, javob berilmasin.
    """
    if not is_from_bot:
        _chain_counts[chat_id] = 0
        _warned_chats.discard(chat_id)
        return True

    count = _chain_counts.get(chat_id, 0) + 1
    _chain_counts[chat_id] = count

    if count > MAX_CONSECUTIVE_BOT_REPLIES:
        logger.warning(
            "Bot-bot cheksiz tsikl xavfi: chat_id=%s, %s marta ketma-ket bot-javob — zanjir uzildi",
            chat_id, count,
        )
        return False

    return True


def should_warn_once(chat_id: int) -> bool:
    """Zanjir uzilganda superadminga faqat BIR marta ogohlantirish yuborish uchun."""
    if chat_id in _warned_chats:
        return False
    _warned_chats.add(chat_id)
    return True
