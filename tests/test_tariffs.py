import asyncio
import time
from types import SimpleNamespace

import pytest

import admin.panel as panel
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


# ── imkoniyatlar ─────────────────────────────────────────────────────────

def test_features_by_tier_staff_vip_and_payer():
    assert tariffs.features_of(U) == frozenset()
    run(tariffs.grant(None, U, "plus"))
    assert tariffs.features_of(U) == {tariffs.FEATURE_VISION}
    run(tariffs.grant(None, U, "pro"))
    assert tariffs.features_of(U) == tariffs.ALL_FEATURES
    assert tariffs.features_of(SUPER) == tariffs.features_of(ADMIN) == tariffs.ALL_FEATURES
    # guruh: yozuvchi YOKI to'lovchi (chatmode egasi); VIP — hammasi
    assert tariffs.features_for_request(77, U) == tariffs.ALL_FEATURES        # to'lovchi Pro
    assert tariffs.features_for_request(U, 77) == tariffs.ALL_FEATURES        # yozuvchi Pro
    assert tariffs.features_for_request(77, 78) == frozenset()
    assert tariffs.features_for_request(77, 78, vip=True) == tariffs.ALL_FEATURES


def test_filter_tools_hides_unavailable_tools():
    tools = [{"function": {"name": n}} for n in ("remember_note", "look_at_image", "create_presentation", "create_diagram",
                                                 "create_docx", "set_my_nickname")]
    is_file = lambda n: n == "create_docx"
    names = lambda feats: [t["function"]["name"] for t in tariffs.filter_tools(tools, feats, is_file)]
    assert names(frozenset()) == ["remember_note", "set_my_nickname"]
    assert names({tariffs.FEATURE_VISION}) == ["remember_note", "look_at_image", "set_my_nickname"]
    assert len(names(tariffs.ALL_FEATURES)) == 6


def test_real_tool_catalog_is_split_as_documented():
    from tools.file_tools import FILE_TOOLS, is_file_tool
    free = {t["function"]["name"] for t in tariffs.filter_tools(ai_tools.TOOLS, frozenset(), is_file_tool)}
    assert not free & {"look_at_image", "create_presentation", "create_diagram", "create_docx", "create_pdf", "read_any_file"}
    assert "remember_note" in free and "set_my_nickname" in free
    assert len(tariffs.filter_tools(ai_tools.TOOLS, tariffs.ALL_FEATURES, is_file_tool)) == len(ai_tools.TOOLS)
    assert len(FILE_TOOLS) > 30


def test_dispatch_enforces_features_even_if_ai_invents_the_call(monkeypatch):
    called = []

    async def stub(user_id, args, ctx):
        called.append(1)
        return {"ok": True}

    monkeypatch.setitem(ai_tools.DISPATCH, "look_at_image", stub)
    monkeypatch.setitem(ai_tools.DISPATCH, "create_diagram", stub)
    deny = run(ai_tools.dispatch("look_at_image", U, {}, {"features": frozenset()}))
    assert deny["tarif_kerak"] == "vision" and called == []
    deny = run(ai_tools.dispatch("create_diagram", U, {}, {"features": {tariffs.FEATURE_VISION}}))
    assert deny["tarif_kerak"] == "files" and called == []
    assert run(ai_tools.dispatch("look_at_image", U, {}, {"features": {tariffs.FEATURE_VISION}})) == {"ok": True}
    assert run(ai_tools.dispatch("create_diagram", U, {}, {"features": tariffs.ALL_FEATURES})) == {"ok": True}
    res = run(ai_tools.dispatch("create_docx", U, {}, {"features": frozenset()}))      # fayl-toolkit ham to'siladi
    assert res["tarif_kerak"] == "files"


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
