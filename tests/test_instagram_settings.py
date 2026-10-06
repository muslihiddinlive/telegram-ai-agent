"""Instagram ilova kalitlari (IG_APP_ID / IG_APP_SECRET): paneldan yoki env'dan; dinamik yoqilish; superadmin paneli."""
import asyncio
import hashlib
import hmac
import json
from types import SimpleNamespace

import pytest
from aiohttp import web

import admin.panel as panel
import core.bot_commands as bot_commands
import core.instagram_accounts as accounts
import core.instagram_api as ig
import core.instagram_context as ictx
import core.instagram_oauth as oauth
import core.instagram_scheduler as scheduler
import core.instagram_settings as settings
import core.instagram_webhook as wh
import core.pending_input as pending_input
import core.roles as roles
import core.tgdb as tgdb
import handlers.pending_text as pt

ID1, SECRET1 = "123456789012345", "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
ID2, SECRET2 = "999888777666555", "ffeeddccbbaa99887766554433221100"
SUPER, ADMIN, STRANGER = 1, 500, 123          # SUPERADMIN_ID = 1 (conftest)


def run(coro):
    return asyncio.run(coro)


class FakeBot:
    def __init__(self):
        self.commands = []

    async def set_my_commands(self, commands, scope=None):
        self.commands.append(([c.command for c in commands], type(scope).__name__, getattr(scope, "chat_id", None)))

    async def delete_my_commands(self, scope=None):
        pass


