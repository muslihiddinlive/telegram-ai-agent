"""
Tariflar (obuna) — Telegram Stars (XTR) bilan to'lanadi, har biri 30 kun, tugagach BEPUL tarifga qaytadi.

Har tarifda:  kunlik so'rov limiti  |  kunlik FAYL yaratish kvotasi  |  kunlik RASM o'qish kvotasi  |  story izohi (caption)
  free  (Bepul)   foydalanuvchining o'z limiti      4        2        yo'q
  plus  (Plus)    100                               20       10       ha
  pro   (Pro)     300                               100      70       ha
Hammasi superadmin tomonidan /panel → 💳 Tariflar orqali o'zgartiriladi (narx ham, limitlar ham) — o'zgarishlar DB'da
(db["tariff_config"]) saqlanadi va darhol hammaga amal qiladi; env (TARIFF_*) faqat BOSHLANG'ICH qiymat.

"Fayl yaratish" = AI tool fayl chiqarsa (docx/xlsx/pptx/pdf/html/py/taqdimot/diagramma... — core/output_files.py bo'yicha), har bir
shunday tool chaqiruvi 1 ta. "Rasm o'qish" = look_at_image muvaffaqiyatli chaqiruvi. Story qo'yish tarifga bog'liq EMAS (hamma uchun
cheksiz); faqat story IZOHI (caption) Plus/Pro uchun.

Qoidalar:
  - Limit = max(foydalanuvchining o'z limiti, tarif limiti): admin qo'lda katta limit bergan bo'lsa u kamaymaydi.
  - Superadmin/bot adminlarida kvota yo'q (cheksiz); VIP chatmode — cheksiz.
  - Guruhda kvota hisobi to'layotgan odamdan (chatmode egasi) ketadi — so'rov limiti bilan bir xil.
  - Xarid: shu tarifni uzaytirish (+30 kun), yuqoriroq tarifga o'tish (30 kun hozirdan; pastroqning qolgan kunlari yo'qoladi —
    oldindan ko'rsatiladi), PASTROQ tarifni faol yuqori tarif ustiga sotib olib bo'lmaydi.
  - To'lov idempotent: bir xil telegram_payment_charge_id ikki marta hisoblanmaydi.
  - Eslatma: tugashiga 3 kun va 1 kun qolganda, tugagandan keyin — har biri bir martadan (send_reminders).
  - db["subscriptions"][uid] = {"tier","until","charges":[...],"stars_total","rem":{"u","k"}}.
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import config
import core.bot_identity as bot_identity
import core.tgdb as tgdb

logger = logging.getLogger("tariffs")

DURATION_DAYS = 30
CHARGES_KEPT = 30
KIND_FILES = "files"
KIND_VISION = "vision"
KIND_GITHUB = "github"     # GitHub amallari (tarmoqqa chiqadiganlari): core/github_ops.py
KIND_SITE = "site"         # sayt frontend'ini o'qish/ko'chirish: core/site_ops.py
KINDS = (KIND_FILES, KIND_VISION, KIND_GITHUB, KIND_SITE)
FILES_OWN_TOOLS = frozenset({"create_presentation", "create_diagram"})
VISION_TOOLS = frozenset({"look_at_image"})
# Fayl chiqarmaydigan (faqat o'qiydigan/qidiradigan) tool'lar prefikslari — kvota tugaganda ham ishlayveradi
READONLY_PREFIXES = ("read_", "get_", "list_", "search_", "scrape_", "fetch_", "extract_page_", "count_")
PAYLOAD_PREFIX = "tariff"
EXPIRED_REMIND_WINDOW = 7 * 86400

# Tahrirlanadigan maydonlar: (min, max, faqat pullik tariflar uchunmi)
FIELDS = {
    "stars": (1, 10000, True),
    "daily_limit": (1, 100000, True),
    "files": (0, 100000, False),
    "vision": (0, 100000, False),
    "github": (0, 100000, False),
    "site": (0, 100000, False),
}
FIELD_LABELS = {"stars": "Narx (⭐)", "daily_limit": "So'rov/kun", "files": "Fayl/kun", "vision": "Rasm o'qish/kun", "github": "GitHub amal/kun", "site": "Sayt o'qish/ko'chirish/kun"}


@dataclass(frozen=True)
class Tier:
    id: str
    name: str
    rank: int
    stars: int
    daily_limit: int | None  # None — foydalanuvchining o'z limiti
    files: int
    vision: int
    caption: bool
    github: int = 0
    site: int = 0


def _defaults() -> dict[str, dict]:
    return {
        "free": {"name": "Bepul", "rank": 0, "stars": 0, "daily_limit": None, "files": 4, "vision": 2, "caption": False, "github": 10, "site": 3},
        "plus": {"name": "Plus ⭐", "rank": 1, "stars": config.TARIFF_PLUS_STARS, "daily_limit": config.TARIFF_PLUS_LIMIT,
                 "files": 20, "vision": 10, "caption": True, "github": 100, "site": 25},
        "pro": {"name": "Pro 💎", "rank": 2, "stars": config.TARIFF_PRO_STARS, "daily_limit": config.TARIFF_PRO_LIMIT,
                "files": 100, "vision": 70, "caption": True, "github": 500, "site": 100},
    }


def _overrides() -> dict:
    return tgdb.get().get("tariff_config", {})


def tiers() -> dict[str, Tier]:
    """Standart qiymatlar + superadmin o'zgartirishlari (DB). Har safar qayta o'qiladi — o'zgarish darhol amal qiladi."""
    over = _overrides()
    out = {}
    for tid, base in _defaults().items():
        vals = {**base, **{k: v for k, v in over.get(tid, {}).items() if k in FIELDS and isinstance(v, int)}}
        out[tid] = Tier(tid, vals["name"], vals["rank"], vals["stars"], vals["daily_limit"], vals["files"],
                        vals["vision"], vals["caption"], vals.get("github", 0), vals.get("site", 0))
    return out


