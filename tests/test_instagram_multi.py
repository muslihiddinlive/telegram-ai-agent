"""Ko'p-akkauntli Instagram: ulash (OAuth), akkauntlar izolyatsiyasi, tariflar (sinov/Plus/Pro), webhook/scheduler yo'naltirish."""
import asyncio
import base64
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

import core.instagram_accounts as accounts
import core.instagram_api as ig
import core.instagram_common as common
import core.instagram_context as ictx
import core.instagram_dm as dm
import core.instagram_manage as manage
import core.instagram_oauth as oauth
import core.instagram_plans as plans
import core.instagram_scheduler as scheduler
import core.instagram_store as store
import core.instagram_tools as tools
import core.instagram_webhook as wh
import core.tgdb as tgdb

A, B, C = 1001, 1002, 1003          # oddiy foydalanuvchilar (Telegram ID); 1 — superadmin (conftest)
TOK = {A: "TOKEN-AAA", B: "TOKEN-BBB", C: "TOKEN-CCC"}
IGID = {A: "9001", B: "9002", C: "9003"}


def run(coro):
    return asyncio.run(coro)


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, parse_mode=None, **kw):
        self.sent.append((chat_id, text))


@pytest.fixture
def mt(monkeypatch, tmp_path):
    for k, v in {"IG_APP_ID": "APPID", "IG_APP_SECRET": "appsecret", "IG_PUBLIC_BASE_URL": "https://bot.example.com",
                 "IG_STORE_DIR": str(tmp_path / "store")}.items():
        monkeypatch.setenv(k, v)
    for k in ("IG_USER_ID", "IG_ACCESS_TOKEN", "IG_ALLOWED_USER_IDS", "META_APP_SECRET", "IG_WEBHOOK_ENABLED"):
        monkeypatch.delenv(k, raising=False)
    db = {"users": {}}
    monkeypatch.setattr(tgdb, "_cache", db)
    monkeypatch.setattr(tgdb, "mark_dirty", lambda: None)
    monkeypatch.setattr(store, "_db", lambda: db)
    monkeypatch.setattr(store, "_dirty", lambda: None)
    common._PENDING.clear()
    oauth._used_states.clear()
    accounts._pending_reauth_notice.clear()
    dm._SENT.clear(); dm._inflight.clear(); dm._hour_times.clear(); dm._locks.clear()
    wh._dm_times.clear(); wh._limit_notified.clear(); common._locks.clear()
    ictx.set_current(None)
    yield SimpleNamespace(db=db, bot=FakeBot())
    ictx.set_current(None)


def connect(uid, now=None, **kw):
    ok, why = accounts.connect(uid, IGID[uid], f"user{uid}", TOK[uid], 60 * 86400, ["instagram_business_basic"], now=now)
    assert ok, why


def grant(mt, uid, tier, secs=10_000):
    mt.db.setdefault("subscriptions", {})[str(uid)] = {"tier": tier, "until": time.time() + secs}


# ── state (CSRF / replay) ──────────────────────────────────────────────────────
def test_state_roundtrip_and_replay_blocked(mt):
    st = oauth.make_state(A)
    assert oauth.verify_state(st) == A
    assert oauth.verify_state(st) is None                      # ikkinchi marta — rad


def test_state_rejects_tamper_expiry_and_garbage(mt):
    st = oauth.make_state(A, now=1000)
    forged = st.replace(f"{A}.", f"{B}.", 1)                   # boshqa odamning ID'siga o'zgartirish
    assert oauth.verify_state(forged, now=1001) is None
    assert oauth.verify_state(st, now=1000 + oauth.STATE_TTL + 5) is None
    for bad in (None, "", "x", "1.2.3", "a.b.c.d"):
        assert oauth.verify_state(bad) is None


def test_authorize_url_has_expected_parts(mt):
    from urllib.parse import parse_qs, urlparse
    u = urlparse(oauth.authorize_url(A))
    q = parse_qs(u.query)
    assert u.netloc == "www.instagram.com" and u.path == "/oauth/authorize"
    assert q["client_id"] == ["APPID"] and q["response_type"] == ["code"]
    assert q["redirect_uri"] == ["https://bot.example.com/ig/callback"]
    assert "instagram_business_content_publish" in q["scope"][0] and "appsecret" not in u.query
    assert oauth.verify_state(q["state"][0]) == A


