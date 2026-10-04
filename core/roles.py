"""
3 bosqichli ruxsat tizimi:
  - superadmin: config.SUPERADMIN_ID (bitta, .env orqali) — hammasini ko'radi/boshqaradi
  - admin: superadmin tomonidan tayinlangan — FAQAT tasdiqlangan userlarni boshqaradi,
    boshqa adminlarni yoki superadminni "bilmaydi" (panelda ko'rinmaydi)
  - approved (oddiy user): /start bosgan HAR KIM avtomatik shu holatga tushadi —
    admin tasdig'i KUTILMAYDI. Kunlik so'rov limiti bilan cheklangan.
  - blocked: superadmin qo'lda bloklagan user, botdan (shaxsiy chatda) foydalana olmaydi.
    (Eski "pending" yozuvlari ham approved sifatida qabul qilinadi.)

StokerDownloader'dagi referral/stars-wallet qismlari QASDDAN OLIB TASHLANDI. Pullik TARIFLAR (Telegram Stars,
oylik) keyinroq alohida qo'shildi — core/tariffs.py: faol tarif kunlik limitni oshiradi (_limit_of).
"""
import datetime
import config
import core.tgdb as tgdb

DEFAULT_DAILY_LIMIT = 20
ADMIN_DAILY_LIMIT = getattr(config, "ADMIN_DAILY_LIMIT", 100)  # bot adminlari + superadmin (chatmode hisobi)


def _bucket(user_id: int) -> dict:
    db = tgdb.get()
    return db["users"].setdefault(str(user_id), {
        "role": "approved",      # approved | blocked  (avto-tasdiq: admin kutilmaydi)
        "approved_by": "auto",
        "daily_limit": DEFAULT_DAILY_LIMIT,
        "requests_today": 0,
        "last_reset": today_str(),
        "name": None,
        "username": None,
    })


async def touch_user_identity(bot, user_id: int, name: str | None, username: str | None):
    """
    Botga yozgan HAR BIR foydalanuvchining ID'si + ism/username'ini
    doimiy yangilab boradi (foydalanuvchi buni sezmaydi — sukut bo'yicha
    ishlaydi). Admin keyinchalik AI orqali "Falonchi kim edi?" desa
    topa olishi uchun kerak (core/ai_tools.py -> lookup_user tool).
    Har xabarda chaqirilgani uchun DEBOUNCED save (force=False) ishlatiladi.
    """
    rec = _bucket(user_id)
    changed = False
    if name and rec.get("name") != name:
        rec["name"] = name
        changed = True
    if username and rec.get("username") != username:
        rec["username"] = username
        changed = True
    if changed:
        await tgdb.save(bot)


def today_str() -> str:
    return datetime.date.today().isoformat()


def is_superadmin(user_id: int) -> bool:
    return user_id == config.SUPERADMIN_ID


def is_admin(user_id: int) -> bool:
    """Faqat superadmin tomonidan tayinlangan adminlar — superadminning o'zi bu ro'yxatda emas."""
    db = tgdb.get()
    return str(user_id) in db.get("admins", {})


def is_blocked(user_id: int) -> bool:
    db = tgdb.get()
    rec = db["users"].get(str(user_id))
    return bool(rec and rec.get("role") == "blocked")


def is_approved(user_id: int) -> bool:
    """Bloklanmagan har bir user (superadmin/admin'dan tashqari) avtomatik 'approved'."""
    return not is_blocked(user_id)


def get_role(user_id: int) -> str:
    if is_superadmin(user_id):
        return "superadmin"
    if is_admin(user_id):
        return "admin"
    if is_blocked(user_id):
        return "blocked"
    return "approved"


def can_use_bot(user_id: int) -> bool:
    return get_role(user_id) in ("superadmin", "admin", "approved")


# ── Superadmin: adminlarni boshqarish ──

async def add_admin(bot, user_id: int, name: str | None = None):
    db = tgdb.get()
    db.setdefault("admins", {})[str(user_id)] = {"name": name}
    await tgdb.save(bot, force=True)