def paid_tiers() -> list[Tier]:
    return [t for t in tiers().values() if t.id != "free"]


PLANS_CALLBACK = "tariff:menu"
PLANS_DEEPLINK = "tariff"   # https://t.me/<bot>?start=tariff — guruhdan shaxsiy chatda tariflar sahifasini ochadi
PLANS_BUTTON_TEXT = "💳 Tariflar"


def plans_markup(in_group: bool = False) -> InlineKeyboardMarkup | None:
    """"💳 Tariflar" inline tugmasi (buyruqsiz kirish). Shaxsiy chatda — callback; guruhda — bot'ga deep-link (tugma
    bosilganda shaxsiy chat ochiladi, chunki to'lov faqat shaxsiy chatda). Bot username noma'lum bo'lsa guruhda tugma yo'q."""
    if not in_group:
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=PLANS_BUTTON_TEXT, callback_data=PLANS_CALLBACK)]])
    username = bot_identity.get_username()
    if not username:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text=PLANS_BUTTON_TEXT, url=f"https://t.me/{username}?start={PLANS_DEEPLINK}")]])


def _bucket() -> dict:
    return tgdb.get().setdefault("subscriptions", {})


def _is_staff(user_id: int) -> bool:
    import core.roles as roles
    return roles.is_superadmin(user_id) or roles.is_admin(user_id)


# ── superadmin: narx va limitlarni tahrirlash ────────────────────────────

def validate_value(tier_id: str, field: str, raw) -> tuple[int | None, str | None]:
    if tier_id not in tiers():
        return None, "Bunday tarif yo'q."
    if field not in FIELDS:
        return None, "Bunday maydon yo'q."
    lo, hi, paid_only = FIELDS[field]
    if paid_only and tier_id == "free":
        return None, "Bepul tarifda bu maydon yo'q (so'rov limiti har bir foydalanuvchi uchun alohida)."
    s = str(raw).strip()
    if not s.isdigit():
        return None, "Faqat butun musbat son yozing."
    value = int(s)
    if not lo <= value <= hi:
        return None, f"Qiymat {lo} dan {hi} gacha bo'lsin."
    return value, None


async def set_config(bot, tier_id: str, field: str, raw) -> tuple[bool, str]:
    value, err = validate_value(tier_id, field, raw)
    if value is None:
        return False, err or "Noto'g'ri qiymat."
    cfg = tgdb.get().setdefault("tariff_config", {}).setdefault(tier_id, {})
    cfg[field] = value
    await tgdb.save(bot, force=True)
    logger.info("tarif sozlamasi o'zgardi: %s.%s=%s", tier_id, field, value)
    return True, f"✅ {tiers()[tier_id].name}: {FIELD_LABELS[field]} = {value}"


