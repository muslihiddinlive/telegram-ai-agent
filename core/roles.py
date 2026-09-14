"""
3 bosqichli ruxsat tizimi:
  - superadmin: config.SUPERADMIN_ID (bitta, .env orqali) — hammasini ko'radi/boshqaradi
  - admin: superadmin tomonidan tayinlangan — FAQAT tasdiqlangan userlarni boshqaradi,
    boshqa adminlarni yoki superadminni "bilmaydi" (panelda ko'rinmaydi)
  - approved (tasdiqlangan user): admin YOKI superadmin tomonidan tasdiqlangan,
    kunlik so'rov limiti bilan cheklangan. Superadmin istalgan vaqt bekor qila oladi.
  - pending: hali hech kim tasdiqlamagan, botdan foydalana olmaydi

StokerDownloader'dagi referral/stars-wallet/premium-sotib-olish qismlari
QASDDAN OLIB TASHLANDI — bu yopiq (faqat taklif qilingan userlar) tizim,
ochiq o'sish/pul ishlash kerak emas.
"""
import datetime
import config
import core.tgdb as tgdb

DEFAULT_DAILY_LIMIT = 50


def _bucket(user_id: int) -> dict:
    db = tgdb.get()
    return db["users"].setdefault(str(user_id), {
        "role": "pending",       # pending | approved
        "approved_by": None,
        "daily_limit": DEFAULT_DAILY_LIMIT,
        "requests_today": 0,
        "last_reset": today_str(),
        "name": None,
    })


def today_str() -> str:
    return datetime.date.today().isoformat()


def is_superadmin(user_id: int) -> bool:
    return user_id == config.SUPERADMIN_ID


def is_admin(user_id: int) -> bool:
    """Faqat superadmin tomonidan tayinlangan adminlar — superadminning o'zi bu ro'yxatda emas."""
    db = tgdb.get()
    return str(user_id) in db.get("admins", {})


def is_approved(user_id: int) -> bool:
    db = tgdb.get()
    rec = db["users"].get(str(user_id))
    return bool(rec and rec.get("role") == "approved")


def get_role(user_id: int) -> str:
    if is_superadmin(user_id):
        return "superadmin"
    if is_admin(user_id):
        return "admin"
    if is_approved(user_id):
        return "approved"
    return "pending"


def can_use_bot(user_id: int) -> bool:
    return get_role(user_id) in ("superadmin", "admin", "approved")


# ── Superadmin: adminlarni boshqarish ──

async def add_admin(bot, user_id: int, name: str | None = None):
    db = tgdb.get()
    db.setdefault("admins", {})[str(user_id)] = {"name": name}
    await tgdb.save(bot, force=True)


async def remove_admin(bot, user_id: int):
    db = tgdb.get()
    db.get("admins", {}).pop(str(user_id), None)
    await tgdb.save(bot, force=True)


def list_admins() -> dict:
    db = tgdb.get()
    return db.get("admins", {})


# ── Admin yoki superadmin: tasdiqlangan userlarni boshqarish ──

async def approve_user(bot, user_id: int, approved_by: int, daily_limit: int = DEFAULT_DAILY_LIMIT):
    rec = _bucket(user_id)
    rec["role"] = "approved"
    rec["approved_by"] = approved_by
    rec["daily_limit"] = daily_limit
    await tgdb.save(bot, force=True)


async def revoke_user(bot, user_id: int):
    """Superadmin ISTALGAN vaqt, kim tasdiqlaganidan qat'iy nazar, bekor qila oladi."""
    rec = _bucket(user_id)
    rec["role"] = "pending"
    rec["approved_by"] = None
    await tgdb.save(bot, force=True)


async def set_user_limit(bot, user_id: int, daily_limit: int):
    rec = _bucket(user_id)
    rec["daily_limit"] = daily_limit
    await tgdb.save(bot, force=True)


def list_approved_users() -> dict:
    db = tgdb.get()
    return {uid: rec for uid, rec in db["users"].items() if rec.get("role") == "approved"}


def list_pending_users() -> dict:
    db = tgdb.get()
    return {uid: rec for uid, rec in db["users"].items() if rec.get("role") == "pending"}


# ── Kunlik limit tekshiruvi (approved userlar uchun; admin/superadmin cheksiz) ──

def _reset_if_new_day(rec: dict):
    if rec.get("last_reset") != today_str():
        rec["requests_today"] = 0
        rec["last_reset"] = today_str()


def can_make_request(user_id: int) -> bool:
    role = get_role(user_id)
    if role in ("superadmin", "admin"):
        return True
    if role != "approved":
        return False
    rec = _bucket(user_id)
    _reset_if_new_day(rec)
    return rec["requests_today"] < rec["daily_limit"]


async def register_request(bot, user_id: int):
    role = get_role(user_id)
    if role in ("superadmin", "admin"):
        return  # limitsiz — sanamaymiz
    rec = _bucket(user_id)
    _reset_if_new_day(rec)
    rec["requests_today"] += 1
    await tgdb.save(bot)  # debounced — kritik emas


def remaining_requests(user_id: int) -> int:
    rec = _bucket(user_id)
    _reset_if_new_day(rec)
    return max(0, rec["daily_limit"] - rec["requests_today"])
