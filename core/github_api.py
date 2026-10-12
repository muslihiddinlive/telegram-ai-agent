"""
core/github_api.py
------------------
GitHub REST API mijozi (httpx). Token faqat Authorization header'ida, hech qachon URL/log/xatoda emas.
Hamma xatolar `GitHubError` ga o'giriladi (matnida token bo'lmaydi). Transport `_send` — testlarda almashtiriladi.
"""
from __future__ import annotations

import logging
from urllib.parse import quote

import httpx

from core.github_sandbox import GitHubError, redact

logger = logging.getLogger("github_api")

API = "https://api.github.com"
TIMEOUT = 25
MAX_ITEMS = 30


async def _send(token: str, method: str, path: str, params: dict | None, body: dict | None) -> tuple[int, object, dict]:
    if not path.startswith("/") or "://" in path:
        raise GitHubError("Ichki xato: API yo'li noto'g'ri.")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "telegram-ai-agent-bot"}
    try:
        # follow_redirects=False: Authorization header boshqa hostga ketib qolmasin
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False) as c:
            r = await c.request(method, API + path, params=params, json=body, headers=headers)
    except httpx.HTTPError:
        raise GitHubError("GitHub bilan aloqa o'rnatilmadi. Birozdan keyin qayta urinib ko'ring.")
    try:
        data = r.json() if r.content else {}
    except ValueError:
        data = {}
    return r.status_code, data, dict(r.headers)


def _fail(status: int, data, token: str) -> GitHubError:
    msg = ""
    if isinstance(data, dict):
        msg = str(data.get("message") or "")
        errs = data.get("errors")
        if isinstance(errs, list) and errs:
            msg += " — " + "; ".join(str(e.get("message") or e) if isinstance(e, dict) else str(e) for e in errs[:3])
    msg = redact(msg, token)[:300]
    base = {
        401: "Token yaroqsiz yoki muddati tugagan. /gh login bilan yangisini kiriting.",
        403: "Ruxsat yo'q yoki limit tugadi (tokenda kerakli ruxsat bo'lmasligi mumkin).",
        404: "Topilmadi yoki bu token uchun ruxsat yo'q (private repo bo'lsa token repo'ga kirish huquqiga ega bo'lsin).",
        409: "Ziddiyat (conflict).", 422: "GitHub so'rovni qabul qilmadi.", 429: "GitHub so'rovlar limiti tugadi, birozdan keyin urining.",
    }.get(status, f"GitHub xatosi (HTTP {status}).")
    return GitHubError(f"{base} {msg}".strip())


async def call(token: str, method: str, path: str, *, params: dict | None = None, body: dict | None = None,
               ok=(200, 201, 202, 204)) -> tuple[object, dict]:
    status, data, headers = await _send(token, method, path, params, body)
    if status not in ok:
        raise _fail(status, data, token)
    return data, headers


def _q(x: str) -> str:
    return quote(x, safe="")


# ── hisob ──────────────────────────────────────────────────────────────────────
async def whoami(token: str) -> dict:
    data, headers = await call(token, "GET", "/user")
    h = {k.lower(): v for k, v in headers.items()}
    return {"login": data.get("login"), "id": data.get("id"), "name": data.get("name"),
            "scopes": [s.strip() for s in (h.get("x-oauth-scopes") or "").split(",") if s.strip()],
            "classic": "x-oauth-scopes" in h, "expires": h.get("github-authentication-token-expiration")}


# ── repolar ────────────────────────────────────────────────────────────────────
def _repo_row(r: dict) -> dict:
    return {"full_name": r.get("full_name"), "private": r.get("private"), "default_branch": r.get("default_branch"),
            "description": (r.get("description") or "")[:120], "size_kb": r.get("size"), "fork": r.get("fork"),
            "pushed_at": r.get("pushed_at"), "archived": r.get("archived"), "html_url": r.get("html_url")}


async def list_repos(token: str, page: int = 1, per_page: int = 15) -> list[dict]:
    data, _ = await call(token, "GET", "/user/repos", params={"per_page": max(1, min(per_page, 30)), "page": max(1, min(page, 50)),
                                                              "sort": "pushed", "affiliation": "owner,collaborator,organization_member"})
    return [_repo_row(r) for r in (data if isinstance(data, list) else [])]


async def get_repo(token: str, owner: str, repo: str) -> dict:
    data, _ = await call(token, "GET", f"/repos/{_q(owner)}/{_q(repo)}")
    out = _repo_row(data)
    out["permissions"] = data.get("permissions") or {}
    return out


async def create_repo(token: str, name: str, private: bool, description: str) -> dict:
    data, _ = await call(token, "POST", "/user/repos", body={"name": name, "private": bool(private), "description": description[:300],
                                                            "auto_init": True})
    return _repo_row(data)


