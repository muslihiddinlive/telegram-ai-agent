"""
core/github_intel.py
--------------------
GitHub profil / repo / qidiruv ma'lumotlarini yig'ish va xulosalash (faqat OCHIQ ma'lumot, rasmiy REST API orqali).

Maxfiylik chegaralari (ataylab): commit mualliflari emaillarini YIGMAYMIZ; foydalanuvchining email'i faqat o'zi GitHub profilida
ommaviy qilgan bo'lsa chiqadi; private ma'lumot yo'q (boshqa odamlar uchun faqat public). Bio/README/tavsiflar — NOISHONCHLI matn.
"""
from __future__ import annotations

from collections import Counter

import core.github_api as api
import core.github_sandbox as sb


def _top(rows: list[dict], key: str, n: int = 5, reverse: bool = True) -> list[dict]:
    return sorted(rows, key=lambda r: (r.get(key) or ""), reverse=reverse)[:n]


def summarize_repos(rows: list[dict]) -> dict:
    owned = [r for r in rows if not r.get("fork")]
    langs = Counter(r["language"] for r in owned if r.get("language"))
    topics = Counter(t for r in owned for t in (r.get("topics") or []))
    stars = sum(int(r.get("stars") or 0) for r in owned)
    by_stars = sorted(owned, key=lambda r: int(r.get("stars") or 0), reverse=True)[:5]
    return {
        "total_public": len(rows), "owned": len(owned), "forks": len(rows) - len(owned),
        "archived": sum(1 for r in rows if r.get("archived")), "stars_total": stars,
        "forks_total": sum(int(r.get("forks") or 0) for r in owned),
        "languages": langs.most_common(8), "topics": topics.most_common(10),
        "top_starred": [{"repo": r["full_name"], "stars": r.get("stars"), "desc": r.get("description")} for r in by_stars],
        "recently_pushed": [{"repo": r["full_name"], "pushed_at": r.get("pushed_at")} for r in _top(owned, "pushed_at", 5)],
        "oldest_repo_at": min((r.get("created_at") for r in rows if r.get("created_at")), default=None),
    }


def summarize_events(events: list[dict]) -> dict:
    kinds = Counter(e["type"] for e in events if e.get("type"))
    repos = Counter(e["repo"] for e in events if e.get("repo"))
    return {"recent_events": len(events), "by_type": dict(kinds.most_common(6)), "active_repos": [r for r, _ in repos.most_common(5)],
            "last_active": max((e["at"] for e in events if e.get("at")), default=None)}


async def profile(token: str, username: str) -> dict:
    user = await api.get_user(token, username)
    login = user["login"]
    rows = await api.list_repos_filtered(token, login, "public", max_pages=3)
    orgs = await api.user_orgs(token, login)
    events = await api.user_events(token, login)
    readme = await api.get_readme(token, login, login, 2500)        # profil README: <login>/<login> repo
    return {"user": user, "repos": summarize_repos(rows), "activity": summarize_events(events), "orgs": orgs, "profile_readme": readme}


def render_profile(p: dict) -> str:
    u, r, a = p["user"], p["repos"], p["activity"]
    lines = [f"👤 {u['login']}" + (f" ({u['name']})" if u.get("name") else "") + f" — {u.get('type')}, a'zo bo'lgan: {(u.get('created_at') or '')[:10]}"]
    for label, key in (("Bio", "bio"), ("Kompaniya", "company"), ("Joy", "location"), ("Sayt", "blog"), ("Twitter/X", "twitter"), ("Email (ommaviy)", "email_public")):
        if u.get(key):
            lines.append(f"{label}: {u[key]}")
    lines.append(f"Kuzatuvchilar: {u.get('followers')}, kuzatayotgani: {u.get('following')}, public repo: {u.get('public_repos')}, gist: {u.get('public_gists')}")
    if p.get("orgs"):
        lines.append("Tashkilotlar: " + ", ".join(p["orgs"]))
    lines.append(f"Repolar (tahlil qilingan {r['total_public']} ta): o'zining {r['owned']}, fork {r['forks']}, arxivlangan {r['archived']}; "
                 f"jami ⭐ {r['stars_total']}, forklar {r['forks_total']}")
    if r["languages"]:
        lines.append("Tillar: " + ", ".join(f"{k} ({v})" for k, v in r["languages"]))
    if r["topics"]:
        lines.append("Mavzular: " + ", ".join(k for k, _ in r["topics"]))
    if r["top_starred"]:
        lines.append("Eng mashhur: " + "; ".join(f"{t['repo']} ⭐{t['stars']}" for t in r["top_starred"]))
    if r["recently_pushed"]:
        lines.append("Oxirgi faol: " + "; ".join(f"{t['repo']} ({(t['pushed_at'] or '')[:10]})" for t in r["recently_pushed"]))
    if a["recent_events"]:
        lines.append(f"Oxirgi faollik: {a['last_active'] or '—'}; {', '.join(f'{k}×{v}' for k, v in a['by_type'].items())}")
    if p.get("profile_readme"):
        lines.append("Profil README (boshi):\n" + sb.clip(p["profile_readme"], 1200))
    return "\n".join(lines)


async def repo_info(token: str, owner: str, repo: str) -> dict:
    info = await api.get_repo(token, owner, repo)
    langs = await api.repo_languages(token, owner, repo)
    total = sum(langs.values()) or 1
    readme = await api.get_readme(token, owner, repo, 5000)
    return {"repo": info, "languages": {k: round(v * 100 / total, 1) for k, v in sorted(langs.items(), key=lambda kv: -kv[1])[:8]}, "readme": readme}


def render_repo(d: dict) -> str:
    r = d["repo"]
    lines = [f"📦 {r['full_name']} ({'private' if r.get('private') else 'public'}{', fork' if r.get('fork') else ''}{', arxiv' if r.get('archived') else ''})"]
    if r.get("description"):
        lines.append(r["description"])
    lines.append(f"⭐ {r.get('stars')}  🍴 {r.get('forks')}  issues: {r.get('open_issues')}  til: {r.get('language') or '—'}  litsenziya: {r.get('license') or '—'}")
    lines.append(f"Yaratilgan: {(r.get('created_at') or '')[:10]}, oxirgi push: {(r.get('pushed_at') or '')[:10]}, hajmi: {(r.get('size_kb') or 0) // 1024} MB")
    if r.get("topics"):
        lines.append("Mavzular: " + ", ".join(r["topics"]))
    if d["languages"]:
        lines.append("Tillar: " + ", ".join(f"{k} {v}%" for k, v in d["languages"].items()))
    if r.get("homepage"):
        lines.append("Sayt: " + r["homepage"])
    if d.get("readme"):
        lines.append("README (boshi):\n" + sb.clip(d["readme"], 1500))
    return "\n".join(lines)
