import asyncio
from types import SimpleNamespace

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import SendMessage

import admin.panel as panel
import core.admin_messaging as am
import core.pending_input as pending_input
import core.roles as roles
import core.tgdb as tgdb

SUPER, ADMIN, USER = 1, 2, 5


def run(coro):
    return asyncio.run(coro)


class FakeBot:
    def __init__(self, fail=None):
        self.sent = []
        self.fail = fail or {}      # chat_id -> exception yoki [exc, None] (birinchisida xato, keyin muvaffaqiyat)

    async def send_message(self, chat_id, text, **kw):
        f = self.fail.get(chat_id)
        if isinstance(f, list):
            f = f.pop(0) if f else None
        if f:
            raise f
        self.sent.append((chat_id, text))


def forbidden():
    return TelegramForbiddenError(method=SendMessage(chat_id=1, text="x"), message="bot was blocked by the user")


def badreq():
    return TelegramBadRequest(method=SendMessage(chat_id=1, text="x"), message="chat not found")


def flood(sec=1):
    return TelegramRetryAfter(method=SendMessage(chat_id=1, text="x"), message="flood", retry_after=sec)


@pytest.fixture(autouse=True)
def env(monkeypatch):
    data = {"admins": {str(ADMIN): {"name": "adm"}},
            "users": {"1": {}, "2": {}, "5": {"role": "approved"}, "6": {}, "7": {"role": "blocked"}, "8": {}}}
    monkeypatch.setattr(tgdb, "_cache", data)
    monkeypatch.setattr(roles.config, "SUPERADMIN_ID", SUPER)
    monkeypatch.setattr(am, "BROADCAST_DELAY", 0)
    am._admin_sent.clear()
    am._broadcast_active = False
    pending_input._pending.clear()

    async def no_sleep(s):
        pass

    # FAQAT admin_messaging ichidagi sleep o'chiriladi (global asyncio.sleep'ga tegilmaydi — testlar unga tayanadi)
    monkeypatch.setattr(am, "asyncio", SimpleNamespace(sleep=no_sleep))
    return data


# ── ruxsatlar ────────────────────────────────────────────────────────────

def test_permissions():
    assert am.can_message_user(SUPER) and am.can_message_user(ADMIN) and not am.can_message_user(USER)
    assert am.can_broadcast(SUPER) and not am.can_broadcast(ADMIN) and not am.can_broadcast(USER)


def test_broadcast_refused_for_plain_admin_and_user_even_if_called_directly():
    for uid in (ADMIN, USER):
        bot = FakeBot()
        res = run(am.broadcast(bot, uid, "salom"))
        assert "faqat superadmin" in res["error"] and bot.sent == []


def test_dm_refused_for_regular_user():
    bot = FakeBot()
    ok, msg = run(am.send_dm(bot, USER, 6, "salom"))
    assert not ok and msg == "Ruxsat yo'q." and bot.sent == []


# ── bitta foydalanuvchiga ────────────────────────────────────────────────

def test_dm_sent_anonymously_and_escaped():
    bot = FakeBot()
    ok, _ = run(am.send_dm(bot, ADMIN, 6, "Salom <b>&</b> aka"))
    assert ok and bot.sent[0][0] == 6
    text = bot.sent[0][1]
    assert text.startswith("📩 <b>Admin xabari</b>") and "&lt;b&gt;&amp;&lt;/b&gt;" in text
    assert str(ADMIN) not in text and str(SUPER) not in text      # jo'natuvchi ko'rsatilmaydi


@pytest.mark.parametrize("text", ["", "   ", None, "x" * (am.MAX_TEXT + 1)])
def test_dm_validates_text(text):
    bot = FakeBot()
    ok, _ = run(am.send_dm(bot, ADMIN, 6, text))
    assert not ok and bot.sent == []


def test_dm_undeliverable_gives_friendly_message():
    bot = FakeBot(fail={6: forbidden()})
    ok, msg = run(am.send_dm(bot, SUPER, 6, "salom"))
    assert not ok and "bot bloklangan" in msg


def test_admin_hourly_limit_but_not_superadmin(monkeypatch):
    monkeypatch.setattr(am, "ADMIN_MSG_PER_HOUR", 3)
    bot = FakeBot()
    assert all(run(am.send_dm(bot, ADMIN, 6, "x"))[0] for _ in range(3))
    ok, msg = run(am.send_dm(bot, ADMIN, 6, "x"))
    assert not ok and "limiti tugadi" in msg and len(bot.sent) == 3
    assert all(run(am.send_dm(bot, SUPER, 6, "x"))[0] for _ in range(10))


# ── broadcast ────────────────────────────────────────────────────────────

def test_recipients_exclude_sender_and_blocked():
    assert sorted(am.recipients(SUPER)) == [2, 5, 6, 8]


def test_broadcast_counts_failures_by_reason_and_continues():
    bot = FakeBot(fail={5: forbidden(), 8: badreq()})
    res = run(am.broadcast(bot, SUPER, "Yangilik!"))
    assert res == {"total": 4, "sent": 2, "failed": 2, "reasons": {"bot bloklangan": 1, "chat topilmadi": 1}}
    assert sorted(c for c, _ in bot.sent) == [2, 6]
    assert all(t.startswith("📢 <b>E'lon</b>") for _, t in bot.sent)


def test_broadcast_retries_once_after_floodwait():
    bot = FakeBot(fail={5: [flood(2), None]})
    res = run(am.broadcast(bot, SUPER, "salom"))
    assert res["sent"] == 4 and res["failed"] == 0