# ── ulash ──────────────────────────────────────────────────────────────────────
def fake_meta(monkeypatch, *, uid="9001", username="shop", account_type="BUSINESS", token="LONG-TOKEN"):
    calls = []

    async def http(method, url, *, data=None, params=None):
        calls.append((method, url))
        if url == oauth.TOKEN_URL:
            return {"data": [{"access_token": "SHORT", "user_id": uid, "permissions": "instagram_business_basic"}]}
        if url.endswith("/access_token"):
            return {"access_token": token, "expires_in": 5_184_000}
        if url.endswith("/me"):
            return {"user_id": uid, "username": username, "account_type": account_type}
        raise AssertionError(url)

    monkeypatch.setattr(oauth, "_http", http)
    return calls


def test_connect_stores_encrypted_token_and_starts_trial(mt, monkeypatch):
    fake_meta(monkeypatch)
    ok, msg = run(oauth.complete_connection(mt.bot, A, "CODE"))
    assert ok and "@shop" in msg and "sinov" in msg.lower()
    rec = accounts.record(A)
    assert rec["ig_id"] == "9001" and rec["token"] != "LONG-TOKEN" and "LONG-TOKEN" not in json.dumps(mt.db)
    assert accounts.account_for(A).token == "LONG-TOKEN"
    assert accounts.trial_active(A)
    assert all("LONG-TOKEN" not in t and "CODE" not in t for _, t in mt.bot.sent)     # xabarda sir yo'q


def test_connect_rejects_personal_account(mt, monkeypatch):
    fake_meta(monkeypatch, account_type="PERSONAL")
    ok, msg = run(oauth.complete_connection(mt.bot, A, "CODE"))
    assert not ok and "Business" in msg and accounts.status(A) == "none"


def test_ig_account_cannot_be_linked_to_two_users(mt, monkeypatch):
    connect(A)
    fake_meta(monkeypatch, uid=IGID[A])
    ok, msg = run(oauth.complete_connection(mt.bot, B, "CODE"))
    assert not ok and "boshqa foydalanuvchiga" in msg and accounts.status(B) == "none"


def test_owner_env_account_cannot_be_connected_by_users(mt, monkeypatch):
    monkeypatch.setenv("IG_USER_ID", "7777"); monkeypatch.setenv("IG_ACCESS_TOKEN", "OWNERTOK")
    ok, why = accounts.connect(A, "7777", "boss", "x", 100)
    assert not ok and "egasiga" in why


def test_connect_blocked_when_trial_already_used(mt, monkeypatch):
    connect(A, now=1000)                                      # sinov 1000 da boshlangan va tugagan
    accounts.disconnect(A)
    ok, why = oauth.can_connect(A)
    assert not ok and "tugagan" in why


def test_paid_user_can_connect_even_after_trial(mt):
    connect(A, now=1000); accounts.disconnect(A)
    grant(mt, A, "plus")
    assert oauth.can_connect(A) == (True, "")


# ── sinov: bir marta ───────────────────────────────────────────────────────────
def test_trial_is_three_days_and_never_renews(mt):
    now = 2_000_000
    connect(A, now=now)
    assert accounts.trial_seconds_left(A, now + 100) == 3 * 86400 - 100
    assert not accounts.trial_active(A, now + 3 * 86400 + 1)
    accounts.disconnect(A)
    connect(A, now=now + 5 * 86400)                           # qayta ulandi — sinov QAYTMAYDI
    assert not accounts.trial_active(A, now + 5 * 86400 + 10)


def test_same_ig_account_gets_no_second_trial_via_other_telegram_user(mt):
    connect(A, now=1000); accounts.disconnect(A)
    ok, _ = accounts.connect(B, IGID[A], "same", "TOK-B", 100, now=time.time())
    assert ok and not accounts.trial_active(B)                # boshqa Telegram — o'sha Instagram: sinov berilmaydi


