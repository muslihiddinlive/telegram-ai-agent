"""
Tariflar (obuna) — Telegram Stars (XTR) bilan to'lanadi, har biri 30 kun, tugagach BEPUL tarifga qaytadi.

Tariflar:                 kunlik limit   rasm o'qish   fayl/hujjat yaratish
  free  (Bepul)           roles'dagi      yo'q          yo'q            (foydalanuvchining o'z limiti, admin o'zgartira oladi)
  plus  (Plus)            100             ha            yo'q
  pro   (Pro)             300             ha            ha
Narx/limitlar config.py'dagi TARIFF_* env'lari bilan o'zgartiriladi.

Qoidalar:
  - Limit = max(foydalanuvchining o'z limiti, tarif limiti): admin qo'lda katta limit bergan bo'lsa u kamaymaydi.
  - Superadmin/bot adminlarida hamma imkoniyat doim yoqiq (tarif kerak emas).
  - Guruhda imkoniyatlar: yozgan odamniki YOKI hisobi to'layotgan odamniki (chatmode egasi); VIP chatmode — hammasi ochiq.
  - Xarid: shu tarifni uzaytirish (+30 kun), yuqoriroq tarifga o'tish (30 kun hozirdan; pastroq tarifning qolgan kunlari
    kuymaydi, lekin yo'qoladi — foydalanuvchiga oldindan ko'rsatiladi), PASTROQ tarifni faol yuqori tarif ustiga sotib olib bo'lmaydi.
  - To'lov idempotent: bir xil telegram_payment_charge_id ikki marta hisoblanmaydi.
  - Hammasi db["subscriptions"][uid] da: {"tier","until","charges":[{id,tier,stars,t,refunded?}], "stars_total"}.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass

import config
import core.tgdb as tgdb

DURATION_DAYS = 30
CHARGES_KEPT = 30
FEATURE_VISION = "vision"  # rasm o'qish (look_at_image, rasm yuklash)
FEATURE_FILES = "files"    # fayl/hujjat yaratish va o'qish (docx/xlsx/pptx/pdf, taqdimot, diagramma, hujjat yuklash)
ALL_FEATURES = frozenset({FEATURE_VISION, FEATURE_FILES})
FILES_OWN_TOOLS = frozenset({"create_presentation", "create_diagram"})  # o'zimizning fayl yaratuvchi tool'lar
VISION_TOOLS = frozenset({"look_at_image"})
PAYLOAD_PREFIX = "tariff"


@dataclass(frozen=True)
class Tier:
    id: str
    name: str
    rank: int
    stars: int
    daily_limit: int | None  # None — foydalanuvchining o'z limiti
    features: frozenset


def _tiers() -> dict[str, Tier]:
    return {
        "free": Tier("free", "Bepul", 0, 0, None, frozenset()),
        "plus": Tier("plus", "Plus ⭐", 1, config.TARIFF_PLUS_STARS, config.TARIFF_PLUS_LIMIT, frozenset({FEATURE_VISION})),
        "pro": Tier("pro", "Pro 💎", 2, config.TARIFF_PRO_STARS, config.TARIFF_PRO_LIMIT, ALL_FEATURES),
    }


def tiers() -> dict[str, Tier]:
    return _tiers()  # config har safar o'qiladi — env o'zgarsa/testda monkeypatch ishlasin


def paid_tiers() -> list[Tier]:
    return [t for t in tiers().values() if t.id != "free"]


def _bucket() -> dict:
    return tgdb.get().setdefault("subscriptions", {})


def _is_staff(user_id: int) -> bool:
    import core.roles as roles
    return roles.is_superadmin(user_id) or roles.is_admin(user_id)


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
    return max(0, math.ceil((rec["until"] - now) / 86400))  # qolgan to'liq/qisman kunlar (yuqoriga)


def until_ts(user_id: int) -> int:
    rec = _bucket().get(str(user_id))
    return int(rec["until"]) if rec else 0


def tier_limit(user_id: int) -> int | None:
    return active_tier(user_id).daily_limit


def features_of(user_id: int) -> frozenset:
    if _is_staff(user_id):
        return ALL_FEATURES
    return active_tier(user_id).features


def features_for_request(writer_id: int, payer_id: int, vip: bool = False) -> frozenset:
    """Shu so'rovda ruxsat etilgan imkoniyatlar (yozuvchi YOKI to'lovchi tarifi; VIP chatmode — hammasi)."""
    if vip:
        return ALL_FEATURES
    return features_of(writer_id) | features_of(payer_id)


def required_feature(tool_name: str, is_file_tool: bool) -> str | None:
    if tool_name in VISION_TOOLS:
        return FEATURE_VISION
    if is_file_tool or tool_name in FILES_OWN_TOOLS:
        return FEATURE_FILES
    return None


def filter_tools(tools: list[dict], features: frozenset, is_file_tool_fn) -> list[dict]:
    """AI'ga FAQAT ruxsat etilgan tool'larni beradi (ruxsatsizlari ko'rinmaydi — token ham tejaladi)."""
    out = []
    for t in tools:
        name = t["function"]["name"]
        need = required_feature(name, is_file_tool_fn(name))
        if need is None or need in features:
            out.append(t)
    return out


# ── xarid / to'lov ───────────────────────────────────────────────────────

def can_purchase(user_id: int, tier_id: str, now: float | None = None) -> tuple[bool, str | None]:
    all_tiers = tiers()
    tier = all_tiers.get(tier_id)
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
            return None, "Narx o'zgargan — /tarif orqali qaytadan oling."
    return tier_id, None


async def apply_payment(bot, user_id: int, tier_id: str, stars: int, charge_id: str, now: float | None = None) -> str:
    """To'langan tarifni qo'shadi. "ok" | "duplicate". Bir xil charge_id ikkinchi marta hisoblanmaydi."""
    now = time.time() if now is None else now
    rec = _bucket().setdefault(str(user_id), {"tier": "free", "until": 0, "charges": [], "stars_total": 0})
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
    rec = _bucket().setdefault(str(user_id), {"tier": "free", "until": 0, "charges": [], "stars_total": 0})
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
