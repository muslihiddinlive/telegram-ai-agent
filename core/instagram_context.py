"""
core/instagram_context.py
-------------------------
"Joriy Instagram akkaunti" — har bir so'rov QAYSI akkaunt nomidan ketishini belgilaydi.

contextvars asyncio task'lariga xos (bir-biriga aralashmaydi), shuning uchun bir vaqtda ishlayotgan
turli foydalanuvchilarning chaqiruvlari bir-birining tokenini ko'rmaydi. Akkauntni FAQAT server belgilaydi
(common.require / webhook / scheduler) — AI tool argumentlaridan hech qachon olinmaydi.

Ko'p-akkauntli rejim (IG_APP_ID + IG_APP_SECRET berilgan — paneldan yoki env'dan) YOQILGANDA kontekstsiz chaqiruv xato beradi
(env'dagi egasi akkauntiga jimgina tushib ketmaydi). O'chiq rejimda (eski, bitta akkaunt) env ishlatiladi.
"""
from __future__ import annotations

import contextvars
import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator, Optional


@dataclass(frozen=True)
class Account:
    ig_id: str
    token: str = field(default="", repr=False)   # logga/repr'ga tushmasin
    host: str = "graph.instagram.com"
    tg_user_id: int = 0                           # akkaunt egasi (Telegram); 0 — noma'lum/env
    username: str = ""
    owner: bool = False                           # env'dagi (IG_USER_ID/IG_ACCESS_TOKEN) egasi akkaunti


_account: contextvars.ContextVar[Optional[Account]] = contextvars.ContextVar("ig_account", default=None)
_plan: contextvars.ContextVar = contextvars.ContextVar("ig_plan", default=None)


def multi_enabled() -> bool:
    """Foydalanuvchilar o'z akkauntini ulashi yoqilganmi (Meta Instagram ilovasi kalitlari: paneldan yoki env'dan)."""
    import core.instagram_settings as settings
    return settings.configured()


def current() -> Optional[Account]:
    return _account.get()


def current_plan():
    return _plan.get()


def account_key() -> str:
    """Joriy akkaunt kaliti (har akkaunt uchun alohida hisoblagich/qulf/kesh)."""
    a = _account.get()
    return a.ig_id if a else "-"


def set_current(account: Optional[Account], plan=None) -> None:
    _account.set(account)
    _plan.set(plan)


@contextmanager
def use(account: Account, plan=None) -> Iterator[Account]:
    t1, t2 = _account.set(account), _plan.set(plan)
    try:
        yield account
    finally:
        _account.reset(t1)
        _plan.reset(t2)