# ── IZOLYATSIYA (eng muhim) ────────────────────────────────────────────────────
def test_each_user_gets_only_their_own_account(mt):
    connect(A); connect(B)
    assert common.require(A, {}, "publish") is None
    assert ig._acct().token == TOK[A] and ig._ig_id() == IGID[A]
    assert common.require(B, {}, "publish") is None
    assert ig._acct().token == TOK[B] and ig._ig_id() == IGID[B]


def test_unconnected_user_never_falls_back_to_owner_env_account(mt, monkeypatch):
    monkeypatch.setenv("IG_USER_ID", "7777"); monkeypatch.setenv("IG_ACCESS_TOKEN", "OWNERTOK")
    err = common.require(C, {}, "publish")
    assert err and "ulanmagan" in err["error"]
    assert ictx.current() is None
    with pytest.raises(ig.InstagramAPIError):                  # kontekstsiz chaqiruv egasi akkauntiga TUSHMAYDI
        ig._ig_id()


def test_owner_still_uses_env_account_in_multi_mode(mt, monkeypatch):
    monkeypatch.setenv("IG_USER_ID", "7777"); monkeypatch.setenv("IG_ACCESS_TOKEN", "OWNERTOK")
    assert common.require(1, {}, "publish") is None            # 1 = superadmin
    assert ig._acct().token == "OWNERTOK" and ictx.current_plan().code == "owner"


def test_concurrent_requests_never_cross_accounts(mt):
    connect(A); connect(B)
    seen = {}

    async def worker(uid):
        assert common.require(uid, {}, "publish") is None
        for _ in range(5):
            await asyncio.sleep(0)                            # boshqa vazifaga o'tish
            seen.setdefault(uid, set()).add(ig._acct().token)

    async def main():
        await asyncio.gather(*(worker(u) for u in (A, B, A, B)))

    run(main())
    assert seen == {A: {TOK[A]}, B: {TOK[B]}}


def test_store_state_is_separated_per_account(mt):
    connect(A); connect(B)
    with ictx.use(accounts.account_for(A)):
        store.add_trigger("narx", "15000"); store.add_banned("spam")
    with ictx.use(accounts.account_for(B)):
        assert store.list_triggers() == [] and store.banned_words() == []
    assert mt.db.get("instagram", {}).get("triggers", []) == []     # egasi (eski) bo'limiga tegilmagan


def test_disconnect_wipes_all_account_state(mt):
    connect(A)
    with ictx.use(accounts.account_for(A)):
        store.add_trigger("narx", "15000")
    assert accounts.disconnect(A)
    assert IGID[A] not in mt.db.get("instagram_by_account", {}) and accounts.status(A) == "none"


def test_publish_lock_is_per_account(mt):
    with ictx.use(accounts.Account("1") if False else ictx.Account("1")):
        l1 = common.lock()
    with ictx.use(ictx.Account("2")):
        l2 = common.lock()
    assert l1 is not l2


# ── tariflar ───────────────────────────────────────────────────────────────────
def test_trial_allows_basics_but_not_schedule_automation_dm(mt):
    connect(A)
    for f in ("publish", "insights", "comments"):
        assert common.require(A, {}, f) is None
    for f in ("schedule", "automation", "dm"):
        err = common.require(A, {}, f)
        assert err and "sinov" in err["error"]


def test_expired_trial_blocks_everything(mt):
    connect(A, now=1000)
    for f in ("publish", "insights", "comments", "schedule", "automation", "dm"):
        err = common.require(A, {}, f)
        assert err and "tugagan" in err["error"]


def test_plus_has_everything_but_with_caps(mt):
    connect(A, now=1000); grant(mt, A, "plus")
    for f in plans.FEATURES:
        assert common.require(A, {}, f) is None
    p = ictx.current_plan()
    assert (p.max_scheduled, p.max_triggers, p.max_banned, p.dm_daily) == (10, 3, 10, 30)


def test_pro_is_unlimited(mt):
    connect(A, now=1000); grant(mt, A, "pro")
    assert common.require(A, {}, "dm") is None
    p = ictx.current_plan()
    assert p.code == "pro" and None in (p.max_scheduled, p.max_triggers, p.max_banned, p.dm_daily)


