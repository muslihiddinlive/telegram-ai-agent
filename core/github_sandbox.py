"""
core/github_sandbox.py
----------------------
GitHub integratsiyasining XAVFSIZLIK poydevori: foydalanuvchi kiritgan hamma narsa (repo nomi, branch, git argumentlari,
fayl yo'llari) shu yerda tekshiriladi va git FAQAT shu yerdagi `run_git()` orqali ishga tushadi.

Hujum yuzalari va himoyalar (har biri tests/test_github_*.py da tekshiriladi):
  * Shell yo'q: subprocess faqat argument RO'YXATI bilan (shell=True hech qachon).
  * Muhit tozalangan: git'ga os.environ BERILMAYDI (BOT_TOKEN, ENCRYPTION_KEY, AI kalitlar sizib chiqmaydi); token faqat
    GIT_CONFIG_* env orqali, faqat https://github.com/ uchun `http.extraheader` sifatida beriladi — argumentda ham,
    .git/config'da ham, URL'da ham BO'LMAYDI (ps/proc argv orqali ko'rinmaydi, redirect bo'lsa boshqa hostga ketmaydi).
  * Hooklar o'chiq (core.hooksPath=/dev/null), fsmonitor/pager/editor/credential helper/submodule o'chiq, symlink'lar
    oddiy fayl sifatida (core.symlinks=false) — klon qilingan repo ichidan sandbox'dan chiqib bo'lmaydi.
  * Faqat https://github.com/<owner>/<repo>: URL o'zimiz quramiz (foydalanuvchi URL bermaydi) — SSRF/ext::/file:// yo'q.
  * Umumiy `git` buyrug'i: faqat ruxsat etilgan subkomandalar, xavfli flaglar (-c, --exec, --upload-pack, --output,
    --no-index ...) va sandbox'dan chiqaruvchi yo'llar (absolyut, '..', ~) rad etiladi.
  * Fayl yo'llari repo ichida qulflangan (realpath + symlink + `.git` ichiga tegish taqiqlangan).
  * Resurs chegaralari: timeout, chiqish hajmi, bir vaqtda 3 ta jarayon, foydalanuvchiga disk kvotasi va repo soni.
  * Barcha chiqishdan token (aniq qiymat va ghp_/github_pat_ shakllari) tozalanadi.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import re
import shutil
import signal
import time
from dataclasses import dataclass

logger = logging.getLogger("github_sandbox")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "github"))
GIT_BASE = "https://github.com"          # testlarda lokal bare-repo bilan almashtiriladi
ALLOW_PROTOCOL = "https"                 # testlarda "file" (production'da HECH QACHON o'zgartirilmaydi)
TOKEN_HOST_PREFIX = "https://github.com/"

NET_TIMEOUT = 150
LOCAL_TIMEOUT = 40
MAX_OUTPUT = 30_000            # AI/foydalanuvchiga qaytariladigan matn chegarasi
MAX_STREAM = 2 * 1024 * 1024   # jarayon shundan ko'p yozsa — to'xtatiladi
MAX_REPO_KB = 150_000          # GitHub API "size" (KB): ~150 MB dan katta repo klon qilinmaydi
USER_DISK_LIMIT = 400 * 1024 * 1024
MAX_REPOS_PER_USER = 5
MAX_READ_BYTES = 200_000
MAX_WRITE_BYTES = 500_000
MAX_LIST_ENTRIES = 300
STALE_DAYS = 3
_MAX_PROCS = asyncio.Semaphore(3)
_user_locks: dict[int, asyncio.Lock] = {}


class GitHubError(Exception):
    """Foydalanuvchiga ko'rsatsa bo'ladigan xato (ichida sir yo'q)."""


# ── Token shakllari va tozalash ────────────────────────────────────────────────
TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_])(gh[pousr]_[A-Za-z0-9]{30,255}|github_pat_[A-Za-z0-9_]{50,255})(?![A-Za-z0-9_])")


def find_token(text: str | None) -> str | None:
    m = TOKEN_RE.search(text or "")
    return m.group(1) if m else None


