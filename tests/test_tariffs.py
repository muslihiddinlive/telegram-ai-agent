import asyncio
import time
from types import SimpleNamespace

import pytest

import admin.panel as panel
import core.pending_input as pending_input
import core.ai_tools as ai_tools
import core.roles as roles
import core.tariffs as tariffs
import core.tgdb as tgdb
import handlers.tariff as th

SUPER, ADMIN, U = 1, 2, 5
DAY = 86400
NOW = 1_800_000_000.0


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def env(monkeypatch):
    data = {"admins": {str(ADMIN): {"name": "adm"}}, "users": {}, "subscriptions": {}}
    monkeypatch.setattr(tgdb, "_cache", data)
    pending_input._pending.clear()
    monkeypatch.setattr(roles.config, "SUPERADMIN_ID", SUPER)
    monkeypatch.setattr(th.config, "SUPERADMIN_ID", SUPER)

    async def noop_save(bot, force=False):
        return None

    monkeypatch.setattr(tgdb, "save", noop_save)
    return data


def buy(uid, tier, charge, stars=None, now=NOW):
    stars = tariffs.tiers()[tier].stars if stars is None else stars
    return run(tariffs.apply_payment(None, uid, tier, stars, charge, now=now))


# ── tarif holati va limit ────────────────────────────────────────────────

def test_free_by_default_and_expiry():
    assert tariffs.active_tier(U, NOW).id == "free" and tariffs.days_left(U, NOW) == 0
    buy(U, "pro", "c1")
    assert tariffs.active_tier(U, NOW + 29 * DAY).id == "pro"
    assert tariffs.active_tier(U, NOW + 31 * DAY).id == "free"      # 30 kundan keyin avtomatik Bepul
    assert tariffs.days_left(U, NOW + 29 * DAY) == 1 and tariffs.days_left(U, NOW + 31 * DAY) == 0


def test_daily_limit_follows_tier_and_never_reduces_manual_limit(monkeypatch):
    assert roles.effective_daily_limit(U) == roles.DEFAULT_DAILY_LIMIT
    run(tariffs.grant(None, U, "plus"))
    assert roles.effective_daily_limit(U) == tariffs.tiers()["plus"].daily_limit
    run(tariffs.grant(None, U, "pro"))
    assert roles.effective_daily_limit(U) == tariffs.tiers()["pro"].daily_limit
    tgdb.get()["users"][str(U)]["daily_limit"] = 1000               # admin qo'lda katta limit bergan
    assert roles.effective_daily_limit(U) == 1000


def test_quota_check_uses_tier_limit_and_reverts_after_expiry():
    run(tariffs.grant(None, U, "plus"))
    rec = tgdb.get()["users"].setdefault(str(U), {"role": "approved", "daily_limit": 20, "requests_today": 50,
                                                  "last_reset": roles.today_str(), "name": None, "username": None})
    rec["requests_today"] = 50                                     # Bepul limitdan (20) oshgan, Plus (100) ichida
    assert roles.can_make_request(U) and roles.can_use_in_group(U) and roles.remaining_requests(U) == 50
    tgdb.get()["subscriptions"][str(U)]["until"] = 0               # tugadi
    assert not roles.can_make_request(U) and not roles.can_use_in_group(U)


# ── tarif qiymatlari va kvotalar ─────────────────────────────────────────

def test_default_tier_values_match_the_spec():
    t = tariffs.tiers()
    assert (t["free"].files, t["free"].vision, t["free"].caption) == (4, 2, False)
    assert (t["plus"].files, t["plus"].vision, t["plus"].caption, t["plus"].daily_limit) == (20, 10, True, 100)
    assert (t["pro"].files, t["pro"].vision, t["pro"].caption, t["pro"].daily_limit) == (100, 70, True, 300)


@pytest.mark.parametrize("name,is_file,expected", [
    ("look_at_image", False, "vision"), ("create_presentation", False, "files"), ("create_diagram", False, "files"),
    ("create_docx", True, "files"), ("create_code_file", True, "files"), ("replace_docx_text", True, "files"),
    ("read_docx_text", True, None), ("get_file_info", True, None), ("list_directory_files", True, None),
    ("search_in_files", True, None), ("scrape_page_text", True, None), ("fetch_url_text", True, None),
    ("remember_note", False, None), ("search_web", False, None), ("react_to_message", False, None),
])
def test_quota_kind_classification(name, is_file, expected):
    assert tariffs.quota_kind(name, is_file) == expected


def test_real_catalog_every_tool_is_classified_sanely():
    from tools.file_tools import FILE_TOOLS, is_file_tool
    kinds = {t["function"]["name"]: tariffs.quota_kind(t["function"]["name"], is_file_tool(t["function"]["name"]))
             for t in ai_tools.TOOLS}
    assert kinds["look_at_image"] == "vision" and kinds["create_presentation"] == "files" and kinds["remember_note"] is None
    creators = [n for n, k in kinds.items() if k == "files"]
    assert len(creators) > 15 and all(not n.startswith(tariffs.READONLY_PREFIXES) for n in creators)
    assert len(FILE_TOOLS) > 30


