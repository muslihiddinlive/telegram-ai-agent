"""GitHub integratsiyasi: haqiqiy git (lokal bare-repo) bilan to'liq oqim, tasdiq menejeri, kvota, token sizmasligi, handler'lar."""
import asyncio
import os
import subprocess
import time
from types import SimpleNamespace

import pytest

import core.github_api as api
import core.github_ops as ops
import core.github_sandbox as sb
import core.github_tools as gtools
import core.roles as roles
import core.tariffs as tariffs
import core.tgdb as tgdb
import handlers.github as gh_handler

U, U2, SUPER = 5, 6, 1
TOKEN = "ghp_" + "a1B2c3D4e5" * 3 + "xYz123"


def run(coro):
    return asyncio.run(coro)


def git(cwd, *args):
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout.strip()


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, reply_markup=None, **kw):
        self.sent.append({"chat_id": chat_id, "text": text, "kb": reply_markup})


@pytest.fixture
def env(monkeypatch, tmp_path):
    root = os.path.realpath(tmp_path)
    remote = os.path.join(root, "remote")
    # remote: octo/hello.git (bare) + boshlang'ich commit
    bare = os.path.join(remote, "octo", "hello.git")
    os.makedirs(bare)
    git(bare, "init", "--bare", "-b", "main")
    seed = os.path.join(root, "seed")
    git(root, "clone", "-q", bare, seed)
    git(seed, "checkout", "-q", "-b", "main")
    open(os.path.join(seed, "README.md"), "w").write("# hello\n")
    git(seed, "add", "-A"); git(seed, "commit", "-q", "-m", "init"); git(seed, "push", "-q", "origin", "main")

    monkeypatch.setattr(sb, "ROOT", os.path.join(root, "data"))
    monkeypatch.setattr(sb, "GIT_BASE", "file://" + remote)
    monkeypatch.setattr(sb, "ALLOW_PROTOCOL", "file")
    data = {"admins": {}, "users": {}, "subscriptions": {}, "ai_sessions": {}}
    monkeypatch.setattr(tgdb, "_cache", data)

    async def noop(bot, force=False):
        return None
    monkeypatch.setattr(tgdb, "save", noop)
    monkeypatch.setattr(roles.config, "SUPERADMIN_ID", SUPER)
    ops._PENDING.clear()

    async def whoami(token):
        return {"login": "octo", "id": 42, "name": "Octo", "scopes": ["repo"], "classic": True, "expires": None}

    async def get_repo(token, o, r):
        return {"full_name": f"{o}/{r}", "private": True, "default_branch": "main", "size_kb": 10, "permissions": {}}

    monkeypatch.setattr(api, "whoami", whoami)
    monkeypatch.setattr(api, "get_repo", get_repo)
    return SimpleNamespace(root=root, bare=bare, bot=FakeBot())


def connect(env, uid=U):
    return run(ops.connect(env.bot, uid, TOKEN))


def R(env, name, args, uid=U, private=True):
    return run(ops.run(name, uid, args, bot=env.bot, chat_id=uid, private=private))


def cloned(env):
    connect(env)
    r = R(env, "gh_clone", {"repo": "octo/hello"})
    assert r.get("ok"), r
    return sb.repo_dir(U, "octo", "hello")


# ── hisob ──────────────────────────────────────────────────────────────────────
def test_connect_encrypts_token_and_rejects_bad_format(env):
    me = connect(env)
    assert me["login"] == "octo" and me["warnings"]
    stored = tgdb.get()["ai_sessions"][str(U)]["github_token"]
    assert TOKEN not in stored and TOKEN not in str(tgdb.get()["github"])          # na DB'da, na meta'da ochiq emas
    assert ops.get_token(U) == TOKEN and ops.identity(U) == ("octo", "42+octo@users.noreply.github.com")
    with pytest.raises(sb.GitHubError):
        run(ops.connect(env.bot, U2, "not-a-token"))
    assert not ops.is_connected(U2)


