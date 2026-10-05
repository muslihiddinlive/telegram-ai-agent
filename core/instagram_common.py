"""
core/instagram_common.py
------------------------
Barcha Instagram tool'lari uchun umumiy: ruxsat, fayl tekshiruvi va SERVER
tomonidan majburlanadigan ikki bosqichli tasdiq ("darvoza").

Darvoza qoidasi: ommaviy yoki qaytarib bo'lmaydigan amal 1-chaqiruvda faqat
preview qaytaradi; 2-chaqiruv (confirmed=true) faqat AYNAN shu parametrlar bilan,
foydalanuvchining KEYINGI xabaridan so'ng, bir marta, 10 daqiqa ichida o'tadi.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from datetime import timedelta, timezone
from typing import Optional

import core.instagram_api as ig
import core.instagram_media as media

TASHKENT = timezone(timedelta(hours=5))  # core/clock.py bilan bir xil
KINDS = ("POST", "CAROUSEL", "REEL", "STORY")
MAX_CAPTION = 2200
MAX_HASHTAGS = 30
CONFIRM_TTL = 600

LOCK = asyncio.Lock()  # bir vaqtda bitta e'lon (qo'lda ham, rejali ham)


# ── Ruxsat ─────────────────────────────────────────────────────────────────────
def allowed(user_id: int) -> bool:
    raw = os.getenv("IG_ALLOWED_USER_IDS", "")
    extra = {int(x) for x in raw.replace(" ", "").split(",") if x.isdigit()}
    if user_id in extra:
        return True
    try:
        import core.roles as roles
        return roles.is_superadmin(user_id)
    except Exception:
        return False


def user_dir(user_id: int) -> str:
    from tools.file_tools import user_dir as _ud
    return _ud(user_id)


def require(user_id: int, ctx: dict) -> Optional[dict]:
    """Xato dict yoki None (ruxsat bor)."""
    if not ig.is_configured():
        return {"error": "Instagram ulanmagan (IG_USER_ID / IG_ACCESS_TOKEN o'rnatilmagan)."}
    if ctx.get("is_group"):
        return {"error": "Instagram amallari faqat shaxsiy chatda ishlaydi."}
    if not allowed(user_id):
        return {"error": "Sizda Instagram huquqi yo'q."}
    return None


# ── Fayl tekshiruvi ────────────────────────────────────────────────────────────
def names(raw) -> list[str]:
    if isinstance(raw, str):
        raw = [raw]
    return [os.path.basename(str(n)) for n in (raw or []) if str(n).strip()]  # ../ himoyasi


def validate(kind: str, file_names: list[str], caption: str, udir: str):
    """(items, xato). items = [(yo'l, is_video), ...]"""
    if kind not in KINDS:
        return None, f"Noma'lum tur '{kind}'. Mumkin: {', '.join(KINDS)}"
    if len(caption) > MAX_CAPTION:
        return None, f"Caption juda uzun ({len(caption)} belgi, eng ko'pi {MAX_CAPTION})"
    if sum(1 for w in caption.split() if w.startswith("#")) > MAX_HASHTAGS:
        return None, f"Hashtag'lar {MAX_HASHTAGS} tadan oshmasligi kerak"

    limits = {"POST": (1, 1), "REEL": (1, 1), "STORY": (1, 1), "CAROUSEL": (2, 10)}
    lo, hi = limits[kind]
    if not lo <= len(file_names) <= hi:
        need = f"{lo}" if lo == hi else f"{lo}-{hi}"
        return None, f"{kind} uchun {need} ta fayl kerak, {len(file_names)} ta berildi"

    items = []
    for n in file_names:
        path = os.path.join(udir, n)
        if not os.path.isfile(path):
            return None, f"'{n}' fayli topilmadi. Foydalanuvchidan qayta yuborishni so'rang."
        k = media.kind_of(n)
        if k is None:
            return None, f"'{n}' — Instagram uchun rasm (jpg/png/webp) yoki video (mp4/mov) bo'lishi kerak"
        if kind == "POST" and k != "image":
            return None, "POST uchun rasm kerak (video uchun REEL tanlang)"
        if kind == "REEL" and k != "video":
            return None, "REEL uchun video kerak"
        items.append((path, k == "video"))
    return items, None


# ── Tasdiq darvozasi ───────────────────────────────────────────────────────────
_PENDING: dict[tuple[int, str], tuple[object, float]] = {}  # (user, digest) -> (xabar_id, tugash)


def digest(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, default=str).encode()).hexdigest()


def gate(user_id: int, parts: tuple, ctx: dict, confirmed: bool, preview: dict) -> Optional[dict]:
    """None → davom etish mumkin. Aks holda AI'ga qaytariladigan dict (preview yoki xato)."""
    now = time.time()
    for k in [k for k, (_, exp) in _PENDING.items() if exp < now]:
        del _PENDING[k]

    key = (user_id, digest(*parts))
    msg_id = ctx.get("message_id")

    if not confirmed:
        _PENDING[key] = (msg_id, now + CONFIRM_TTL)
        return {
            "status": "tasdiq_kerak",
            "preview": preview,
            "ai_uchun": (
                "Hali HECH NARSA bajarilmadi. Foydalanuvchiga yuqoridagini ko'rsating va aniq so'rang. "
                "U KEYINGI xabarida aniq rozilik bersa, AYNAN shu parametrlar bilan confirmed=true qilib "
                "qayta chaqiring."
            ),
        }

    pending = _PENDING.get(key)
    if not pending:
        return {"error": "Tasdiqlanmagan yoki muddati o'tgan (yoki parametrlar o'zgargan). "
                         "Avval confirmed'siz chaqirib, foydalanuvchiga ko'rsating."}
    if msg_id is not None and pending[0] == msg_id:
        return {"error": "Foydalanuvchining alohida tasdig'i kerak: uning keyingi xabarini kuting."}
    del _PENDING[key]  # bir martalik
    return None