def fresh_user(uid=U):
    return tgdb.get()["users"].setdefault(str(uid), {"role": "approved", "daily_limit": 20, "requests_today": 0,
                                                     "last_reset": roles.today_str(), "name": None, "username": None})


def test_quota_limits_follow_tier_expiry_and_staff():
    assert tariffs.quota_limit(U, "files") == 4 and tariffs.quota_limit(U, "vision") == 2
    run(tariffs.grant(None, U, "plus"))
    assert (tariffs.quota_limit(U, "files"), tariffs.quota_limit(U, "vision")) == (20, 10)
    run(tariffs.grant(None, U, "pro"))
    assert (tariffs.quota_limit(U, "files"), tariffs.quota_limit(U, "vision")) == (100, 70)
    tgdb.get()["subscriptions"][str(U)]["until"] = 0                    # tugadi -> Bepul kvotasi
    assert tariffs.quota_limit(U, "files") == 4
    assert tariffs.quota_limit(SUPER, "files") is None and tariffs.quota_limit(ADMIN, "vision") is None   # admin cheksiz


def test_consume_counts_and_resets_next_day():
    fresh_user()
    for _ in range(3):
        run(tariffs.consume(None, U, "files"))
    run(tariffs.consume(None, U, "vision"))
    assert (tariffs.quota_used(U, "files"), tariffs.quota_left(U, "files"), tariffs.quota_used(U, "vision")) == (3, 1, 1)
    tgdb.get()["users"][str(U)]["last_reset"] = "2000-01-01"            # kecha edi
    assert tariffs.quota_used(U, "files") == 0 and tariffs.quota_left(U, "files") == 4
    run(tariffs.consume(None, U, "files"))                              # yangi kun hisobi 0 dan boshlanadi
    assert tariffs.quota_used(U, "files") == 1


def test_staff_consume_is_noop():
    run(tariffs.consume(None, SUPER, "files"))
    assert str(SUPER) not in tgdb.get()["users"] or tgdb.get()["users"][str(SUPER)].get("files_today", 0) == 0


# ── dispatch: kvotani serverda majburlash ────────────────────────────────

def stub_tools(monkeypatch, tmp_path):
    calls = []
    f = tmp_path / "out.docx"
    f.write_text("x")

    async def make_file(user_id, args, ctx):
        calls.append("file")
        return {"status": "ok", "file_path": str(f)}

    async def broken(user_id, args, ctx):
        calls.append("broken")
        return {"error": "xato"}

    async def see(user_id, args, ctx):
        calls.append("see")
        return {"description": "rasm"}

    async def reader(user_id, args, ctx):
        calls.append("read")
        return {"text": "matn"}

    monkeypatch.setitem(ai_tools.DISPATCH, "create_diagram", make_file)
    monkeypatch.setitem(ai_tools.DISPATCH, "create_presentation", broken)
    monkeypatch.setitem(ai_tools.DISPATCH, "look_at_image", see)
    monkeypatch.setitem(ai_tools.DISPATCH, "remember_note", reader)
    return calls


def ctx_for(uid=U, unlimited=False):
    return {"quota_user": uid, "quota_unlimited": unlimited, "bot": None}


def test_free_user_gets_4_files_then_denied_without_running_tool(monkeypatch, tmp_path):
    calls = stub_tools(monkeypatch, tmp_path)
    fresh_user()
    for _ in range(4):
        assert "error" not in run(ai_tools.dispatch("create_diagram", U, {}, ctx_for()))
    res = run(ai_tools.dispatch("create_diagram", U, {}, ctx_for()))
    assert res["kvota_tugadi"] == "files" and "4/4" in res["error"] and "/tarif" in res["error"]
    assert calls.count("file") == 4                                      # 5-chi marta tool UMUMAN ishga tushmadi
    assert tariffs.quota_used(U, "files") == 4


def test_failed_tool_does_not_consume_quota(monkeypatch, tmp_path):
    calls = stub_tools(monkeypatch, tmp_path)
    fresh_user()
    for _ in range(6):
        assert run(ai_tools.dispatch("create_presentation", U, {}, ctx_for())) == {"error": "xato"}
    assert tariffs.quota_used(U, "files") == 0 and calls.count("broken") == 6


def test_vision_quota_2_free_10_plus_70_pro(monkeypatch, tmp_path):
    stub_tools(monkeypatch, tmp_path)
    fresh_user()
    for tier, n in (("free", 2), ("plus", 10), ("pro", 70)):
        fresh_user(); tgdb.get()["users"][str(U)]["vision_today"] = 0
        if tier != "free":
            run(tariffs.grant(None, U, tier))
        for i in range(n):
            assert "error" not in run(ai_tools.dispatch("look_at_image", U, {}, ctx_for())), (tier, i)
        assert run(ai_tools.dispatch("look_at_image", U, {}, ctx_for()))["kvota_tugadi"] == "vision"


def test_files_quota_20_plus_100_pro(monkeypatch, tmp_path):
    stub_tools(monkeypatch, tmp_path)
    for tier, n in (("plus", 20), ("pro", 100)):
        fresh_user(); tgdb.get()["users"][str(U)]["files_today"] = 0
        run(tariffs.grant(None, U, tier))
        for _ in range(n):
            assert "error" not in run(ai_tools.dispatch("create_diagram", U, {}, ctx_for()))
        assert run(ai_tools.dispatch("create_diagram", U, {}, ctx_for()))["kvota_tugadi"] == "files"