def test_not_connected_and_group_are_refused(env):
    r = R(env, "gh_status", {})
    assert "/gh login" in r["error"]
    connect(env)
    assert "shaxsiy chat" in R(env, "gh_status", {}, private=False)["error"]
    assert "Noma'lum" in R(env, "gh_nope", {})["error"]


# ── to'liq oqim: klon → tahrir → commit → push (tasdiq bilan) ───────────────────
def test_full_flow_with_confirmed_push(env):
    path = cloned(env)
    assert R(env, "gh_read_file", {"repo": "hello", "path": "README.md"})["text"].startswith("1: # hello")
    assert R(env, "gh_write_file", {"repo": "hello", "path": "src/app.py", "content": "print('hi')\n"})["ok"]
    assert R(env, "gh_edit_file", {"repo": "hello", "path": "README.md", "old": "# hello", "new": "# hello world"})["ok"]
    assert R(env, "gh_branch", {"repo": "hello", "action": "create", "name": "feat/x"})["ok"]
    c = R(env, "gh_commit", {"repo": "hello", "message": "add app"})
    assert c["ok"], c
    assert git(path, "log", "-1", "--format=%an <%ae>") == "octo <42+octo@users.noreply.github.com>"   # muallif — foydalanuvchining o'zi

    before = git(env.bare, "rev-parse", "--verify", "-q", "refs/heads/feat/x") if False else None
    r = R(env, "gh_push", {"repo": "hello"})
    assert r["pending_confirmation"] and len(env.bot.sent) == 1
    sent = env.bot.sent[0]
    assert "Push" in sent["text"] and "feat/x" in sent["text"] and "add app" in sent["text"] and "src/app.py" in sent["text"]
    assert [b.callback_data for row in sent["kb"].inline_keyboard for b in row][0].startswith("gh:ok:")
    # tasdiqlanmaguncha remote'ga HECH NARSA bormaydi
    assert subprocess.run(["git", "rev-parse", "--verify", "-q", "refs/heads/feat/x"], cwd=env.bare).returncode != 0
    pid = next(iter(ops._PENDING))
    p = ops.pop_pending(pid, U)
    res = run(ops.execute_pending(env.bot, U, p))
    assert res["ok"], res
    assert git(env.bare, "log", "-1", "--format=%s", "refs/heads/feat/x") == "add app"
    assert tariffs.quota_used(U, tariffs.KIND_GITHUB) == 2      # clone + push (tasdiqdan keyin) sanaldi, push-so'rovning o'zi emas


def test_push_toctou_new_commit_after_confirmation_is_refused(env):
    path = cloned(env)
    R(env, "gh_branch", {"repo": "hello", "action": "create", "name": "evil"})
    R(env, "gh_write_file", {"repo": "hello", "path": "a.txt", "content": "ok"})
    R(env, "gh_commit", {"repo": "hello", "message": "good"})
    assert R(env, "gh_push", {"repo": "hello"})["pending_confirmation"]
    p = ops.pop_pending(next(iter(ops._PENDING)), U)
    # tasdiqdan KEYIN (AI/prompt-injection) yana commit qo'shiladi
    R(env, "gh_write_file", {"repo": "hello", "path": "backdoor.txt", "content": "x"})
    R(env, "gh_commit", {"repo": "hello", "message": "sneaky"})
    res = run(ops.execute_pending(env.bot, U, p))
    assert "o'zgargan" in res["error"]
    assert subprocess.run(["git", "rev-parse", "--verify", "-q", "refs/heads/evil"], cwd=env.bare).returncode != 0


def test_force_push_to_default_branch_is_refused(env):
    cloned(env)
    assert "taqiqlangan" in R(env, "gh_push", {"repo": "hello", "branch": "main", "force": True})["error"]


