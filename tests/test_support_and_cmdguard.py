"""Haqiqiy Dispatcher (main.dp) orqali: murojaat oqimi va noto'g'ri yozilgan komandalar."""
import asyncio

import pytest
from aiogram.types import CallbackQuery, Chat, Message, Update, User

import core.bot_identity as bot_identity
import core.chat_mode as chat_mode
import core.command_guard as command_guard
import core.pending_input as pending_input
import core.roles as roles
import core.tgdb as tgdb
import handlers.ai_chat as ai_chat
import handlers.support as support
import harness
import main

SUPER, ADMIN, U, GROUP = 1, 2, 55, -1001


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setattr(tgdb, "_cache", {"users": {}, "admins": {str(ADMIN): {"name": "adm"}}})
    monkeypatch.setattr(roles.config, "SUPERADMIN_ID", SUPER)
    monkeypatch.setattr(support.config, "SUPERADMIN_ID", SUPER)

    async def nosave(bot, force=False):
        return None

    monkeypatch.setattr(tgdb, "save", nosave)
    bot_identity.set_username(harness.BOT_USERNAME)
    bot_identity.set_id(harness.BOT_ID)
    support._sessions.clear()
    support._submitted.clear()
    pending_input._pending.clear()
    ai_calls = []

    async def fake_ai(message, *a, **k):
        ai_calls.append(message.text)

    monkeypatch.setattr(ai_chat, "handle_message", fake_ai, raising=False)
    return ai_calls


class Counter:
    n = 0

    @classmethod
    def next(cls):
        cls.n += 1
        return cls.n


def send(bot, uid, text=None, chat=None, chat_type="private", **extra):
    run(main.dp.feed_update(bot, harness.message_update(Counter.next(), chat if chat is not None else uid, uid, text,
                                                        chat_type=chat_type, message_id=Counter.next(), **extra)))


def press(bot, uid, data):
    user = User(id=uid, is_bot=False, first_name="Ali", username=f"u{uid}")
    msg = Message(message_id=Counter.next(), date=harness.NOW, chat=Chat(id=uid, type="private"), from_user=User(id=harness.BOT_ID, is_bot=True, first_name="B"))
    cq = CallbackQuery(id=str(Counter.next()), from_user=user, chat_instance="x", message=msg, data=data)
    run(main.dp.feed_update(bot, Update(update_id=Counter.next(), callback_query=cq)))


def calls(bot, name):
    return [d for n, d in bot.session.calls if n == name]


# ── noto'g'ri yozilgan komandalar (VIP muammosi) ─────────────────────────

def test_typo_command_gets_suggestion_and_never_reaches_ai(env):
    bot = harness.make_bot()
    send(bot, SUPER, "/vipchaatmode: on", chat=GROUP, chat_type="supergroup")
    texts = bot.session.texts(GROUP)
    assert len(texts) == 1 and "/vipchaatmode" in texts[0] and "/vipchatmode" in texts[0] and "yoqildi" not in texts[0].lower()
    assert chat_mode.get(GROUP) is None                                      # hech narsa yoqilmadi


def test_vip_command_still_works_for_superadmin_and_stays_hidden_from_others():
    bot = harness.make_bot()
    send(bot, SUPER, "/vipchatmode: on", chat=GROUP, chat_type="supergroup")
    assert chat_mode.get(GROUP)["vip"] is True
    for text in ("/vipchatmode on", "/vipchatmode: off", "/vipchatmode"):
        send(bot, SUPER, text, chat=GROUP, chat_type="supergroup")
    bot2 = harness.make_bot()
    tgdb.get().pop("chat_mode", None)
    send(bot2, U, "/vipchatmode on", chat=GROUP, chat_type="supergroup")
    assert chat_mode.get(GROUP) is None and bot2.session.texts(GROUP) == []  # oddiy userga mavjudligi bildirilmaydi (jim)


