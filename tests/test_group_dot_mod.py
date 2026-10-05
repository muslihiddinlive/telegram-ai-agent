"""Nuqtali guruh moderatsiyasi: .ban .unban .kick .mute .unmute .del — tahlil (parser) va bajarish (executor)."""
import asyncio
from types import SimpleNamespace

import pytest

import core.bot_identity as bot_identity
import core.dot_mod as dm
import core.mod_commands as mod_commands
import core.moderation as moderation
import core.roles as roles
import handlers.group_mod as gm

BOT_ID, MOD, VICTIM, OTHER, STAFF = 999, 500, 600, 700, 800     # SUPERADMIN_ID = 1 (conftest)


def run(coro):
    return asyncio.run(coro)


# ── parser ─────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text,exp", [
    (".ban", ("ban", None, None, None)),
    (".ban @jasur_bek", ("ban", "@jasur_bek", None, None)),
    (".ban 2k spam", ("ban", None, 2880, "spam")),
    (".ban @jasur_bek 1d reklama yubordi", ("ban", "@jasur_bek", 1440, "reklama yubordi")),
    (".mute", ("mute", None, None, None)),
    (".mute 1h", ("mute", None, 60, None)),
    (".mute 1 h so'kindi", ("mute", None, 60, "so'kindi")),
    (".mute @jasur_bek 30m", ("mute", "@jasur_bek", 30, None)),
    (".mute 30m @jasur_bek", ("mute", "@jasur_bek", 30, None)),          # tartib erkin
    (".mute 123456789 2soat", ("mute", "123456789", 120, None)),         # 9 xonali — ID, "2soat" — muddat
    (".mute -1001234567 1k", ("mute", "-1001234567", 1440, None)),
    (".mute 1hafta", ("mute", None, 10080, None)),
    (".kick @jasur_bek sabab bor", ("kick", "@jasur_bek", None, "sabab bor")),
    (".kick 5m", ("kick", None, None, "5m")),                            # kick'da muddat yo'q — sabab
    (".unmute @jasur_bek", ("unmute", "@jasur_bek", None, None)),
    (".UNBAN 123456789", ("unban", "123456789", None, None)),
    (".mute 5 ta xabar uchun", ("mute", None, None, "5 ta xabar uchun")),  # "5 ta" muddat emas
    (".mute so'kindi 1h", ("mute", None, None, "so'kindi 1h")),            # muddat faqat boshida
    (".mute @ali 1h so'kindi", ("mute", "@ali", 60, "so'kindi")),          # qisqa username ham nishon
    (".del", ("del", None, None, None)),
    (".modhelp", ("modhelp", None, None, None)),
])
def test_parse(text, exp):
    p = dm.parse(text)
    assert (p.action, p.target, p.minutes, p.reason) == exp


@pytest.mark.parametrize("text", [".banana", ".bank x", "ban", "..ban", "x .ban", ".", "", ".foo", "salom .mute", None])
def test_not_commands(text):
    assert dm.parse(text) is None


def test_duration_units_and_caps():
    assert dm.parse_duration_token("30s") == 1                           # soniya — 1 daqiqagacha yaxlitlanadi
    assert dm.parse_duration_token("90m") == 90 and dm.parse_duration_token("3kun") == 4320
    assert dm.parse_duration_token("2o") == 86400 and dm.parse_duration_token("1y") == 525600
    assert dm.parse_duration_token("5y") == 366 * 1440                   # Telegram chegarasi: 366 kun
    for bad in ("0m", "1x", "m", "1.5h", "", "abc", "10"):
        assert dm.parse_duration_token(bad) is None


def test_reason_is_capped():
    assert len(dm.parse(".ban " + "x" * 500).reason) == dm.MAX_REASON


def test_command_pattern():
    assert dm.COMMAND_PATTERN.match("  .mute x") and dm.COMMAND_PATTERN.match(".DEL")
    assert not dm.COMMAND_PATTERN.match(".mutex") and not dm.COMMAND_PATTERN.match("mute")


# ── executor uchun soxtalar ────────────────────────────────────────────────────
def user(uid, name="Ali", username=None, bot=False):
    return SimpleNamespace(id=uid, full_name=name, username=username, is_bot=bot)