def test_readonly_tools_and_other_tools_unaffected_when_quota_exhausted(monkeypatch, tmp_path):
    calls = stub_tools(monkeypatch, tmp_path)
    fresh_user()["files_today"] = 4
    tgdb.get()["users"][str(U)]["vision_today"] = 2
    assert run(ai_tools.dispatch("remember_note", U, {}, ctx_for())) == {"text": "matn"}
    assert calls == ["read"]


def test_unlimited_for_vip_and_staff_and_no_ctx(monkeypatch, tmp_path):
    calls = stub_tools(monkeypatch, tmp_path)
    fresh_user()["files_today"] = 999
    assert "error" not in run(ai_tools.dispatch("create_diagram", U, {}, ctx_for(unlimited=True)))   # VIP chatmode
    assert "error" not in run(ai_tools.dispatch("create_diagram", SUPER, {}, ctx_for(SUPER)))        # admin
    assert "error" not in run(ai_tools.dispatch("create_diagram", U, {}, {"bot": None}))             # ichki chaqiruv (quota_user yo'q)
    assert calls.count("file") == 3


def test_quota_charged_to_payer_not_writer(monkeypatch, tmp_path):
    stub_tools(monkeypatch, tmp_path)
    fresh_user(U)["files_today"] = 4                                      # to'lovchi (chatmode egasi) kvotasi tugagan
    fresh_user(8)
    res = run(ai_tools.dispatch("create_diagram", 8, {}, {"quota_user": U, "quota_unlimited": False, "bot": None}))
    assert res["kvota_tugadi"] == "files"
    ok = run(ai_tools.dispatch("create_diagram", U, {}, {"quota_user": 8, "quota_unlimited": False, "bot": None}))
    assert "error" not in ok and tariffs.quota_used(8, "files") == 1 and tariffs.quota_used(U, "files") == 4


# ── superadmin narx va limitlarni tahrirlaydi ────────────────────────────

@pytest.mark.parametrize("tier,field,raw,why", [
    ("plus", "files", "abc", "son"), ("plus", "files", "-5", "son"), ("plus", "files", "1.5", "son"),
    ("plus", "files", "100001", "gacha"), ("plus", "stars", "0", "gacha"), ("plus", "stars", "10001", "gacha"),
    ("free", "stars", "100", "Bepul"), ("free", "daily_limit", "50", "Bepul"),
    ("gold", "files", "5", "tarif yo'q"), ("plus", "nope", "5", "maydon yo'q"),
])
def test_set_config_rejects_bad_input(tier, field, raw, why):
    ok, msg = run(tariffs.set_config(None, tier, field, raw))
    assert not ok and why in msg and "tariff_config" not in tgdb.get()


def test_set_config_applies_live_to_price_limits_and_quotas():
    assert run(tariffs.set_config(None, "plus", "stars", "99"))[0]
    assert run(tariffs.set_config(None, "plus", "files", "33"))[0]
    assert run(tariffs.set_config(None, "plus", "vision", "0"))[0]               # 0 — o'chirish
    assert run(tariffs.set_config(None, "plus", "daily_limit", "250"))[0]
    assert run(tariffs.set_config(None, "free", "files", "7"))[0]
    t = tariffs.tiers()
    assert (t["plus"].stars, t["plus"].files, t["plus"].vision, t["plus"].daily_limit) == (99, 33, 0, 250)
    assert t["free"].files == 7 and t["pro"].files == 100                          # boshqa tarif tegilmagan
    run(tariffs.grant(None, U, "plus"))
    assert tariffs.quota_limit(U, "files") == 33 and tariffs.quota_limit(U, "vision") == 0
    assert not tariffs.quota_available(U, "vision")                                # 0 — butunlay yopiq
    assert roles.effective_daily_limit(U) == 250


def test_new_price_applies_to_new_invoices_but_not_existing_subscription():
    buy(U, "plus", "c1")
    until = tariffs.until_ts(U)
    run(tariffs.set_config(None, "plus", "stars", "500"))
    assert tariffs.until_ts(U) == until and tariffs.active_tier(U, NOW + DAY).id == "plus"
    old_price = tariffs.check_payment(tariffs.make_payload(6, "plus"), 6, "XTR", 150, strict_price=True)
    assert old_price[0] is None and "Narx o'zgargan" in old_price[1]               # eski narxdagi hisob-faktura rad etiladi
    assert tariffs.check_payment(tariffs.make_payload(6, "plus"), 6, "XTR", 500, strict_price=True)[0] == "plus"


def test_reset_config_restores_defaults():
    run(tariffs.set_config(None, "pro", "files", "5"))
    assert run(tariffs.reset_config(None, "pro")) is True and tariffs.tiers()["pro"].files == 100
    assert run(tariffs.reset_config(None, "pro")) is False


