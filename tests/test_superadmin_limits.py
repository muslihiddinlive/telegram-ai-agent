"""Superadmin: bepul foydalanuvchilar limitini TO'LIQ tahrirlash (so'rov limiti, fayl/rasm kvotasi, aniq override)."""
import asyncio
from types import SimpleNamespace

import pytest

import admin.panel as panel
import core.pending_input as pending_input
import core.roles as roles
import core.tariffs as tariffs
import core.tgdb as tgdb
import handlers.pending_text as pt

SUPER, ADMIN, U, U2 = 1, 2, 5, 6


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def env(monkeypatch):
    data = {"admins": {str(ADMIN): {"name": "adm"}}, "users": {}, "subscriptions": {}}
    monkeypatch.setattr(tgdb, "_cache", data)
    pending_input._pending.clear()
    monkeypatch.setattr(roles.config, "SUPERADMIN_ID", SUPER)

    async def noop_save(bot, force=False):
        return None

    monkeypatch.setattr(tgdb, "save", noop_save)
    return data


def user(uid, **kw):
    rec = {"role": "approved", "daily_limit": 20, "requests_today": 0, "last_reset": roles.today_str(),
           "name": "N", "username": None}
    rec.update(kw)
    return tgdb.get()["users"].setdefault(str(uid), rec)


def msg(uid, text):
    out = []

    async def answer(t, **kw):
        out.append(t)

    return SimpleNamespace(from_user=SimpleNamespace(id=uid), chat=SimpleNamespace(type="private"), text=text,
                           answer=answer, bot=None, out=out)


def call(uid, data):
    alerts, edits, answers = [], [], []

    async def ans(text=None, show_alert=False):
        alerts.append((text, show_alert))

    async def edit_text(text, reply_markup=None, **kw):
        edits.append((text, reply_markup))

    async def m_answer(text, **kw):
        answers.append((text, kw))

    return SimpleNamespace(from_user=SimpleNamespace(id=uid), data=data, answer=ans,
                           message=SimpleNamespace(edit_text=edit_text, answer=m_answer),
                           alerts=alerts, edits=edits, answers=answers)


# ── bepul tarifning so'rov limiti endi tahrirlanadi ──────────────────────────
def test_free_daily_limit_is_editable_and_sets_default_for_new_users():
    assert run(tariffs.set_config(None, "free", "daily_limit", "7"))[0]
    assert roles.default_daily_limit() == 7
    assert roles.can_use_in_group(U2) and tgdb.get()["users"][str(U2)]["daily_limit"] == 7   # yangi user — 7
    assert roles.effective_daily_limit(U2) == 7


def test_free_default_does_not_raise_or_lower_existing_users_and_is_no_floor():
    user(U, daily_limit=3)                      # admin avval 3 qilgan
    run(tariffs.set_config(None, "free", "daily_limit", "50"))
    assert roles.effective_daily_limit(U) == 3  # bepul qiymat "pol" emas — mavjudlar o'zgarmaydi
    assert tariffs.tier_limit(U) is None


def test_apply_free_limit_to_all_skips_blocked_and_overridden():
    user(U); user(U2, limit_override=9); user(7, role="blocked")
    run(tariffs.set_config(None, "free", "daily_limit", "11"))
    assert sorted(roles.free_limit_targets()) == [str(U)]
    assert run(roles.apply_free_limit_to_all(None, 11)) == 1
    us = tgdb.get()["users"]
    assert us[str(U)]["daily_limit"] == 11 and us[str(U2)]["daily_limit"] == 20 and us["7"]["daily_limit"] == 20


# ── aniq (exact) shaxsiy limit: tarifdan past ham bo'ladi ───────────────────
def test_superadmin_exact_limit_can_lower_below_paid_tier_but_admin_edit_cannot():
    user(U)
    run(tariffs.grant(None, U, "plus"))
    plus = tariffs.tiers()["plus"].daily_limit
    run(roles.set_user_limit(None, U, 10))                    # oddiy (admin) — eski qoida: tarif pol
    assert roles.effective_daily_limit(U) == plus
    run(roles.set_user_limit(None, U, 10, exact=True))        # superadmin — aynan 10
    assert roles.effective_daily_limit(U) == 10 and roles.remaining_requests(U) == 10
    run(roles.set_user_limit(None, U, 500))                   # oddiy tahrir override'ni olib tashlaydi
    assert "limit_override" not in tgdb.get()["users"][str(U)] and roles.effective_daily_limit(U) == 500


# ── foydalanuvchi bo'yicha fayl/rasm kvotasi ────────────────────────────────
def test_per_user_quota_override_beats_tier_and_resets():
    user(U)
    assert tariffs.quota_limit(U, "files") == 4
    run(tariffs.set_user_quota(None, U, "files", 1))
    assert tariffs.quota_limit(U, "files") == 1 and tariffs.quota_limit(U, "vision") == 2
    run(tariffs.grant(None, U, "pro"))
    assert tariffs.quota_limit(U, "files") == 1               # tarifdan ustun
    run(tariffs.set_user_quota(None, U, "vision", 0))
    assert not tariffs.quota_available(U, "vision")
    run(tariffs.set_user_quota(None, U, "files", None))
    assert tariffs.quota_limit(U, "files") == 100
    with pytest.raises(ValueError):
        run(tariffs.set_user_quota(None, U, "evil", 5))
    assert tariffs.quota_limit(ADMIN, "files") is None        # staff — baribir cheksiz