def test_push_preview_warns_about_secrets_and_workflows(env):
    cloned(env)
    R(env, "gh_branch", {"repo": "hello", "action": "create", "name": "ci"})
    R(env, "gh_write_file", {"repo": "hello", "path": ".github/workflows/x.yml", "content": "on: push\n"})
    R(env, "gh_write_file", {"repo": "hello", "path": ".env", "content": f"TOKEN={TOKEN}\n"})
    c = R(env, "gh_commit", {"repo": "hello", "message": "oops"})
    assert c["secret_warning"] and "maxfiy" in c["text"].lower()
    R(env, "gh_push", {"repo": "hello"})
    text = env.bot.sent[-1]["text"]
    assert "workflow" in text.lower() and "GitHub token" in text


def test_hooks_never_run_and_commit_is_clean(env):
    path = cloned(env)
    marker = os.path.join(env.root, "PWNED")
    hook = os.path.join(path, ".git", "hooks", "pre-commit")
    open(hook, "w").write(f"#!/bin/sh\ntouch {marker}\n"); os.chmod(hook, 0o755)
    R(env, "gh_write_file", {"repo": "hello", "path": "x.txt", "content": "1"})
    assert R(env, "gh_commit", {"repo": "hello", "message": "m"})["ok"]
    assert not os.path.exists(marker)


# ── gh_git filtri va tasdiq ────────────────────────────────────────────────────
def test_generic_git_blocked_and_destructive_requires_confirmation(env):
    cloned(env)
    for args in (["push", "origin", "main"], ["rebase", "-x", "id"], ["log", "--output=/tmp/x"], ["config", "user.name", "x"]):
        assert "error" in R(env, "gh_git", {"repo": "hello", "args": args})
    assert R(env, "gh_git", {"repo": "hello", "args": ["log", "--oneline"]})["ok"]
    R(env, "gh_write_file", {"repo": "hello", "path": "junk.txt", "content": "x"})
    r = R(env, "gh_git", {"repo": "hello", "args": ["clean", "-fd"]})
    assert r["pending_confirmation"] and os.path.exists(os.path.join(sb.repo_dir(U, "octo", "hello"), "junk.txt"))


def test_tools_cannot_escape_repo(env):
    path = cloned(env)
    for bad in ("../../../etc/passwd", "/etc/passwd", ".git/config", ".git/hooks/pre-commit", "a/../../x"):
        assert "error" in R(env, "gh_write_file", {"repo": "hello", "path": bad, "content": "x"})
        assert "error" in R(env, "gh_read_file", {"repo": "hello", "path": bad})
    os.symlink("/etc/hostname", os.path.join(path, "sl"))
    assert "error" in R(env, "gh_read_file", {"repo": "hello", "path": "sl"})
    assert "error" in R(env, "gh_clone", {"repo": "../../etc"})
    assert "error" in R(env, "gh_commit", {"repo": "hello", "message": "x", "paths": ["../x"]})


def test_remove_local_requires_confirmation(env):
    path = cloned(env)
    assert R(env, "gh_remove_local", {"repo": "hello"})["pending_confirmation"] and os.path.isdir(path)
    p = ops.pop_pending(next(iter(ops._PENDING)), U)
    assert run(ops.execute_pending(env.bot, U, p))["ok"] and not os.path.exists(path)


# ── tasdiq menejeri ────────────────────────────────────────────────────────────
def test_pending_is_owner_only_one_shot_expiring_and_capped(env):
    connect(env)
    p = ops.new_pending(U, "gh_push", {}, {}, "x")
    assert ops.pop_pending(p.id, U2) is None                 # boshqa odam ololmaydi
    assert ops.pop_pending(p.id, U) is p and ops.pop_pending(p.id, U) is None      # bir martalik
    old = ops.new_pending(U, "gh_push", {}, {}, "x")
    old.created = time.time() - ops.CONFIRM_TTL - 1
    assert ops.pop_pending(old.id, U) is None                # muddati o'tgan
    for _ in range(ops.MAX_PENDING_PER_USER):
        ops.new_pending(U, "gh_push", {}, {}, "x")
    with pytest.raises(sb.GitHubError):
        ops.new_pending(U, "gh_push", {}, {}, "x")