@pytest.fixture
def st(monkeypatch):
    for k in ("IG_APP_ID", "IG_APP_SECRET", "META_APP_SECRET", "IG_USER_ID", "IG_ACCESS_TOKEN",
              "WEBHOOK_URL", "PUBLIC_BASE_URL", "RENDER_EXTERNAL_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("IG_PUBLIC_BASE_URL", "https://bot.example.com")
    db = {"users": {}, "admins": {}}
    monkeypatch.setattr(tgdb, "_cache", db)
    saves = []

    async def save(bot, force=False):
        saves.append(force)

    monkeypatch.setattr(tgdb, "save", save)
    monkeypatch.setattr(tgdb, "mark_dirty", lambda: None)
    pending_input._pending.clear()
    ictx.set_current(None)
    yield SimpleNamespace(db=db, saves=saves, bot=FakeBot())
    pending_input._pending.clear()
    ictx.set_current(None)


def panel_set(st, id_=ID1, secret=SECRET1):
    assert run(settings.set_app_id(st.bot, id_))[0]
    assert run(settings.set_app_secret(st.bot, secret))[0]


# ── manba va juftlik qoidasi ───────────────────────────────────────────────────
def test_nothing_configured_by_default(st):
    assert not settings.configured() and settings.source() == "" and settings.app_secret() == ""
    assert not ictx.multi_enabled()


def test_env_pair(st, monkeypatch):
    monkeypatch.setenv("IG_APP_ID", ID1); monkeypatch.setenv("IG_APP_SECRET", SECRET1)
    assert settings.configured() and settings.source() == "env"
    assert (settings.app_id(), settings.app_secret()) == (ID1, SECRET1) and ictx.multi_enabled()


def test_panel_pair_overrides_env(st, monkeypatch):
    monkeypatch.setenv("IG_APP_ID", ID1); monkeypatch.setenv("IG_APP_SECRET", SECRET1)
    panel_set(st, ID2, SECRET2)
    assert settings.source() == "panel" and (settings.app_id(), settings.app_secret()) == (ID2, SECRET2)


def test_pairs_are_never_mixed(st, monkeypatch):
    """Panelda faqat App ID bo'lsa, u env'ning App Secret'i bilan JUFTLANMAYDI (boshqa ilova -> yaroqsiz juft)."""
    monkeypatch.setenv("IG_APP_ID", ID1); monkeypatch.setenv("IG_APP_SECRET", SECRET1)
    run(settings.set_app_id(st.bot, ID2))
    assert settings.source() == "env" and settings.app_id() == ID1 and settings.app_secret() == SECRET1
    monkeypatch.delenv("IG_APP_ID"); monkeypatch.delenv("IG_APP_SECRET")
    assert not settings.configured()                           # panelda yarim juft + env yo'q = o'chiq


def test_secret_is_encrypted_at_rest(st):
    panel_set(st)
    assert st.db["ig_settings"]["app_secret"] != SECRET1 and SECRET1 not in json.dumps(st.db)
    assert settings.app_secret() == SECRET1 and all(st.saves)  # force=True bilan darhol saqlandi


def test_changing_app_id_drops_old_secret(st):
    panel_set(st)
    run(settings.set_app_id(st.bot, ID1))                      # o'sha ID — Secret saqlanadi
    assert settings.app_secret() == SECRET1
    run(settings.set_app_id(st.bot, ID2))                      # boshqa ilova — eski Secret mos emas
    assert "app_secret" not in st.db["ig_settings"] and not settings.configured()


@pytest.mark.parametrize("bad", ["", "abc", "1234", "12345678901234567890123", "123 456 789 012", "12345678x"])
def test_app_id_validation(st, bad):
    ok, why = run(settings.set_app_id(st.bot, bad))
    assert not ok and "App ID" in why and "ig_settings" not in st.db


@pytest.mark.parametrize("bad", ["", "short", "with space inside 0123456789abcdef", "x" * 65, "abc-def-ghi-jkl-mno-pqr-stu"])
def test_app_secret_validation(st, bad):
    ok, why = run(settings.set_app_secret(st.bot, bad))
    assert not ok and "Secret" in why and "ig_settings" not in st.db


def test_values_are_stripped(st):
    assert run(settings.set_app_id(st.bot, f"  {ID1}\n"))[0] and st.db["ig_settings"]["app_id"] == ID1


def test_clear_falls_back_to_env(st, monkeypatch):
    monkeypatch.setenv("IG_APP_ID", ID1); monkeypatch.setenv("IG_APP_SECRET", SECRET1)
    panel_set(st, ID2, SECRET2)
    assert run(settings.clear(st.bot)) and settings.source() == "env"
    assert run(settings.clear(st.bot)) is False


def test_undecryptable_secret_does_not_crash(st, monkeypatch):
    panel_set(st)
    import core.crypto_store as cs
    monkeypatch.setattr(cs, "decrypt", lambda v: (_ for _ in ()).throw(ValueError("kalit almashgan")))
    assert settings.app_secret() == "" and settings.status()["secret"] == ""


def test_status_never_reveals_secret(st):
    panel_set(st)
    s = settings.status()
    assert SECRET1 not in json.dumps(s) and ID1 not in json.dumps(s) and s["configured"] and s["source"] == "panel"


# ── dinamik yoqilish: hamma joy yangi qiymatni ko'radi ──────────────────────────
def test_everything_follows_panel_values(st, monkeypatch):
    assert not ictx.multi_enabled() and oauth._app_id() == ""
    panel_set(st)
    assert ictx.multi_enabled() and oauth._app_id() == ID1 and oauth._app_secret() == SECRET1
    body = b'{"entry":[]}'
    sig = "sha256=" + hmac.new(SECRET1.encode(), body, hashlib.sha256).hexdigest()
    assert ig.verify_signature(body, sig)                       # webhook imzosi panel Secret'i bilan tekshiriladi
    monkeypatch.setenv("IG_WEBHOOK_ENABLED", "1"); monkeypatch.setenv("WEBHOOK_VERIFY_TOKEN", "v")
    assert wh.enabled()
    run(settings.clear(st.bot))
    assert not ictx.multi_enabled() and not wh.enabled() and not ig.verify_signature(body, sig)


def test_authorize_url_and_code_exchange_use_panel_credentials(st, monkeypatch):
    from urllib.parse import parse_qs, urlparse
    panel_set(st)
    assert parse_qs(urlparse(oauth.authorize_url(77)).query)["client_id"] == [ID1]
    sent = {}

    async def http(method, url, *, data=None, params=None):
        sent.update(data or {})
        return {"access_token": "T", "user_id": "9"}

    monkeypatch.setattr(oauth, "_http", http)
    run(oauth.exchange_code("CODE"))
    assert sent["client_id"] == ID1 and sent["client_secret"] == SECRET1


# ── OAuth yo'llari: har doim ro'yxatda, lekin yoqilgan bo'lsagina ishlaydi ──────
class Req:
    def __init__(self, query=None, form=None):
        self.query, self._form = query or {}, form or {}

    async def post(self):
        return self._form


def test_routes_always_registered_but_guarded(st):
    app = web.Application()
    assert oauth.register(app, FakeBot())
    paths = {r.resource.canonical for r in app.router.routes()}
    assert {"/ig/callback", "/ig/deauth", "/ig/data-deletion", "/ig/privacy", "/ig/data-deletion-status"} <= paths
    handler = oauth._guarded(oauth._make_callback(FakeBot()))
    r = run(handler(Req({"code": "c", "state": "bad"})))
    assert r.status == 404 and "yoqilmagan" in r.text                # kalitlar yo'q — hech narsa bajarilmaydi
    panel_set(st)
    r = run(handler(Req({"code": "c", "state": "bad"})))
    assert r.status == 400                                           # yoqildi — endi haqiqiy tekshiruv (state yaroqsiz)


def test_deauth_and_deletion_are_closed_without_keys(st):
    h = oauth._guarded(oauth._make_deauth(FakeBot()))
    assert run(h(Req(form={"signed_request": "x.y"}))).status == 404


# ── scheduler: kalitlar keyin kiritilsa ham ishga tushadi ──────────────────────
def test_scheduler_loop_starts_idle_and_wakes_when_enabled(st, monkeypatch):
    ticks = []

    async def tick(bot, now=None):
        ticks.append(1)

    async def noop(*a, **k):
        return 0

    monkeypatch.setattr(scheduler, "tick", tick)
    monkeypatch.setattr(scheduler, "CHECK_INTERVAL", 0.01)
    import core.instagram_oauth as o
    monkeypatch.setattr(o, "refresh_due", noop); monkeypatch.setattr(o, "flush_reauth_notices", noop)

    async def main():
        task = asyncio.create_task(scheduler.run_forever(FakeBot()))
        await asyncio.sleep(0.08)
        idle = len(ticks)
        await settings.set_app_id(st.bot, ID1); await settings.set_app_secret(st.bot, SECRET1)   # paneldan yoqildi
        await asyncio.sleep(0.08)
        task.cancel()
        return idle, len(ticks)

    idle, active = run(main())
    assert idle == 0 and active > 0                              # sozlanmaguncha bo'sh, so'ng restartsiz ishlaydi


# ── buyruq menyusi ─────────────────────────────────────────────────────────────
def test_instagram_command_appears_only_when_enabled(st):
    assert "instagram" not in [c.command for c in bot_commands.general_commands()]
    panel_set(st)
    assert "instagram" in [c.command for c in bot_commands.general_commands()]
    assert "panel" in [c.command for c in bot_commands.admin_commands()]


def test_refresh_commands_updates_default_and_admin_menus(st):
    st.db["admins"] = {str(ADMIN): {}}
    panel_set(st)
    run(bot_commands.refresh_commands(st.bot))
    scopes = {(s, cid): names for names, s, cid in st.bot.commands}
    assert "instagram" in scopes[("BotCommandScopeDefault", None)]
    assert "instagram" in scopes[("BotCommandScopeChat", SUPER)] and "panel" in scopes[("BotCommandScopeChat", SUPER)]
    assert ("BotCommandScopeChat", ADMIN) in scopes


# ── panel ──────────────────────────────────────────────────────────────────────
class Msgish:
    def __init__(self):
        self.edits, self.sent = [], []

    async def edit_text(self, text, reply_markup=None):
        self.edits.append((text, reply_markup))

    async def answer(self, text, reply_markup=None):
        self.sent.append(text)


class Call:
    def __init__(self, uid, data=""):
        self.from_user, self.data, self.message, self.answers = SimpleNamespace(id=uid), data, Msgish(), []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))