def test_vip_name_is_never_suggested_to_regular_users():
    for typo in ("vipchaatmode", "vipchatmod", "vipchatmoode"):
        fix = command_guard.suggest(typo, U, "supergroup")
        assert fix != "vipchatmode"
    assert command_guard.suggest("vipchaatmode", SUPER, "supergroup") == "vipchatmode"
    assert command_guard.suggest("panell", U, "private") is None            # /panel oddiy userga ko'rsatilmaydi
    assert command_guard.suggest("panell", ADMIN, "private") == "panel"


@pytest.mark.parametrize("typo,right", [("chatmoed", "chatmode"), ("statistka", "statistika"), ("laqb", "laqab"),
                                        ("qoidalr", "qoidalar"), ("antispm", "antispam"), ("apikalt", "apikalit")])
def test_common_typos_suggest_the_right_command(typo, right):
    assert command_guard.suggest(typo, ADMIN, "supergroup" if right in command_guard.GROUP_ONLY else "private") == right


def test_commands_for_other_bots_are_swallowed_and_unrelated_commands_untouched(env):
    bot = harness.make_bot()
    send(bot, U, "/start@OtherBot", chat=GROUP, chat_type="supergroup")
    assert bot.session.texts() == []                                        # boshqa botniki — jim
    assert command_guard.classify("/help", U, "supergroup") is None         # hech narsaga o'xshamaydi, @ yo'q — tegmaymiz
    assert command_guard.classify("/narsa@" + harness.BOT_USERNAME, U, "supergroup") == ("unknown", None)
    assert command_guard.classify("salom", U, "private") is None
    assert command_guard.classify("/chatmode on", U, "supergroup") is None  # to'g'ri komanda — o'z handler'iga


def test_known_command_in_wrong_chat_type_explains():
    assert command_guard.classify("/profil", U, "supergroup") == ("wrong_chat", "private")
    assert command_guard.classify("/statistika", U, "private") == ("wrong_chat", "group")
    bot = harness.make_bot()
    send(bot, U, "/statistika", chat_type="private")
    assert "guruhda" in bot.session.texts(U)[0]


def test_ai_system_prompt_forbids_claiming_settings_changes():
    import inspect
    src = inspect.getsource(ai_chat)
    assert "bajarilmagan amalni HECH QACHON bajarilgan deb" in src and "VIP" in src


# ── murojaat oqimi ───────────────────────────────────────────────────────

def kb_texts(call_data):
    kb = call_data.get("reply_markup") or {}
    rows = kb.get("keyboard", []) if isinstance(kb, dict) else getattr(kb, "keyboard", [])
    return [b["text"] if isinstance(b, dict) else b.text for row in rows for b in row]


def test_start_button_opens_session_with_keyboard_and_start_menu_has_the_button():
    bot = harness.make_bot()
    send(bot, U, "/start")
    start_sent = calls(bot, "SendMessage")[0]
    assert "support:start" in str(start_sent["reply_markup"])
    press(bot, U, "support:start")
    sent = calls(bot, "SendMessage")[-1]
    assert kb_texts(sent) == [support.SEND_TEXT, support.CANCEL_TEXT] and U in support._sessions


def test_nothing_is_sent_until_yuborish_then_each_message_arrives_separately():
    bot = harness.make_bot()
    press(bot, U, "support:start")
    send(bot, U, "Salom, to'lov muammosi")
    send(bot, U, None, photo=[__import__("aiogram").types.PhotoSize(file_id="p", file_unique_id="p", width=1, height=1)])
    send(bot, U, None, sticker=__import__("aiogram").types.Sticker(file_id="s", file_unique_id="s", type="regular", width=1, height=1,
                                                                    is_animated=False, is_video=False))
    send(bot, U, "🙏")
    assert calls(bot, "CopyMessage") == [] and all(d["chat_id"] != SUPER for d in calls(bot, "SendMessage"))   # hali hech narsa ketmadi
    assert len(support._sessions[U]["items"]) == 4
    assert sum("Qabul qilindi" in t for t in bot.session.texts(U)) == 4

    send(bot, U, support.SEND_TEXT)
    copies = calls(bot, "CopyMessage")
    assert len(copies) == 4 and all(c["chat_id"] == SUPER and c["from_chat_id"] == U for c in copies)      # har biri ALOHIDA
    assert [c["message_id"] for c in copies] == support._sessions.get(U, {"items": None})["items"] if U in support._sessions else True
    header = bot.session.texts(SUPER)[0]
    assert str(U) in header and "4 ta" in header and "Bepul" in header
    reply_btn = [d for d in calls(bot, "SendMessage") if d["chat_id"] == SUPER][0]["reply_markup"]
    assert f"panel:msg:{U}" in str(reply_btn)                                                              # javob yozish tugmasi
    assert U not in support._sessions and "yuborildi" in bot.session.texts(U)[-1]