async def fork_repo(token: str, owner: str, repo: str) -> dict:
    data, _ = await call(token, "POST", f"/repos/{_q(owner)}/{_q(repo)}/forks", body={})
    return _repo_row(data)


async def list_branches(token: str, owner: str, repo: str) -> list[dict]:
    data, _ = await call(token, "GET", f"/repos/{_q(owner)}/{_q(repo)}/branches", params={"per_page": 50})
    return [{"name": b.get("name"), "protected": b.get("protected")} for b in (data if isinstance(data, list) else [])]


async def delete_branch(token: str, owner: str, repo: str, branch: str) -> None:
    await call(token, "DELETE", f"/repos/{_q(owner)}/{_q(repo)}/git/refs/heads/{quote(branch, safe='/')}", ok=(204,))


# ── pull request / issue / CI ──────────────────────────────────────────────────
def _pr_row(p: dict) -> dict:
    return {"number": p.get("number"), "title": (p.get("title") or "")[:150], "state": p.get("state"), "draft": p.get("draft"),
            "merged": p.get("merged"), "mergeable": p.get("mergeable"), "user": (p.get("user") or {}).get("login"),
            "head": (p.get("head") or {}).get("ref"), "head_sha": (p.get("head") or {}).get("sha"),
            "base": (p.get("base") or {}).get("ref"), "html_url": p.get("html_url")}


async def create_pr(token: str, owner: str, repo: str, title: str, head: str, base: str, body: str, draft: bool) -> dict:
    data, _ = await call(token, "POST", f"/repos/{_q(owner)}/{_q(repo)}/pulls",
                         body={"title": title, "head": head, "base": base, "body": body, "draft": bool(draft)})
    return _pr_row(data)


async def list_prs(token: str, owner: str, repo: str, state: str = "open") -> list[dict]:
    data, _ = await call(token, "GET", f"/repos/{_q(owner)}/{_q(repo)}/pulls", params={"state": state, "per_page": MAX_ITEMS})
    return [_pr_row(p) for p in (data if isinstance(data, list) else [])]


async def get_pr(token: str, owner: str, repo: str, number: int) -> dict:
    data, _ = await call(token, "GET", f"/repos/{_q(owner)}/{_q(repo)}/pulls/{int(number)}")
    return _pr_row(data)


async def merge_pr(token: str, owner: str, repo: str, number: int, method: str, sha: str) -> dict:
    data, _ = await call(token, "PUT", f"/repos/{_q(owner)}/{_q(repo)}/pulls/{int(number)}/merge",
                         body={"merge_method": method, "sha": sha})   # sha: tasdiq bergan holatdan keyin PR o'zgargan bo'lsa GitHub rad etadi
    return {"merged": data.get("merged"), "message": data.get("message")}


async def list_issues(token: str, owner: str, repo: str, state: str = "open") -> list[dict]:
    data, _ = await call(token, "GET", f"/repos/{_q(owner)}/{_q(repo)}/issues", params={"state": state, "per_page": MAX_ITEMS})
    return [{"number": i.get("number"), "title": (i.get("title") or "")[:150], "state": i.get("state"),
             "user": (i.get("user") or {}).get("login"), "labels": [l.get("name") for l in i.get("labels", []) if isinstance(l, dict)],
             "html_url": i.get("html_url")} for i in (data if isinstance(data, list) else []) if "pull_request" not in i]


async def create_issue(token: str, owner: str, repo: str, title: str, body: str) -> dict:
    data, _ = await call(token, "POST", f"/repos/{_q(owner)}/{_q(repo)}/issues", body={"title": title, "body": body})
    return {"number": data.get("number"), "html_url": data.get("html_url")}


async def comment_issue(token: str, owner: str, repo: str, number: int, body: str) -> dict:
    data, _ = await call(token, "POST", f"/repos/{_q(owner)}/{_q(repo)}/issues/{int(number)}/comments", body={"body": body})
    return {"html_url": data.get("html_url")}


async def list_runs(token: str, owner: str, repo: str, branch: str | None = None) -> list[dict]:
    params = {"per_page": 10}
    if branch:
        params["branch"] = branch
    data, _ = await call(token, "GET", f"/repos/{_q(owner)}/{_q(repo)}/actions/runs", params=params)
    runs = (data or {}).get("workflow_runs", []) if isinstance(data, dict) else []
    return [{"name": r.get("name"), "status": r.get("status"), "conclusion": r.get("conclusion"), "branch": r.get("head_branch"),
             "event": r.get("event"), "html_url": r.get("html_url"), "created_at": r.get("created_at")} for r in runs]