def test_menu_button_is_superadmin_only(st, monkeypatch):
    monkeypatch.setattr(roles, "is_admin", lambda u: u == ADMIN)
    cb = lambda uid: [b.callback_data for row in panel.main_menu_kb(uid).inline_keyboard for b in row]  # noqa: E731
    assert "panel:ig" in cb(SUPER) and "panel:ig" not in cb(ADMIN)


@pytest.mark.parametrize("handler", ["ig_open", "ig_ask_id", "ig_ask_secret", "ig_clear_ask"])
def test_panel_callbacks_reject_non_superadmin(st, monkeypatch, handler):
    monkeypatch.setattr(roles, "is_admin", lambda u: u == ADMIN)
    for uid in (ADMIN, STRANGER):
        c = Call(uid)
        run(getattr(panel, handler)(c))
        assert c.answers == [("Faqat superadmin", True)] and c.message.edits == [] and c.message.sent == []
        assert pending_input.get(uid) is None


def test_clear_do_rejects_non_superadmin_and_keeps_data(st):
    panel_set(st)
    c = Call(STRANGER)
    run(panel.ig_clear_do(c, st.bot))
    assert c.answers == [("Faqat superadmin", True)] and settings.configured()


def test_panel_view_shows_status_urls_and_no_secret(st):
    c = Call(SUPER)
    run(panel.ig_open(c))
    text = c.message.edits[0][0]
    assert "o'chiq" in text and "https://bot.example.com/ig/callback" in text and "/ig/privacy" in text
    panel_set(st)
    accounts.connect(SUPER + 1000, "9001", "u", "TOKEN", 100)
    text, kb = panel.ig_view()
    assert "yoqilgan (manba: panel)" in text and "Ulangan akkauntlar: <b>1</b>" in text and "tokenlari ishlamay" in text
    assert SECRET1 not in text and ID1 not in text and ID1[:3] in text      # ID niqoblangan, Secret ko'rinmaydi
    assert "panel:ig_clear" in [b.callback_data for row in kb.inline_keyboard for b in row]