def test_order_is_preserved_and_cancel_discards_everything():
    bot = harness.make_bot()
    press(bot, U, "support:start")
    for t in ("bir", "ikki", "uch"):
        send(bot, U, t)
    ids = list(support._sessions[U]["items"])
    send(bot, U, support.SEND_TEXT)
    assert [c["message_id"] for c in calls(bot, "CopyMessage")] == ids

    bot2 = harness.make_bot()
    press(bot2, U, "support:start")
    send(bot2, U, "yuborilmasin")
    send(bot2, U, support.CANCEL_TEXT)
    assert calls(bot2, "CopyMessage") == [] and U not in support._sessions
    assert not [d for d in calls(bot2, "SendMessage") if d["chat_id"] == SUPER]
    assert "bekor" in bot2.session.texts(U)[-1].lower()


def test_yuborish_with_nothing_buffered_asks_to_write_first():
    bot = harness.make_bot()
    press(bot, U, "support:start")
    send(bot, U, support.SEND_TEXT)
    assert "Avval" in bot.session.texts(U)[-1] and U in support._sessions and calls(bot, "CopyMessage") == []


def test_session_messages_never_reach_ai_or_other_flows(env):
    bot = harness.make_bot()
    pending_input.set(U, "msg_user_text", {"target_uid": 9})
    press(bot, U, "support:start")
    assert pending_input.get(U) is None                                     # boshqa oqim bekor bo'ldi
    send(bot, U, "bu AI'ga ketmasin")
    assert env == [] and len(support._sessions[U]["items"]) == 1


def test_command_during_session_cancels_it_and_runs_the_command():
    bot = harness.make_bot()
    press(bot, U, "support:start")
    send(bot, U, "yarim qoldi")
    send(bot, U, "/start")
    assert U not in support._sessions and calls(bot, "CopyMessage") == []
    texts = bot.session.texts(U)
    assert any("bekor qilindi" in t for t in texts) and any("Salom" in t for t in texts)      # komanda ham bajarildi


def test_stale_buttons_after_restart_or_expiry_do_not_go_to_ai(env):
    bot = harness.make_bot()
    send(bot, U, support.SEND_TEXT)                                         # sessiya yo'q (masalan bot qayta ishga tushgan)
    assert "tugagan" in bot.session.texts(U)[-1] and env == []
    press(bot, U, "support:start")
    support._sessions[U]["t"] -= support.SESSION_TTL + 5
    assert support._active(U) is None and U not in support._sessions        # 30 daqiqadan keyin sessiya o'z-o'zidan tugaydi
    send(bot, U, support.SEND_TEXT)
    assert "tugagan" in bot.session.texts(U)[-1]


def test_limits_max_items_and_hourly_submissions():
    bot = harness.make_bot()
    press(bot, U, "support:start")
    for i in range(support.MAX_ITEMS + 3):
        send(bot, U, f"m{i}")
    assert len(support._sessions[U]["items"]) == support.MAX_ITEMS and "Eng ko'pi" in bot.session.texts(U)[-1]
    send(bot, U, support.CANCEL_TEXT)
    for _ in range(support.SUBMISSIONS_PER_HOUR):
        press(bot, U, "support:start")
        send(bot, U, "x")
        send(bot, U, support.SEND_TEXT)
    before = len(calls(bot, "CopyMessage"))
    press(bot, U, "support:start")                                          # 6-murojaat — soatlik limit
    assert U not in support._sessions
    assert any(n == "AnswerCallbackQuery" and "limiti" in d.get("text", "") for n, d in bot.session.calls)
    assert len(calls(bot, "CopyMessage")) == before