class Msg:
    def __init__(self, text, sender=MOD, reply_to=None, entities=None, thread=None, mid=10):
        self.text, self.from_user = text, user(sender, "Moderator")
        self.chat = SimpleNamespace(id=-100, type="supergroup")
        self.reply_to_message, self.entities = reply_to, entities or []
        self.message_id, self.message_thread_id = mid, thread
        self.bot, self.replies, self.deleted = object(), [], False

    async def reply(self, text, **kw):
        self.replies.append(text)

    async def delete(self):
        self.deleted = True


def replied(uid=VICTIM, name="Vali", mid=5, **kw):
    return SimpleNamespace(from_user=user(uid, name, **kw), message_id=mid)


@pytest.fixture
def env(monkeypatch):
    calls, st = [], SimpleNamespace(access=moderation.ModAccess(MOD, rights={"can_restrict_members", "can_delete_messages"}),
                                    result={"ok": True}, resolved=None)

    async def get_access(bot, chat_id, user_id):
        return st.access if user_id == MOD or user_id == STAFF else None

    async def dispatch(bot, name, args, ctx):
        calls.append((name, args, ctx))
        return st.result

    async def resolve_username(bot, chat_id, uname):
        return st.resolved or (None, None, f"@{uname} ni topa olmadim.")

    monkeypatch.setattr(moderation, "get_access", get_access)
    monkeypatch.setattr(moderation, "dispatch", dispatch)
    monkeypatch.setattr(mod_commands, "resolve_username", resolve_username)
    monkeypatch.setattr(bot_identity, "_id", BOT_ID)
    monkeypatch.setattr(roles, "is_superadmin", lambda u: False)
    monkeypatch.setattr(roles, "is_admin", lambda u: u == OTHER)       # OTHER — bot admini
    st.calls = calls
    return st


def go(msg):
    run(gm.execute(msg))
    return msg


# ── ruxsat ─────────────────────────────────────────────────────────────────────
def test_non_moderator_gets_silence(env):
    m = go(Msg(".ban", sender=123, reply_to=replied()))
    assert m.replies == [] and env.calls == []                          # jim: spam yo'q, hech narsa bajarilmaydi


def test_admin_without_restrict_right_is_told_why(env):
    env.access = moderation.ModAccess(MOD, rights={"can_delete_messages"})
    m = go(Msg(".ban", reply_to=replied()))
    assert env.calls == [] and "A'zolarni cheklash" in m.replies[0]


def test_del_needs_delete_right(env):
    env.access = moderation.ModAccess(MOD, rights={"can_restrict_members"})
    m = go(Msg(".del", reply_to=replied()))
    assert env.calls == [] and "Xabarlarni o'chirish" in m.replies[0] and not m.deleted


def test_anonymous_admin_cannot_be_verified(env):
    m = go(Msg(".ban", sender=gm.ANON_ADMIN_ID, reply_to=replied()))
    assert env.calls == [] and "Anonim" in m.replies[0]


# ── bajarish ───────────────────────────────────────────────────────────────────
def test_reply_ban_dispatches_through_core(env):
    m = go(Msg(".ban spam yubordi", reply_to=replied()))
    (name, args, ctx), = env.calls
    assert name == "ban_user" and args == {"user_id": VICTIM}
    assert ctx["chat_id"] == -100 and ctx["is_group"] and ctx["mod"] is env.access and ctx["mod_minutes"] is None
    assert "Vali" in m.replies[0] and "ban qilindi" in m.replies[0] and "Sabab: spam yubordi" in m.replies[0]


def test_timed_mute_passes_minutes_and_forces_them(env):
    m = go(Msg(".mute 1h so'kindi", reply_to=replied()))
    (name, args, ctx), = env.calls
    assert name == "mute_user" and args == {"user_id": VICTIM, "minutes": 60} and ctx["mod_minutes"] == 60
    assert "1 soatga mute qilindi" in m.replies[0]


def test_untimed_mute_is_permanent(env):
    m = go(Msg(".mute", reply_to=replied()))
    assert env.calls[0][1] == {"user_id": VICTIM} and "butunlay mute" in m.replies[0]


def test_timed_ban_label(env):
    m = go(Msg(".ban 2k", reply_to=replied()))
    assert env.calls[0][1]["minutes"] == 2880 and "(2 kun)" in m.replies[0]


@pytest.mark.parametrize("cmd,tool,word", [(".kick", "kick_user", "chiqarildi"), (".unban", "unban_user", "ban'dan chiqarildi"),
                                           (".unmute", "unmute_user", "mute'dan chiqarildi")])
