"""
Suhbat tarixi juda uzun bo'lib ketganda (topic_sessions.MAX_HISTORY'dan oshsa),
ESKI xabarlarni butunlay TASHLAB YUBORISH o'rniga — ularni AI yordamida
QISQA XULOSA ("rolling summary")ga aylantirib, session'da saqlab qolamiz.

Shunday qilib suhbat qancha uzun davom etmasin, muhim faktlar (ism, qaror,
davom etayotgan vazifa/mavzu) YO'QOLMAYDI — faqat so'z-ma-so'z matn emas,
uning MAZMUNI saqlanadi. Har safar YANGI eski xabarlar to'plangan sayin,
oldingi xulosa bilan birlashtirilib, YANGILANGAN bitta xulosaga aylanadi.

Diqqat: bu ICHKI/tizim darajasidagi chaqiruv — foydalanuvchining shaxsiy
kaliti yoki kunlik limitiga UMUMAN tegmaydi (ai.chat(..., user_id=None)
har doim umumiy/admin kalitini ishlatadi).
"""
import logging
from core.ai_rotator import ai

logger = logging.getLogger("history_summarizer")

_SUMMARIZE_SYSTEM_PROMPT = (
    "Quyida foydalanuvchi bilan AI-yordamchi orasidagi suhbatning ESKI qismi "
    "berilgan. Buni QISQA (5-10 gap) xulosaga aylantiring — muhim faktlar, "
    "qabul qilingan qarorlar, ismlar, raqamlar, davom etayotgan vazifa/"
    "mavzularni saqlab qoling, keraksiz tafsilotlarni tashlab yuboring. "
    "Agar 'OLDINGI XULOSA' ham berilgan bo'lsa, uni YANGI xabarlar bilan "
    "BIRLASHTIRIB, bitta yangilangan xulosaga aylantiring — takrorlanishlarsiz. "
    "Faqat xulosa matnining O'ZINI qaytaring, boshqa hech qanday izoh/sarlavha yozmang."
)


async def summarize(old_summary: str, messages_to_fold: list[dict]) -> str:
    """Eskirib, tarixdan chiqarib yuborilayotgan xabarlarni oldingi xulosa
    bilan birlashtirib, YANGI xulosa qaytaradi. Xatolik bo'lsa — hech
    bo'lmasa OLDINGI xulosani yo'qotmaslik uchun uni o'zgarishsiz qaytaradi."""
    convo_text = "\n".join(
        f"{'Foydalanuvchi' if m.get('role') == 'user' else 'AI'}: {m.get('content')}"
        for m in messages_to_fold if m.get("content")
    )
    if not convo_text.strip():
        return old_summary

    prior = f"OLDINGI XULOSA:\n{old_summary}\n\n" if old_summary else ""
    user_content = f"{prior}SUHBATNING ESKI QISMI:\n{convo_text}"

    try:
        result = await ai.chat(
            messages=[
                {"role": "system", "content": _SUMMARIZE_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            tools=None,
            user_id=None,  # umumiy kalit — hech kimning shaxsiy limitiga tegmaydi
        )
        new_summary = result["response"].choices[0].message.content
        return (new_summary or old_summary).strip()
    except Exception as e:
        logger.warning("Suhbat xulosasini yasab bo'lmadi (%s) — oldingi xulosa saqlanadi", e)
        return old_summary