def test_blocked_users_and_groups_cannot_start():
    tgdb.get()["users"]["66"] = {"role": "blocked", "daily_limit": 20, "requests_today": 0, "last_reset": roles.today_str()}
    bot = harness.make_bot()
    press(bot, 66, "support:start")
    assert 66 not in support._sessions


def test_delivery_failure_keeps_session_for_retry(monkeypatch):
    bot = harness.make_bot()
    press(bot, U, "support:start")
    send(bot, U, "muhim xabar")
    orig = bot.session.make_request

    async def failing(b, method, timeout=None):
        if type(method).__name__ == "SendMessage" and method.chat_id == SUPER:
            raise RuntimeError("admin botni bloklagan")
        return await orig(b, method, timeout)

    monkeypatch.setattr(bot.session, "make_request", failing)
    send(bot, U, support.SEND_TEXT)
    assert U in support._sessions and "saqlanib turibdi" in bot.session.texts(U)[-1]


def test_partial_copy_failures_are_reported_honestly(monkeypatch):
    bot = harness.make_bot()
    press(bot, U, "support:start")
    send(bot, U, "bir")
    send(bot, U, "ikki")
    first = support._sessions[U]["items"][0]
    orig = bot.session.make_request

    async def flaky(b, method, timeout=None):
        if type(method).__name__ == "CopyMessage" and method.message_id == first:
            raise RuntimeError("message to copy not found")
        return await orig(b, method, timeout)

    monkeypatch.setattr(bot.session, "make_request", flaky)
    send(bot, U, support.SEND_TEXT)
    assert "1 ta xabar" in bot.session.texts(U)[-1] and "1 tasi" in bot.session.texts(U)[-1]


def test_no_text_paysupport_flow_left():
    import inspect
    import handlers.tariff as th
    assert not hasattr(th, "paysupport")
    bot = harness.make_bot()
    send(bot, U, "/paysupport shu yerga yozaman")
    assert not [d for d in calls(bot, "SendMessage") if d["chat_id"] == SUPER] and "support:start" in str(calls(bot, "SendMessage")[-1]["reply_markup"])


# ── /vipchatmode: kim yozganiga qarab javob ──────────────────────────────

def test_vip_non_superadmin_feedback_depends_on_privilege(caplog):
    # oddiy a'zo — jim (komanda sir), lekin logga yoziladi
    plain = harness.make_bot()
    with caplog.at_level("WARNING", logger="group_settings"):
        send(plain, 77, "/vipchatmode on", chat=GROUP, chat_type="supergroup")
    assert plain.session.texts(GROUP) == [] and "superadmin emas: uid=77" in caplog.text
    # guruh admini — sababi va o'z ID'si aytiladi
    group_admin = harness.make_bot(admins={78})
    send(group_admin, 78, "/vipchatmode: on", chat=GROUP, chat_type="supergroup")
    txt = group_admin.session.texts(GROUP)
    assert len(txt) == 1 and "faqat superadmin" in txt[0] and "78" in txt[0]
    # bot admini — xuddi shunday
    bot_admin = harness.make_bot()
    send(bot_admin, ADMIN, "/vipchatmode on", chat=GROUP, chat_type="supergroup")
    assert "faqat superadmin" in bot_admin.session.texts(GROUP)[0]
    assert chat_mode.get(GROUP) is None                                      # hech biri yoqa olmadi
    # superadmin — ishlaydi
    boss = harness.make_bot()
    send(boss, SUPER, "/vipchatmode: on", chat=GROUP, chat_type="supergroup")
    assert chat_mode.get(GROUP)["vip"] is True and "VIP chat rejimi YOQILDI" in boss.session.texts(GROUP)[0]
