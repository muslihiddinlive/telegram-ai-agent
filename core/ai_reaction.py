"""
/aireakmode: on|off — yoqilsa, bot guruhdagi xabarlarga (tag/reply shart emas) mavzusiga
mos emoji bilan avtomatik REAKSIYA qo'yadi (masalan hazilga 😁, "telefonim sindi" kabi
gapga 😔). Bot JAVOB YOZMAYDI, faqat reaksiya — shuning uchun suhbatga halaqit bermaydi.
Har bir xabarga emas — AI "mos emas" desa, hech narsa qo'yilmaydi.
"""
import asyncio
import logging

from aiogram.types import ReactionTypeEmoji

import core.tgdb as tgdb
from core.ai_rotator import ai
import core.token_usage as token_usage

logger = logging.getLogger("ai_reaction")

MIN_WORDS = 3  # juda qisqa xabarlarga (AI chaqirmasdan) reaksiya qo'ymaymiz — xarajatni tejash
ALLOWED_EMOJI = (
    "👍 👎 ❤️ 🔥 🥰 👏 😁 🤔 🤯 😱 🎉 🤩 🙏 👌 😢 🤡 🥱 😍 💯 🤣 ⚡ 🏆 💔 😐 😭 😨 🤗 🙊 😎"
)
_SYSTEM = (
    "Guruh suhbatidagi BITTA xabarni o'qiysan. Mavzusiga/ohangiga chinakam mos keladigan BITTA emoji bilan "
    "reaksiya berish kerakmi, aniqlaysan. Faqat aniq hissiyot bor bo'lsa (hazil, xursandchilik, xafagarchilik, "
    "g'alaba, afsus va h.k.) emoji tanla; oddiy, neytral yoki tushunarsiz xabarga HECH NARSA qo'yma. "
    f"Faqat shu ro'yxatdan birini tanla: {ALLOWED_EMOJI}\n"
    'FAQAT JSON qaytar: {"emoji": "😁"} yoki mos kelmasa {"emoji": null}'
)


def _bucket() -> dict:
    return tgdb.get().setdefault("ai_reaction_mode", {})


def is_enabled(chat_id: int) -> bool:
    return bool(_bucket().get(str(chat_id)))


async def set_enabled(bot, chat_id: int, enabled: bool):
    _bucket()[str(chat_id)] = enabled
    await tgdb.save(bot, force=True)


def _parse_emoji(raw: str) -> str | None:
    import json
    import re

    m = re.search(r"\{.*\}", raw or "", re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except (ValueError, TypeError):
        return None
    emoji = data.get("emoji") if isinstance(data, dict) else None
    emoji = (emoji or "").strip()
    return emoji if emoji and emoji in ALLOWED_EMOJI else None


async def maybe_react(bot, chat_id: int, message_id: int, text: str, user_id: int | None):
    """Fon vazifasi sifatida chaqiriladi (xabar oqimini kutib turmaydi)."""
    if len(text.split()) < MIN_WORDS:
        return
    try:
        with token_usage.scope(chat_id=chat_id, chat_type="supergroup", user_id=user_id, purpose="reaction"):
            result = await ai.chat(
                messages=[{"role": "system", "content": _SYSTEM}, {"role": "user", "content": text[:500]}],
                tools=None, user_id=user_id,
            )
        emoji = _parse_emoji(result["response"].choices[0].message.content)
        if not emoji:
            return
        await bot.set_message_reaction(chat_id=chat_id, message_id=message_id, reaction=[ReactionTypeEmoji(emoji=emoji)])
    except Exception as e:  # noqa: BLE001 — fon vazifasi, hech qachon asosiy oqimni buzmasin
        logger.info("AI reaksiya qo'yilmadi: %s", e)


def react_in_background(bot, chat_id: int, message_id: int, text: str, user_id: int | None):
    asyncio.create_task(maybe_react(bot, chat_id, message_id, text, user_id))