def redact(text: str, token: str | None = None) -> str:
    """Matndan token (aniq qiymat, base64 header va umumiy ghp_/github_pat_ shakllari) olib tashlanadi."""
    text = text or ""
    if token:
        text = text.replace(token, "***")
        text = text.replace(base64.b64encode(f"x-access-token:{token}".encode()).decode(), "***")
    return TOKEN_RE.sub("***", text)


def clip(text: str, limit: int = MAX_OUTPUT) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n… (kesildi, jami {len(text)} belgi)"


# ── Validatorlar ───────────────────────────────────────────────────────────────
_OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
_REPO_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
_SHA_RE = re.compile(r"^[0-9a-f]{7,64}$")
_URL_RE = re.compile(r"^https://(?:www\.)?github\.com/([^/\s]+)/([^/\s?#]+?)(?:\.git)?/?$", re.I)


def parse_repo(spec: str) -> tuple[str, str]:
    """'owner/repo' yoki https://github.com/owner/repo(.git) -> (owner, repo). Boshqa hamma narsa rad etiladi."""
    s = (spec or "").strip()
    if len(s) > 200 or any(c in s for c in "\x00\n\r\t "):
        raise GitHubError("Repo nomi noto'g'ri. Format: owner/repo")
    m = _URL_RE.match(s)
    if m:
        owner, repo = m.group(1), m.group(2)
    else:
        parts = s.split("/")
        if len(parts) != 2:
            raise GitHubError("Repo nomi noto'g'ri. Format: owner/repo (yoki https://github.com/owner/repo)")
        owner, repo = parts
        if repo.lower().endswith(".git"):
            repo = repo[:-4]
    if not _OWNER_RE.match(owner) or not _REPO_RE.match(repo) or repo in (".", "..") or repo.startswith("."):
        raise GitHubError("Repo nomi noto'g'ri. Format: owner/repo")
    return owner, repo


def valid_branch(name: str) -> str:
    n = (name or "").strip()
    bad = (not n or len(n) > 100 or n.startswith(("-", "/", ".")) or n.endswith(("/", ".", ".lock"))
           or ".." in n or "//" in n or "@{" in n or n == "@" or not re.fullmatch(r"[A-Za-z0-9._/-]+", n))
    if bad:
        raise GitHubError("Branch nomi noto'g'ri (harf, raqam, . _ - / ishlating; '-' bilan boshlanmasin).")
    return n


def valid_ref(ref: str) -> str:
    """Branch yoki commit-ish (HEAD, HEAD~3, sha, main, origin/main). Flag ko'rinishidagi yoki '..' li qiymatlar rad etiladi."""
    r = (ref or "").strip()
    if not r or len(r) > 100 or r.startswith(("-", "/", ".")) or ".." in r or "//" in r or not re.fullmatch(r"[A-Za-z0-9._/~^-]+", r):
        raise GitHubError("Ref (branch/commit) noto'g'ri.")
    return r


_SECRET_PATTERNS = (
    ("GitHub token", TOKEN_RE),
    ("Shaxsiy kalit (PRIVATE KEY)", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----")),
    ("AWS kalit", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Telegram bot token", re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b")),
    ("API kalit (sk-/gsk_/xox)", re.compile(r"\b(?:sk-[A-Za-z0-9_-]{20,}|gsk_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{10,})")),
)


def scan_secrets(text: str) -> list[str]:
    """Diff/matn ichida maxfiy kalitga o'xshash narsalar nomlari (faqat ogohlantirish uchun)."""
    return [name for name, rx in _SECRET_PATTERNS if rx.search(text or "")]


def valid_sha(sha: str) -> str:
    s = (sha or "").strip().lower()
    if not _SHA_RE.match(s):
        raise GitHubError("Commit SHA noto'g'ri.")
    return s


def valid_message(msg: str) -> str:
    m = (msg or "").replace("\x00", "").strip()
    if not m:
        raise GitHubError("Commit xabari bo'sh bo'lmasligi kerak.")
    if len(m) > 5000:
        raise GitHubError("Commit xabari juda uzun (5000 belgigacha).")
    return m