async def reset_config(bot, tier_id: str) -> bool:
    removed = tgdb.get().get("tariff_config", {}).pop(tier_id, None) is not None
    if removed:
        await tgdb.save(bot, force=True)
    return removed


# ── holat ────────────────────────────────────────────────────────────────

def active_tier(user_id: int, now: float | None = None) -> Tier:
    """Hozir amalda bo'lgan tarif (muddati tugagan bo'lsa — free)."""
    now = time.time() if now is None else now
    rec = _bucket().get(str(user_id))
    all_tiers = tiers()
    if rec and rec.get("tier") in all_tiers and rec.get("until", 0) > now:
        return all_tiers[rec["tier"]]
    return all_tiers["free"]


def days_left(user_id: int, now: float | None = None) -> int:
    now = time.time() if now is None else now
    rec = _bucket().get(str(user_id))
    if not rec or active_tier(user_id, now).id == "free":
        return 0
    return max(0, math.ceil((rec["until"] - now) / 86400))


def until_ts(user_id: int) -> int:
    rec = _bucket().get(str(user_id))
    return int(rec["until"]) if rec else 0


def tier_limit(user_id: int) -> int | None:
    return active_tier(user_id).daily_limit


def can_caption(user_id: int) -> bool:
    """Story izohi (caption): Plus/Pro yoki admin. Story qo'yishning o'zi hamma uchun."""
    return _is_staff(user_id) or active_tier(user_id).caption


# ── kunlik kvotalar (fayl yaratish / rasm o'qish) ────────────────────────

def quota_kind(tool_name: str, is_file_tool: bool) -> str | None:
    if tool_name in VISION_TOOLS:
        return KIND_VISION
    if tool_name in FILES_OWN_TOOLS or (is_file_tool and not tool_name.startswith(READONLY_PREFIXES)):
        return KIND_FILES
    return None


def quota_limit(user_id: int, kind: str) -> int | None:
    """Kunlik kvota; None — cheksiz (admin)."""
    if _is_staff(user_id):
        return None
    return getattr(active_tier(user_id), kind)


def quota_used(user_id: int, kind: str) -> int:
    import core.roles as roles
    rec = tgdb.get()["users"].get(str(user_id))
    if not rec or rec.get("last_reset") != roles.today_str():
        return 0
    return int(rec.get(f"{kind}_today", 0))


def quota_left(user_id: int, kind: str) -> int | None:
    limit = quota_limit(user_id, kind)
    return None if limit is None else max(0, limit - quota_used(user_id, kind))


def quota_available(user_id: int, kind: str) -> bool:
    left = quota_left(user_id, kind)
    return left is None or left > 0


def quota_denied_text(user_id: int, kind: str) -> str:
    what = {KIND_FILES: "fayl yaratish", KIND_GITHUB: "GitHub amallari", KIND_SITE: "sayt o'qish/ko'chirish"}.get(kind, "rasm o'qish")
    limit = quota_limit(user_id, kind)
    return (f"Bugungi {what} limiti tugadi ({limit}/{limit}). Limit ertaga yangilanadi; ko'proq kerak bo'lsa Plus/Pro tarifini olish "
            f"mumkin — javobingiz tagiga «💳 Tariflar» tugmasi avtomatik qo'shiladi. Foydalanuvchiga shuni muloyim ayting "
            f"(buyruq yozishni aytmang).")


def counts_as_use(kind: str, result) -> bool:
    """Tool natijasi kvotadan sanalishi kerakmi (faqat muvaffaqiyatli bajarilganda)."""
    from core.output_files import output_files
    if kind == KIND_FILES:
        return bool(output_files(result))
    return isinstance(result, dict) and not result.get("error")


async def consume(bot, user_id: int, kind: str, n: int = 1) -> None:
    if quota_limit(user_id, kind) is None:
        return
    import core.roles as roles
    rec = roles._bucket(user_id)
    roles._reset_if_new_day(rec)
    key = f"{kind}_today"
    rec[key] = rec.get(key, 0) + n
    await tgdb.save(bot)  # debounced


# ── xarid / to'lov ───────────────────────────────────────────────────────

def can_purchase(user_id: int, tier_id: str, now: float | None = None) -> tuple[bool, str | None]:
    tier = tiers().get(tier_id)
    if tier is None or tier.id == "free" or tier.stars <= 0:
        return False, "Bunday tarif yo'q."
    cur = active_tier(user_id, now)
    if cur.rank > tier.rank:
        return False, f"Sizda {cur.name} tarifi faol — undan pastroq tarifni sotib olib bo'lmaydi."
    return True, None