def test_panel_view_warns_without_public_url_and_on_partial_pair(st, monkeypatch):
    monkeypatch.delenv("IG_PUBLIC_BASE_URL")
    run(settings.set_app_id(st.bot, ID1))
    text, _ = panel.ig_view()
    assert "IG_PUBLIC_BASE_URL" in text and "juftlik to'liq emas" in text and "o'chiq" in text


# ── kiritish oqimi (pending_text) ──────────────────────────────────────────────
class PMsg:
    def __init__(self, uid, text, bot):
        self.from_user, self.text, self.bot = SimpleNamespace(id=uid), text, bot
        self.chat, self.answers, self.deleted = SimpleNamespace(type="private"), [], False

    async def answer(self, text, reply_markup=None):
        self.answers.append(text)

    async def delete(self):
        self.deleted = True


def send(st, uid, text):
    m = PMsg(uid, text, st.bot)
    run(pt.handle_pending(m))
    return m


def test_full_flow_id_then_secret(st):
    run(panel.ig_ask_id(Call(SUPER)))
    assert pending_input.get(SUPER)["action"] == "ig_set_app_id"
    m = send(st, SUPER, "abc")
    assert "App ID" in m.answers[0] and pending_input.get(SUPER) is not None and not settings.configured()   # qayta so'raydi
    m = send(st, SUPER, ID1)
    assert "Saqlandi" in m.answers[0] and pending_input.get(SUPER) is None and not settings.configured()      # Secret hali yo'q
    run(panel.ig_ask_secret(Call(SUPER)))
    m = send(st, SUPER, SECRET1)
    assert m.deleted and settings.configured() and SECRET1 not in "".join(m.answers)                          # xabar o'chirildi, javobda yo'q
    assert "yoqilgan" in m.answers[0]
    assert any("instagram" in names for names, scope, _ in st.bot.commands)                                   # menyu yangilandi


def test_secret_message_is_deleted_even_when_invalid(st):
    pending_input.set(SUPER, "ig_set_app_secret")
    m = send(st, SUPER, "noto'g'ri secret")
    assert m.deleted and "Secret" in m.answers[0] and not settings.configured()
    assert pending_input.get(SUPER) is not None                  # qayta urinish mumkin


def test_forged_pending_state_cannot_write_settings(st):
    pending_input.set(STRANGER, "ig_set_app_id")                  # oddiy foydalanuvchi uchun qo'lda o'rnatilgan holat
    m = send(st, STRANGER, ID1)
    assert m.answers == ["Ruxsat yo'q."] and "ig_settings" not in st.db and pending_input.get(STRANGER) is None
    pending_input.set(STRANGER, "ig_set_app_secret")
    m = send(st, STRANGER, SECRET1)
    assert m.answers == ["Ruxsat yo'q."] and "ig_settings" not in st.db


def test_clear_flow(st):
    panel_set(st)
    c = Call(SUPER)
    run(panel.ig_clear_ask(c))
    assert "O'CHADI" in c.message.edits[0][0] and settings.configured()          # tasdiq so'raydi, hali o'chmagan
    c = Call(SUPER)
    run(panel.ig_clear_do(c, st.bot))
    assert not settings.configured() and "ig_settings" not in st.db
    assert any("instagram" not in names for names, scope, _ in st.bot.commands[-1:])   # menyudan /instagram olib tashlandi
