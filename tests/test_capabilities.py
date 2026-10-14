"""AI o'zi haqida TO'LIQ biladi (capabilities) va GitHub/sayt uchun buyruqlar YO'Q — hamma narsa suhbat orqali."""
import asyncio
import importlib
import re

import pytest

import core.ai_tools as ai_tools
import core.ai_persona as ai_persona
import core.capabilities as cap
import core.github_ops as gh
import core.github_sandbox as sb
import core.roles as roles
import core.tariffs as tariffs
import core.tgdb as tgdb

U, GROUP_USER, ADMIN = 5, 6, 2


def run(c):
    return asyncio.run(c)


@pytest.fixture(autouse=True)
def env(monkeypatch):
    data = {"admins": {str(ADMIN): {"name": "a"}}, "users": {}, "subscriptions": {}, "ai_sessions": {}}
    monkeypatch.setattr(tgdb, "_cache", data)
    monkeypatch.setattr(roles.config, "SUPERADMIN_ID", 1)
    return data


# ── har bir tool bilimga kiritilgan (yangi tool qo'shilib, bu yerga yozilmasa — test yiqiladi) ─────────────────
def all_tool_names() -> set[str]:
    import core.github_tools as gtools
    import core.instagram_tools as ig
    import core.moderation as mod
    import core.site_tools as stools
    import core.userbot_tools as ub
    names = {s["function"]["name"] for s in ai_tools.TOOLS}
    names |= set(ai_tools.DISPATCH)
    names |= {s["function"]["name"] for s in gtools.SCHEMAS} | {s["function"]["name"] for s in stools.SCHEMAS}
    names |= {s["function"]["name"] for s in ub.SCHEMAS} | set(ig.HANDLERS) | set(mod._RIGHT_FOR_TOOL)
    names.add(cap.SCHEMA["function"]["name"])
    return names


def test_every_tool_belongs_to_a_known_capability_group():
    names = all_tool_names()
    assert len(names) > 100
    uncovered = sorted(n for n in names if cap.classify(n) is None)
    assert not uncovered, f"Quyidagi tool'lar core/capabilities.py da guruhga bog'lanmagan (AI ular haqida bilmaydi): {uncovered}"
    groups = {cap.classify(n) for n in names}
    assert {"fayllar", "taqdimot", "ko'rish", "internet", "sayt", "github", "xotira", "guruh", "userbot", "moderatsiya", "instagram", "o'zim"} <= groups


def test_static_block_covers_every_group_and_says_no_commands_needed():
    b = cap.STATIC_BLOCK
    for needle in ("Word (.docx)", "Excel", "PowerPoint", "PDF", "OCR", "QR", "ZIP", "Prezentatsiya", "👁", "Internet", "Sayt frontend", "GitHub", "ommaviy klon",
                   "tasdiq tugmasi", "Xotira", "HAQIQATAN o'chirasiz", "Userbot", "moderatsiyasi", "Instagram", "Tariflar", "bot_capabilities", "diskda saqlanmaydi",
                   "FAQAT shaxsiy chatda", "phishing"):
        assert needle in b, needle
    assert "buyruq YO'Q" in b and "/gh" not in b and "/site" not in b
    assert "masalan ismi/laqabi" not in b and "mavjud bo'lmagan imkoniyatni bor deb ko'rsatmang" in b


def test_persona_always_includes_the_capabilities_even_with_custom_prompt(monkeypatch):
    assert ai_persona.CAPABILITIES_BLOCK is cap.STATIC_BLOCK
    monkeypatch.setitem(tgdb.get().setdefault("settings", {}), "system_prompt", "Men boshqa shaxsiyatman")
    full = ai_persona.get_full_system_prompt()
    assert "Men boshqa shaxsiyatman" in full and "GitHub" in full and "Sayt frontend" in full


# ── foydalanuvchi holati ───────────────────────────────────────────────────────
def test_state_line_reflects_tier_quota_github_and_chat_type(monkeypatch):
    s = cap.state_line(U, False)
    assert "tarif" in s and "GitHub 0/10" in s and "sayt 0/3" in s and "fayl 0/" in s and "ULANMAGAN" in s
    monkeypatch.setattr(gh, "is_connected", lambda uid: True)
    monkeypatch.setattr(gh, "meta", lambda uid: {"login": "octo"})
    assert "ulangan (octo)" in cap.state_line(U, False)
    g = cap.state_line(U, True)
    assert "GURUH" in g and "ishlamaydi" in g and "octo" not in g
    assert "GitHub cheksiz" in cap.state_line(ADMIN, False) and "sayt cheksiz" in cap.state_line(ADMIN, False)
    roles._bucket(U)["github_today"], roles._bucket(U)["last_reset"] = 4, roles.today_str()
    assert "GitHub 4/10" in cap.state_line(U, False)


def test_state_line_never_breaks_the_chat(monkeypatch):
    monkeypatch.setattr(tariffs, "active_tier", lambda uid: (_ for _ in ()).throw(RuntimeError("boom")))
    assert cap.state_line(U, False) == ""


