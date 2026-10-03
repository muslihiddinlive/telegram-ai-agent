import asyncio
import json
from types import SimpleNamespace

import pytest

import core.ai_tools as ai_tools
import core.antispam as antispam
import core.bot_loop_guard as bot_loop_guard
import core.group_wipe as group_wipe
import core.moderation as moderation
import core.tgdb as tgdb

A, B = -1001111, -1002222
SECRET = "Mocci opa"


def run(coro):
    return asyncio.run(coro)


class FakeBot:
    def __init__(self):
        self.docs = []

    async def send_document(self, chat_id, file, caption=None):
        self.docs.append((chat_id, file.data.decode("utf-8"), caption))


def populate(chat):
    c = str(chat)
    return {
        "group_mem": {f"{c}:g": {"log": [{"r": "u", "n": "Ali", "u": "ali", "i": 7, "t": f"meni {SECRET} deb chaqir", "m": 1}],
                                 "summary": f"Ali {SECRET} deb chaqirilishni so'radi"},
                      f"{c}:55": {"log": [], "summary": "topic"}},
        "group_members": {c: {"7": {"n": "Ali", "u": "ali", "t": 1}}},
        "group_stats": {c: {"7": {"n": 4, "name": "Ali"}}},
        "group_notes": {c: {"7": [f"Ali'ni {SECRET} deb chaqirish kerak"]}},
        "group_rules": {c: ["qoida 1"]}, "banned_words": {c: ["so'z"]}, "chat_mode": {c: {"enabled": True, "owner_id": 1, "vip": False}},
        "auto_top_mode": {c: True}, "antispam_mode": {c: True}, "ai_reaction_mode": {c: True},
        "group_settings": {c: {"allowed_usernames": ["x"]}}, "warns": {c: {"7": 2}}, "blacklist_strikes": {c: {"7": 1}},
        "channels": {c: {"title": "G", "added_by": 1}},
    }


def merge(*dbs):
    out = {}
    for d in dbs:
        for bucket, val in d.items():
            if bucket == "group_mem":
                out.setdefault(bucket, {}).update(val)
            else:
                out.setdefault(bucket, {}).update(val)
    return out


@pytest.fixture
def db(monkeypatch):
    data = merge(populate(A), populate(B))
    data["users"] = {"7": {"name": "Ali", "notes": ["shaxsiy chat eslatmasi"]}, "1": {}}
    data["admins"] = {"2": {"name": "adm"}}
    data["nicknames"] = {"7": "Ali aka"}
    monkeypatch.setattr(tgdb, "_cache", data)

    async def noop_save(bot, force=False):
        return None

    monkeypatch.setattr(tgdb, "save", noop_save)
    import core.roles as roles
    monkeypatch.setattr(roles.config, "SUPERADMIN_ID", 1)
    return data


def keys_mentioning(obj, chat):
    """db ichida chat_id'ga bog'langan (kalit sifatida) barcha yo'llar."""
    found = []

    def walk(o, path):
        if isinstance(o, dict):
            for k, v in o.items():
                if str(k) == str(chat) or str(k).startswith(f"{chat}:"):
                    found.append(path + [k])
                walk(v, path + [k])

    walk(obj, [])
    return found


def test_full_reset_leaves_no_trace_of_group_and_spares_others(db):
    snapshot_b = json.dumps({k: v.get(str(B)) for k, v in db.items() if k not in ("users", "admins", "nicknames", "group_mem")},
                            sort_keys=True)
    run(group_wipe.wipe(FakeBot(), A, full=True))
    assert keys_mentioning(db, A) == []                       # hech bir bucket'da A guruh kaliti qolmadi
    assert len(keys_mentioning(db, B)) >= 12                  # B guruh to'liq saqlangan
    assert snapshot_b == json.dumps({k: v.get(str(B)) for k, v in db.items() if k not in ("users", "admins", "nicknames", "group_mem")},
                                    sort_keys=True)
    assert f"{B}:g" in db["group_mem"] and f"{A}:g" not in db["group_mem"]
    assert db["users"]["7"]["notes"] == ["shaxsiy chat eslatmasi"] and db["nicknames"] == {"7": "Ali aka"}


def test_memory_wipe_clears_notes_but_keeps_admin_settings(db):
    removed = run(group_wipe.wipe(FakeBot(), A))
    assert removed["notes"] == 1 and removed["mem_threads"] == 2
    for bucket in ("group_mem", "group_members", "group_stats", "group_notes"):
        assert keys_mentioning({bucket: db.get(bucket, {})}, A) == []
    for bucket in ("group_rules", "banned_words", "chat_mode", "antispam_mode", "warns", "channels"):
        assert str(A) in db[bucket], bucket


def test_wipe_is_idempotent_and_safe_on_unknown_group(db):
    assert run(group_wipe.wipe(FakeBot(), -999, full=True))["mem_threads"] == 0
    run(group_wipe.wipe(FakeBot(), A, full=True))
    assert run(group_wipe.wipe(FakeBot(), A, full=True))["notes"] == 0