def test_disconnect_wipes_everything(env):
    path = cloned(env)
    ops.new_pending(U, "gh_push", {}, {}, "x")
    run(ops.disconnect(env.bot, U))
    assert not ops.is_connected(U) and not os.path.exists(path) and not ops._PENDING
    assert "github_token" not in tgdb.get()["ai_sessions"].get(str(U), {})


# ── kvota ──────────────────────────────────────────────────────────────────────
def test_quota_blocks_network_ops_only_and_counts_successes(env):
    connect(env)
    rec = roles._bucket(U)
    limit = tariffs.quota_limit(U, tariffs.KIND_GITHUB)
    assert limit == 10                                         # bepul tarif
    rec["github_today"], rec["last_reset"] = limit, roles.today_str()
    r = R(env, "gh_clone", {"repo": "octo/hello"})
    assert r["kvota_tugadi"] == "github" and not os.path.exists(sb.repo_dir(U, "octo", "hello"))
    assert R(env, "gh_local_repos", {})["ok"]                  # lokal amallar kvotasiz
    rec["github_today"] = 0
    assert R(env, "gh_clone", {"repo": "octo/hello"})["ok"] and rec["github_today"] == 1
    assert "error" in R(env, "gh_clone", {"repo": "octo/hello"}) and rec["github_today"] == 1     # xato sanalmaydi


def test_staff_unlimited_and_no_double_counting_in_ai_dispatch(env):
    assert tariffs.quota_limit(SUPER, tariffs.KIND_GITHUB) is None
    assert tariffs.quota_kind("gh_push", False) is None and tariffs.quota_kind("gh_clone", False) is None


# ── token sizib chiqmaydi ──────────────────────────────────────────────────────
def test_token_never_in_argv_and_env_clean(env, monkeypatch):
    seen = []
    real = asyncio.create_subprocess_exec

    async def spy(*cmd, **kw):
        seen.append((list(cmd), dict(kw["env"])))
        return await real(*cmd, **kw)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spy)
    monkeypatch.setenv("BOT_TOKEN", "SENTINEL-BOT"); monkeypatch.setenv("ENCRYPTION_KEY", "SENTINEL-KEY")
    cloned(env)
    R(env, "gh_branch", {"repo": "hello", "action": "create", "name": "b"})
    assert seen
    for cmd, e in seen:
        assert TOKEN not in " ".join(cmd) and "x-access-token" not in " ".join(cmd)
        assert not any("SENTINEL" in v for v in e.values())
    net_envs = [e for cmd, e in seen if "clone" in cmd]
    assert net_envs and "Authorization: Basic" in net_envs[0]["GIT_CONFIG_VALUE_0"]
    local_envs = [e for cmd, e in seen if "switch" in cmd]
    assert local_envs and "GIT_CONFIG_VALUE_0" not in local_envs[0]       # lokal amalda token yo'q
    assert not any(TOKEN in open(os.path.join(dp, f), "rb").read().decode("latin1")
                   for dp, _, fs in os.walk(sb.repo_dir(U, "octo", "hello")) for f in fs if ".git/objects" not in dp)   # .git/config va fayllarda yo'q


def test_errors_are_redacted(env):
    e = ops._safe_error(sb.GitHubError(f"fatal: bad credentials {TOKEN}"), TOKEN)
    assert TOKEN not in e["error"]
    assert "ichki xato" in ops._safe_error(RuntimeError(f"boom {TOKEN}"), TOKEN)["error"].lower()


# ── AI tool qatlami ────────────────────────────────────────────────────────────
def test_ai_schemas_gated_and_handlers_refuse_groups(env):
    assert gtools.schemas_for(U) == [] and gtools.schemas_for(U, is_group=True) == []
    connect(env)
    assert len(gtools.schemas_for(U)) == len(ops.OPS) and gtools.schemas_for(U, is_group=True) == []
    ctx = {"bot": env.bot, "chat_id": -100, "is_group": True}
    assert "shaxsiy chat" in run(gtools.HANDLERS["gh_status"](U, {}, ctx))["error"]
    pctx = {"bot": env.bot, "chat_id": U, "is_group": False}
    assert run(gtools.HANDLERS["gh_local_repos"](U, {}, pctx))["ok"]
    import core.ai_tools as ai_tools
    assert set(ops.OPS) <= set(ai_tools.DISPATCH)
    assert "GitHub" in gtools.connect_hint(U2, "github'dagi repo'ni ko'r") and not gtools.connect_hint(U2, "salom")