async def remove_admin(bot, user_id: int) -> bool:
    """Adminlikni olib tashlaydi. Admin bo'lgan bo'lsa True. Moderatsiya keshidagi (chat, user) yozuvlari ham tozalanadi —
    aks holda eski admin huquqi kesh muddati tugaguncha ishlab turardi."""
    db = tgdb.get()
    existed = db.get("admins", {}).pop(str(user_id), None) is not None
    if existed:
        import core.moderation as moderation
        for key in [k for k in moderation._access_cache if k[1] == user_id]:
            moderation._access_cache.pop(key, None)
        await tgdb.save(bot, force=True)
    return existed


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
    """Superadmin istalgan userni bloklay oladi (qayta ochish: approve_user)."""
    rec = _bucket(user_id)
    rec["role"] = "blocked"
    rec["approved_by"] = None
    await tgdb.save(bot, force=True)


async def set_user_limit(bot, user_id: int, daily_limit: int):
    rec = _bucket(user_id)
    rec["daily_limit"] = daily_limit
    await tgdb.save(bot, force=True)


def list_approved_users() -> dict:
    db = tgdb.get()
    return {uid: rec for uid, rec in db["users"].items() if rec.get("role") != "blocked"}


def list_blocked_users() -> dict:
    db = tgdb.get()
    return {uid: rec for uid, rec in db["users"].items() if rec.get("role") == "blocked"}


# ── Kunlik limit tekshiruvi ──
# MUHIM: shaxsiy chatda bloklanmagan bo'lish kerak (admin tasdig'i KERAK EMAS),
# GURUHDA esa bloklash ham tekshirilmaydi — faqat
# kunlik limit tekshiriladi (can_use_in_group). Ikkalasi ham BIR XIL
# hisoblagichni (requests_today/daily_limit) ishlatadi — ya'ni bitta odam
# shaxsiy chatda va guruhlarda ishlatgani BIRGALIKDA bitta kunlik limitdan
# kamayadi (chat bo'yicha alohida emas, foydalanuvchi bo'yicha yagona).

FILE_GENERATION_WEIGHT = 3  # fayl/prezentatsiya/diagramma yaratish — 3x qimmatroq


def _limit_of(user_id: int, rec: dict) -> int:
    """Kunlik limit = max(foydalanuvchining o'z limiti, faol tarif limiti) — admin qo'lda bergan katta limit kamaymaydi."""
    import core.tariffs as tariffs
    return max(rec["daily_limit"], tariffs.tier_limit(user_id) or 0)


def _reset_if_new_day(rec: dict):
    if rec.get("last_reset") != today_str():
        rec["requests_today"] = 0
        rec["files_today"] = 0   # tarif kvotalari (core/tariffs.py): fayl yaratish / rasm o'qish — kunlik
        rec["vision_today"] = 0
        rec["last_reset"] = today_str()


def can_make_request(user_id: int) -> bool:
    """Shaxsiy chat uchun — bloklanmagan bo'lish + kunlik limit."""
    role = get_role(user_id)
    if role in ("superadmin", "admin"):
        return True
    if role != "approved":
        return False
    rec = _bucket(user_id)
    _reset_if_new_day(rec)
    return rec["requests_today"] < _limit_of(user_id, rec)


def can_use_in_group(user_id: int) -> bool:
    """
    Guruh uchun — global tasdiqlash SHART EMAS, faqat kunlik limit
    tekshiriladi. Foydalanuvchi yozuvi hali bo'lmasa, standart (20/kun)
    limit bilan avtomatik yaratiladi — admin tasdig'i kutilmaydi.
    """
    role = get_role(user_id)
    if role in ("superadmin", "admin"):
        return True
    rec = _bucket(user_id)  # avtomatik yaratadi (role="approved")
    _reset_if_new_day(rec)
    return rec["requests_today"] < _limit_of(user_id, rec)


