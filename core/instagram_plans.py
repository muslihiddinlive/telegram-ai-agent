"""
core/instagram_plans.py
-----------------------
Instagram imkoniyatlari tarif bo'yicha (bot tariflari: core/tariffs.py — Free / Plus / Pro).

  Bepul : birinchi ulanishdan 3 KUN, umrida 1 marta. Joylash, statistika, izohlarni boshqarish.
          Rejalashtirish / avtomatlashtirish / DM'da AI — YO'Q. Sinov tugagach — hech narsa (tarif kerak).
  Plus  : joylash/statistika/izohlar cheksiz (Instagram'ning o'z limiti ichida); rejalashtirish ≤10 ta,
          avtomatlashtirish ≤3 qoida (+≤10 taqiqlangan so'z), DM'da AI kuniga ≤30 javob.
  Pro   : hammasi cheksiz (Instagram limiti ichida).
  Egasi : bot egasi/adminlar va env'dagi akkaunt — Pro bilan bir xil.

Plus chegaralarini env bilan o'zgartirish mumkin: IG_PLUS_SCHEDULED, IG_PLUS_TRIGGERS, IG_PLUS_BANNED, IG_PLUS_DM_DAILY.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Optional

FEATURES = ("publish", "insights", "comments", "schedule", "automation", "dm")
FEATURE_LABELS = {
    "publish": "joylash", "insights": "statistika", "comments": "izohlarni boshqarish",
    "schedule": "rejalashtirish", "automation": "avtomatlashtirish", "dm": "DM'da AI yordamchi",
}


@dataclass(frozen=True)
class Plan:
    code: str                       # none | trial | plus | pro | owner
    label: str
    publish: bool
    insights: bool
    comments: bool
    max_scheduled: Optional[int]    # 0 — yo'q; None — cheksiz
    max_triggers: Optional[int]
    max_banned: Optional[int]
    dm: bool
    dm_daily: Optional[int]         # akkaunt bo'yicha kuniga AI javoblari; None — cheksiz

    def allows(self, feature: str) -> bool:
        if feature == "schedule":
            return self.max_scheduled != 0
        if feature == "automation":
            return self.max_triggers != 0
        return bool(getattr(self, feature, False))


def _env_int(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, default)))
    except ValueError:
        return default


NONE = Plan("none", "Sinov tugagan", False, False, False, 0, 0, 0, False, 0)
TRIAL = Plan("trial", "Bepul sinov", True, True, True, 0, 0, 0, False, 0)
PRO = Plan("pro", "Pro", True, True, True, None, None, None, True, None)
OWNER = Plan("owner", "Egasi", True, True, True, None, None, None, True, None)


def plus() -> Plan:
    return Plan("plus", "Plus", True, True, True, _env_int("IG_PLUS_SCHEDULED", 10), _env_int("IG_PLUS_TRIGGERS", 3),
                _env_int("IG_PLUS_BANNED", 10), True, _env_int("IG_PLUS_DM_DAILY", 30))


def plan_for(user_id: int, account=None, now: Optional[float] = None) -> Plan:
    """Foydalanuvchining hozirgi Instagram rejasi (tarif + sinov)."""
    if account is not None and getattr(account, "owner", False):
        return OWNER
    import core.roles as roles
    if roles.is_superadmin(user_id) or roles.is_admin(user_id):
        return OWNER
    import core.tariffs as tariffs
    tier = tariffs.active_tier(user_id, now)
    if tier.id == "pro" or tier.rank >= 2:
        return PRO
    if tier.rank >= 1:
        return plus()
    import core.instagram_accounts as accounts
    return TRIAL if accounts.trial_active(user_id, now) else NONE


def upgrade_hint() -> str:
    return "Plus yoki Pro tarifini oling (💳 Tariflar tugmasi)."


def deny_text(plan: Plan, feature: str) -> str:
    label = FEATURE_LABELS.get(feature, feature)
    if plan.code == "none":
        return ("Instagram bepul sinov muddati (3 kun) tugagan. Davom etish uchun " + upgrade_hint())
    return f"«{label}» bepul sinovda yo'q. " + upgrade_hint()


def limit_text(plan: Plan, what: str, limit: int) -> str:
    return f"{plan.label} tarifda {what} {limit} tagacha. Cheksiz uchun Pro tarifini oling (💳 Tariflar tugmasi)."


def trial_text(seconds_left: int) -> str:
    d, h = seconds_left // 86400, (seconds_left % 86400) // 3600
    return f"{d} kun {h} soat" if d else f"{h} soat"
