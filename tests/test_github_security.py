"""GitHub sandbox: validatorlar, git argument filtri, yo'l qulfi, muhit toza ekani, token tozalash (mock'siz, sof funksiyalar)."""
import os

import pytest

import core.github_sandbox as sb
from core.github_sandbox import GitHubError

TOKEN = "ghp_" + "a1B2c3D4e5" * 3 + "xYz123"          # 36 belgi


# ── repo / branch / ref validatsiyasi ──────────────────────────────────────────
@pytest.mark.parametrize("spec,expected", [
    ("octo/hello", ("octo", "hello")), ("octo/hello.git", ("octo", "hello")),
    ("https://github.com/octo/hello", ("octo", "hello")), ("https://github.com/octo/hello.git/", ("octo", "hello")),
    ("https://www.github.com/Octo/Hello-World_1.x", ("Octo", "Hello-World_1.x")),
])
def test_parse_repo_ok(spec, expected):
    assert sb.parse_repo(spec) == expected


@pytest.mark.parametrize("bad", [
    "", "hello", "a/b/c", "../etc", "octo/..", "octo/.", "octo/.hidden", "-evil/x", "octo/x y", "octo/x\ny", "ext::sh -c id/x",
    "file:///etc/passwd", "http://github.com/a/b", "https://evil.com/a/b", "https://github.com.evil.com/a/b", "git@github.com:a/b.git",
    "octo/" + "x" * 101, "a" * 40 + "/x", "octo/x;rm -rf", "octo/$(id)", "octo/x`id`", "https://github.com/a/b?x=1",
])
def test_parse_repo_rejects(bad):
    with pytest.raises(GitHubError):
        sb.parse_repo(bad)


@pytest.mark.parametrize("bad", ["", "-x", "--upload-pack=sh", "a..b", "a//b", "a@{u}", "/abs", ".hidden", "x.lock", "x/", "a b", "a;b", "x" * 101, "@"])
def test_branch_rejects(bad):
    with pytest.raises(GitHubError):
        sb.valid_branch(bad)


@pytest.mark.parametrize("ok", ["main", "feature/x-1", "release_1.2", "fix.v2"])
def test_branch_ok(ok):
    assert sb.valid_branch(ok) == ok


@pytest.mark.parametrize("bad", ["--output=x", "-p", "a..b", "HEAD@{1}", "x y", "", "/etc"])
def test_ref_rejects(bad):
    with pytest.raises(GitHubError):
        sb.valid_ref(bad)


def test_ref_ok():
    assert sb.valid_ref("HEAD~3") == "HEAD~3" and sb.valid_ref("origin/main") == "origin/main"


# ── umumiy git buyrug'i filtri ─────────────────────────────────────────────────
@pytest.mark.parametrize("args", [
    ["push", "origin", "main"], ["clone", "https://x"], ["fetch"], ["config", "user.name", "x"], ["remote", "add", "o", "u"],
    ["submodule", "update"], ["archive", "HEAD"], ["bisect", "run", "sh"], ["filter-branch"], ["gc"], ["worktree", "add", "x"],
    ["rebase", "-x", "touch /tmp/pwn"], ["rebase", "--exec", "id"], ["rebase", "-i", "HEAD~2"], ["merge", "-s", "x"],
    ["log", "--output=/tmp/x"], ["diff", "--no-index", "/etc/passwd", "/etc/hostname"], ["grep", "--open-files-in-pager=sh", "x"],
    ["log", "--git-dir=/etc"], ["log", "--work-tree=/"], ["diff", "--ext-diff"], ["show", "--textconv", "HEAD"], ["log", "-c"],
    ["add", "/etc/passwd"], ["add", "../x"], ["diff", "a/../../b"], ["add", ".git/config"], ["add", ".GIT/hooks/x"], ["add", "~/x"],
    ["ls-files", "dir/.git/x"], [], "log", ["log", 5], ["log", "a\nb"], ["log"] + ["x"] * 45, ["add", "C:\\Windows"],
])
def test_generic_git_rejects(args):
    with pytest.raises(GitHubError):
        sb.check_generic(args)


@pytest.mark.parametrize("args", [["status"], ["log", "--oneline", "-5", "main..feature"], ["diff", "--stat", "HEAD~1", "--", "src/a.py"],
                                  ["stash", "list"], ["show", "abc1234"], ["branch", "-vv"], ["tag"], ["grep", "-n", "TODO"], ["blame", "a.py"]])
def test_generic_git_allows_safe(args):
    sub, rest, needs = sb.check_generic(args)
    assert sub == args[0] and not needs


@pytest.mark.parametrize("args", [["reset", "--hard", "HEAD~1"], ["clean", "-fd"], ["checkout", "-f", "main"], ["checkout", "--", "a.py"],
                                  ["restore", "a.py"], ["branch", "-D", "x"], ["rebase", "main"], ["switch", "--force", "x"]])
def test_destructive_git_needs_confirmation(args):
    assert sb.check_generic(args)[2] is True