def remote_url(owner: str, repo: str) -> str:
    """Remote manzilni FAQAT o'zimiz quramiz (foydalanuvchi URL bermaydi)."""
    return f"{GIT_BASE.rstrip('/')}/{owner}/{repo}.git"


# ── Ish papkalari ──────────────────────────────────────────────────────────────
def user_root(uid: int) -> str:
    return os.path.join(ROOT, str(int(uid)))


def repos_root(uid: int) -> str:
    p = os.path.join(user_root(uid), "repos")
    os.makedirs(p, exist_ok=True)
    return p


def home_dir(uid: int) -> str:
    p = os.path.join(user_root(uid), "home")
    os.makedirs(p, exist_ok=True)
    return p


def repo_dir(uid: int, owner: str, repo: str) -> str:
    return os.path.join(repos_root(uid), f"{owner.lower()}__{repo.lower()}")


def list_local(uid: int) -> list[tuple[str, str]]:
    """[(owner, repo)] — diskdagi klonlar (kichik harflarda)."""
    out = []
    try:
        for name in sorted(os.listdir(repos_root(uid))):
            if "__" in name and os.path.isdir(os.path.join(repos_root(uid), name, ".git")):
                o, r = name.split("__", 1)
                out.append((o, r))
    except OSError:
        pass
    return out


def resolve_local(uid: int, spec: str) -> tuple[str, str, str]:
    """Foydalanuvchi bergan 'owner/repo' yoki faqat 'repo' nomini diskdagi klonga bog'laydi -> (owner, repo, yo'l)."""
    s = (spec or "").strip()
    local = list_local(uid)
    if "/" not in s and not s.startswith("http"):
        hits = [(o, r) for o, r in local if r == s.lower()]
        if len(hits) == 1:
            o, r = hits[0]
            return o, r, repo_dir(uid, o, r)
        if len(hits) > 1:
            raise GitHubError("Bu nomli bir nechta repo bor, to'liq yozing: " + ", ".join(f"{o}/{r}" for o, r in hits))
        raise GitHubError(f"'{s}' klon qilinmagan. Avval klon qiling yoki /gh ls ni ko'ring.")
    owner, repo = parse_repo(s)
    path = repo_dir(uid, owner, repo)
    if not os.path.isdir(os.path.join(path, ".git")):
        raise GitHubError(f"{owner}/{repo} klon qilinmagan. Avval klon qiling.")
    return owner.lower(), repo.lower(), path


def dir_size(path: str) -> int:
    total = 0
    for dp, _dn, files in os.walk(path):
        for f in files:
            try:
                total += os.lstat(os.path.join(dp, f)).st_size
            except OSError:
                pass
    return total


def touch(path: str) -> None:
    """Klon 'yangi' deb hisoblansin (cleanup_stale faqat uzoq tegilmaganlarni o'chiradi)."""
    try:
        os.utime(path, None)
    except OSError:
        pass


def ensure_capacity(uid: int, extra_bytes: int = 0, new_repo: bool = False) -> None:
    if new_repo and len(list_local(uid)) >= MAX_REPOS_PER_USER:
        raise GitHubError(f"Bir vaqtda {MAX_REPOS_PER_USER} tagacha repo saqlanadi. Keraksizini o'chiring (/gh rm <repo>).")
    if dir_size(user_root(uid)) + extra_bytes > USER_DISK_LIMIT:
        raise GitHubError(f"Disk kvotasi ({USER_DISK_LIMIT // 1024 // 1024} MB) to'ldi. Keraksiz repolarni o'chiring (/gh rm <repo>).")


def remove_local(uid: int, owner: str, repo: str) -> bool:
    path = repo_dir(uid, owner, repo)
    if os.path.realpath(path).startswith(os.path.realpath(repos_root(uid)) + os.sep) and os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)
        return True
    return False


def wipe_user(uid: int) -> None:
    shutil.rmtree(user_root(uid), ignore_errors=True)


