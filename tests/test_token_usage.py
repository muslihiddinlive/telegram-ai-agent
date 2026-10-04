import asyncio
import datetime as dt
from types import SimpleNamespace

import pytest

import admin.panel as panel
import core.ai_rotator as ai_rotator
import core.roles as roles
import core.scheduler as scheduler
import core.tgdb as tgdb
import core.token_usage as tu
import core.vision as vision
import harness
import main

SUPER = 1
UTC = dt.timezone.utc


def run(coro):
    return asyncio.run(coro)


def at(day, hour=12):
    y, m, d = map(int, day.split("-"))
    return dt.datetime(y, m, d, hour, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setattr(tgdb, "_cache", {"users": {}, "admins": {}})
    monkeypatch.setattr(roles.config, "SUPERADMIN_ID", SUPER)
    monkeypatch.setattr(tu.config, "SUPERADMIN_ID", SUPER)
    tu._report_attempts.clear()
    tu._ctx.set({})


def usage(p, c):
    return SimpleNamespace(prompt_tokens=p, completion_tokens=c, total_tokens=p + c)


def resp(p=None, c=None, model="llama-3.3-70b-versatile", text="javob", tool_calls=None):
    msg = SimpleNamespace(content=text, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=usage(p, c) if p is not None else None, model=model)


def tool_call(name, args="{}"):
    return SimpleNamespace(function=SimpleNamespace(name=name, arguments=args), id="1")


D = "2026-10-03"


# ── yozish ───────────────────────────────────────────────────────────────

def test_record_aggregates_totals_models_purposes_and_scopes():
    tu.set_context(chat_id=-1001, chat_type="supergroup", chat_title="Guruh A", user_id=7, user_name="@ali", purpose="chat")
    tu.record("groq", "llama", 100, 20, now=at(D))
    tu.record("groq", "llama", 50, 10, now=at(D))
    with tu.scope(purpose="vision"):
        tu.record("gemini", "flash", 200, 30, now=at(D))
    agg = tu.day_data(D)["shared"]
    assert (agg["r"], agg["p"], agg["c"]) == (3, 350, 60)
    assert agg["model"]["groq|llama"]["r"] == 2 and agg["model"]["gemini|flash"]["p"] == 200
    assert agg["purpose"]["chat"]["r"] == 2 and agg["purpose"]["vision"]["r"] == 1          # scope() faqat ichida purpose'ni almashtiradi
    assert agg["scope"]["group"]["r"] == 3
    assert agg["chat"]["-1001"]["n"] == "Guruh A" and agg["user"]["7"]["n"] == "@ali"


def test_scope_restores_previous_context_and_private_vs_system():
    tu.set_context(chat_id=55, chat_type="private", user_id=55, purpose="chat")
    with tu.scope(purpose="summary"):
        assert tu.current()["purpose"] == "summary" and tu.current()["chat_id"] == 55
    assert tu.current()["purpose"] == "chat"
    tu.record("groq", "m", 10, 5, now=at(D))
    tu._ctx.set({})
    tu.record("groq", "m", 1, 1, now=at(D))                                                  # kontekstsiz — tizim/fon
    sc = tu.day_data(D)["shared"]["scope"]
    assert sc["private"]["r"] == 1 and sc["system"]["r"] == 1


def test_personal_key_usage_is_separate_from_bot_owner_usage():
    tu.record("openai", "gpt", 100, 10, personal=True, now=at(D))
    tu.record("groq", "m", 40, 5, now=at(D))
    data = tu.day_data(D)
    assert data["personal"]["p"] == 100 and data["shared"]["p"] == 40
    text = "\n".join(tu.build_report(D))
    assert "Jami: 45 token" in text and "Shaxsiy kalitlar" in text and "110 token" in text


def test_tool_tokens_are_split_between_requested_tools():
    tu.record("groq", "m", 100, 20, tools=["create_docx", "remember_note"], now=at(D))
    tool = tu.day_data(D)["shared"]["tool"]
    assert tool["create_docx"]["p"] == 50 and tool["remember_note"]["c"] == 10


def test_negative_or_garbage_values_never_break_recording():
    tu.record("groq", None, -5, "x", now=at(D))
    tu.record("groq", "m", None, None, now=at(D))
    assert tu.day_data(D)["shared"]["p"] == 0


def test_chat_and_user_tables_are_capped_and_overflow_goes_to_others(monkeypatch):
    monkeypatch.setattr(tu, "MAX_CHATS_PER_DAY", 3)
    monkeypatch.setattr(tu, "MAX_USERS_PER_DAY", 2)
    for i in range(6):
        tu.set_context(chat_id=-1000 - i, chat_type="supergroup", chat_title=f"G{i}", user_id=i, user_name=f"u{i}")
        tu.record("groq", "m", 10, 0, now=at(D))
    agg = tu.day_data(D)["shared"]
    assert len(agg["chat"]) == 4 and tu.OTHERS in agg["chat"] and agg["chat"][tu.OTHERS]["r"] == 3
    assert len(agg["user"]) == 3 and agg["user"][tu.OTHERS]["r"] == 4
    assert agg["r"] == 6 and sum(v["r"] for v in agg["chat"].values()) == 6                   # jami hisob yo'qolmaydi


def test_old_days_are_pruned_to_retention_window():
    for i in range(1, tu.RETENTION_DAYS + 4):
        tu.record("groq", "m", 1, 1, now=at(f"2026-09-{i:02d}"))
    days = sorted(tgdb.get()["token_usage"])
    assert len(days) == tu.RETENTION_DAYS and days[-1] == f"2026-09-{tu.RETENTION_DAYS + 3:02d}"


def test_usage_extraction_openai_anthropic_missing():
    assert tu.usage_from_response(resp(120, 30)) == (120, 30, False)
    assert tu.usage_from_response(SimpleNamespace(usage={"input_tokens": 7, "output_tokens": 3})) == (7, 3, False)
    assert tu.usage_from_response(SimpleNamespace(usage=SimpleNamespace(input_tokens=9, output_tokens=1))) == (9, 1, False)
    assert tu.usage_from_response(SimpleNamespace(usage=SimpleNamespace(total_tokens=50))) == (50, 0, False)
    assert tu.usage_from_response(resp()) == (0, 0, True) and tu.usage_from_response({"usage": None}) == (0, 0, True)


def test_missing_usage_is_estimated_and_flagged():
    tu.record_response("xkiro", resp(), est_prompt_text="a" * 400, est_completion_text="b" * 80)
    agg = tu.day_data(tu._day())["shared"]
    assert (agg["p"], agg["c"], agg["est"]) == (100, 20, 1)
    assert "taxminiy" in "\n".join(tu.build_report(tu._day()))


# ── rotator va vision haqiqiy yo'llari ───────────────────────────────────

class FakeRotator:
    available = True

    async def next_key(self):
        return "k"

    def mark_rate_limited(self, key):
        pass


def make_ai(monkeypatch, responses):
    a = ai_rotator.MultiProviderAI()
    a.rotators = {"groq": FakeRotator()}
    a.priority = ["groq"]
    calls = []

    async def fake_call(provider, key, messages, tools):
        calls.append(provider)
        return responses.pop(0)

    monkeypatch.setattr(a, "_call", fake_call)
    return a


def test_rotator_records_each_successful_call_with_context_and_tools(monkeypatch):
    a = make_ai(monkeypatch, [resp(500, 50, tool_calls=[tool_call("create_docx"), tool_call("create_pdf")]), resp(300, 100)])
    tu.set_context(chat_id=-1001, chat_type="supergroup", chat_title="Guruh A", user_id=7, user_name="@ali", purpose="chat")
    run(a.chat([{"role": "user", "content": "salom"}], tools=[{"type": "function"}]))
    run(a.chat([{"role": "user", "content": "yana"}]))
    agg = tu.day_data(tu._day())["shared"]
    assert (agg["r"], agg["p"], agg["c"]) == (2, 800, 150) and agg["chat"]["-1001"]["r"] == 2
    assert agg["tool"]["create_docx"]["p"] == 250 and agg["model"]["groq|llama-3.3-70b-versatile"]["r"] == 2


def test_rotator_counts_tokens_even_when_provider_output_is_rejected_and_retried(monkeypatch):
    bad = resp(100, 10, text="could not execute tool: expected array, got string")
    a = ai_rotator.MultiProviderAI()
    a.rotators = {"groq": FakeRotator(), "openai": FakeRotator()}
    a.priority = ["groq", "openai"]
    seq = [bad, resp(200, 20)]

    async def fake_call(provider, key, messages, tools):
        return seq.pop(0)

    monkeypatch.setattr(a, "_call", fake_call)
    run(a.chat([{"role": "user", "content": "x"}], tools=[{"type": "function"}]))
    agg = tu.day_data(tu._day())["shared"]
    assert agg["r"] == 2 and agg["p"] == 300                                                  # rad etilgan chaqiruv tokeni ham sarflangan


def test_failed_calls_record_nothing(monkeypatch):
    a = ai_rotator.MultiProviderAI()
    a.rotators = {"groq": FakeRotator()}
    a.priority = ["groq"]

    async def boom(*args):
        raise RuntimeError("429")

    monkeypatch.setattr(a, "_call", boom)
    with pytest.raises(ai_rotator.AllKeysExhaustedError):
        run(a.chat([{"role": "user", "content": "x"}]))
    assert tu.day_data(tu._day()) == {}


def test_personal_key_calls_are_recorded_as_personal(monkeypatch):
    import core.user_api_keys as user_api_keys
    monkeypatch.setattr(user_api_keys, "get_any_personal_key", lambda uid: ("openai", "sk-own"))
    a = make_ai(monkeypatch, [resp(70, 7, model="gpt-4o-mini")])
    run(a.chat([{"role": "user", "content": "x"}], user_id=5))
    data = tu.day_data(tu._day())
    assert data["personal"]["p"] == 70 and "shared" not in data


def test_anthropic_fake_response_carries_usage(monkeypatch):
    r = ai_rotator._FakeResponse([], usage={"input_tokens": 11, "output_tokens": 4}, model="claude-x")
    assert tu.usage_from_response(r) == (11, 4, False)


def test_vision_providers_record_usage_as_vision(monkeypatch):
    tu.set_context(chat_id=55, chat_type="private", user_id=55, purpose="chat")

    class Comp:
        async def create(self, **kw):
            return resp(900, 40, model=kw["model"], text="rasm tavsifi")

    class FakeClient:
        def __init__(self, *a, **k):
            self.chat = SimpleNamespace(completions=Comp())

    import sys
    import types
    fake_openai = types.ModuleType("openai")
    fake_openai.AsyncOpenAI = FakeClient
    monkeypatch.setitem(sys.modules, "openai", fake_openai)
    monkeypatch.setattr(vision.shared_keys, "get_vision_model", lambda p: "gpt-4o-mini")
    with tu.scope(purpose="vision"):
        out = run(vision._call_openai_like("openai", "k", [b"x"], "tasvirla"))
    assert out == "rasm tavsifi"
    agg = tu.day_data(tu._day())["shared"]
    assert agg["purpose"]["vision"]["p"] == 900 and agg["chat"]["55"]["r"] == 1               # vision tokeni shu chatga yozildi


def test_gemini_usage_metadata_is_parsed(monkeypatch):
    class R:
        status_code = 200
        text = ""

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "salom"}]}}],
                    "usageMetadata": {"promptTokenCount": 321, "candidatesTokenCount": 12}}

    class C:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            return R()

    monkeypatch.setattr(vision.httpx, "AsyncClient", C)
    monkeypatch.setattr(vision.shared_keys, "get_vision_model", lambda p: "gemini-2.5-flash")
    assert run(vision._call_gemini("k", [b"x"], "p")) == "salom"
    agg = tu.day_data(tu._day())["shared"]
    assert (agg["p"], agg["c"]) == (321, 12) and agg["model"]["gemini|gemini-2.5-flash"]["r"] == 1