def test_plus_trigger_cap_enforced_on_creation(mt):
    connect(A, now=1000); grant(mt, A, "plus")
    for i in range(3):
        r = run(manage._automation(A, {"action": "add_trigger", "keyword": f"kalit{i}", "reply": "salom"}, {"message_id": 1}))
        assert "xato" not in r and "error" not in r, r
        r = run(manage._automation(A, {"action": "add_trigger", "keyword": f"kalit{i}", "reply": "salom", "confirmed": True},
                                   {"message_id": 2}))
        assert r.get("status") == "qo'shildi", r
        common._PENDING.clear()
    r = run(manage._automation(A, {"action": "add_trigger", "keyword": "toʻrtinchi", "reply": "salom"}, {"message_id": 3}))
    assert "error" in r and "Pro" in r["error"]


def test_plus_downgraded_extra_triggers_sleep(mt):
    connect(A, now=1000); grant(mt, A, "pro")
    common.require(A, {}, "automation")
    for i in range(5):
        store.add_trigger(f"kalit{i}", "x")
    assert store.match_trigger("kalit4 bormi", None, limit=3) is None       # 4-qoida Plus'da uxlaydi
    assert store.match_trigger("kalit2 bormi", None, limit=3)["keyword"] == "kalit2"


def test_staff_gets_owner_plan(mt):
    connect(A, now=1000)
    mt.db["admins"] = {str(A): {}}
    assert plans.plan_for(A).code == "owner"


# ── AI schema'lari ─────────────────────────────────────────────────────────────
def test_schemas_only_for_connected_users_in_private(mt):
    assert tools.schemas_for(C) == []
    connect(A)
    assert tools.schemas_for(A) == tools.ALL_TOOLS and len(tools.ALL_TOOLS) == 8
    assert tools.schemas_for(A, is_group=True) == []


def test_connect_hint_only_when_relevant(mt):
    assert "/instagram" in tools.connect_hint(C, "instagramga post qo'y")
    assert tools.connect_hint(C, "ob-havo qanday") == ""
    connect(A)
    assert tools.connect_hint(A, "instagramga post qo'y") == ""


# ── webhook yo'naltirish ───────────────────────────────────────────────────────
class Rec:
    """ig.hide_comment / send_private_reply chaqiruvlarida QAYSI token ishlatilganini yozib boradi."""
    def __init__(self, monkeypatch):
        self.hidden, self.replies = [], []

        async def hide(comment_id, hide=True):
            self.hidden.append((ig._acct().token, comment_id))

        async def reply(comment_id, text):
            self.replies.append((ig._acct().token, comment_id, text))

        monkeypatch.setattr(ig, "hide_comment", hide)
        monkeypatch.setattr(ig, "send_private_reply", reply)


def comment_payload(ig_id, cid, text, sender="55"):
    return {"entry": [{"id": ig_id, "changes": [{"field": "comments", "value": {
        "comment_id": cid, "text": text, "from": {"id": sender, "username": "kimdir"}, "media": {"id": "M1"}}}]}]}


def test_webhook_routes_to_the_right_account_and_notifies_owner_only(mt, monkeypatch):
    rec = Rec(monkeypatch)
    connect(A, now=1000); connect(B, now=1000); grant(mt, A, "pro"); grant(mt, B, "pro")
    with ictx.use(accounts.account_for(A)):
        store.add_banned("reklama")
    with ictx.use(accounts.account_for(B)):
        store.add_trigger("narx", "B ning narxi")
    run(wh.process_payload(mt.bot, comment_payload(IGID[A], "c1", "bu reklama")))
    run(wh.process_payload(mt.bot, comment_payload(IGID[B], "c2", "narx qancha?")))
    run(wh.process_payload(mt.bot, comment_payload(IGID[B], "c3", "bu reklama")))   # A ning so'zi B'da YO'Q
    assert rec.hidden == [(TOK[A], "c1")]
    assert rec.replies == [(TOK[B], "c2", "B ning narxi")]
    targets = {chat for chat, _ in mt.bot.sent}
    assert targets == {A, B} and {c for c, t in mt.bot.sent if "yashirildi" in t} == {A}