def effective_daily_limit(user_id: int) -> int:
    """Superadmin/bot admini uchun ADMIN_DAILY_LIMIT (100), qolganlar uchun o'z limiti."""
    if get_role(user_id) in ("superadmin", "admin"):
        return ADMIN_DAILY_LIMIT
    return _limit_of(user_id, _bucket(user_id))


def _quota_left(user_id: int) -> bool:
    """Roldan qat'iy nazar, foydalanuvchining KUNLIK hisobida joy bormi?"""
    rec = _bucket(user_id)
    _reset_if_new_day(rec)
    return rec["requests_today"] < effective_daily_limit(user_id)


def resolve_chatmode_payer(owner_id: int, writer_id: int) -> int | None:
    """
    /chatmode on (VIP EMAS) guruhida bu xabar kimning hisobidan ketishini aniqlaydi:
      1) rejimni yoqqan odamning (owner) limiti bor  -> owner
         (owner superadmin/admin bo'lsa ham u yoqqan rejim UNING kunlik hisobidan
          ketadi, limiti ADMIN_DAILY_LIMIT=100/kun — cheksiz rejim uchun /vipchatmode bor)
      2) owner'niki tugagan -> xabarni YOZGAN odamning o'z limiti
         (superadmin/admin yozuvchi o'z rolida limitsiz)
      3) ikkalasi ham tugagan -> None (javob berilmaydi)
    """
    if _quota_left(owner_id):
        return owner_id
    if can_use_in_group(writer_id):
        return writer_id
    return None


async def register_request(bot, user_id: int, weight: int = 1, force: bool = False):
    """
    weight — nechta so'rov sifatida hisoblansin (oddiy suhbat=1,
    fayl/prezentatsiya/diagramma generatsiyasi=FILE_GENERATION_WEIGHT).
    Ishlaydi role'idan qat'iy nazar (pending guruh-userlari uchun ham) —
    faqat superadmin/admin uchun sanalmaydi (ular limitsiz).
    force=True — rolidan qat'iy nazar sanaydi (chatmode owner'i hisobidan ketganda).
    """
    role = get_role(user_id)
    if role in ("superadmin", "admin") and not force:
        return  # limitsiz — sanamaymiz
    rec = _bucket(user_id)
    _reset_if_new_day(rec)
    rec["requests_today"] += weight
    await tgdb.save(bot)  # debounced — kritik emas


def remaining_requests(user_id: int) -> int:
    rec = _bucket(user_id)
    _reset_if_new_day(rec)
    return max(0, _limit_of(user_id, rec) - rec["requests_today"])


def build_users_csv() -> str:
    """
    Barcha foydalanuvchilar ro'yxatini CSV matn sifatida qaytaradi —
    StokerDownloader/build_users_csv patternidan.

    Eslatma: "approved_by" (kim tasdiqlagan) ustuni QASDDAN qo'shilmagan —
    aks holda admin CSV'ni ochib, kimning ID'si superadmin ekanini
    (barcha yozuvlarda takrorlangan ID orqali) bilib olishi mumkin edi.
    """
    import csv
    import io

    db = tgdb.get()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["user_id", "name", "role", "daily_limit", "requests_today", "last_reset"])

    for uid, rec in db["users"].items():
        writer.writerow([
            uid,
            rec.get("name") or "",
            rec.get("role", "approved"),
            rec.get("daily_limit", ""),
            rec.get("requests_today", 0),
            rec.get("last_reset", ""),
        ])

    return buf.getvalue()


def search_users(query: str) -> dict:
    """
    ID (aniq mos kelish) yoki ism bo'yicha (substring, katta-kichik harf
    farqisiz) qidiradi — StokerDownloader/search_users_by_prefix patternidan,
    lekin prefix emas, "contains" qidiruv (qulayroq).
    """
    db = tgdb.get()
    query = query.strip()

    if query.isdigit() and query in db["users"]:
        return {query: db["users"][query]}

    query_lower = query.lstrip("@").lower()
    return {
        uid: rec for uid, rec in db["users"].items()
        if query_lower in (rec.get("name") or "").lower()
        or query_lower in (rec.get("username") or "").lower()
        or query_lower in uid
    }