def test_other_actions(env, cmd, tool, word):
    m = go(Msg(cmd, reply_to=replied()))
    assert env.calls[0][0] == tool and env.calls[0][1] == {"user_id": VICTIM} and word in m.replies[0]


def test_reason_is_html_escaped(env):
    m = go(Msg(".ban <b>x</b>", reply_to=replied()))
    assert "<b>x</b>" not in m.replies[0] and "&lt;b&gt;x&lt;/b&gt;" in m.replies[0]


def test_username_target_resolution(env):
    env.resolved = (VICTIM, "<b>Vali</b>", None)
    m = go(Msg(".mute @vali_bek 30m"))
    assert env.calls[0][1] == {"user_id": VICTIM, "minutes": 30} and "Vali" in m.replies[0]


def test_unresolvable_username_is_reported_not_dispatched(env):
    m = go(Msg(".ban @yoq_odam"))
    assert env.calls == [] and "topa olmadim" in m.replies[0]


def test_numeric_id_target(env):
    m = go(Msg(".kick 123456789"))
    assert env.calls[0][1] == {"user_id": 123456789} and "123456789" in m.replies[0]


def test_text_mention_target(env):
    ent = SimpleNamespace(type="text_mention", user=user(VICTIM, "Username'siz", None))
    go(Msg(".mute 10m", entities=[ent]))
    assert env.calls[0][1] == {"user_id": VICTIM, "minutes": 10}


def test_reply_and_explicit_must_agree(env):
    env.resolved = (OTHER + 1, "<b>Boshqa</b>", None)
    m = go(Msg(".ban @boshqa_odam", reply_to=replied()))
    assert env.calls == [] and "bittasini" in m.replies[0]
    env.resolved = (VICTIM, "<b>Vali</b>", None)                         # bir xil odam — muammo yo'q
    go(Msg(".ban @vali_bek", reply_to=replied()))
    assert len(env.calls) == 1


def test_no_target(env):
    m = go(Msg(".ban"))
    assert env.calls == [] and "Kimga" in m.replies[0]


def test_forum_topic_root_is_not_a_reply(env):
    root = replied(uid=OTHER + 5, mid=77)                                # mavzu ildizi — reply emas
    m = go(Msg(".ban", reply_to=root, thread=77))
    assert env.calls == [] and "Kimga" in m.replies[0]
    go(Msg(".ban", reply_to=replied(mid=78), thread=77))                 # haqiqiy reply (boshqa xabarga)
    assert len(env.calls) == 1


def test_reply_to_channel_or_anonymous_message(env):
    r = SimpleNamespace(from_user=user(gm.ANON_ADMIN_ID, "Anon"), message_id=5)
    m = go(Msg(".ban", reply_to=r))
    assert env.calls == [] and "anonim" in m.replies[0].lower()


def test_cannot_target_self_or_bot(env):
    m = go(Msg(".ban", reply_to=replied(uid=MOD)))
    assert env.calls == [] and "O'zingizga" in m.replies[0]
    m = go(Msg(".ban", reply_to=replied(uid=BOT_ID, bot=True)))
    assert env.calls == [] and "Botning o'ziga" in m.replies[0]


def test_bot_admin_is_protected_from_group_moderators(env):
    for cmd in (".ban", ".kick", ".mute 1h"):
        m = go(Msg(cmd, reply_to=replied(uid=OTHER)))
        assert "qo'llab bo'lmaydi" in m.replies[0]
    assert env.calls == []
    go(Msg(".unban", reply_to=replied(uid=OTHER)))                       # teskari amallar mumkin
    go(Msg(".unmute", reply_to=replied(uid=OTHER)))
    assert [c[0] for c in env.calls] == ["unban_user", "unmute_user"]


def test_bot_staff_can_moderate_other_bot_staff(env, monkeypatch):
    monkeypatch.setattr(roles, "is_admin", lambda u: u in (OTHER, STAFF))      # ikkalasi ham bot admini
    m = go(Msg(".ban", sender=STAFF, reply_to=replied(uid=OTHER)))
    assert [c[0] for c in env.calls] == ["ban_user"] and "ban qilindi" in m.replies[0]


def test_nobody_gets_protection_if_target_is_ordinary(env):
    go(Msg(".ban", reply_to=replied(uid=VICTIM)))
    assert [c[0] for c in env.calls] == ["ban_user"]