# ── hisobot mazmuni ──────────────────────────────────────────────────────

def seed_day():
    for chat, title, user, uname, p, c, purpose, tools in [
        (-1001, "Katta guruh", 7, "@ali", 6000, 1000, "chat", ["create_docx"]),
        (-1001, "Katta guruh", 8, "@vali", 1000, 500, "chat", None),
        (-1002, "Kichik <b>guruh</b>", 7, "@ali", 300, 100, "reaction", None),
        (55, "Ali", 55, "Ali", 200, 50, "vision", None),
    ]:
        tu.set_context(chat_id=chat, chat_type="supergroup" if chat < 0 else "private", chat_title=title, user_id=user,
                       user_name=uname, purpose=purpose)
        tu.record("groq", "llama", p, c, tools=tools, now=at(D))


def test_report_has_all_requested_sections_and_numbers():
    seed_day()
    text = "\n".join(tu.build_report(D))
    total = 6000 + 1000 + 1000 + 500 + 300 + 100 + 200 + 50
    assert f"Jami: {tu._n(total)} token" in text and "4 so'rov" in text
    assert "Qaysi provayder/model" in text and "groq · llama" in text
    assert "Nimaga ketdi" in text and "Suhbat (AI javoblari)" in text and "Avto-reaksiya" in text and "Rasm/video o'qish" in text
    assert "Qayerda" in text and "guruhlar" in text and "shaxsiy chat" in text
    assert "Eng ko'p sarflangan joy" in text and "Katta guruh" in text and "-1001" in text
    assert "Top guruh/chatlar" in text and "Eng ko'p ishlatgan foydalanuvchilar" in text and "@ali" in text
    assert "tool'lar" in text and "create_docx" in text
    top_line = [l for l in text.split("\n") if "Eng ko'p sarflangan joy" in l][0]
    assert "8 500" in top_line and "<b>" in top_line                                           # 6000+1000+1000+500