def test_webhook_ignores_unknown_and_unentitled_accounts(mt, monkeypatch):
    rec = Rec(monkeypatch)
    connect(A)                                                # sinovda: avtomatlashtirish YO'Q
    with ictx.use(accounts.account_for(A)):
        store.add_banned("reklama")
    run(wh.process_payload(mt.bot, comment_payload(IGID[A], "c1", "reklama")))
    run(wh.process_payload(mt.bot, comment_payload("123456", "c2", "reklama")))        # noma'lum akkaunt
    assert rec.hidden == [] and mt.bot.sent == []


def test_webhook_ignores_reauth_account(mt, monkeypatch):
    rec = Rec(monkeypatch)
    connect(A, now=1000); grant(mt, A, "pro")
    with ictx.use(accounts.account_for(A)):
        store.add_banned("reklama")
    accounts.mark_reauth(A)
    run(wh.process_payload(mt.bot, comment_payload(IGID[A], "c1", "reklama")))
    assert rec.hidden == []


def test_webhook_signature_accepts_either_secret(mt, monkeypatch):
    body = b'{"entry":[]}'
    sig = "sha256=" + hmac.new(b"appsecret", body, hashlib.sha256).hexdigest()
    assert ig.verify_signature(body, sig)                      # IG_APP_SECRET bilan
    monkeypatch.setenv("META_APP_SECRET", "other")
    sig2 = "sha256=" + hmac.new(b"other", body, hashlib.sha256).hexdigest()
    assert ig.verify_signature(body, sig2) and not ig.verify_signature(body, "sha256=00")


# ── scheduler ──────────────────────────────────────────────────────────────────
def schedule_entry(uid, when):
    with ictx.use(accounts.account_for(uid)):
        e = store.add_scheduled(kind="POST", caption="cap" + str(uid), when=when, items=[], created_by=uid)
    return e


def test_scheduler_publishes_each_account_with_its_own_token(mt, monkeypatch):
    connect(A, now=1000); connect(B, now=1000); grant(mt, A, "plus"); grant(mt, B, "pro")
    now = datetime.now(common.TASHKENT)
    schedule_entry(A, now - timedelta(minutes=1)); schedule_entry(B, now - timedelta(minutes=1))
    used = []

    async def publish(kind, items, caption=""):
        used.append((ig._acct().token, caption))
        return {"media_id": "m", "permalink": "https://i/p"}

    async def quota():
        return {"used": 0, "total": 100}

    monkeypatch.setattr(ig, "publish", publish); monkeypatch.setattr(ig, "get_quota", quota)
    run(scheduler.tick(mt.bot, now))
    assert sorted(used) == [(TOK[A], f"cap{A}"), (TOK[B], f"cap{B}")]
    assert {c for c, _ in mt.bot.sent} == {A, B}


def test_scheduler_fails_due_post_when_plan_lost(mt, monkeypatch):
    connect(A)                                                # sinov — rejalashtirish tarifda yo'q
    now = datetime.now(common.TASHKENT)
    e = schedule_entry(A, now - timedelta(minutes=1))
    called = []
    monkeypatch.setattr(ig, "publish", lambda *a, **k: called.append(1))
    run(scheduler.tick(mt.bot, now))
    with ictx.use(accounts.account_for(A)):
        assert store.get_scheduled(e["id"])["status"] == "failed"
    assert not called and any("tarif" in t for _, t in mt.bot.sent)


def test_scheduler_fails_due_post_for_reauth_account(mt, monkeypatch):
    connect(A, now=1000); grant(mt, A, "pro")
    now = datetime.now(common.TASHKENT)
    e = schedule_entry(A, now - timedelta(minutes=1))
    accounts.mark_reauth(A)
    called = []
    monkeypatch.setattr(ig, "publish", lambda *a, **k: called.append(1))
    run(scheduler.tick(mt.bot, now))
    with ictx.use(accounts.account_for(A) or accounts.iter_accounts()[0][1]):
        assert store.get_scheduled(e["id"])["status"] == "failed"
    assert not called and any("uzilgan" in t for _, t in mt.bot.sent)