def test_garbage_in_stored_config_is_ignored():
    tgdb.get()["tariff_config"] = {"plus": {"files": "evil", "stars": 77, "name": "Hack", "rank": 9}}
    t = tariffs.tiers()["plus"]
    assert t.files == 20 and t.stars == 77 and t.name == "Plus ⭐" and t.rank == 1  # faqat ruxsat etilgan butun maydonlar


# ── story izohi (caption) ────────────────────────────────────────────────

def test_caption_requires_plus_pro_or_staff():
    assert tariffs.can_caption(U) is False
    run(tariffs.grant(None, U, "plus"))
    assert tariffs.can_caption(U) is True
    tgdb.get()["subscriptions"][str(U)]["until"] = 0
    assert tariffs.can_caption(U) is False
    assert tariffs.can_caption(SUPER) and tariffs.can_caption(ADMIN)


def test_profile_story_caption_locked_for_free_but_posting_unlimited(monkeypatch):
    import handlers.profile as profile
    import core.story_caption as story_caption
    resolved = []

    async def fake_resolve(bot, uid, caption, kind, photo_path=None, cache=None):
        resolved.append(caption)
        return caption, story_caption.LITERAL, None

    monkeypatch.setattr(story_caption, "resolve", fake_resolve)
    profile._waiting[U] = {"step": "period", "orig_caption": "Bugungi kun!", "orig_entities": None, "kind": "photo",
                           "src": "x", "path": "x", "t": 0}
    run(profile._apply_caption(None, U))
    st = profile._waiting[U]
    assert resolved == [] and st["caption"] is None and st["mode"] == story_caption.NONE and st["caption_locked"]
    text, kb = profile._period_view(st)
    assert "izohsiz" in text and "Plus yoki Pro" in text and "profile:post:24" in str(kb)   # joylash tugmasi bor — story baribir ketadi
    # izoh yozmagan bepul foydalanuvchi — oddiy oqim (limitga tegmaydi)
    profile._waiting[U] = {"step": "period", "orig_caption": None, "orig_entities": None, "kind": "photo", "src": "x", "path": "x", "t": 0}
    run(profile._apply_caption(None, U))
    assert resolved == [None] and not profile._waiting[U].get("caption_locked")
    # Plus — izoh ishlaydi
    run(tariffs.grant(None, U, "plus"))
    profile._waiting[U] = {"step": "period", "orig_caption": "Bugungi kun!", "orig_entities": None, "kind": "photo", "src": "x", "path": "x", "t": 0}
    run(profile._apply_caption(None, U))
    assert resolved[-1] == "Bugungi kun!" and profile._waiting[U]["caption"] == "Bugungi kun!"
    profile._waiting.pop(U, None)


# ── muddat tugashi haqida eslatma ────────────────────────────────────────

class ReminderBot:
    def __init__(self, fail=()):
        self.sent, self.fail = [], set(fail)

    async def send_message(self, chat_id, text, **kw):
        if chat_id in self.fail:
            raise RuntimeError("blocked")
        self.sent.append((chat_id, text))


def test_reminders_d3_d1_end_each_once():
    buy(U, "plus", "c1")                                                  # until = NOW + 30 kun
    until = tariffs.until_ts(U)
    bot = ReminderBot()
    at = lambda days_left: until - days_left * DAY
    assert run(tariffs.send_reminders(bot, now=at(10))) == 0              # hali erta
    assert run(tariffs.send_reminders(bot, now=at(2.9))) == 1 and "3 kundan kam" in bot.sent[-1][1]
    assert run(tariffs.send_reminders(bot, now=at(2.0))) == 0             # d3 qayta yuborilmaydi
    assert run(tariffs.send_reminders(bot, now=at(0.9))) == 1 and "1 kundan kam" in bot.sent[-1][1]
    assert run(tariffs.send_reminders(bot, now=at(0.5))) == 0
    assert run(tariffs.send_reminders(bot, now=until + 3600)) == 1 and "tugadi" in bot.sent[-1][1]
    assert run(tariffs.send_reminders(bot, now=until + 7200)) == 0
    assert [c for c, _ in bot.sent] == [U, U, U] and all("/tarif" in t for _, t in bot.sent)


def test_one_day_left_skips_d3_and_renewal_resets_reminders():
    buy(U, "plus", "c1")
    until = tariffs.until_ts(U)
    bot = ReminderBot()
    assert run(tariffs.send_reminders(bot, now=until - 0.5 * DAY)) == 1 and "1 kundan kam" in bot.sent[-1][1]
    assert run(tariffs.send_reminders(bot, now=until - 0.4 * DAY)) == 0   # d3 ham yuborilmaydi (d1 allaqachon bor)
    buy(U, "plus", "c2", now=until - 0.3 * DAY)                           # uzaytirdi -> muddat 30 kun surildi
    new_until = tariffs.until_ts(U)
    assert new_until > until + 29 * DAY and tariffs.due_reminders(now=until) == []
    assert run(tariffs.send_reminders(bot, now=new_until - 2 * DAY)) == 1  # yangi muddat uchun eslatma yana ishlaydi


