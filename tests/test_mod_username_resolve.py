"""@username -> ID: bot indeksi -> get_chat -> userbot (MTProto) zaxirasi (mute/ban nishonini aniqlash)."""
import asyncio
from types import SimpleNamespace

import pytest

import core.bot_identity as bot_identity
import core.mod_commands as mod_commands
import core.moderation as moderation
import core.tgdb as tgdb
import core.userbot as userbot

CHAT = -1001


def run(coro):
    return asyncio.run(coro)


class FakeBot:
    """Bot API oddiy userni @username bo'yicha topa olmaydi — get_chat har doim xato beradi."""
    def __init__(self, private_chat=None):
        self.private_chat = private_chat

    async def get_chat(self, ref):
        if self.private_chat is not None:
            return self.private_chat
        raise RuntimeError("Bad Request: chat not found")


def mention_msg(text):
    start = text.index("@")
    end = start + len(text[start:].split()[0])
    ent = SimpleNamespace(type="mention", user=None, extract_from=lambda raw, s=start, e=end: raw[s:e])
    return SimpleNamespace(text=text, caption=None, entities=[ent], caption_entities=None, reply_to_message=None,
                           chat=SimpleNamespace(id=CHAT, type="supergroup"))


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(tgdb, "_cache", {"users": {}, "group_members": {}})
    monkeypatch.setattr(bot_identity, "_username", "my_bot")
    monkeypatch.setattr(bot_identity, "_id", 999, raising=False)
    calls = []

    async def fake_find(username, now=None):
        calls.append(username)
        return {"yangi_odam": (555, "Yangi Odam")}.get(username)

    monkeypatch.setattr(userbot, "find_user_by_username", fake_find)
    monkeypatch.setattr(userbot, "is_enabled", lambda: True)
    return SimpleNamespace(calls=calls)


def test_resolve_target_falls_back_to_userbot(env):
    uid, name, err = run(mod_commands._resolve_target(FakeBot(), mention_msg("@yangi_odam mute ber"), "@yangi_odam mute ber"))
    assert (uid, err) == (555, None)
    assert "Yangi Odam" in name
    assert env.calls == ["yangi_odam"]


def test_resolve_target_prefers_own_index_over_userbot(env):
    tgdb.get()["group_members"][str(CHAT)] = {"42": {"n": "Indeksdagi", "u": "yangi_odam", "t": 1}}
    uid, _, err = run(mod_commands._resolve_target(FakeBot(), mention_msg("@yangi_odam mute ber"), "@yangi_odam mute ber"))
    assert (uid, err) == (42, None)
    assert env.calls == []                                                # indeksda bor — Telegram'ga bormaymiz


def test_resolve_target_prefers_get_chat_over_userbot(env):
    bot = FakeBot(private_chat=SimpleNamespace(type="private", id=77, full_name="Ochiq Odam"))
    uid, _, err = run(mod_commands._resolve_target(bot, mention_msg("@yangi_odam mute ber"), "@yangi_odam mute ber"))
    assert (uid, err) == (77, None)
    assert env.calls == []


def test_resolve_target_not_found_with_userbot_enabled(env):
    uid, name, err = run(mod_commands._resolve_target(FakeBot(), mention_msg("@yoq_odam mute ber"), "@yoq_odam mute ber"))
    assert uid is None and name is None
    assert "ochiq username yo'q" in err and "reply" in err


def test_resolve_target_not_found_with_userbot_disabled(env, monkeypatch):
    monkeypatch.setattr(userbot, "is_enabled", lambda: False)
    _, _, err = run(mod_commands._resolve_target(FakeBot(), mention_msg("@yoq_odam mute ber"), "@yoq_odam mute ber"))
    assert "hech narsa yozmagan" in err                                   # eski xabar saqlanadi


def test_context_line_gives_userbot_resolved_id_to_ai(env):
    line = run(moderation.context_line(FakeBot(), mention_msg("@yangi_odam ga 10 daqiqaga mute ber")))
    assert "ID=555" in line and "@yangi_odam" in line


def test_context_line_unresolved_still_asks_for_reply(env):
    line = run(moderation.context_line(FakeBot(), mention_msg("@yoq_odam ga mute ber")))
    assert "ID=" not in line.split("Aniqlangan")[0] and "REPLY" in line