def test_pr_and_merge_need_confirmation_and_bind_sha(env, monkeypatch):
    cloned(env)
    calls = []

    async def create_pr(token, o, r, title, head, base, body, draft):
        calls.append(("pr", title, head, base)); return {"number": 7, "html_url": "https://x/7"}

    async def get_pr(token, o, r, n):
        return {"number": n, "title": "T", "state": "open", "head": "feat", "base": "main", "head_sha": "abc123", "user": "octo", "mergeable": True}

    async def merge_pr(token, o, r, n, method, sha):
        calls.append(("merge", n, method, sha)); return {"merged": True, "message": "ok"}

    monkeypatch.setattr(api, "create_pr", create_pr); monkeypatch.setattr(api, "get_pr", get_pr); monkeypatch.setattr(api, "merge_pr", merge_pr)
    assert R(env, "gh_create_pr", {"repo": "hello", "title": "My <b>PR</b>", "head": "feat"})["pending_confirmation"]
    assert "My &lt;b&gt;PR&lt;/b&gt;" in env.bot.sent[-1]["text"] and not calls          # HTML-injection escape; tasdiqsiz chaqirilmadi
    assert R(env, "gh_merge_pr", {"repo": "hello", "number": 7, "method": "squash"})["pending_confirmation"] and not calls
    for p in list(ops._PENDING.values()):
        assert run(ops.execute_pending(env.bot, U, ops.pop_pending(p.id, U)))["ok"]
    assert ("pr", "My <b>PR</b>", "feat", "main") in calls and ("merge", 7, "squash", "abc123") in calls     # merge — tasdiq paytidagi SHA bilan


# ── Telegram handler'lari ──────────────────────────────────────────────────────
def fake_message(text, chat_type="private", uid=U, bot=None):
    out = {"deleted": False, "answers": []}

    async def delete():
        out["deleted"] = True

    async def answer(t, **kw):
        out["answers"].append(t)

    m = SimpleNamespace(text=text, chat=SimpleNamespace(type=chat_type, id=uid if chat_type == "private" else -100), from_user=SimpleNamespace(id=uid),
                        bot=bot, delete=delete, answer=answer)
    return m, out


def test_private_token_message_is_deleted_saved_and_never_echoed(env):
    m, out = fake_message(f"mana tokenim {TOKEN} iltimos clone qil", bot=env.bot)
    run(gh_handler.private_token(m))
    assert out["deleted"] and ops.is_connected(U)
    reply = " ".join(out["answers"])
    assert TOKEN not in reply and "octo" in reply and "AI'ga yuborilmadi" in reply


def test_private_token_invalid_is_reported_without_echo(env, monkeypatch):
    async def bad(token):
        raise sb.GitHubError(f"Token yaroqsiz {token}")
    monkeypatch.setattr(api, "whoami", bad)
    m, out = fake_message(TOKEN, bot=env.bot)
    run(gh_handler.private_token(m))
    assert out["deleted"] and not ops.is_connected(U) and TOKEN not in " ".join(out["answers"])


def test_group_token_is_deleted_with_warning(env):
    m, out = fake_message(TOKEN, chat_type="supergroup", bot=env.bot)
    run(gh_handler.group_token(m))
    assert out["deleted"] and "revoke" in out["answers"][0] and TOKEN not in out["answers"][0] and not ops.is_connected(U)