def test_no_reminders_for_free_revoked_refunded_or_long_expired():
    assert tariffs.due_reminders(NOW) == []
    buy(U, "plus", "c1")
    run(tariffs.revoke(None, U))
    assert tariffs.due_reminders(NOW + 29 * DAY) == []                    # bekor qilingan (until=0)
    buy(6, "pro", "c2")
    until = tariffs.until_ts(6)
    assert tariffs.due_reminders(until + 8 * DAY) == []                   # 7 kundan oshgan eski muddat — bezovta qilmaymiz
    assert tariffs.due_reminders(until + 1 * DAY) == [(6, "end", until)]


def test_blocked_user_is_marked_so_it_is_not_retried_forever():
    buy(U, "plus", "c1")
    until = tariffs.until_ts(U)
    bot = ReminderBot(fail={U})
    assert run(tariffs.send_reminders(bot, now=until - 2 * DAY)) == 0 and bot.sent == []
    assert tariffs.due_reminders(until - 2 * DAY) == []


def test_scheduler_runs_reminders_job(monkeypatch):
    import core.scheduler as scheduler
    calls = []

    async def fake_send(bot):
        calls.append(1)

    monkeypatch.setattr(scheduler.tariffs, "send_reminders", fake_send)

    async def one_cycle():
        async def stop(_):
            raise asyncio.CancelledError

        monkeypatch.setattr(scheduler.asyncio, "sleep", stop)
        scheduler._last_tariff_check = 0.0
        with pytest.raises(asyncio.CancelledError):
            await scheduler.run_forever(None)

    run(one_cycle())
    assert calls == [1]


# ── panel: sozlamalarni tahrirlash ───────────────────────────────────────

def test_panel_tariff_config_is_superadmin_only():
    for data, fn in (("panel:tcfg:plus", panel.tariff_config_open), ("panel:tset:plus:files", panel.tariff_config_ask)):
        c = pcall(ADMIN, data)
        run(fn(c))
        assert c.alerts == [("Faqat superadmin", True)]
    c = pcall(ADMIN, "panel:treset:plus")
    run(panel.tariff_config_reset(c, FakeBot()))
    assert c.alerts == [("Faqat superadmin", True)]
    assert pending_input.get(ADMIN) is None


def test_panel_config_flow_end_to_end():
    import handlers.pending_text as pt
    c = pcall(SUPER, "panel:tariffs")
    run(panel.show_tariffs(c))
    kb_data = [b.callback_data for r in c.edits[0][1].inline_keyboard for b in r]
    assert {"panel:tcfg:free", "panel:tcfg:plus", "panel:tcfg:pro"} <= set(kb_data)

    c = pcall(SUPER, "panel:tcfg:plus")
    run(panel.tariff_config_open(c))
    buttons_ = [b.callback_data for r in c.edits[0][1].inline_keyboard for b in r]
    assert {"panel:tset:plus:stars", "panel:tset:plus:daily_limit", "panel:tset:plus:files", "panel:tset:plus:vision"} <= set(buttons_)
    c = pcall(SUPER, "panel:tcfg:free")
    run(panel.tariff_config_open(c))
    free_buttons = [b.callback_data for r in c.edits[0][1].inline_keyboard for b in r]
    assert "panel:tset:free:stars" not in free_buttons and "panel:tset:free:files" in free_buttons

    ask = pcall(SUPER, "panel:tset:plus:files")
    ask.message.answer = lambda *a, **k: _noop()
    run(panel.tariff_config_ask(ask))
    assert pending_input.get(SUPER) == {"action": "tariff_value", "data": {"tier": "plus", "field": "files"}}

    bad = make_msg(SUPER, text="abc")
    run(pt.handle_pending(bad))
    assert "Faqat butun" in bad.out.answers[0][0] and pending_input.get(SUPER) is not None      # qayta so'raydi
    good = make_msg(SUPER, text="42")
    good.bot = None
    run(pt.handle_pending(good))
    assert tariffs.tiers()["plus"].files == 42 and pending_input.get(SUPER) is None and "42" in good.out.answers[0][0]

    run(panel.tariff_config_reset(pcall(SUPER, "panel:treset:plus"), FakeBot()))
    assert tariffs.tiers()["plus"].files == 20


async def _noop():
    return None


def test_pending_tariff_value_rejects_non_superadmin_and_supports_cancel():
    import handlers.pending_text as pt
    pending_input.set(ADMIN, "tariff_value", {"tier": "plus", "field": "files"})
    m = make_msg(ADMIN, text="9999")
    run(pt.handle_pending(m))
    assert "Ruxsat yo'q" in m.out.answers[0][0] and tariffs.tiers()["plus"].files == 20 and pending_input.get(ADMIN) is None
    pending_input.set(SUPER, "tariff_value", {"tier": "plus", "field": "files"})
    m = make_msg(SUPER, text="/panel")
    run(pt.handle_pending(m))
    assert "Bekor" in m.out.answers[0][0] and tariffs.tiers()["plus"].files == 20


def test_user_detail_and_tarif_page_show_usage():
    fresh_user()["files_today"] = 3
    m = make_msg(U)
    run(th.tarif_cmd(m))
    text = m.out.answers[0][0]
    assert "fayl: 3/4" in text and "rasm: 0/2" in text and "fayl yaratish 20/kun" in text and "fayl yaratish 100/kun" in text
    assert "story izohi" in text


