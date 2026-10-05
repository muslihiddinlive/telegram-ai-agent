"""
core/instagram_accounts.py
--------------------------
Foydalanuvchilar ULAGAN Instagram akkauntlari va bir martalik bepul sinov.

  db["ig_accounts"][tg_uid] = {ig_id, username, token (Fernet bilan SHIFRLANGAN), issued, expires,
                               connected_at, status: "ok" | "reauth", scopes}
  db["ig_trials"][tg_uid]   = {start, until, ig_id}      — 3 kunlik sinov, har Telegram foydalanuvchiga BIR marta

Qoidalar:
  * Bitta Telegram foydalanuvchi — bitta akkaunt; bitta Instagram akkaunt — bitta Telegram foydalanuvchi.
  * Token hech qachon ochiq saqlanmaydi, loglarga/xatolarga tushmaydi.
  * Uzish (disconnect) tokenni va shu akkauntning barcha holatini (triggerlar, rejalar, DM suhbatlari) o'chiradi;
    sinov esa QAYTMAYDI (uzib-ulab ko'p marta sinab bo'lmaydi).
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import core.instagram_api as ig
import core.instagram_context as ictx

logger = logging.getLogger("instagram_accounts")

TRIAL_DAYS = 3
IG_HOST = "graph.instagram.com"
REFRESH_WITHIN = 10 * 86400     # tugashiga 10 kundan kam qolsa yangilaymiz
REFRESH_MIN_AGE = 86400 + 300   # Meta: token kamida 24 soat eski bo'lishi shart


def _db() -> dict:  # testlarda almashtiriladi
    import core.tgdb as tgdb
    return tgdb.get()


def _dirty() -> None:  # testlarda almashtiriladi
    import core.tgdb as tgdb
    tgdb.mark_dirty()


def _enc(s: str) -> str:
    from core.crypto_store import encrypt
    return encrypt(s)


def _dec(s: str) -> str:
    from core.crypto_store import decrypt
    return decrypt(s)


def _accounts() -> dict:
    return _db().setdefault("ig_accounts", {})


def _trials() -> dict:
    return _db().setdefault("ig_trials", {})


# ── o'qish ─────────────────────────────────────────────────────────────────────
def record(tg_uid: int) -> Optional[dict]:
    return _accounts().get(str(tg_uid))


def status(tg_uid: int) -> str:
    """'none' | 'ok' | 'reauth' (token eskirgan/bekor qilingan — qayta ulash kerak)."""
    rec = record(tg_uid)
    if not rec:
        return "none"
    return "ok" if rec.get("status", "ok") == "ok" else "reauth"


def _to_account(tg_uid: int, rec: dict) -> Optional[ictx.Account]:
    try:
        return ictx.Account(ig_id=rec["ig_id"], token=_dec(rec["token"]), host=IG_HOST,
                            tg_user_id=int(tg_uid), username=rec.get("username", ""))
    except Exception:  # noqa: BLE001 — ENCRYPTION_KEY almashgan/buzilgan yozuv
        logger.warning("IG token shifrini ochib bo'lmadi (tg=%s)", tg_uid)
        return None


def account_for(tg_uid: int) -> Optional[ictx.Account]:
    """Faqat holati 'ok' bo'lgan akkaunt (aks holda None)."""
    rec = record(tg_uid)
    if not rec or rec.get("status", "ok") != "ok":
        return None
    return _to_account(tg_uid, rec)


def by_ig_id(ig_id: str) -> Optional[ictx.Account]:
    """Webhook yo'naltirish uchun: Instagram akkaunt ID'si -> Account (faqat 'ok')."""
    ig_id = str(ig_id)
    for uid, rec in _accounts().items():
        if rec.get("ig_id") == ig_id:
            return account_for(int(uid))
    return None


def all_accounts() -> list[ictx.Account]:
    out = []
    for uid in list(_accounts()):
        a = account_for(int(uid))
        if a:
            out.append(a)
    return out


def iter_accounts(only_with_work: bool = False) -> list[tuple[int, ictx.Account, bool]]:
    """Barcha ulangan akkauntlar: (tg_uid, Account, token_yaroqli). Scheduler uchun."""
    import core.instagram_store as store
    out = []
    for uid, rec in list(_accounts().items()):
        if only_with_work and not store.has_pending(rec["ig_id"]):
            continue
        a = _to_account(int(uid), rec)
        if a:
            out.append((int(uid), a, rec.get("status", "ok") == "ok"))
    return out


def owner_of(ig_id: str) -> Optional[int]:
    for uid, rec in _accounts().items():
        if rec.get("ig_id") == str(ig_id):
            return int(uid)
    return None


# ── Sinov ──────────────────────────────────────────────────────────────────────
def trial(tg_uid: int) -> Optional[dict]:
    return _trials().get(str(tg_uid))