def upgrade_warning(user_id: int, tier_id: str, now: float | None = None) -> str | None:
    """Yuqoriroq tarifga o'tishda qolgan kunlar yo'qolishi haqida oldindan ogohlantirish matni."""
    cur = active_tier(user_id, now)
    tier = tiers().get(tier_id)
    if tier and cur.id != "free" and cur.rank < tier.rank:
        return (f"Diqqat: sizda {cur.name} tarifi bor ({days_left(user_id, now)} kun qolgan). "
                f"{tier.name}ga o'tsangiz, {tier.name} 30 kun hozirdan boshlanadi, {cur.name}ning qolgan kunlari kuymaydi.")
    return None


def make_payload(user_id: int, tier_id: str) -> str:
    return f"{PAYLOAD_PREFIX}:{tier_id}:{user_id}"


def parse_payload(payload: str) -> tuple[str, int] | None:
    parts = (payload or "").split(":")
    if len(parts) != 3 or parts[0] != PAYLOAD_PREFIX or not parts[2].lstrip("-").isdigit():
        return None
    return parts[1], int(parts[2])


def check_payment(payload: str, payer_id: int, currency: str, amount: int, strict_price: bool,
                  now: float | None = None) -> tuple[str | None, str | None]:
    """(tier_id, None) yoki (None, xato). strict_price=True (pre_checkout) — narx hozirgisiga teng bo'lishi shart.
    successful_payment'da (Telegram allaqachon yechgan) narx qat'iy tekshirilmaydi — foydalanuvchi mablag'i yo'qolmasin."""
    parsed = parse_payload(payload)
    if parsed is None:
        return None, "To'lov ma'lumoti noto'g'ri."
    tier_id, owner = parsed
    if owner != payer_id:
        return None, "Bu hisob-faktura boshqa foydalanuvchi uchun."
    if currency != "XTR":
        return None, "Faqat Telegram Stars qabul qilinadi."
    tier = tiers().get(tier_id)
    if tier is None or tier.id == "free":
        return None, "Bunday tarif yo'q."
    if strict_price:
        ok, why = can_purchase(payer_id, tier_id, now)
        if not ok:
            return None, why
        if amount != tier.stars:
            return None, "Narx o'zgargan — «💳 Tariflar» tugmasi orqali qaytadan oling."
    return tier_id, None


def _new_rec() -> dict:
    return {"tier": "free", "until": 0, "charges": [], "stars_total": 0}


async def apply_payment(bot, user_id: int, tier_id: str, stars: int, charge_id: str, now: float | None = None) -> str:
    """To'langan tarifni qo'shadi. "ok" | "duplicate". Bir xil charge_id ikkinchi marta hisoblanmaydi."""
    now = time.time() if now is None else now
    rec = _bucket().setdefault(str(user_id), _new_rec())
    if any(c.get("id") == charge_id for c in rec["charges"]):
        return "duplicate"
    cur = active_tier(user_id, now)
    new = tiers()[tier_id]
    span = DURATION_DAYS * 86400
    if cur.id == new.id:
        rec["until"] = int(max(rec.get("until", 0), now) + span)  # uzaytirish
    else:
        rec["tier"], rec["until"] = new.id, int(now + span)       # yangi/yuqoriroq tarif — hozirdan 30 kun
    rec["charges"] = (rec["charges"] + [{"id": charge_id, "tier": tier_id, "stars": stars, "t": int(now)}])[-CHARGES_KEPT:]
    rec["stars_total"] = rec.get("stars_total", 0) + stars
    await tgdb.save(bot, force=True)
    return "ok"


async def grant(bot, user_id: int, tier_id: str, days: int = DURATION_DAYS, now: float | None = None) -> None:
    """Superadmin sovg'a/qo'lda berish: to'lovsiz. Mavjud tarifni almashtiradi (days kundan hozirdan; xuddi shu tarif bo'lsa uzaytiradi)."""
    now = time.time() if now is None else now
    rec = _bucket().setdefault(str(user_id), _new_rec())
    if active_tier(user_id, now).id == tier_id:
        rec["until"] = int(max(rec.get("until", 0), now) + days * 86400)
    else:
        rec["tier"], rec["until"] = tier_id, int(now + days * 86400)
    await tgdb.save(bot, force=True)