def test_reset_user_limits_clears_everything():
    user(U)
    run(roles.set_user_limit(None, U, 1, exact=True))
    run(tariffs.set_user_quota(None, U, "files", 0))
    run(roles.reset_user_limits(None, U))
    rec = tgdb.get()["users"][str(U)]
    assert not {"limit_override", "files_override", "vision_override"} & set(rec)
    assert roles.effective_daily_limit(U) == roles.default_daily_limit()


# ── kiritish oqimi: validatsiya, bekor qilish, ruxsat ───────────────────────
@pytest.mark.parametrize("bad", ["abc", "-5", "1.5", "100001", "²", "٣", ""])
def test_pending_limit_rejects_bad_values_without_crashing(bad):
    user(U)
    pending_input.set(SUPER, "set_user_limit", {"target_uid": str(U)})
    m = msg(SUPER, bad)
    run(pt.handle_pending(m))
    assert "0 dan 100000" in m.out[0] and pending_input.get(SUPER) is not None
    assert tgdb.get()["users"][str(U)]["daily_limit"] == 20


def test_pending_limit_cancel_and_superadmin_exact_and_admin_regular():
    user(U)
    pending_input.set(SUPER, "set_user_limit", {"target_uid": str(U)})
    m = msg(SUPER, "/panel")
    run(pt.handle_pending(m))
    assert "Bekor" in m.out[0] and pending_input.get(SUPER) is None

    pending_input.set(SUPER, "set_user_limit", {"target_uid": str(U)})
    m = msg(SUPER, "0"); run(pt.handle_pending(m))             # 0 — ruxsat (so'rovlarni to'xtatish)
    assert tgdb.get()["users"][str(U)]["limit_override"] == 0 and "aniq" in m.out[0]

    pending_input.set(ADMIN, "set_user_limit", {"target_uid": str(U)})
    m = msg(ADMIN, "15"); run(pt.handle_pending(m))
    rec = tgdb.get()["users"][str(U)]
    assert rec["daily_limit"] == 15 and "limit_override" not in rec


def test_pending_quota_is_superadmin_only_and_rechecks_role():
    user(U)
    pending_input.set(ADMIN, "set_user_quota", {"target_uid": str(U), "kind": "files"})
    m = msg(ADMIN, "99"); run(pt.handle_pending(m))
    assert "Ruxsat yo'q" in m.out[0] and tariffs.quota_limit(U, "files") == 4

    pending_input.set(SUPER, "set_user_quota", {"target_uid": str(U), "kind": "vision"})
    m = msg(SUPER, "12"); run(pt.handle_pending(m))
    assert tariffs.quota_limit(U, "vision") == 12 and "12/kun" in m.out[0]

    pending_input.set(U2, "set_user_limit", {"target_uid": str(U)})     # oddiy foydalanuvchi (admin emas)
    m = msg(U2, "999"); run(pt.handle_pending(m))
    assert "Ruxsat yo'q" in m.out[0] and tgdb.get()["users"][str(U)]["daily_limit"] == 20


# ── panel ──────────────────────────────────────────────────────────────────
def test_panel_quota_and_reset_callbacks_are_superadmin_only_and_validate_input():
    user(U)
    for data, fn in ((f"panel:setquota:files:{U}", panel.set_quota_start), (f"panel:limreset:{U}", panel.limits_reset),
                     ("panel:freeapply", panel.free_apply_ask)):
        c = call(ADMIN, data)
        run(fn(c, None) if fn is panel.limits_reset else fn(c))
        assert c.alerts and c.alerts[0][1] is True
    assert pending_input.get(ADMIN) is None
    c = call(SUPER, "panel:setquota:evil:5"); run(panel.set_quota_start(c))
    assert c.alerts[0][0] == "Noto'g'ri so'rov" and pending_input.get(SUPER) is None
    c = call(SUPER, "panel:setquota:files:5x"); run(panel.set_quota_start(c))
    assert pending_input.get(SUPER) is None
    c = call(SUPER, f"panel:setquota:vision:{U}"); run(panel.set_quota_start(c))
    assert pending_input.get(SUPER) == {"action": "set_user_quota", "data": {"target_uid": str(U), "kind": "vision"}}


def test_user_detail_shows_effective_limit_and_superadmin_buttons_only_for_superadmin():
    user(U, limit_override=4)
    c = call(SUPER, f"panel:user_detail:{U}"); run(panel.user_detail(c))
    text, kb = c.edits[0]
    data = [b.callback_data for r in kb.inline_keyboard for b in r]
    assert "Kunlik limit: 4 (aniq" in text
    assert {f"panel:setquota:files:{U}", f"panel:setquota:vision:{U}", f"panel:limreset:{U}"} <= set(data)
    c = call(ADMIN, f"panel:user_detail:{U}"); run(panel.user_detail(c))
    data = [b.callback_data for r in c.edits[0][1].inline_keyboard for b in r]
    assert not any(d.startswith(("panel:setquota", "panel:limreset")) for d in data)


def test_free_tier_view_has_request_limit_and_apply_button():
    text, kb = panel.tariff_config_view("free")
    data = [b.callback_data for r in kb.inline_keyboard for b in r]
    assert "panel:tset:free:daily_limit" in data and "panel:freeapply" in data
    assert "panel:tset:free:stars" not in data
    _, kb = panel.tariff_config_view("plus")
    assert "panel:freeapply" not in [b.callback_data for r in kb.inline_keyboard for b in r]