# ── DM: Plus kunlik chegarasi ──────────────────────────────────────────────────
def test_plus_dm_daily_cap(mt, monkeypatch):
    connect(A, now=1000); grant(mt, A, "plus")
    monkeypatch.setenv("IG_PLUS_DM_DAILY", "2")
    sent = []

    async def send_dm(to, text):
        sent.append(text); return f"mid{len(sent)}"

    async def llm(system, history):
        return "javob"

    async def typing(to):
        pass

    monkeypatch.setattr(ig, "send_dm", send_dm); monkeypatch.setattr(ig, "typing_on", typing)
    monkeypatch.setattr(dm, "_llm", llm); monkeypatch.setattr(dm, "ECHO_GRACE", 0)
    clock = {"t": 1_800_000_000.0}
    monkeypatch.setattr(dm, "_now", lambda: clock["t"])
    acct = accounts.account_for(A)
    with ictx.use(acct, plans.plan_for(A, acct)):
        st = store.dm_state(); st["mode"], st["instructions"] = "auto", "Do'kon. Narx 10 000."
    for i, who in enumerate(("11", "12", "13", "14")):
        ev = {"sender": {"id": who}, "recipient": {"id": IGID[A]},
              "message": {"mid": f"m{i}", "text": "salom"}}
        run(wh.process_payload(mt.bot, {"entry": [{"id": IGID[A], "messaging": [ev]}]}))
    replies = [t for t in sent if t == "javob"]
    assert len(replies) == 2                                   # 3-4-mijozga javob ketmadi
    assert any("kunlik AI javob limiti" in t for _, t in mt.bot.sent)


# ── token yangilash ────────────────────────────────────────────────────────────
def test_refresh_selects_only_aged_expiring_tokens(mt):
    now = 10_000_000
    connect(A, now=now - 55 * 86400)                          # 5 kun qolgan, 55 kunlik -> yangilanadi
    connect(B, now=now - 3600)                                # yangi (1 soat) -> hali emas
    assert accounts.due_for_refresh(now) == [A]


def test_refresh_due_updates_token_and_handles_permanent_failure(mt, monkeypatch):
    now = time.time()
    connect(A, now=now - 55 * 86400); connect(B, now=now - 55 * 86400)

    async def refresh(token):
        if token == TOK[B]:
            raise oauth.OAuthError("bekor", permanent=True)
        return "NEW-" + token, 5_184_000

    monkeypatch.setattr(oauth, "refresh_token", refresh)
    assert run(oauth.refresh_due(mt.bot)) == 1
    assert accounts.account_for(A).token == "NEW-" + TOK[A] and accounts.status(A) == "ok"
    assert accounts.status(B) == "reauth" and accounts.account_for(B) is None
    assert any(c == B and "eskirdi" in t for c, t in mt.bot.sent)         # faqat B ga xabar


def test_transient_refresh_failure_keeps_account_ok(mt, monkeypatch):
    now = time.time(); connect(A, now=now - 55 * 86400)

    async def refresh(token):
        raise oauth.OAuthError("tarmoq", permanent=False)

    monkeypatch.setattr(oauth, "refresh_token", refresh)
    run(oauth.refresh_due(mt.bot))
    assert accounts.status(A) == "ok"


def test_expired_unrefreshed_token_requires_reauth(mt):
    connect(A, now=time.time() - 61 * 86400)
    assert accounts.expired() == [A]


