"""
core/instagram_settings.py
--------------------------
Meta'dagi *Instagram ilovasi* kalitlari — IG_APP_ID va IG_APP_SECRET. Ikki joydan beriladi:
  1) superadmin paneldan (/panel -> 📸 Instagram) — qayta deploy SHART EMAS; App Secret Fernet bilan shifrlanib saqlanadi;
  2) Render env'dan (IG_APP_ID / IG_APP_SECRET).

Qoida: qiymatlar faqat JUFT bo'lib ishlatiladi (panelda ikkalasi ham bo'lsa — panel; aks holda env juftligi) — panelning
App ID'si env'ning boshqa App Secret'i bilan HECH QACHON aralashmaydi. Panel qiymatlari env'dan ustun (superadmin ataylab kiritgan).
"""
from __future__ import annotations

import logging
import os
import re
from typing import Optional

logger = logging.getLogger("instagram_settings")

APP_ID_RE = re.compile(r"^\d{8,20}$")
APP_SECRET_RE = re.compile(r"^[A-Za-z0-9]{20,64}$")


def _stored() -> dict:
    try:
        import core.tgdb as tgdb
        return tgdb.get().get("ig_settings") or {}
    except Exception:  # noqa: BLE001 — DB hali yuklanmagan (ishga tushish/testlar): faqat env
        return {}


def _pair() -> tuple[str, Optional[tuple[str, str]], str]:
    """(app_id, (tur, secret), manba) — manba: 'panel' | 'env' | ''. Juftlik to'liq bo'lmasa — bo'sh."""
    st = _stored()
    if st.get("app_id") and st.get("app_secret"):
        return st["app_id"], ("enc", st["app_secret"]), "panel"
    e_id, e_secret = os.getenv("IG_APP_ID", "").strip(), os.getenv("IG_APP_SECRET", "").strip()
    if e_id and e_secret:
        return e_id, ("plain", e_secret), "env"
    return "", None, ""


def configured() -> bool:
    """Instagram ulash yoqilganmi (to'liq juftlik bormi). Shifr ochilmaydi — tez."""
    return _pair()[1] is not None


def source() -> str:
    return _pair()[2]


def app_id() -> str:
    return _pair()[0]


def app_secret() -> str:
    _, sec, _ = _pair()
    if sec is None:
        return ""
    kind, value = sec
    if kind == "plain":
        return value
    try:
        from core.crypto_store import decrypt
        return decrypt(value)
    except Exception:  # noqa: BLE001 — ENCRYPTION_KEY almashgan/buzilgan yozuv
        logger.warning("IG App Secret shifrini ochib bo'lmadi (ENCRYPTION_KEY o'zgargan bo'lishi mumkin)")
        return ""


def masked_id(value: str) -> str:
    return f"{value[:3]}…{value[-3:]}" if len(value) > 8 else "•••"


def masked_secret(value: str) -> str:
    return f"••••{value[-4:]}" if len(value) >= 8 else "••••"


def status() -> dict:
    """Panel uchun holat (sirlarni OCHMAYDI — faqat niqoblangan ko'rinish)."""
    st = _stored()
    pid, sec, src = _pair()
    secret_plain = ""
    if sec is not None:
        secret_plain = app_secret()
    return {
        "configured": sec is not None, "source": src, "app_id": masked_id(pid) if pid else "",
        "secret": masked_secret(secret_plain) if secret_plain else "",
        "panel_id": bool(st.get("app_id")), "panel_secret": bool(st.get("app_secret")),
        "env": bool(os.getenv("IG_APP_ID") and os.getenv("IG_APP_SECRET")),
    }


# ── yozish (faqat superadmin paneli chaqiradi) ─────────────────────────────────
async def _save(bot) -> None:
    import core.tgdb as tgdb
    await tgdb.save(bot, force=True)


def _bucket() -> dict:
    import core.tgdb as tgdb
    return tgdb.get().setdefault("ig_settings", {})


async def set_app_id(bot, value: str) -> tuple[bool, str]:
    value = (value or "").strip()
    if not APP_ID_RE.match(value):
        return False, "App ID faqat raqamlardan iborat (8–20 ta raqam). Meta → Instagram → API setup dagi «Instagram App ID»."
    b = _bucket()
    if b.get("app_id") and b["app_id"] != value:
        b.pop("app_secret", None)           # boshqa ilova — eski Secret mos kelmaydi, qayta kiritiladi
    b["app_id"] = value
    await _save(bot)
    return True, ""


async def set_app_secret(bot, value: str) -> tuple[bool, str]:
    value = (value or "").strip()
    if not APP_SECRET_RE.match(value):
        return False, "App Secret noto'g'ri ko'rinadi (20–64 ta harf/raqam, bo'sh joysiz). Meta → «Instagram App Secret»."
    from core.crypto_store import encrypt
    _bucket()["app_secret"] = encrypt(value)
    await _save(bot)
    return True, ""


async def clear(bot) -> bool:
    import core.tgdb as tgdb
    had = bool(tgdb.get().pop("ig_settings", None))
    if had:
        await _save(bot)
    return had