def cleanup_stale(max_age_days: int = STALE_DAYS) -> int:
    """Uzoq vaqt tegilmagan klonlarni o'chiradi (bot qayta ishga tushganda). Disk to'lib ketmasligi uchun."""
    n, cutoff = 0, time.time() - max_age_days * 86400
    if not os.path.isdir(ROOT):
        return 0
    for uid in os.listdir(ROOT):
        rr = os.path.join(ROOT, uid, "repos")
        if not os.path.isdir(rr):
            continue
        for name in os.listdir(rr):
            p = os.path.join(rr, name)
            try:
                if os.path.getmtime(p) < cutoff:
                    shutil.rmtree(p, ignore_errors=True)
                    n += 1
            except OSError:
                pass
    return n


def user_lock(uid: int) -> asyncio.Lock:
    return _user_locks.setdefault(int(uid), asyncio.Lock())


# ── Fayl yo'llari (repo ichida qulflangan) ─────────────────────────────────────
def _is_git_component(part: str) -> bool:
    n = part.rstrip(" .").lower()
    return n == ".git" or n == "git~1"        # Windows/NTFS variantlari ham (.git., .git␠, GIT~1)


def safe_path(base: str, rel: str, *, allow_missing: bool = True) -> str:
    """Repo ichidagi nisbiy yo'lni xavfsiz absolyut yo'lga aylantiradi; sandbox'dan chiqish, symlink va .git — rad."""
    r = (rel or "").strip()
    if not r or "\x00" in r or r.startswith(("/", "~", "\\")) or re.match(r"^[A-Za-z]:", r) or len(r) > 400:
        raise GitHubError("Fayl yo'li noto'g'ri (repo ichidagi nisbiy yo'l bo'lsin, masalan: src/main.py).")
    parts = [p for p in r.replace("\\", "/").split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        raise GitHubError("Fayl yo'li noto'g'ri ('..' mumkin emas).")
    if any(_is_git_component(p) for p in parts):
        raise GitHubError(".git papkasiga tegish taqiqlangan.")
    base_real = os.path.realpath(base)
    cur = base_real
    for p in parts:
        cur = os.path.join(cur, p)
        if os.path.islink(cur):
            raise GitHubError("Symlink orqali yurish taqiqlangan.")
    final = os.path.realpath(cur)
    if final != base_real and not final.startswith(base_real + os.sep):
        raise GitHubError("Fayl yo'li repo'dan tashqariga chiqadi.")
    if not allow_missing and not os.path.exists(final):
        raise GitHubError("Fayl topilmadi.")
    return final


# ── Umumiy `git` buyrug'i filtri ───────────────────────────────────────────────
ALLOWED_SUBCOMMANDS = frozenset({
    "status", "log", "diff", "show", "branch", "switch", "checkout", "add", "restore", "merge", "rebase", "stash", "tag",
    "cherry-pick", "revert", "blame", "ls-files", "grep", "rm", "mv", "reset", "clean", "shortlog", "describe",
    "rev-parse", "rev-list", "diff-tree", "cat-file", "ls-tree", "reflog", "show-ref", "count-objects", "whatchanged",
})
# Subkomandadan KEYIN ham taqiqlanadigan flaglar: konfig/kod bajarish/sandbox'dan chiqish/fayl yozish imkoniyatlari
BLOCKED_FLAGS = frozenset({
    "-c", "-C", "--exec", "--exec-path", "--upload-pack", "--receive-pack", "--git-dir", "--work-tree", "--namespace",
    "--output", "--ext-diff", "--textconv", "--no-index", "--open-files-in-pager", "--super-prefix", "--config",
    "--template", "--attr-source", "--pager", "--paginate", "--bare", "--edit-todo", "--run",
})
# Faqat ayrim subkomandalarda xavfli (rebase --exec/-x kod bajaradi; -s/--strategy tashqi merge dasturini chaqirishi mumkin)
BLOCKED_BY_SUB = {
    "rebase": frozenset({"-x", "-i", "--interactive"}),
    "merge": frozenset({"-s", "--strategy"}),
    "cherry-pick": frozenset({"-s", "--strategy"}),
    "revert": frozenset({"-s", "--strategy"}),
}


def _check_path_arg(a: str) -> None:
    if a.startswith(("/", "~", "\\")) or re.match(r"^[A-Za-z]:[\\/]", a):
        raise GitHubError("Absolyut yo'l berish mumkin emas (faqat repo ichidagi nisbiy yo'llar).")
    segs = a.replace("\\", "/").split("/")
    if any(seg == ".." for seg in segs):
        raise GitHubError("'..' yo'l ishlatish mumkin emas.")
    if any(_is_git_component(seg) for seg in segs):
        raise GitHubError(".git papkasiga tegish taqiqlangan.")


def _flag_name(arg: str) -> str:
    return arg.split("=", 1)[0]


def check_generic(args: list[str]) -> tuple[str, list[str], bool]:
    """Umumiy git buyrug'ini tekshiradi -> (subkomanda, argumentlar, lokal_tasdiq_kerakmi)."""
    if not isinstance(args, list) or not args or not all(isinstance(a, str) for a in args):
        raise GitHubError("git argumentlari ro'yxat (matnlar) bo'lishi kerak.")
    if len(args) > 40 or any(len(a) > 500 or "\x00" in a or "\n" in a or "\r" in a for a in args):
        raise GitHubError("git argumentlari juda ko'p yoki noto'g'ri.")
    sub, rest = args[0], args[1:]
    if sub not in ALLOWED_SUBCOMMANDS:
        raise GitHubError(f"'{sub}' buyrug'i bu yerda ruxsat etilmagan. Ruxsat: " + ", ".join(sorted(ALLOWED_SUBCOMMANDS)))
    extra = BLOCKED_BY_SUB.get(sub, frozenset())
    short_blocked = {f[1] for f in (BLOCKED_FLAGS | extra) if len(f) == 2 and f[0] == "-"}
    for a in rest:
        if a.startswith("-") and a != "--":
            name = _flag_name(a)
            if name in BLOCKED_FLAGS or name in extra:
                raise GitHubError(f"'{name}' flagi xavfsizlik uchun taqiqlangan.")
            if not a.startswith("--") and len(a) > 1 and a[1] in short_blocked:      # -C/x, -xid kabi yopishgan shakllar ham
                raise GitHubError(f"'-{a[1]}' flagi xavfsizlik uchun taqiqlangan.")
            # Qiymat flagga yopishgan bo'lishi mumkin: --pathspec-from-file=/etc/passwd, -F/etc/passwd — uni ham yo'l sifatida tekshiramiz
            value = a.split("=", 1)[1] if a.startswith("--") and "=" in a else (a[2:] if not a.startswith("--") and len(a) > 2 else "")
            if value:
                _check_path_arg(value)
            continue
        if a == "--":
            continue
        _check_path_arg(a)
    needs_confirm = (
        sub == "clean"
        or (sub == "reset" and "--hard" in rest)
        or (sub in ("checkout", "switch") and any(a in ("-f", "--force", "-B", "--discard-changes") for a in rest))
        or (sub == "checkout" and "--" in rest)
        or sub == "restore"
        or (sub == "branch" and any(a in ("-D", "--delete", "-d") for a in rest))
        or sub == "rebase"
    )
    return sub, rest, needs_confirm


# ── git ishga tushirish ────────────────────────────────────────────────────────
@dataclass
class GitResult:
    code: int
    out: str
    err: str

    @property
    def ok(self) -> bool:
        return self.code == 0

    def text(self) -> str:
        return (self.out + (("\n" + self.err) if self.err and not self.ok else "")).strip()


_BASE_FLAGS = [
    "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "core.symlinks=false",
    "-c", "credential.helper=", "-c", "core.askPass=", "-c", "submodule.recurse=false", "-c", "diff.external=",
    "-c", "core.pager=cat", "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false", "-c", "gc.auto=0",
    "-c", "protocol.version=2", "-c", "advice.detachedHead=false", "-c", "init.defaultBranch=main",
]


def build_env(uid: int, *, token: str | None, identity: tuple[str, str] | None) -> dict[str, str]:
    """git jarayoni uchun TOZA muhit. os.environ'dan HECH NARSA olinmaydi."""
    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": home_dir(uid),
        "LC_ALL": "C.UTF-8", "LANG": "C.UTF-8",
        "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "/bin/false", "SSH_ASKPASS": "/bin/false",
        "GIT_PAGER": "cat", "PAGER": "cat", "GIT_EDITOR": "true", "GIT_SEQUENCE_EDITOR": "true", "EDITOR": "true",
        "GIT_ALLOW_PROTOCOL": ALLOW_PROTOCOL,
        "GIT_OPTIONAL_LOCKS": "0",
    }
    if identity:
        name, email = identity
        env.update({"GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email, "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email})
    if token:
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        env.update({
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": f"http.{TOKEN_HOST_PREFIX}.extraheader",
            "GIT_CONFIG_VALUE_0": f"Authorization: Basic {basic}",
        })
    return env