async def revoke(bot, user_id: int) -> bool:
    rec = _bucket().get(str(user_id))
    if not rec or active_tier(user_id).id == "free":
        return False
    rec["until"] = 0
    await tgdb.save(bot, force=True)
    return True


def last_refundable_charge(user_id: int) -> dict | None:
    rec = _bucket().get(str(user_id))
    for c in reversed((rec or {}).get("charges", [])):
        if not c.get("refunded"):
            return c
    return None


async def mark_refunded(bot, user_id: int, charge_id: str) -> bool:
    """Qaytarilgan to'lovni belgilaydi, Stars hisobidan ayiradi va tarifni bekor qiladi."""
    rec = _bucket().get(str(user_id))
    for c in (rec or {}).get("charges", []):
        if c.get("id") == charge_id and not c.get("refunded"):
            c["refunded"] = True
            rec["stars_total"] = max(0, rec.get("stars_total", 0) - c.get("stars", 0))
            rec["until"] = 0
            await tgdb.save(bot, force=True)
            return True
    return False


def stats(now: float | None = None) -> dict:
    now = time.time() if now is None else now
    active = {t.id: 0 for t in paid_tiers()}
    total_stars = 0
    for uid, rec in _bucket().items():
        total_stars += rec.get("stars_total", 0)
        t = active_tier(int(uid), now)
        if t.id in active:
            active[t.id] += 1
    return {"active": active, "stars_total": total_stars, "subscribers": len(_bucket())}


# ── muddat tugashi haqida eslatma ────────────────────────────────────────

def due_reminders(now: float | None = None) -> list[tuple[int, str, int]]:
    """[(user_id, "d3"|"d1"|"end", until)] — hali yuborilmagan eslatmalar. Har bir (until, belgi) bir marta."""
    now = time.time() if now is None else now
    due = []
    for uid, rec in _bucket().items():
        until = int(rec.get("until", 0))
        if until <= 0 or rec.get("tier") not in tiers() or rec.get("tier") == "free":
            continue
        sent = set(rec.get("rem", {}).get("k", [])) if rec.get("rem", {}).get("u") == until else set()
        left = until - now
        if left <= 0:
            if now - until <= EXPIRED_REMIND_WINDOW and "end" not in sent:
                due.append((int(uid), "end", until))
            continue
        if left <= 1 * 86400:  # eng yaqin chegara (1 kun qolgan bo'lsa d3 emas, d1)
            kind = "d1"
        elif left <= 3 * 86400:
            kind = "d3"
        else:
            continue
        if kind not in sent:
            due.append((int(uid), kind, until))
    return due


def reminder_text(user_id: int, kind: str) -> str:
    rec = _bucket().get(str(user_id), {})
    name = tiers().get(rec.get("tier"), tiers()["free"]).name
    if kind == "end":
        return (f"⌛ <b>{name}</b> tarifingiz muddati tugadi, Bepul tarifga qaytdingiz.\n"
                f"Davom ettirish uchun pastdagi tugmani bosing.")
    left = "1 kundan kam" if kind == "d1" else "3 kundan kam"
    return (f"⏰ <b>{name}</b> tarifingiz tugashiga {left} vaqt qoldi.\n"
            f"Uzaytirish (muddat ustiga +{DURATION_DAYS} kun qo'shiladi) uchun pastdagi tugmani bosing.")


async def send_reminders(bot, now: float | None = None) -> int:
    """Fon vazifasi (core/scheduler.py) chaqiradi. Yuborilganlar sonini qaytaradi. Bloklagan foydalanuvchiga qayta-qayta
    urinmaslik uchun xato bo'lsa ham belgilanadi."""
    now = time.time() if now is None else now
    sent = processed = 0
    for uid, kind, until in due_reminders(now):
        processed += 1
        rec = _bucket()[str(uid)]
        try:
            await bot.send_message(uid, reminder_text(uid, kind), reply_markup=plans_markup())
            sent += 1
        except Exception as e:  # noqa: BLE001
            logger.info("Tarif eslatmasi yuborilmadi (uid=%s): %s", uid, type(e).__name__)
        rem = rec.get("rem") if rec.get("rem", {}).get("u") == until else {"u": until, "k": []}
        rem["k"] = list(set(rem["k"]) | ({"d3", "d1"} if kind == "d1" else {kind}))  # d1 yuborilsa d3 ham kerak emas
        rec["rem"] = rem
    if processed:
        await tgdb.save(bot)
    return sent