def test_names_are_html_escaped_in_report():
    seed_day()
    text = "\n".join(tu.build_report(D))
    assert "Kichik &lt;b&gt;guruh&lt;/b&gt;" in text and "Kichik <b>guruh</b>" not in text


def test_report_compares_with_previous_day():
    tu.record("groq", "m", 1000, 0, now=at("2026-10-02"))
    tu.record("groq", "m", 1500, 0, now=at(D))
    assert "▲ 50%" in "\n".join(tu.build_report(D, "2026-10-02"))
    tu.record("groq", "m", 400, 0, now=at("2026-10-04"))
    assert "▼ 73%" in "\n".join(tu.build_report("2026-10-04", D))


def test_empty_day_and_long_report_splitting():
    assert "AI so'rovlari bo'lmagan" in tu.build_report("2000-01-01")[0]
    for i in range(100):
        tu.set_context(chat_id=-2000 - i, chat_type="supergroup", chat_title="G" * 40 + str(i), user_id=i, user_name="U" * 30)
        tu.record("p" + str(i % 3), "model-" + str(i), 1000 + i, 100, tools=[f"tool_{i}"], now=at(D))
    chunks = tu.build_report(D)
    assert all(len(c) <= 4096 for c in chunks)
    assert "Jami" in chunks[0]