def test_runtime_caches_cleared_only_for_that_group(db):
    antispam._recent[(A, 7)] = [(1.0, "x")]
    antispam._recent[(B, 7)] = [(1.0, "x")]
    moderation._access_cache[(A, 7)] = (1.0, None)
    moderation._access_cache[(B, 7)] = (1.0, None)
    bot_loop_guard._chain_counts[A] = 3
    bot_loop_guard._warned_chats.add(A)
    run(group_wipe.wipe(FakeBot(), A))
    assert (A, 7) not in antispam._recent and (B, 7) in antispam._recent
    assert (A, 7) not in moderation._access_cache and (B, 7) in moderation._access_cache
    assert A not in bot_loop_guard._chain_counts and A not in bot_loop_guard._warned_chats
    antispam._recent.clear(); moderation._access_cache.clear()


# ── eslatmalar: ildiz sabab ──────────────────────────────────────────────

def test_note_said_in_group_stays_in_that_group_only(db):
    ctx = {"is_group": True, "chat_id": A, "bot": FakeBot()}
    run(ai_tools._remember_note(8, {"note": f"{SECRET} deb chaqir"}, ctx))
    assert ai_tools.get_user_notes(8, A) == [f"{SECRET} deb chaqir"]
    assert ai_tools.get_user_notes(8, B) == []          # boshqa guruhga sizmaydi
    assert ai_tools.get_user_notes(8) == []             # shaxsiy chatga ham
    assert "notes" not in db["users"].get("8", {})      # global eslatmaga YOZILMAYDI


def test_private_notes_never_shown_in_groups(db):
    db["users"]["9"] = {"notes": ["faqat shaxsiy chatda aytilgan"]}
    assert ai_tools.get_user_notes(9) == ["faqat shaxsiy chatda aytilgan"]
    assert ai_tools.get_user_notes(9, A) == []                  # shaxsiy gap guruhga chiqmaydi
    assert ai_tools.get_user_notes(7) == ["shaxsiy chat eslatmasi"]
    run(ai_tools._remember_note(7, {"note": "yangi"}, {"is_group": False, "chat_id": 7, "bot": FakeBot()}))
    assert ai_tools.get_user_notes(7)[-1] == "yangi"


def test_group_note_gone_after_wipe(db):
    run(ai_tools._remember_note(8, {"note": SECRET}, {"is_group": True, "chat_id": A, "bot": FakeBot()}))
    run(group_wipe.wipe(FakeBot(), A))
    assert ai_tools.get_user_notes(8, A) == [] and ai_tools.get_user_notes(7, A) == []


def test_clear_user_notes_also_clears_group_notes(db):
    run(ai_tools.clear_user_notes(FakeBot(), 7))
    assert ai_tools.get_user_notes(7) == [] and ai_tools.get_user_notes(7, A) == [] and ai_tools.get_user_notes(7, B) == []


# ── AI tool: ruxsat va xabarlar ──────────────────────────────────────────

def tool_ctx(bot, mod=None, chat=A):
    return {"bot": bot, "chat_id": chat, "is_group": True, "mod": mod}


def test_tool_requires_admin_and_group(db):
    assert "faqat guruhda" in run(ai_tools._wipe_group_memory(5, {}, {**tool_ctx(FakeBot()), "is_group": False}))["error"]
    assert "faqat guruh yoki bot adminlari" in run(ai_tools._wipe_group_memory(5, {}, tool_ctx(FakeBot())))["error"]
    assert str(A) in db["group_mem"] or f"{A}:g" in db["group_mem"]  # hech narsa o'chmadi


def test_memory_tool_sets_flag_sends_backup_with_notes_and_wipes(db):
    bot, ctx = FakeBot(), None
    ctx = tool_ctx(bot, mod=moderation.ModAccess(5))  # oddiy guruh admini
    res = run(ai_tools._wipe_group_memory(5, {}, ctx))
    assert res["status"].endswith("o'chirildi") and ctx["wiped"] == "memory"
    assert SECRET in bot.docs[0][1] and "ESLATMALAR" in bot.docs[0][1]  # zaxirada bor edi
    assert keys_mentioning({"group_notes": db["group_notes"]}, A) == []
    assert str(A) in db["group_rules"]  # standart rejimda sozlamalar qoladi


def test_full_reset_only_for_owner_or_bot_admin(db):
    plain_admin = tool_ctx(FakeBot(), mod=moderation.ModAccess(5))
    assert "faqat bot adminlari yoki guruh egasi" in run(ai_tools._wipe_group_memory(5, {"full_reset": True}, plain_admin))["error"]
    assert "wiped" not in plain_admin and str(A) in db["group_rules"]

    owner = tool_ctx(FakeBot(), mod=moderation.ModAccess(6, is_owner=True))
    assert run(ai_tools._wipe_group_memory(6, {"full_reset": True}, owner))["status"].startswith("guruh to'liq reset")
    assert owner["wiped"] == "full" and str(A) not in db["group_rules"]
    assert "ADMIN SOZLAMALARI" in owner["bot"].docs[0][1] and "qoida 1" in owner["bot"].docs[0][1]

    bot_admin = tool_ctx(FakeBot(), chat=B)
    assert "error" not in run(ai_tools._wipe_group_memory(2, {"full_reset": True}, bot_admin))
    assert keys_mentioning(db, B) == []


def test_reply_text_is_fixed_and_mode_aware():
    assert "xotira o'chirildi" in group_wipe.reply_text("memory")
    assert "reset" in group_wipe.reply_text("full")