# ── xarid qoidalari va to'lovni tekshirish ───────────────────────────────

def test_purchase_rules():
    assert tariffs.can_purchase(U, "plus")[0] and tariffs.can_purchase(U, "pro")[0]
    assert not tariffs.can_purchase(U, "free")[0] and not tariffs.can_purchase(U, "nope")[0]
    run(tariffs.grant(None, U, "pro"))
    ok, why = tariffs.can_purchase(U, "plus")
    assert not ok and "pastroq" in why                              # Pro ustiga Plus sotib olib bo'lmaydi
    assert tariffs.can_purchase(U, "pro")[0]                        # uzaytirish mumkin


def test_upgrade_warning_only_when_replacing_lower_active_tier():
    assert tariffs.upgrade_warning(U, "pro") is None
    run(tariffs.grant(None, U, "plus"))
    assert "kuymaydi" in tariffs.upgrade_warning(U, "pro") and tariffs.upgrade_warning(U, "plus") is None


@pytest.mark.parametrize("payload,payer,currency,amount,why", [
    ("garbage", U, "XTR", 150, "noto'g'ri"),
    ("tariff:plus:999", U, "XTR", 150, "boshqa foydalanuvchi"),
    ("tariff:plus:5", U, "USD", 150, "Stars"),
    ("tariff:free:5", U, "XTR", 0, "yo'q"),
    ("tariff:gold:5", U, "XTR", 150, "yo'q"),
    ("tariff:plus:5", U, "XTR", 1, "Narx o'zgargan"),
])
def test_check_payment_rejects_bad_invoices(payload, payer, currency, amount, why):
    tier, err = tariffs.check_payment(payload, payer, currency, amount, strict_price=True)
    assert tier is None and why in err


def test_check_payment_ok_and_lenient_after_charge():
    assert tariffs.check_payment(tariffs.make_payload(U, "pro"), U, "XTR", tariffs.tiers()["pro"].stars, True) == ("pro", None)
    # Pul allaqachon yechilgan: narx o'zgargan bo'lsa ham foydalanuvchining puli yo'qolmasin
    assert tariffs.check_payment(tariffs.make_payload(U, "pro"), U, "XTR", 1, strict_price=False) == ("pro", None)


def test_pre_checkout_blocks_downgrade_over_active_higher_tier():
    run(tariffs.grant(None, U, "pro"))
    tier, err = tariffs.check_payment(tariffs.make_payload(U, "plus"), U, "XTR", tariffs.tiers()["plus"].stars, True)
    assert tier is None and "pastroq" in err


# ── to'lovni hisoblash ───────────────────────────────────────────────────

def test_apply_payment_new_extend_upgrade_and_idempotency():
    assert buy(U, "plus", "c1") == "ok"
    until1 = tariffs.until_ts(U)
    assert until1 == int(NOW + 30 * DAY)
    assert buy(U, "plus", "c2", now=NOW + 10 * DAY) == "ok"          # uzaytirish: mavjud muddat ustiga +30
    assert tariffs.until_ts(U) == until1 + 30 * DAY
    assert buy(U, "plus", "c2", now=NOW + 10 * DAY) == "duplicate"   # Telegram qayta yuborsa — ikki marta hisoblanmaydi
    assert tariffs.until_ts(U) == until1 + 30 * DAY
    assert buy(U, "pro", "c3", now=NOW + 11 * DAY) == "ok"           # yuqoriroq tarif — hozirdan 30 kun
    assert tariffs.active_tier(U, NOW + 12 * DAY).id == "pro" and tariffs.until_ts(U) == int(NOW + 41 * DAY)
    assert tgdb.get()["subscriptions"][str(U)]["stars_total"] == 150 + 150 + 400


def test_expired_then_renew_starts_from_now():
    buy(U, "plus", "c1")
    buy(U, "plus", "c2", now=NOW + 100 * DAY)
    assert tariffs.until_ts(U) == int(NOW + 130 * DAY)


def test_refund_flow():
    buy(U, "pro", "c1")
    buy(U, "pro", "c2", now=NOW + DAY)
    ch = tariffs.last_refundable_charge(U)
    assert ch["id"] == "c2"
    assert run(tariffs.mark_refunded(None, U, "c2"))
    assert tariffs.active_tier(U, NOW + DAY).id == "free"
    assert tgdb.get()["subscriptions"][str(U)]["stars_total"] == 400
    assert tariffs.last_refundable_charge(U)["id"] == "c1"
    assert not run(tariffs.mark_refunded(None, U, "c2"))             # ikki marta qaytarib bo'lmaydi


def test_grant_and_revoke():
    run(tariffs.grant(None, U, "plus", days=3))
    assert tariffs.active_tier(U).id == "plus" and tariffs.days_left(U) == 3
    assert run(tariffs.revoke(None, U)) is True and tariffs.active_tier(U).id == "free"
    assert run(tariffs.revoke(None, U)) is False


def test_stats_counts_active_only():
    buy(U, "plus", "a")
    buy(6, "pro", "b")
    buy(7, "pro", "c", now=NOW - 100 * DAY)                          # allaqachon tugagan
    st = tariffs.stats(now=NOW + DAY)
    assert st["active"] == {"plus": 1, "pro": 1} and st["stars_total"] == 150 + 400 + 400