def _limit_child(pid: int) -> None:
    """Jarayon boshlangach unga chegara qo'yamiz (preexec_fn thread'lar bilan xavfli, shuning uchun prlimit)."""
    try:
        import resource
        big = MAX_STREAM * 150     # ~300 MB bitta fayl
        resource.prlimit(pid, resource.RLIMIT_FSIZE, (big, big))
        resource.prlimit(pid, resource.RLIMIT_CORE, (0, 0))
    except Exception:  # noqa: BLE001
        pass


async def _read_capped(stream, cap: int, proc) -> tuple[bytes, bool]:
    buf, total = bytearray(), 0
    while True:
        chunk = await stream.read(65536)
        if not chunk:
            return bytes(buf), False
        total += len(chunk)
        if total > cap:
            _kill(proc)          # juda ko'p chiqish — darhol to'xtatamiz (pipe to'lib qotib qolmasin)
            return bytes(buf), True
        buf.extend(chunk)


async def run_git(uid: int, args: list[str], *, cwd: str | None, token: str | None = None, net: bool = False,
                  identity: tuple[str, str] | None = None, timeout: int | None = None, raw: bool = False) -> GitResult:
    """git'ni xavfsiz ishga tushiradi. Hech qachon shell yo'q; chiqishdan token tozalanadi.
    raw=True — token shakllari tozalanMAYDI: FAQAT ichki maxfiy-kalit skaneri uchun (natija foydalanuvchi/AI'ga berilmaydi)."""
    if cwd is not None:
        real = os.path.realpath(cwd)
        if not real.startswith(os.path.realpath(ROOT) + os.sep):
            raise GitHubError("Ichki xato: ish papkasi noto'g'ri.")
    cmd = ["git", "--no-pager", *_BASE_FLAGS, *args]
    env = build_env(uid, token=token if net else None, identity=identity)
    limit = timeout or (NET_TIMEOUT if net else LOCAL_TIMEOUT)
    async with _MAX_PROCS:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, cwd=cwd, env=env, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, start_new_session=True)
        except FileNotFoundError:
            raise GitHubError("Serverda git o'rnatilmagan.")
        _limit_child(proc.pid)

        async def _drain():
            (o, o_over), (e, e_over) = await asyncio.gather(_read_capped(proc.stdout, MAX_STREAM, proc),
                                                            _read_capped(proc.stderr, MAX_STREAM, proc))
            return o, e, o_over or e_over

        try:
            out_b, err_b, over = await asyncio.wait_for(_drain(), timeout=limit)
            await asyncio.wait_for(proc.wait(), timeout=10)
        except asyncio.TimeoutError:
            _kill(proc)
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except Exception:  # noqa: BLE001
                pass
            raise GitHubError(f"Amal vaqti tugadi ({limit} soniya).")
        out = out_b.decode("utf-8", "replace")
        err = err_b.decode("utf-8", "replace")
        if not raw:
            out, err = redact(out, token), redact(err, token)
        elif token:
            out, err = out.replace(token, "***"), err.replace(token, "***")      # foydalanuvchining O'Z tokeni baribir tozalanadi
        if over:
            out += "\n… (chiqish juda katta, to'xtatildi)"
        return GitResult(proc.returncode if proc.returncode is not None else 1, clip(out), clip(err, 4000))


def _kill(proc) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:  # noqa: BLE001
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
