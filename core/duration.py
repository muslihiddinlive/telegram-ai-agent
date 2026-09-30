"""
Matndan muddatni (vaqt birligi bilan) aniq ajratib olish: "14 daqiqaga", "2 soat", "1 kun",
"1 soat 30 daqiqa", "1.5 soat", "yarim soat", "besh daqiqa", "2h", "30min", "3 дня", "10 minutes".

Nima uchun kodda: moderatsiya tool'lari (mute_user/ban_user) muddatni FAQAT daqiqada (butun son)
qabul qiladi. Soat/kunni daqiqaga o'girishni AI'ga ishonib qoldirsak, xato qilishi mumkin —
shuning uchun aniq hisob shu yerda bajariladi va tool'ga majburan uzatiladi (core/moderation.py).

Telegram cheklovi: 30 soniyadan qisqa yoki 366 kundan uzoq muddat "cheksiz" hisoblanadi.
Tool daqiqa bilan ishlagani uchun soniyalar 1 daqiqagacha yuqoriga yaxlitlanadi,
366 kundan uzoq muddat esa 366 kunga tenglanadi.
"""
import math
import re

MAX_MINUTES = 366 * 24 * 60

_ONES = {"bir": 1, "ikki": 2, "uch": 3, "to'rt": 4, "besh": 5, "olti": 6, "yetti": 7, "sakkiz": 8, "to'qqiz": 9}
_TENS = {"o'n": 10, "yigirma": 20, "o'ttiz": 30, "qirq": 40, "ellik": 50, "oltmish": 60}

_NUM_WORDS = (
    r"(?:(?:" + "|".join(re.escape(w) for w in _TENS) + r")(?:\s+(?:" + "|".join(re.escape(w) for w in _ONES) + r"))?"
    r"|" + "|".join(re.escape(w) for w in _ONES) + r"|yarim)"
)
_NUM = r"(?:\d+(?:[.,]\d+)?|" + _NUM_WORDS + r")"
_PAIR = re.compile(rf"(?<![\w'])({_NUM})\s*([^\W\d_]+)", re.UNICODE)

# (prefiks, daqiqadagi qiymati) — aniq mos kelish talab qilinadigan qisqa belgilar alohida
_EXACT = {"m": 1, "min": 1, "h": 60, "d": 1440, "w": 10080, "ч": 60}
_PREFIX = [
    ("soniya", 1 / 60), ("sekund", 1 / 60), ("second", 1 / 60), ("sek", 1 / 60), ("sec", 1 / 60), ("секунд", 1 / 60), ("сек", 1 / 60),
    ("daqiqa", 1), ("daq", 1), ("minut", 1), ("min", 1), ("минут", 1), ("мин", 1),
    ("soat", 60), ("hour", 60), ("hr", 60), ("час", 60),
    ("kun", 1440), ("day", 1440), ("сут", 1440), ("дн", 1440), ("день", 1440), ("дней", 1440),
    ("hafta", 10080), ("week", 10080), ("нед", 10080),
    ("oy", 43200), ("month", 43200), ("мес", 43200),
    ("yil", 525600), ("year", 525600), ("год", 525600), ("лет", 525600),
]
_JOINERS = {"", "va", "u", "и", "and", ",", "+", "&"}


def _normalize(text: str) -> str:
    text = (text or "").lower()
    for ch in ("’", "ʻ", "ʼ", "`", "‘"):
        text = text.replace(ch, "'")
    return re.sub(r"@\w+", " ", text)  # username'dagi raqamlar ("@user5") muddat bo'lib qolmasin


def _number(token: str) -> float | None:
    token = token.strip()
    if re.fullmatch(r"\d+(?:[.,]\d+)?", token):
        return float(token.replace(",", "."))
    if token == "yarim":
        return 0.5
    total = 0
    for w in token.split():
        total += _TENS.get(w, 0) or _ONES.get(w, 0)
    return float(total) if total else None


def _unit_minutes(word: str) -> float | None:
    if word in _EXACT:
        return _EXACT[word]
    for prefix, mins in _PREFIX:
        if word.startswith(prefix):
            return mins
    return None


def parse_all(text: str) -> list[int]:
    """Matndagi HAR BIR alohida muddatni daqiqada qaytaradi. Yonma-yon kelgan bo'laklar
    ("1 soat 30 daqiqa") bitta muddatga qo'shiladi; "A ga 5 daqiqa, B ga 10 daqiqa" — ikkita."""
    text = _normalize(text)
    groups: list[float] = []
    last_end = None
    for m in _PAIR.finditer(text):
        num, mult = _number(m.group(1)), _unit_minutes(m.group(2))
        if num is None or mult is None:
            continue
        value = num * mult
        gap = text[last_end:m.start()].strip() if last_end is not None else None
        if gap is not None and gap in _JOINERS and groups:
            groups[-1] += value
        else:
            groups.append(value)
        last_end = m.end()
    return [min(max(1, math.ceil(v - 1e-9)), MAX_MINUTES) for v in groups if v > 0]


def single_minutes(text: str) -> int | None:
    """Xabarda AYNAN BITTA muddat bo'lsa — uni, aks holda None (aniq emas)."""
    found = parse_all(text)
    return found[0] if len(found) == 1 else None


def fmt(minutes: int) -> str:
    """90 -> '1 soat 30 daqiqa'"""
    d, rem = divmod(int(minutes), 1440)
    h, m = divmod(rem, 60)
    parts = []
    if d:
        parts.append(f"{d} kun")
    if h:
        parts.append(f"{h} soat")
    if m or not parts:
        parts.append(f"{m} daqiqa")
    return " ".join(parts)