def test_broadcast_long_floodwait_counts_as_failed():
    bot = FakeBot(fail={5: [flood(am.MAX_RETRY_AFTER + 10)]})
    res = run(am.broadcast(bot, SUPER, "salom"))
    assert res["failed"] == 1 and res["reasons"] == {"flood": 1}


def test_only_one_broadcast_at_a_time():
    async def scenario():
        gate = asyncio.Event()

        class SlowBot(FakeBot):
            async def send_message(self, chat_id, text, **kw):
                await gate.wait()
                await super().send_message(chat_id, text)

        bot = SlowBot()
        first = asyncio.create_task(am.broadcast(bot, SUPER, "bir"))
        await asyncio.sleep(0)
        second = await am.broadcast(bot, SUPER, "ikki")
        gate.set()
        return await first, second

    first, second = run(scenario())
    assert first["sent"] == 4 and "ishlayapti" in second["error"]
    assert am.is_broadcast_active() is False       # tugagach flag tushadi


def test_broadcast_flag_released_after_crash(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(am, "send_one", boom)
    with pytest.raises(RuntimeError):
        run(am.broadcast(FakeBot(), SUPER, "salom"))
    assert am.is_broadcast_active() is False


# ── panel: tugmalar va callback'lar ──────────────────────────────────────

def buttons(kb):
    return [b.callback_data for row in kb.inline_keyboard for b in row]


class FakeMsg:
    def __init__(self):
        self.answers, self.edits = [], []

    async def answer(self, text, **kw):
        self.answers.append((text, kw))

    async def edit_text(self, text, **kw):
        self.edits.append(text)


def make_call(uid, data):
    msg = FakeMsg()
    alerts = []

    async def answer(text=None, show_alert=False):
        alerts.append((text, show_alert))

    return SimpleNamespace(from_user=SimpleNamespace(id=uid), data=data, message=msg, answer=answer, alerts=alerts)


def test_menu_shows_broadcast_to_superadmin_only():
    assert "panel:bc" in buttons(panel.main_menu_kb(SUPER))
    assert "panel:bc" not in buttons(panel.main_menu_kb(ADMIN))


def test_message_button_present_in_user_detail_markup(monkeypatch):
    for uid in (SUPER, ADMIN):
        captured = {}

        class M(FakeMsg):
            async def edit_text(self, text, reply_markup=None, **kw):
                captured["kb"] = reply_markup

        call = make_call(uid, "panel:user_detail:5")
        call.message = M()
        run(panel.user_detail(call))
        assert "panel:msg:5" in buttons(captured["kb"])


def test_message_user_flow_sets_pending_only_for_admins():
    call = make_call(USER, "panel:msg:6")
    run(panel.message_user_start(call))
    assert call.alerts == [("Ruxsat yo'q", True)] and pending_input.get(USER) is None
    call = make_call(ADMIN, "panel:msg:6")
    run(panel.message_user_start(call))
    assert pending_input.get(ADMIN) == {"action": "msg_user_text", "data": {"target_uid": 6}}


def test_broadcast_callbacks_reject_non_superadmin():
    for data, fn in (("panel:bc", panel.broadcast_start),):
        call = make_call(ADMIN, data)
        run(fn(call))
        assert call.alerts == [("Faqat superadmin", True)] and pending_input.get(ADMIN) is None
    # tasdiqlash tugmasini admin soxta holatda bossa ham yuborilmaydi
    pending_input.set(ADMIN, "broadcast_confirm", {"text": "reklama"})
    bot = FakeBot()
    call = make_call(ADMIN, "panel:bc_yes")
    run(panel.broadcast_confirm(call, bot))
    assert call.alerts[0][1] is True and bot.sent == []


def test_confirm_requires_pending_state_and_sends_once_on_double_click():
    async def scenario():
        bot = FakeBot()
        # holat yo'q — hech narsa ketmaydi
        c0 = make_call(SUPER, "panel:bc_yes")
        await panel.broadcast_confirm(c0, bot)
        assert "Muddati" in c0.alerts[0][0] and bot.sent == []
        # normal oqim: ikki marta bosish
        pending_input.set(SUPER, "broadcast_confirm", {"text": "Salom hammaga"})
        c1, c2 = make_call(SUPER, "panel:bc_yes"), make_call(SUPER, "panel:bc_yes")
        await panel.broadcast_confirm(c1, bot)
        await panel.broadcast_confirm(c2, bot)
        await asyncio.gather(*panel._bg_tasks)
        return bot, c2

    bot, c2 = run(scenario())
    broadcast_msgs = [(c, t) for c, t in bot.sent if t.startswith("📢 <b>E'lon</b>")]  # hisobot ("📢 Broadcast tugadi") emas
    assert sorted(c for c, _ in broadcast_msgs) == [2, 5, 6, 8]       # har kimga FAQAT 1 marta
    assert any("Broadcast tugadi" in t and "4 / 4" in t for c, t in bot.sent if c == SUPER)  # hisobot superadminga
    assert c2.alerts[0][0].startswith("Muddati")


def test_cancel_clears_pending_and_panel_command_resets_flow():
    pending_input.set(SUPER, "broadcast_confirm", {"text": "x"})
    call = make_call(SUPER, "panel:bc_no")
    run(panel.broadcast_cancel(call))
    assert pending_input.get(SUPER) is None and "bekor" in call.message.edits[0].lower()

    pending_input.set(SUPER, "msg_user_text", {"target_uid": 6})
    msg = SimpleNamespace(from_user=SimpleNamespace(id=SUPER), answer=FakeMsg().answer)
    run(panel.open_panel(msg))
    assert pending_input.get(SUPER) is None