def test_error_190_marks_account_reauth(mt, monkeypatch):
    connect(A, now=1000)
    acct = accounts.account_for(A)

    class Resp:
        status_code, content, text = 400, b"x", "x"
        def json(self): return {"error": {"code": 190, "message": "Invalid OAuth access token"}}

    class Client:
        def __init__(self, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def request(self, *a, **k): return Resp()

    monkeypatch.setattr(ig.httpx, "AsyncClient", Client)
    with ictx.use(acct):
        with pytest.raises(ig.InstagramAPIError) as ei:
            run(ig._request("GET", "/me"))
    assert accounts.status(A) == "reauth" and "TOKEN-AAA" not in str(ei.value)


# ── Meta: deauth / data deletion ───────────────────────────────────────────────
def signed(payload: dict, secret="appsecret") -> str:
    p = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    s = base64.urlsafe_b64encode(hmac.new(secret.encode(), p.encode(), hashlib.sha256).digest()).decode().rstrip("=")
    return f"{s}.{p}"


class Req:
    def __init__(self, form=None, query=None):
        self._form, self.query = form or {}, query or {}

    async def post(self):
        return self._form


def test_signed_request_parsing(mt):
    assert oauth.parse_signed_request(signed({"user_id": "9001"}), "appsecret") == {"user_id": "9001"}
    assert oauth.parse_signed_request(signed({"user_id": "9001"}, secret="wrong"), "appsecret") is None
    assert oauth.parse_signed_request("garbage", "appsecret") is None


def test_deauth_disconnects_and_notifies(mt):
    connect(A)
    r = run(oauth._make_deauth(mt.bot)(Req({"signed_request": signed({"user_id": IGID[A]})})))
    assert r.status == 200 and accounts.status(A) == "none"
    assert any(c == A for c, _ in mt.bot.sent)


def test_deauth_rejects_forged_request(mt):
    connect(A)
    r = run(oauth._make_deauth(mt.bot)(Req({"signed_request": signed({"user_id": IGID[A]}, secret="evil")})))
    assert r.status == 400 and accounts.status(A) == "ok"


def test_data_deletion_returns_confirmation_and_wipes(mt):
    connect(A)
    r = run(oauth._make_delete(mt.bot)(Req({"signed_request": signed({"user_id": IGID[A]})})))
    body = json.loads(r.text)
    assert accounts.status(A) == "none" and body["confirmation_code"] in body["url"]
    page = run(oauth._delete_status(Req(query={"code": body["confirmation_code"]})))
    assert page.status == 200
    assert run(oauth._delete_status(Req(query={"code": "nope"}))).status == 404


def test_callback_bad_state_and_success(mt, monkeypatch):
    cb = oauth._make_callback(mt.bot)
    assert run(cb(Req(query={"code": "c", "state": "bad"}))).status == 400
    assert run(cb(Req(query={"error": "access_denied"}))).status == 200
    fake_meta(monkeypatch)
    r = run(cb(Req(query={"code": "CODE#_", "state": oauth.make_state(A)})))
    assert r.status == 200 and accounts.status(A) == "ok"
    assert "LONG-TOKEN" not in r.text                                     # sahifada sir yo'q


def test_privacy_page_served(mt):
    r = run(oauth._privacy(Req()))
    assert r.status == 200 and "7" in r.text and "Privacy Policy" in r.text


# ── /instagram menyusi ─────────────────────────────────────────────────────────
def test_menu_states(mt):
    import handlers.instagram as h
    txt, st = h._status_text(C)
    assert st == "none" and "3 kunlik" in txt and "bepul" in txt.lower()
    kb = h._kb(C, st)
    assert kb.inline_keyboard[0][0].url.startswith("https://www.instagram.com/oauth/authorize")
    connect(A)
    txt, st = h._status_text(A)
    assert st == "ok" and "@user1001" in txt and "Bepul sinov" in txt and "qolgan vaqt" in txt
    connect(B, now=1000)
    txt, st = h._status_text(B)
    assert "tugagan" in txt
    accounts.mark_reauth(A)
    txt, st = h._status_text(A)
    assert st == "reauth" and "Qayta ulang" in txt


def test_menu_hides_connect_button_when_trial_used(mt):
    import handlers.instagram as h
    connect(A, now=1000); accounts.disconnect(A)
    txt, st = h._status_text(A)
    kb = h._kb(A, st)
    assert st == "none" and "tugagan" in txt
    assert not any(getattr(b, "url", None) for row in kb.inline_keyboard for b in row)


# ── qo'shimcha: egasi env akkaunti bilan birga + sinovni aylanib o'tish ─────────
def test_webhook_with_owner_env_configured_routes_by_entry_id(mt, monkeypatch):
    monkeypatch.setenv("IG_USER_ID", "7777"); monkeypatch.setenv("IG_ACCESS_TOKEN", "OWNERTOK")
    rec = Rec(monkeypatch)
    connect(A, now=1000); grant(mt, A, "pro")
    with ictx.use(accounts.account_for(A)):
        store.add_banned("reklama")
    with ictx.use(ig.env_account(), plans.OWNER):
        store.add_banned("reklama")
    run(wh.process_payload(mt.bot, comment_payload(IGID[A], "c1", "reklama")))      # foydalanuvchi akkaunti
    run(wh.process_payload(mt.bot, comment_payload("7777", "c2", "reklama")))       # egasi akkaunti
    assert rec.hidden == [(TOK[A], "c1"), ("OWNERTOK", "c2")]
    notified = {c: t for c, t in mt.bot.sent}
    assert set(notified) == {A, 1}                                                   # 1 = superadmin (egasi xabari)


def test_user_cannot_get_new_trial_by_switching_to_another_ig_account(mt):
    now = 3_000_000
    connect(A, now=now)
    accounts.disconnect(A)
    ok, _ = accounts.connect(A, "9100", "boshqa", "TOK-X", 100, now=now + 10 * 86400)
    assert ok and not accounts.trial_active(A, now + 10 * 86400 + 5)
    assert oauth.can_connect(A)[0] is False


def test_switching_account_wipes_old_account_state(mt):
    connect(A)
    with ictx.use(accounts.account_for(A)):
        store.add_trigger("narx", "x")
    ok, _ = accounts.connect(A, "9100", "boshqa", "TOK-X", 100)
    assert ok and IGID[A] not in mt.db.get("instagram_by_account", {})


def test_webhook_enabled_with_only_ig_app_secret(mt, monkeypatch):
    monkeypatch.setenv("IG_WEBHOOK_ENABLED", "1"); monkeypatch.setenv("WEBHOOK_VERIFY_TOKEN", "v")
    assert wh.enabled()                                         # META_APP_SECRET yo'q, IG_APP_SECRET yetarli
    monkeypatch.delenv("IG_APP_SECRET")
    assert not wh.enabled()


def test_menu_survives_missing_public_url(mt, monkeypatch):
    import handlers.instagram as h
    for k in ("IG_PUBLIC_BASE_URL", "WEBHOOK_URL", "PUBLIC_BASE_URL", "RENDER_EXTERNAL_URL"):
        monkeypatch.delenv(k, raising=False)
    kb = h._kb(C, "none")                                       # qulamasligi kerak
    assert not any(getattr(b, "url", None) for row in kb.inline_keyboard for b in row)
    sent = []

    class Msg:
        async def answer(self, text, **kw): sent.append(text)

    run(h._show(Msg(), C))
    assert sent and "sozlanmagan" in sent[0]


def test_scheduler_skips_accounts_without_pending_work(mt, monkeypatch):
    connect(A, now=1000); grant(mt, A, "pro")
    opened = []
    orig = accounts._to_account
    monkeypatch.setattr(accounts, "_to_account", lambda uid, rec: (opened.append(uid), orig(uid, rec))[1])
    run(scheduler.tick(mt.bot, datetime.now(common.TASHKENT)))
    assert opened == []                                          # ish yo'q — token ochilmadi


def test_end_to_end_tool_calls_hit_the_callers_own_account(mt, monkeypatch):
    """Haqiqiy tool (require -> kontekst -> ig._request) orqali: har kim O'Z akkaunti/tokeni bilan so'raydi."""
    monkeypatch.setenv("IG_USER_ID", "7777"); monkeypatch.setenv("IG_ACCESS_TOKEN", "OWNERTOK")
    connect(A, now=1000); grant(mt, A, "plus")
    connect(B, now=1000); grant(mt, B, "pro")
    seen = []

    async def req(method, path, **kw):
        seen.append((path, ig._acct().token))
        return {"data": [{"quota_usage": 1, "config": {"quota_total": 100}}]}

    monkeypatch.setattr(ig, "_request", req)
    for uid in (A, 1, B):                                      # 1 = bot egasi (superadmin)
        run(tools._instagram_quota(uid, {}, {}))
    assert [t for _, t in seen] == [TOK[A], "OWNERTOK", TOK[B]]
    assert IGID[A] in seen[0][0] and "7777" in seen[1][0] and IGID[B] in seen[2][0]
    # begona (ulanmagan) foydalanuvchi — hech narsaga chiqmaydi
    seen.clear()
    r = run(tools._instagram_quota(C, {}, {}))
    assert "error" in r and seen == []