def test_gh_command_private_only_and_parsing(env):
    from aiogram.filters import CommandObject
    m, out = fake_message("/gh help", chat_type="supergroup", bot=env.bot)
    run(gh_handler.gh_cmd(m, CommandObject(command="gh", args="repos")))
    assert "shaxsiy chat" in out["answers"][0]
    m, out = fake_message("/gh", bot=env.bot)
    run(gh_handler.gh_cmd(m, CommandObject(command="gh", args='clone "unterminated')))
    assert "Qo'shtirnoq" in out["answers"][0]
    run(gh_handler.gh_cmd(m, CommandObject(command="gh", args="")))
    assert "GitHub" in out["answers"][-1]
    run(gh_handler.gh_cmd(m, CommandObject(command="gh", args="nope")))
    assert "Noma'lum" in out["answers"][-1]
    run(gh_handler.gh_cmd(m, CommandObject(command="gh", args="clone")))
    assert "Format" in out["answers"][-1]
    assert gh_handler._flag(["a", "--base", "x", "b"], "--base", True) == ("x", ["a", "b"])
    with pytest.raises(sb.GitHubError):
        gh_handler._flag(["a", "--base"], "--base", True)


def fake_call(data, uid=U, chat_type="private"):
    st = {"alerts": [], "edits": []}

    async def answer(text=None, show_alert=False):
        st["alerts"].append((text, show_alert))

    async def edit_text(text, **kw):
        st["edits"].append(text)

    async def edit_reply_markup(**kw):
        pass

    msg = SimpleNamespace(chat=SimpleNamespace(type=chat_type, id=uid), edit_text=edit_text, edit_reply_markup=edit_reply_markup)
    return SimpleNamespace(data=data, from_user=SimpleNamespace(id=uid), message=msg, answer=answer), st


def test_confirm_callback_owner_only_group_refused_and_replay_proof(env):
    path = cloned(env)
    R(env, "gh_remove_local", {"repo": "hello"})
    pid = next(iter(ops._PENDING))
    c, st = fake_call(f"gh:ok:{pid}", uid=U2)                        # boshqa odam
    run(gh_handler.confirm_cb(c, env.bot))
    assert st["alerts"][0][1] and os.path.isdir(path) and pid in ops._PENDING
    c, st = fake_call(f"gh:ok:{pid}", chat_type="supergroup")        # guruh
    run(gh_handler.confirm_cb(c, env.bot))
    assert st["alerts"][0][1] and os.path.isdir(path)
    c, st = fake_call("gh:zz:" + pid)
    run(gh_handler.confirm_cb(c, env.bot))
    assert st["alerts"][0][0] == "Noto'g'ri so'rov"
    c, st = fake_call(f"gh:ok:{pid}")                                # egasi
    run(gh_handler.confirm_cb(c, env.bot))
    assert not os.path.exists(path) and any("✅" in e for e in st["edits"])
    c, st = fake_call(f"gh:ok:{pid}")                                # replay
    run(gh_handler.confirm_cb(c, env.bot))
    assert "eskirgan" in st["alerts"][0][0]
    R(env, "gh_clone", {"repo": "octo/hello"}); R(env, "gh_remove_local", {"repo": "hello"})
    pid = next(iter(ops._PENDING))
    c, st = fake_call(f"gh:no:{pid}")
    run(gh_handler.confirm_cb(c, env.bot))
    assert os.path.isdir(sb.repo_dir(U, "octo", "hello")) and "Bekor" in st["edits"][0] and not ops._PENDING


def test_confirmation_shows_full_body_so_nothing_can_hide_in_the_tail(env, monkeypatch):
    cloned(env)
    body = "A" * 2400 + "SECRET-TAIL"
    r = R(env, "gh_create_issue", {"repo": "hello", "title": "t", "body": body})
    assert r["pending_confirmation"] and "SECRET-TAIL" in env.bot.sent[-1]["text"]      # to'liq ko'rsatiladi
    assert "error" in R(env, "gh_create_issue", {"repo": "hello", "title": "t", "body": "B" * 2600})   # ko'rsatib bo'lmaydigan uzunlik rad etiladi