def test_env_overrides_prices(monkeypatch):
    monkeypatch.setattr(tariffs.config, "TARIFF_PRO_STARS", 999)
    monkeypatch.setattr(tariffs.config, "TARIFF_PLUS_LIMIT", 77)
    assert tariffs.tiers()["pro"].stars == 999 and tariffs.tiers()["plus"].daily_limit == 77


# ── Telegram handler'lari ────────────────────────────────────────────────

class FakeBot:
    def __init__(self):
        self.sent, self.refunds = [], []
        self.refund_error = None

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))

    async def refund_star_payment(self, user_id, telegram_payment_charge_id):
        if self.refund_error:
            raise self.refund_error
        self.refunds.append((user_id, telegram_payment_charge_id))


def make_msg(uid, text="/tarif", chat="private", payment=None):
    out = SimpleNamespace(answers=[], replies=[])

    async def answer(t, **kw):
        out.answers.append((t, kw))

    async def reply(t, **kw):
        out.replies.append((t, kw))

    return SimpleNamespace(from_user=SimpleNamespace(id=uid, full_name="Ali <b>"), chat=SimpleNamespace(type=chat), text=text,
                           answer=answer, reply=reply, bot=FakeBot(), successful_payment=payment, out=out)


def make_call(uid, data, chat="private"):
    invoices, alerts = [], []

    async def answer_invoice(**kw):
        invoices.append(kw)

    async def answer(text=None, show_alert=False):
        alerts.append((text, show_alert))

    msg = SimpleNamespace(chat=SimpleNamespace(type=chat), answer_invoice=answer_invoice)
    return SimpleNamespace(from_user=SimpleNamespace(id=uid), data=data, message=msg, answer=answer, invoices=invoices, alerts=alerts)


def buttons(kb):
    return [b.callback_data for row in kb.inline_keyboard for b in row] if kb else []


def test_tarif_command_private_shows_buy_buttons_and_group_redirects():
    m = make_msg(U)
    run(th.tarif_cmd(m))
    text, kw = m.out.answers[0]
    assert buttons(kw["reply_markup"]) == ["tariff:buy:plus", "tariff:buy:pro"] and "Bepul" in text and "150" in text
    g = make_msg(U, chat="supergroup")
    run(th.tarif_cmd(g))
    assert "shaxsiy chatda" in g.out.replies[0][0] and not g.out.answers


def test_tarif_command_hides_buttons_that_cannot_be_bought_and_staff_note():
    run(tariffs.grant(None, U, "pro"))
    m = make_msg(U)
    run(th.tarif_cmd(m))
    assert buttons(m.out.answers[0][1]["reply_markup"]) == ["tariff:buy:pro"]    # Plus yo'q (pastroq), Pro — uzaytirish
    s = make_msg(SUPER)
    run(th.tarif_cmd(s))
    assert "adminsiz" in s.out.answers[0][0]


def test_buy_sends_stars_invoice_with_exact_price_and_payload():
    call = make_call(U, "tariff:buy:pro")
    run(th.buy_cb(call))
    inv = call.invoices[0]
    assert inv["currency"] == "XTR" and inv["provider_token"] == "" and inv["payload"] == f"tariff:pro:{U}"
    assert [(p.amount) for p in inv["prices"]] == [tariffs.tiers()["pro"].stars]
    assert len(inv["description"]) <= 255


def test_buy_refused_in_group_for_unknown_tier_and_downgrade():
    c = make_call(U, "tariff:buy:pro", chat="supergroup")
    run(th.buy_cb(c))
    assert c.invoices == [] and c.alerts[0][1] is True
    c = make_call(U, "tariff:buy:gold")
    run(th.buy_cb(c))
    assert c.invoices == []
    run(tariffs.grant(None, U, "pro"))
    c = make_call(U, "tariff:buy:plus")
    run(th.buy_cb(c))
    assert c.invoices == [] and "pastroq" in c.alerts[0][0]


def test_buy_upgrade_invoice_carries_warning():
    run(tariffs.grant(None, U, "plus"))
    call = make_call(U, "tariff:buy:pro")
    run(th.buy_cb(call))
    assert "kuymaydi" in call.invoices[0]["description"]


def make_query(uid, payload, amount, currency="XTR"):
    res = {}

    async def answer(ok, error_message=None):
        res.update(ok=ok, error=error_message)

    return SimpleNamespace(from_user=SimpleNamespace(id=uid), invoice_payload=payload, total_amount=amount, currency=currency,
                           answer=answer, res=res)


def test_pre_checkout_handler():
    q = make_query(U, tariffs.make_payload(U, "plus"), tariffs.tiers()["plus"].stars)
    run(th.pre_checkout(q))
    assert q.res["ok"] is True
    for bad in (make_query(U, tariffs.make_payload(U, "plus"), 1), make_query(9, tariffs.make_payload(U, "plus"), 150),
                make_query(U, "x", 150), make_query(U, tariffs.make_payload(U, "plus"), 150, "USD")):
        run(th.pre_checkout(bad))
        assert bad.res["ok"] is False and bad.res["error"]