# ── bot_capabilities tool ──────────────────────────────────────────────────────
def call(topic=None, uid=U, is_group=False):
    args = {} if topic is None else {"topic": topic}
    return run(ai_tools.DISPATCH["bot_capabilities"](uid, args, {"is_group": is_group}))


def test_every_topic_returns_a_detailed_guide():
    assert set(cap.SCHEMA["function"]["parameters"]["properties"]["topic"]["enum"]) == set(cap.TOPICS) == set(cap.GUIDES) | {"hammasi"}
    for t in cap.TOPICS:
        r = call(t)
        assert r["ok"] and len(r["text"]) > 150, t
    assert "tushunmadim" not in call("hammasi")["text"]
    allr = call("hammasi")["text"]
    assert cap.STATIC_BLOCK in allr and "FOYDALANUVCHI HOLATI" in allr and "github" in allr
    assert "Noma'lum mavzu" in call("nope")["error"]
    assert call()["ok"]                                                     # mavzusiz — umumiy ko'rinish


def test_github_guide_is_accurate_and_matches_real_limits(monkeypatch):
    t = call("github")["text"]
    for needle in ("tasdiq tugmasi", "workspace=true", "DISKDA SAQLANMAYDI", "gh_clone_all", "gh_profile", "gh_disconnect", "pending_confirmation",
                   "SHAXSIY chatda", "zaxira ZIP", f"{sb.MAX_REPO_KB // 1024} MB", f"{sb.MAX_REPOS_PER_USER} ta ish nusxasi", "GitHub 0/10", "fine-grained"):
        assert needle in t, needle
    assert not re.search(r"(?<![\w/])/gh\b", t) and "bot egasiga" in t     # buyruq yo'q; standart: superadmin nusxasi bor — AI buni aytadi
    import config
    monkeypatch.setattr(config, "GITHUB_BACKUP_TO_ADMIN", False)
    assert "bot egasiga" not in call("github")["text"]                    # bayroq o'chiq bo'lsa AI bunga va'da bermaydi
    monkeypatch.setattr(gh, "is_connected", lambda uid: True)
    monkeypatch.setattr(gh, "meta", lambda uid: {"login": "octo"})
    assert "ulangan (octo)" in call("github")["text"]
    assert "ulanmagan yoki guruh chati" in call("github", is_group=True)["text"]                     # guruhda ulangan ko'rinmaydi


def test_site_and_other_guides_mention_real_constraints():
    t = call("sayt")["text"]
    for needle in ("site_read", "site_resource", "site_download", "single", "zip", "JS bajarilmaydi", "150 fayl", "phishing", "ichki tarmoq", "sayt 0/3"):
        assert needle in t, needle
    assert "admin huquqi" in call("moderatsiya")["text"] and "faqat guruhda" in call("moderatsiya")["text"]
    assert "HAQIQATAN" in call("xotira")["text"] and "Plus" in call("tarif")["text"]
    assert "post_story" in call("guruh")["text"] and "instagram_publish" in call("instagram")["text"]


def test_tool_is_wired_into_dispatch_labels_and_chat():
    assert "bot_capabilities" in ai_tools.DISPATCH and "bot_capabilities" in ai_tools._TOOL_STATUS_LABELS
    src = open("handlers/ai_chat.py", encoding="utf-8").read()
    assert "capabilities.SCHEMA" in src and "capabilities.state_line(user_id, is_group)" in src


# ── buyruqlar yig'ishtirildi ───────────────────────────────────────────────────
def test_gh_and_site_commands_are_gone_everywhere():
    import core.bot_commands as bc
    import core.command_guard as cg
    cmds = [getattr(c, "command", None) for name in dir(bc) for c in (getattr(bc, name) if isinstance(getattr(bc, name), list) else [])]
    assert "gh" not in cmds and "site" not in cmds
    assert "gh" not in cg.KNOWN and "site" not in cg.KNOWN and "gh" not in cg.PRIVATE_ONLY and "site" not in cg.EVERYWHERE
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("handlers.site")
    import handlers.github as ghh
    assert not hasattr(ghh, "gh_cmd") and not hasattr(ghh, "HELP") and not hasattr(ghh, "LOGIN_HELP")
    assert sorted(h.callback.__name__ for h in ghh.router.message.handlers) == ["group_token", "private_token"]       # faqat token ushlagich
    assert [h.callback.__name__ for h in ghh.router.callback_query.handlers] == ["confirm_cb"]
    assert "site_router" not in open("main.py", encoding="utf-8").read() and "handlers.site" not in open("main.py", encoding="utf-8").read()


def test_no_user_facing_text_tells_people_to_use_gh_or_site_commands():
    offenders = []
    for path in ("core/github_ops.py", "core/github_tools.py", "core/github_sandbox.py", "core/github_backup.py", "core/github_intel.py", "core/site_ops.py",
                 "core/site_tools.py", "core/site_pack.py", "core/capabilities.py", "handlers/github.py", "config.py"):
        for i, line in enumerate(open(path, encoding="utf-8").read().splitlines(), 1):
            if re.search(r"(?<![\w/])/(gh|site)\b", line):
                offenders.append(f"{path}:{i}: {line.strip()[:90]}")
    assert not offenders, offenders
