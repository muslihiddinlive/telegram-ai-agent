"""
core/instagram_store.py
-----------------------
Instagram holati bot DB'sida (core/tgdb.py) `db["instagram"]` ostida saqlanadi —
shuning uchun Render qayta deploy qilganda ham yo'qolmaydi (tgdb pin orqali tiklaydi).

  scheduled    : rejalashtirilgan postlar
  triggers     : kalit so'z → DM (private reply) qoidalari
  banned_words : shu so'z bor izoh avtomatik YASHIRILADI (o'chirilmaydi)
  seen         : qayta ishlangan izoh ID'lari (Meta webhook'ni takrorlashi mumkin)
  log          : oxirgi hodisalar
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime
from typing import Optional

MAX_SCHEDULED_PENDING = 30
MAX_TRIGGERS = 50
MAX_BANNED = 200
MAX_SEEN = 500
MAX_LOG = 100


def _db() -> dict:  # testlarda almashtiriladi
    import core.tgdb as tgdb
    return tgdb.get()


def _dirty() -> None:  # testlarda almashtiriladi
    import core.tgdb as tgdb
    tgdb.mark_dirty()


def store_dir() -> str:
    return os.getenv("IG_STORE_DIR") or os.path.join(os.path.dirname(__file__), "..", "data", "ig_scheduled")


def _key() -> str:
    """Joriy akkaunt holati kaliti: egasi akkaunti (env) — eski `instagram` bo'limi (ma'lumot yo'qolmasin);
    foydalanuvchi akkauntlari — `instagram_by_account[ig_id]` (bir-biridan to'liq ajratilgan)."""
    import core.instagram_context as ictx
    a = ictx.current()
    if a is None or a.owner:
        return ""
    return a.ig_id


def _fill(st: dict) -> dict:
    for key, default in (("scheduled", []), ("triggers", []), ("banned_words", []), ("seen", []), ("log", [])):
        st.setdefault(key, default)
    return st


def state() -> dict:
    k = _key()
    if not k:
        return _fill(_db().setdefault("instagram", {}))
    return _fill(_db().setdefault("instagram_by_account", {}).setdefault(k, {}))


def has_pending(ig_id: str) -> bool:
    """Akkauntda kutayotgan/chiqayotgan reja bormi (scheduler har daqiqada behuda token ochmasin)."""
    st = _db().get("instagram_by_account", {}).get(str(ig_id)) or {}
    return any(e.get("status") in ("scheduled", "publishing") for e in st.get("scheduled", []))


def drop_account_state(ig_id: str) -> None:
    """Akkaunt uzilganda: rejalashtirilgan fayllar va butun holat o'chadi (maxfiylik)."""
    by = _db().setdefault("instagram_by_account", {})
    st = by.pop(str(ig_id), None)
    if st:
        for e in st.get("scheduled", []):
            delete_files(e)
        _dirty()


def new_id() -> str:
    return uuid.uuid4().hex[:6]


def log(event: str, detail: str = "") -> None:
    st = state()
    st["log"].append({"t": datetime.now().isoformat(timespec="seconds"), "event": event, "detail": detail[:200]})
    del st["log"][:-MAX_LOG]
    _dirty()


# ── Rejalashtirilgan postlar ───────────────────────────────────────────────────
def add_scheduled(*, kind: str, caption: str, when: datetime, items: list[dict], created_by: int,
                  entry_id: Optional[str] = None) -> dict:
    entry = {
        "id": entry_id or new_id(), "kind": kind, "caption": caption, "when": when.isoformat(),
        "items": items, "status": "scheduled", "created_by": created_by,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    state()["scheduled"].append(entry)
    _dirty()
    return entry


def pending_count() -> int:
    return sum(1 for e in state()["scheduled"] if e["status"] == "scheduled")


def list_scheduled(statuses: Optional[list[str]] = None) -> list[dict]:
    return [e for e in state()["scheduled"] if statuses is None or e["status"] in statuses]


def get_scheduled(entry_id: str) -> Optional[dict]:
    return next((e for e in state()["scheduled"] if e["id"] == entry_id), None)


def set_status(entry_id: str, status: str, **extra) -> None:
    e = get_scheduled(entry_id)
    if e:
        e["status"] = status
        e.update(extra)
        _dirty()


def due(now: datetime) -> list[dict]:
    out = []
    for e in state()["scheduled"]:
        if e["status"] == "scheduled" and datetime.fromisoformat(e["when"]) <= now:
            out.append(e)
    return sorted(out, key=lambda e: e["when"])


def delete_files(entry: dict) -> None:
    for it in entry.get("items", []):
        try:
            os.remove(it["path"])
        except OSError:
            pass
    try:
        os.rmdir(os.path.join(store_dir(), entry["id"]))
    except OSError:
        pass


def cancel_scheduled(entry_id: str) -> bool:
    e = get_scheduled(entry_id)
    if not e or e["status"] != "scheduled":
        return False
    e["status"] = "cancelled"
    delete_files(e)
    _dirty()
    return True


def prune_finished(keep: int = 20) -> None:
    """Tugagan yozuvlardan eng oxirgi `keep` tasini qoldiradi (DB shishmasin)."""
    st = state()
    done = [e for e in st["scheduled"] if e["status"] in ("published", "failed", "cancelled", "unknown")]
    drop = {e["id"] for e in done[:-keep]} if len(done) > keep else set()
    if drop:
        st["scheduled"] = [e for e in st["scheduled"] if e["id"] not in drop]
        _dirty()


# ── Triggerlar ─────────────────────────────────────────────────────────────────
def add_trigger(keyword: str, reply: str, media_id: Optional[str] = None) -> dict:
    t = {"id": new_id(), "keyword": keyword.strip().lower(), "reply": reply.strip(),
         "media_id": media_id or None, "hits": 0}
    state()["triggers"].append(t)
    _dirty()
    return t


def list_triggers() -> list[dict]:
    return state()["triggers"]


def remove_trigger(trigger_id: str) -> bool:
    st = state()
    before = len(st["triggers"])
    st["triggers"] = [t for t in st["triggers"] if t["id"] != trigger_id]
    if len(st["triggers"]) != before:
        _dirty()
        return True
    return False


def match_trigger(text: str, media_id: Optional[str], limit: Optional[int] = None) -> Optional[dict]:
    """limit — tarif chegarasi: faqat dastlabki `limit` ta qoida faol (tarif pasaysa ortig'i uxlaydi)."""
    low = text.lower()
    for t in (state()["triggers"] if limit is None else state()["triggers"][:limit]):
        if t["keyword"] in low and (not t.get("media_id") or t["media_id"] == media_id):
            return t
    return None


def hit_trigger(trigger_id: str) -> None:
    for t in state()["triggers"]:
        if t["id"] == trigger_id:
            t["hits"] = t.get("hits", 0) + 1
            _dirty()


# ── Taqiqlangan so'zlar ────────────────────────────────────────────────────────
def banned_words() -> list[str]:
    return state()["banned_words"]


def add_banned(word: str) -> bool:
    w = word.strip().lower()
    st = state()
    if w in st["banned_words"]:
        return False
    st["banned_words"].append(w)
    _dirty()
    return True


def remove_banned(word: str) -> bool:
    w = word.strip().lower()
    st = state()
    if w in st["banned_words"]:
        st["banned_words"].remove(w)
        _dirty()
        return True
    return False


def match_banned(text: str, limit: Optional[int] = None) -> Optional[str]:
    low = text.lower()
    words = state()["banned_words"] if limit is None else state()["banned_words"][:limit]
    return next((w for w in words if w and w in low), None)


# ── Takroriy webhook'dan himoya ────────────────────────────────────────────────
def mark_seen(comment_id: str) -> bool:
    """True — yangi; False — allaqachon ko'rilgan."""
    st = state()
    if comment_id in st["seen"]:
        return False
    st["seen"].append(comment_id)
    del st["seen"][:-MAX_SEEN]
    _dirty()
    return True


# ── AI DM: sozlama va suhbatlar ────────────────────────────────────────────────
DM_MAX_MSGS = 10          # har suhbatda eslab qolinadigan oxirgi xabarlar
DM_TTL = 7 * 86400        # shundan uzoq jim suhbat o'chiriladi (maxfiylik)
DM_MAX_CONVS = 200


def dm_state() -> dict:
    d = state().setdefault("dm", {})
    d.setdefault("mode", "off")          # off | shadow | auto
    d.setdefault("instructions", "")
    d.setdefault("convs", {})
    return d


def dm_conv(igsid: str) -> dict:
    return dm_state()["convs"].setdefault(igsid, {
        "msgs": [], "human_until": 0, "last_user_ts": 0, "disclosed": False,
        "day": "", "n_today": 0, "notified": False, "cap_notified": False,
    })


def dm_prune(now: float) -> None:
    convs = dm_state()["convs"]
    for k in [k for k, c in convs.items() if now - c.get("last_user_ts", 0) > DM_TTL]:
        del convs[k]
    if len(convs) > DM_MAX_CONVS:
        for k in sorted(convs, key=lambda k: convs[k].get("last_user_ts", 0))[: len(convs) - DM_MAX_CONVS]:
            del convs[k]


def dm_forget(igsid: str) -> bool:
    removed = dm_state()["convs"].pop(igsid, None) is not None
    if removed:
        _dirty()
    return removed


def dm_touch() -> None:
    _dirty()