# ── 00:00 UTC da yuborish ────────────────────────────────────────────────

class ReportBot:
    def __init__(self, fail_times=0):
        self.sent, self.fail_times = [], fail_times

    async def send_message(self, chat_id, text, **kw):
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("blocked")
        self.sent.append((chat_id, text))


def test_first_run_only_sets_marker_no_empty_report():
    bot = ReportBot()
    assert run(tu.send_daily_report(bot, now=at("2026-10-04", 14))) is False and bot.sent == []
    assert tgdb.get()["token_usage_meta"]["last_report"] == "2026-10-03"


def test_report_for_yesterday_sent_once_after_midnight_utc():
    tu.record("groq", "m", 100, 10, now=at("2026-10-03"))
    tgdb.get()["token_usage_meta"] = {"last_report": "2026-10-02"}
    bot = ReportBot()
    assert run(tu.send_daily_report(bot, now=at("2026-10-03", 23))) is False                  # hali o'sha kun — kecha 10-02 allaqachon yuborilgan
    assert bot.sent == []
    assert run(tu.send_daily_report(bot, now=dt.datetime(2026, 10, 4, 0, 0, 30, tzinfo=UTC))) is True
    assert len(bot.sent) == 1 and bot.sent[0][0] == SUPER and "2026-10-03" in bot.sent[0][1] and "Jami: 110 token" in bot.sent[0][1]
    assert run(tu.send_daily_report(bot, now=at("2026-10-04", 5))) is False and len(bot.sent) == 1     # ikkinchi marta yuborilmaydi


def test_late_start_still_delivers_and_missed_days_dont_flood():
    tu.record("groq", "m", 5, 5, now=at("2026-10-03"))
    tgdb.get()["token_usage_meta"] = {"last_report": "2026-09-28"}                             # bot bir necha kun o'chiq bo'lgan
    bot = ReportBot()
    assert run(tu.send_daily_report(bot, now=at("2026-10-04", 3))) is True
    assert len(bot.sent) == 1 and tgdb.get()["token_usage_meta"]["last_report"] == "2026-10-03"       # faqat kecha uchun bitta hisobot


def test_failed_delivery_is_retried_then_given_up(monkeypatch):
    tu.record("groq", "m", 5, 5, now=at("2026-10-03"))
    tgdb.get()["token_usage_meta"] = {"last_report": "2026-10-02"}
    bot = ReportBot(fail_times=100)
    now = at("2026-10-04", 1)
    results = [run(tu.send_daily_report(bot, now=now)) for _ in range(tu.REPORT_ATTEMPTS)]
    assert results == [False] * (tu.REPORT_ATTEMPTS - 1) + [True]                              # oxirgi urinishdan keyin tashlab ketiladi
    assert tgdb.get()["token_usage_meta"]["last_report"] == "2026-10-03"
    assert run(tu.send_daily_report(bot, now=now)) is False                                     # qayta urinmaydi