def pay(uid, tier, amount=None, charge="ch1", currency="XTR", payload=None):
    return SimpleNamespace(invoice_payload=payload or tariffs.make_payload(uid, tier), currency=currency,
                           total_amount=tariffs.tiers()[tier].stars if amount is None else amount,
                           telegram_payment_charge_id=charge)


def test_successful_payment_activates_tier_once():
    m = make_msg(U, payment=pay(U, "pro"))
    run(th.successful_payment(m))
    assert tariffs.active_tier(U).id == "pro" and "yoqildi" in m.out.answers[0][0]
    m2 = make_msg(U, payment=pay(U, "pro"))                            # Telegram bir xil to'lovni qayta yubordi
    until = tariffs.until_ts(U)
    run(th.successful_payment(m2))
    assert tariffs.until_ts(U) == until and "allaqachon" in m2.out.answers[0][0]


def test_unrecognised_paid_invoice_is_not_swallowed():
    m = make_msg(U, payment=pay(U, "pro", payload="tariff:gold:5", charge="zz"))
    run(th.successful_payment(m))
    assert tariffs.active_tier(U).id == "free"
    assert "paysupport" in m.out.answers[0][0]
    assert m.bot.sent and m.bot.sent[0][0] == SUPER and "zz" in m.bot.sent[0][1]     # superadmin refund uchun xabar oladi


def test_paysupport_forwards_to_superadmin_escaped():
    m = make_msg(U, text="/paysupport pul yechildi <b>tarif yo'q</b>")
    run(th.paysupport(m))
    chat, text = m.bot.sent[0]
    assert chat == SUPER and "&lt;b&gt;" in text and "Ali &lt;b&gt;" in text
    empty = make_msg(U, text="/paysupport")
    run(th.paysupport(empty))
    assert not empty.bot.sent and "paysupport muammo" in empty.out.answers[0][0]


# ── panel ────────────────────────────────────────────────────────────────

def pcall(uid, data):
    alerts, edits = [], []

    async def answer(text=None, show_alert=False):
        alerts.append((text, show_alert))

    async def edit_text(text, reply_markup=None, **kw):
        edits.append((text, reply_markup))

    return SimpleNamespace(from_user=SimpleNamespace(id=uid), data=data, answer=answer,
                           message=SimpleNamespace(edit_text=edit_text), alerts=alerts, edits=edits)


def test_panel_tariff_actions_are_superadmin_only():
    for data, fn in ((f"panel:tgrant:pro:{U}", panel.tariff_grant_cb), (f"panel:trevoke:{U}", panel.tariff_revoke_cb),
                     (f"panel:trefund:{U}", panel.tariff_refund_cb)):
        c = pcall(ADMIN, data)
        run(fn(c, FakeBot()))
        assert c.alerts == [("Faqat superadmin", True)]
    c = pcall(ADMIN, "panel:tariffs")
    run(panel.show_tariffs(c))
    assert c.alerts == [("Faqat superadmin", True)]
    assert tariffs.active_tier(U).id == "free"
    assert "panel:tariffs" in [b.callback_data for r in panel.main_menu_kb(SUPER).inline_keyboard for b in r]
    assert "panel:tariffs" not in [b.callback_data for r in panel.main_menu_kb(ADMIN).inline_keyboard for b in r]


def test_panel_grant_revoke_and_stats():
    run(panel.tariff_grant_cb(pcall(SUPER, f"panel:tgrant:pro:{U}"), FakeBot()))
    assert tariffs.active_tier(U).id == "pro"
    c = pcall(SUPER, "panel:tariffs")
    run(panel.show_tariffs(c))
    assert "faol: <b>1</b>" in c.edits[0][0]
    c = pcall(SUPER, f"panel:trevoke:{U}")
    run(panel.tariff_revoke_cb(c, FakeBot()))
    assert tariffs.active_tier(U).id == "free" and "bekor" in c.alerts[0][0]
    bad = pcall(SUPER, "panel:tgrant:gold:5")
    run(panel.tariff_grant_cb(bad, FakeBot()))
    assert bad.alerts[0][1] is True


def test_panel_refund_calls_telegram_and_revokes_and_handles_failure():
    buy(U, "pro", "chg-1")
    bot = FakeBot()
    bot.refund_error = RuntimeError("boom")
    c = pcall(SUPER, f"panel:trefund:{U}")
    run(panel.tariff_refund_cb(c, bot))
    assert "bajarilmadi" in c.alerts[0][0] and tariffs.active_tier(U).id != "free"      # xatoda tarif tegilmaydi
    bot.refund_error = None
    c = pcall(SUPER, f"panel:trefund:{U}")
    run(panel.tariff_refund_cb(c, bot))
    assert bot.refunds == [(U, "chg-1")] and tariffs.active_tier(U).id == "free" and "qaytarildi" in c.alerts[0][0]
    c = pcall(SUPER, f"panel:trefund:{U}")
    run(panel.tariff_refund_cb(c, bot))
    assert "yo'q" in c.alerts[0][0] and len(bot.refunds) == 1                           # ikki marta qaytarilmaydi