def test_core_failure_message_is_relayed(env):
    env.result = {"ok": False, "message": "Botda «A'zolarni cheklash» huquqi yo'q."}
    m = go(Msg(".ban", reply_to=replied()))
    assert "Ban bajarilmadi" in m.replies[0] and "huquqi yo'q" in m.replies[0]


# ── .del / .modhelp ────────────────────────────────────────────────────────────
def test_del_deletes_replied_message_then_the_command(env):
    m = go(Msg(".del", reply_to=replied(mid=55)))
    assert env.calls[0][0] == "delete_message" and env.calls[0][1] == {"message_id": 55}
    assert m.deleted and m.replies == []


def test_del_without_reply_and_on_failure(env):
    m = go(Msg(".del"))
    assert env.calls == [] and "reply" in m.replies[0] and not m.deleted
    env.result = {"ok": False, "message": "Bot admin emas"}
    m = go(Msg(".del", reply_to=replied()))
    assert "o'chirib bo'lmadi" in m.replies[0].lower() and not m.deleted


def test_modhelp_only_for_moderators(env):
    assert dm.HELP in go(Msg(".modhelp")).replies
    assert go(Msg(".modhelp", sender=123)).replies == []


# ── real dispatch bilan: yadro shartnomasi ─────────────────────────────────────
def test_through_real_dispatch_forces_minutes_and_chat(monkeypatch):
    calls = []

    async def get_access(bot, chat_id, user_id):
        return moderation.ModAccess(MOD, rights={"can_restrict_members"})

    async def ok(*a, **k):
        return None

    async def verify(*a, **k):
        return True

    class Toolkit:
        async def call(self, name, **kw):
            calls.append((name, kw))
            return SimpleNamespace(ok=True, as_dict=lambda: {"ok": True})

    monkeypatch.setattr(moderation, "get_access", get_access)
    monkeypatch.setattr(moderation, "bot_rights_error", ok)
    monkeypatch.setattr(moderation, "target_error", ok)
    monkeypatch.setattr(moderation, "verify_effect", verify)
    monkeypatch.setattr(moderation, "get_toolkit", lambda bot: Toolkit())
    monkeypatch.setattr(bot_identity, "_id", BOT_ID)
    monkeypatch.setattr(roles, "is_superadmin", lambda u: False)
    monkeypatch.setattr(roles, "is_admin", lambda u: False)
    async def get_chat_member(chat_id, uid):
        return SimpleNamespace(status="member")

    msg = Msg(".mute 2h reklama", reply_to=replied())
    msg.bot = SimpleNamespace(get_chat_member=get_chat_member)
    m = go(msg)
    assert calls == [("mute_user", {"user_id": VICTIM, "minutes": 120, "chat_id": -100})]
    assert "2 soatga mute qilindi" in m.replies[0]


def test_real_dispatch_fails_closed_when_target_cannot_be_checked(monkeypatch):
    """Maqsadli foydalanuvchini tekshirib bo'lmasa (get_chat_member xato) — hech narsa bajarilmaydi."""
    calls = []

    async def get_access(bot, chat_id, user_id):
        return moderation.ModAccess(MOD, rights={"can_restrict_members"})

    async def ok(*a, **k):
        return None

    class Toolkit:
        async def call(self, name, **kw):
            calls.append(name)

    monkeypatch.setattr(moderation, "get_access", get_access)
    monkeypatch.setattr(moderation, "bot_rights_error", ok)
    monkeypatch.setattr(moderation, "target_error", ok)
    monkeypatch.setattr(moderation, "get_toolkit", lambda bot: Toolkit())
    monkeypatch.setattr(bot_identity, "_id", BOT_ID)
    monkeypatch.setattr(roles, "is_superadmin", lambda u: False)
    monkeypatch.setattr(roles, "is_admin", lambda u: False)
    m = go(Msg(".ban", reply_to=replied()))                   # bot.get_chat_member yo'q -> tekshirib bo'lmaydi
    assert calls == [] and "bajarilmadi" in m.replies[0]


# ── ulanish ────────────────────────────────────────────────────────────────────
def test_router_filter_only_matches_dot_commands():
    assert gm._is_dot_command(SimpleNamespace(text=".ban x")) and not gm._is_dot_command(SimpleNamespace(text="ban x"))
    assert not gm._is_dot_command(SimpleNamespace(text=None))


def test_group_mod_router_is_registered_before_ai_chat():
    src = open("main.py", encoding="utf-8").read()
    assert src.index("include_router(group_mod_router)") < src.index("include_router(ai_chat_router)")