def test_failure_then_success_marks_sent():
    tu.record("groq", "m", 5, 5, now=at("2026-10-03"))
    tgdb.get()["token_usage_meta"] = {"last_report": "2026-10-02"}
    bot = ReportBot(fail_times=1)
    assert run(tu.send_daily_report(bot, now=at("2026-10-04", 1))) is False and bot.sent == []
    assert run(tu.send_daily_report(bot, now=at("2026-10-04", 1))) is True and len(bot.sent) == 1


def test_scheduler_calls_report_each_cycle_and_survives_its_errors(monkeypatch):
    calls = []

    async def boom(bot):
        calls.append(1)
        raise RuntimeError("x")

    monkeypatch.setattr(scheduler.token_usage, "send_daily_report", boom)

    async def one_cycle():
        async def stop(_):
            raise asyncio.CancelledError

        monkeypatch.setattr(scheduler.asyncio, "sleep", stop)
        with pytest.raises(asyncio.CancelledError):
            await scheduler.run_forever(None)

    run(one_cycle())
    assert calls == [1]                                                                         # xato tsiklni o'ldirmadi (sleep'gacha yetdi)


# ── panel ────────────────────────────────────────────────────────────────

def pcall(uid, data):
    edits, answers = [], []

    async def edit_text(text, reply_markup=None, **kw):
        edits.append((text, reply_markup))

    async def answer(text, reply_markup=None, **kw):
        answers.append(text)

    async def call_answer(text=None, show_alert=False):
        pass

    return SimpleNamespace(from_user=SimpleNamespace(id=uid), data=data, answer=call_answer,
                           message=SimpleNamespace(edit_text=edit_text, answer=answer), edits=edits, answers=answers)


def test_panel_token_report_is_superadmin_only_and_shows_today_or_yesterday():
    c = pcall(7, "panel:tokens:today")
    run(panel.show_tokens(c))
    assert c.edits == []
    tu.record("groq", "m", 100, 10)
    c = pcall(SUPER, "panel:tokens:today")
    run(panel.show_tokens(c))
    assert "hozirgacha" in c.edits[0][0] and "Jami: 110 token" in c.edits[0][0]
    c = pcall(SUPER, "panel:tokens:yesterday")
    run(panel.show_tokens(c))
    assert "AI so'rovlari bo'lmagan" in c.edits[0][0]
    assert "panel:tokens:today" in [b.callback_data for r in panel.main_menu_kb(SUPER).inline_keyboard for b in r]
    assert "panel:tokens:today" not in [b.callback_data for r in panel.main_menu_kb(2).inline_keyboard for b in r]


# ── butun yo'l: haqiqiy dispatcher → ai_chat → rotator → hisob ───────────

def test_group_message_end_to_end_is_attributed_to_that_group_and_user(monkeypatch):
    import core.bot_identity as bot_identity
    import core.chat_mode as chat_mode
    bot_identity.set_username(harness.BOT_USERNAME)
    bot_identity.set_id(harness.BOT_ID)

    async def nosave(bot, force=False):
        return None

    monkeypatch.setattr(tgdb, "save", nosave)
    from core.ai_rotator import ai
    monkeypatch.setattr(ai, "rotators", {"groq": FakeRotator()})
    monkeypatch.setattr(ai, "priority", ["groq"])

    async def fake_call(provider, key, messages, tools):
        return resp(1234, 56, text="Salom!")

    monkeypatch.setattr(ai, "_call", fake_call)
    tgdb.get()["users"]["77"] = {"role": "approved", "daily_limit": 50, "requests_today": 0, "last_reset": roles.today_str(),
                                 "name": "Ali", "username": "ali77"}
    run(chat_mode.enable(None, -1009, SUPER, vip=True)) if asyncio.iscoroutinefunction(chat_mode.enable) else chat_mode.enable(None, -1009, SUPER, vip=True)
    bot = harness.make_bot()
    run(main.dp.feed_update(bot, harness.message_update(1, -1009, 77, "salom bot", chat_type="supergroup", message_id=5)))
    day = tu.day_data(tu._day())
    agg = day.get("shared")
    assert agg and agg["p"] == 1234 and agg["c"] == 56
    assert "-1009" in agg["chat"] and "77" in agg["user"] and agg["purpose"]["chat"]["r"] >= 1 and agg["scope"]["group"]["r"] >= 1
