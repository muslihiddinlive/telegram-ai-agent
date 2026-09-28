"""
AI'ning "soati" — har so'rovda system prompt'ga hozirgi sana/vaqt qo'shiladi.

Nima uchun kerak: til modeli o'zi bugungi sanani bilmaydi (faqat o'qitilgan
davrigacha bilimi bor), shuning uchun "Ronaldo necha yosh?" kabi savollarda
"41 yosh, yoki 40" deb taxmin qilib qoladi. Aniq sana berilsa, hisoblay oladi.

Toshkent vaqti (UTC+5) — O'zbekistonda yozgi/qishki vaqtga o'tish YO'Q, shuning
uchun oddiy doimiy siljish yetarli (tzdata paketiga bog'liq bo'lmaslik uchun
zoneinfo ishlatilmadi — python:slim'da tz ma'lumotlar bazasi bo'lmasligi mumkin).
"""
from datetime import datetime, timedelta, timezone

TASHKENT = timezone(timedelta(hours=5))

_MONTHS = [
    "yanvar", "fevral", "mart", "aprel", "may", "iyun",
    "iyul", "avgust", "sentabr", "oktabr", "noyabr", "dekabr",
]
_WEEKDAYS = [
    "dushanba", "seshanba", "chorshanba", "payshanba",
    "juma", "shanba", "yakshanba",
]


def now() -> datetime:
    return datetime.now(TASHKENT)


def time_context_line() -> str:
    n = now()
    return (
        f"Hozirgi sana va vaqt (Toshkent, UTC+5): {n.year}-yil {n.day}-{_MONTHS[n.month - 1]}, "
        f"{_WEEKDAYS[n.weekday()]}, soat {n:%H:%M}. "
        "Yosh, muddat, \"bugun\", \"hozir\", \"yaqinda\", \"oxirgi\" kabi vaqtga bog'liq "
        "savollarda AYNAN shu sanaga tayan — taxmin qilib, ikki variant aytma. "
        "Internetdan qidirganda topilgan ma'lumot sanasini ham shu sana bilan solishtir."
    )
