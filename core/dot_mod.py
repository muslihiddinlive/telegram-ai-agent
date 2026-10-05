"""
core/dot_mod.py
---------------
Nuqtali guruh moderatsiya buyruqlarining TAHLILI (sof funksiyalar; Telegram'ga tegmaydi).
Sintaksis StokerDownloader'dagi `.ban/.unban/.kick/.mute/.unmute/.del` dan olingan:

  .ban    [@user|ID] [muddat] [sabab]     — ban (muddat bo'lmasa — butunlay)
  .unban  [@user|ID] [sabab]
  .kick   [@user|ID] [sabab]              — chiqarish (qaytib kira oladi)
  .mute   [@user|ID] [muddat] [sabab]     — muddat bo'lmasa — butunlay
  .unmute [@user|ID] [sabab]
  .del                                    — reply qilingan xabarni (va buyruqni) o'chiradi
  .modhelp                                — yordam

Nishon: xabarga REPLY qilib yoki @username / raqamli ID bilan. Muddat: `30m`, `1h`, `2k`, `1 h`, `3kun`, `1hafta`, `2o`...
Birliklar: s(soniya) m(daqiqa) h(soat) d|k(kun) w(hafta) o(oy=30 kun) y(yil=365 kun). Tartib erkin:
`.mute @jasur_bek 1h so'kindi`, `.mute 1h @jasur_bek`, reply + `.mute 30m spam`.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Optional

import core.duration as duration

ACTIONS = ("ban", "unban", "kick", "mute", "unmute", "del", "modhelp")
TIMED = {"ban", "mute"}
MAX_REASON = 200

# Guruhda e'tibor beriladigan xabar: nuqta + buyruq, so'ng bo'sh joy yoki oxir ("banana", ".bank" mos kelmaydi)
COMMAND_PATTERN = re.compile(r"^\s*\.(" + "|".join(ACTIONS) + r")(?:\s|$)", re.IGNORECASE)

_UNIT_MINUTES: dict[str, float] = {
    "s": 1 / 60, "sek": 1 / 60, "sec": 1 / 60, "soniya": 1 / 60,
    "m": 1, "min": 1, "daq": 1, "daqiqa": 1,
    "h": 60, "hr": 60, "soat": 60,
    "d": 1440, "k": 1440, "kun": 1440,
    "w": 10080, "hafta": 10080,
    "o": 43200, "oy": 43200,
    "y": 525600, "yil": 525600,
}
_DURATION_RE = re.compile(r"^(\d{1,7})([a-z']{1,8})$")
_ID_RE = re.compile(r"^-?\d{5,15}$")                 # Telegram ID'lari kamida 5 xonali: "30" muddat, "123456789" ID
# "@" bilan boshlangan so'z — nishon (noto'g'ri/qisqa bo'lsa ham: "topa olmadim" deyish jimgina "sabab" deb olishdan yaxshi)
_USERNAME_RE = re.compile(r"^@\w{2,32}$", re.ASCII)


@dataclass
class Parsed:
    action: str
    target: Optional[str] = None      # "@username" yoki raqamli ID (matn ko'rinishida) — reply bo'lsa None
    minutes: Optional[int] = None     # faqat ban/mute; None — butunlay
    reason: Optional[str] = None


def _norm(token: str) -> str:
    low = token.lower()
    for ch in ("’", "ʻ", "ʼ", "`", "‘"):
        low = low.replace(ch, "'")
    return low


def parse_duration_token(token: str) -> Optional[int]:
    """'30m', '1h', '2k', '3kun' -> daqiqa (butun, kamida 1; Telegram chegarasi 366 kun). Muddat bo'lmasa None."""
    m = _DURATION_RE.match(_norm(token.strip()))
    if not m:
        return None
    mult = _UNIT_MINUTES.get(m.group(2))
    n = int(m.group(1))
    if mult is None or n <= 0:
        return None
    return min(max(1, math.ceil(n * mult - 1e-9)), duration.MAX_MINUTES)


def parse(text: str) -> Optional[Parsed]:
    """Xabar matni -> Parsed yoki None (nuqtali moderatsiya buyrug'i emas)."""
    m = COMMAND_PATTERN.match(text or "")
    if not m:
        return None
    action = m.group(1).lower()
    tokens = (text or "").strip()[len(m.group(0).strip()):].split()
    parsed = Parsed(action)
    i = 0
    while i < len(tokens) and i < 3:             # nishon va muddat faqat boshida; qolgani — sabab
        tok = tokens[i]
        if parsed.target is None and (_USERNAME_RE.match(tok) or _ID_RE.match(tok)):
            parsed.target, i = tok, i + 1
            continue
        if action in TIMED and parsed.minutes is None:
            d = parse_duration_token(tok)
            if d is not None:
                parsed.minutes, i = d, i + 1
                continue
            if tok.isdigit() and i + 1 < len(tokens):          # "1 h" (ikki so'z)
                d = parse_duration_token(tok + tokens[i + 1])
                if d is not None:
                    parsed.minutes, i = d, i + 2
                    continue
        break
    reason = " ".join(tokens[i:]).strip()
    parsed.reason = reason[:MAX_REASON] or None
    return parsed


HELP = (
    "🛡 <b>Guruh moderatsiyasi</b> (botga tag qilish shart emas)\n"
    "Nishon: xabarga <b>reply</b> qiling yoki <code>@username</code> / ID yozing.\n\n"
    "<code>.ban [@user] [muddat] [sabab]</code> — ban (muddat yo'q — butunlay)\n"
    "<code>.unban [@user] [sabab]</code> — ban'dan chiqarish\n"
    "<code>.kick [@user] [sabab]</code> — chiqarish (qaytib kira oladi)\n"
    "<code>.mute [@user] [muddat] [sabab]</code> — mute (muddat yo'q — butunlay)\n"
    "<code>.unmute [@user] [sabab]</code> — mute'dan chiqarish\n"
    "<code>.del</code> — reply qilingan xabarni o'chirish\n\n"
    "Muddat: <code>30m</code> <code>1h</code> <code>2k</code> <code>1hafta</code> "
    "(s soniya · m daqiqa · h soat · k kun · w hafta · o oy · y yil).\n"
    "Misol: <code>.mute @jasur_bek 1h so'kindi</code>\n"
    "Huquq: Telegram'da sizda tegishli admin huquqi bo'lishi kerak (ban/mute — «A'zolarni cheklash», "
    ".del — «Xabarlarni o'chirish»); botda ham shu huquqlar yoqilgan bo'lishi shart."
)