def trial_used(tg_uid: int) -> bool:
    return trial(tg_uid) is not None


def trial_active(tg_uid: int, now: Optional[float] = None) -> bool:
    t = trial(tg_uid)
    return bool(t) and t.get("until", 0) > (time.time() if now is None else now)


def trial_seconds_left(tg_uid: int, now: Optional[float] = None) -> int:
    t = trial(tg_uid)
    if not t:
        return 0
    return max(0, int(t.get("until", 0) - (time.time() if now is None else now)))


def _grant_trial(tg_uid: int, ig_id: str, now: float) -> None:
    """Birinchi ulanishda sinovni belgilaydi. Shu Instagram akkaunt avval boshqa odamning sinovida
    ishlatilgan bo'lsa — yozuv yaratiladi, lekin allaqachon tugagan (sinov berilmaydi)."""
    if trial_used(tg_uid):
        return
    reused = any(t.get("ig_id") == ig_id for t in _trials().values())
    _trials()[str(tg_uid)] = {"start": now, "until": now if reused else now + TRIAL_DAYS * 86400, "ig_id": ig_id}


# ── yozish ─────────────────────────────────────────────────────────────────────
def connect(tg_uid: int, ig_id: str, username: str, token: str, expires_in: int,
            scopes: Optional[list[str]] = None, now: Optional[float] = None) -> tuple[bool, str]:
    """Akkauntni saqlaydi. (True, '') yoki (False, sabab)."""
    now = time.time() if now is None else now
    ig_id = str(ig_id)
    holder = owner_of(ig_id)
    if holder is not None and holder != int(tg_uid):
        return False, "Bu Instagram akkaunt boshqa foydalanuvchiga ulangan."
    env = ig.env_account()
    if env and env.ig_id == ig_id:
        return False, "Bu akkaunt bot egasiga tegishli — uni ulab bo'lmaydi."
    old = record(tg_uid)
    if old and old.get("ig_id") != ig_id:      # boshqa akkauntga o'tish — eskisining holati tozalanadi
        _purge_state(old["ig_id"])
    _accounts()[str(tg_uid)] = {
        "ig_id": ig_id, "username": username, "token": _enc(token), "issued": now,
        "expires": now + int(expires_in), "connected_at": (old or {}).get("connected_at", now),
        "status": "ok", "scopes": list(scopes or []),
    }
    _grant_trial(tg_uid, ig_id, now)
    _dirty()
    return True, ""


def update_token(tg_uid: int, token: str, expires_in: int, now: Optional[float] = None) -> bool:
    rec = record(tg_uid)
    if not rec:
        return False
    now = time.time() if now is None else now
    rec.update(token=_enc(token), issued=now, expires=now + int(expires_in), status="ok")
    _dirty()
    return True


def mark_reauth(tg_uid: int) -> bool:
    """Token yaroqsiz — akkaunt to'xtatiladi (ma'lumotlar saqlanadi, qayta ulagach davom etadi).
    True — holat shu chaqiruvda o'zgardi (xabar bir marta yuborilishi uchun)."""
    rec = record(tg_uid)
    if not rec or rec.get("status") == "reauth":
        return False
    rec["status"] = "reauth"
    _dirty()
    return True


def _purge_state(ig_id: str) -> None:
    import core.instagram_store as store
    store.drop_account_state(ig_id)


def disconnect(tg_uid: int) -> bool:
    """Tokenni va shu akkauntning BARCHA holatini o'chiradi. Sinov qaytmaydi."""
    rec = _accounts().pop(str(tg_uid), None)
    if not rec:
        return False
    _purge_state(rec["ig_id"])
    _dirty()
    return True


def due_for_refresh(now: Optional[float] = None) -> list[int]:
    now = time.time() if now is None else now
    out = []
    for uid, rec in _accounts().items():
        if rec.get("status", "ok") != "ok":
            continue
        if rec["expires"] - now < REFRESH_WITHIN and now - rec["issued"] > REFRESH_MIN_AGE:
            out.append(int(uid))
    return out


def expired(now: Optional[float] = None) -> list[int]:
    """Muddati o'tib ketgan (yangilanmagan) tokenlar — qayta ulash kerak."""
    now = time.time() if now is None else now
    return [int(u) for u, r in _accounts().items() if r.get("status", "ok") == "ok" and r["expires"] <= now]


def on_auth_error(account: ictx.Account) -> None:
    """ig._request 190 xatosida chaqiradi."""
    if account.tg_user_id and mark_reauth(account.tg_user_id):
        logger.info("IG token yaroqsiz — qayta ulash kerak (tg=%s)", account.tg_user_id)
        _pending_reauth_notice.add(account.tg_user_id)


_pending_reauth_notice: set[int] = set()


ig.auth_error_hook = on_auth_error