# ── fayl yo'llari ──────────────────────────────────────────────────────────────
def test_safe_path_jail(tmp_path):
    base = tmp_path / "repo"
    (base / "src").mkdir(parents=True)
    (base / "src" / "a.py").write_text("x")
    assert sb.safe_path(str(base), "src/a.py") == os.path.realpath(base / "src" / "a.py")
    assert sb.safe_path(str(base), "new/dir/f.txt").endswith("new/dir/f.txt")          # hali yo'q yo'l — yozish uchun ruxsat
    for bad in ["", "/etc/passwd", "../x", "src/../../x", "~/x", ".git/config", ".GIT/hooks/pre-commit", "a/.git/x", ".git./config",
                "GIT~1/config", "a\x00b", "C:\\x", "\\x", "x" * 500]:
        with pytest.raises(GitHubError):
            sb.safe_path(str(base), bad)
    (tmp_path / "secret.txt").write_text("TOP SECRET")
    os.symlink(str(tmp_path / "secret.txt"), base / "link.txt")
    os.symlink(str(tmp_path), base / "dirlink")
    for bad in ["link.txt", "dirlink/secret.txt"]:
        with pytest.raises(GitHubError):
            sb.safe_path(str(base), bad)
    with pytest.raises(GitHubError):
        sb.safe_path(str(base), "nope.txt", allow_missing=False)


# ── muhit va token ─────────────────────────────────────────────────────────────
def test_env_is_clean_and_token_only_scoped_header(monkeypatch, tmp_path):
    monkeypatch.setattr(sb, "ROOT", str(tmp_path))
    for k in ("BOT_TOKEN", "ENCRYPTION_KEY", "GROQ_API_KEY", "TAVILY_API_KEY"):
        monkeypatch.setenv(k, "SENTINEL-SECRET")
    env = sb.build_env(7, token=TOKEN, identity=("octo", "1+octo@users.noreply.github.com"))
    assert not any("SENTINEL-SECRET" in v for v in env.values())
    assert env["GIT_CONFIG_GLOBAL"] == "/dev/null" and env["GIT_TERMINAL_PROMPT"] == "0" and env["GIT_ALLOW_PROTOCOL"] == "https"
    assert env["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraheader"      # faqat github.com'ga
    assert TOKEN not in "".join(v for k, v in env.items() if k != "GIT_CONFIG_VALUE_0")
    assert env["GIT_AUTHOR_EMAIL"] == env["GIT_COMMITTER_EMAIL"] == "1+octo@users.noreply.github.com"
    assert "GIT_CONFIG_COUNT" not in sb.build_env(7, token=None, identity=None)
    assert env["HOME"].startswith(str(tmp_path))


def test_base_flags_disable_dangerous_features():
    flat = " ".join(sb._BASE_FLAGS)
    for needle in ("core.hooksPath=/dev/null", "core.symlinks=false", "core.fsmonitor=false", "credential.helper=", "submodule.recurse=false"):
        assert needle in flat


def test_redact_and_find_token():
    import base64
    b64 = base64.b64encode(f"x-access-token:{TOKEN}".encode()).decode()
    s = sb.redact(f"fatal: {TOKEN} bad; header {b64}; other ghp_{'Z' * 36} github_pat_{'q' * 60}", TOKEN)
    assert TOKEN not in s and b64 not in s and "ghp_" not in s and "github_pat_" not in s
    assert sb.find_token(f"mana token: {TOKEN}!") == TOKEN
    assert sb.find_token("github_pat_" + "A" * 70) is not None
    assert sb.find_token("ghp_short") is None and sb.find_token("hello world") is None and sb.find_token(None) is None


def test_secret_scanner():
    assert "GitHub token" in sb.scan_secrets("x=" + TOKEN)
    assert sb.scan_secrets("-----BEGIN OPENSSH PRIVATE KEY-----")
    assert sb.scan_secrets("AKIAABCDEFGHIJKLMNOP")
    assert sb.scan_secrets("123456789:" + "A" * 35)
    assert not sb.scan_secrets("def hello():\n    return 1")


def test_remote_url_is_built_by_us_only():
    assert sb.remote_url("octo", "hello") == "https://github.com/octo/hello.git"


@pytest.mark.parametrize("args", [
    ["stash", "push", "--pathspec-from-file=/etc/passwd"], ["add", "--pathspec-from-file=../x"], ["tag", "-F/etc/passwd", "v1"],
    ["grep", "-f/etc/passwd", "x"], ["log", "-C/x"], ["tag", "-F../secret", "v1"], ["add", "--pathspec-from-file", "/etc/passwd"],
    ["rebase", "-xid", "main"], ["rebase", "--exec=id", "main"], ["log", "--format=%H", "--output=/tmp/x"],
])
def test_generic_git_blocks_attached_values(args):
    with pytest.raises(GitHubError):
        sb.check_generic(args)


@pytest.mark.parametrize("args", [["log", "-n5", "--format=%h %s"], ["log", "--grep=fix", "--since=2.days"], ["diff", "-U3", "--stat"],
                                  ["add", "--pathspec-from-file=paths.txt"], ["tag", "-m", "release v1", "v1"]])
def test_generic_git_still_allows_normal_flags(args):
    assert sb.check_generic(args)[0] == args[0]
