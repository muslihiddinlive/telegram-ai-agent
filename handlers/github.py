"""
/gh — GitHub bilan ishlash (faqat shaxsiy chat). AI tool'lari bilan BIR XIL core/github_ops.run() orqali ishlaydi.

Muhim xavfsizlik nuqtalari:
  * Token yozilgan xabar DARHOL o'chiriladi va hech qachon AI'ga/xotiraga yetib bormaydi (bu router ai_chat'dan oldin).
  * Guruhga token yuborilsa — o'chirishga urinamiz va revoke qilishni eslatamiz.
  * Tasdiq tugmalari: faqat shu foydalanuvchi, faqat shaxsiy chat, bir martalik, 10 daqiqa.
"""
from __future__ import annotations

import html
import logging
import shlex

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

import core.github_ops as ops
import core.github_sandbox as sb
import core.tariffs as tariffs
from core.github_sandbox import GitHubError

logger = logging.getLogger("handlers.github")
router = Router()

PRE_OPS = {"gh_read_file", "gh_diff", "gh_log", "gh_git", "gh_repo_status", "gh_list_files", "gh_branch"}

HELP = (
    "🐙 <b>GitHub</b> (faqat shaxsiy chatda)\n\n"
    "<b>Ulash</b>\n/gh login — tokenni ulash (xabar darhol o'chiriladi)\n/gh whoami — holat, token ruxsatlari, kvota\n"
    "/gh logout — tokenni va lokal repolarni o'chirish\n\n"
    "<b>Repolar</b>\n/gh repos [sahifa]\n/gh clone owner/repo [branch]\n/gh ls — lokal repolar\n/gh rm repo — lokal nusxani o'chirish*\n\n"
    "<b>Ko'rish</b>\n/gh st repo\n/gh log repo [soni]\n/gh diff repo [fayl]\n/gh files repo [papka]\n/gh cat repo fayl\n\n"
    "<b>O'zgartirish</b>\n/gh branch repo [yangi_nom]\n/gh switch repo branch\n/gh commit repo \"xabar\"\n"
    "/gh pull repo · /gh fetch repo\n/gh push repo [branch] [--force]*\n/gh git repo &lt;git argumentlari&gt;\n\n"
    "<b>PR / Issue / CI</b>\n/gh prs repo · /gh pr repo \"sarlavha\" [--base main] [--head branch] [--body \"matn\"]*\n"
    "/gh merge repo raqam [squash|merge|rebase]*\n/gh issues repo · /gh issue repo \"sarlavha\" [\"matn\"]*\n"
    "/gh runs repo [branch] · /gh newrepo nom [--public]* · /gh fork owner/repo*\n\n"
    "* — tugma bilan tasdiq so'raladi.\n"
    "💡 Oddiy suhbatda ham yozishingiz mumkin: «myrepo'ni klon qil, README'dagi xatoni tuzat va push qil» — AI shu amallarni bajaradi "
    "(push/PR/merge uchun baribir tasdiq tugmasi chiqadi)."
)

LOGIN_HELP = (
    "🔑 GitHub tokenini ulash\n\n1) GitHub → Settings → Developer settings → Personal access tokens. "
    "Tavsiya: <b>fine-grained</b> token (faqat kerakli repolar, Contents + Pull requests: Read/Write). "
    "Classic token bo'lsa — faqat <code>repo</code> ruxsati (va workflow fayllarga tegsangiz <code>workflow</code>).\n"
    "2) Tokenni <b>shu chatga</b> yuboring — xabar darhol o'chiriladi, token shifrlab saqlanadi va AI uni hech qachon ko'rmaydi.\n"
    "3) Ish tugagach GitHub'dan tokenni o'chiring (revoke) yoki /gh logout qiling."
)


def _fmt(name: str, res: dict) -> str:
    if res.get("error"):
        return "❌ " + html.escape(str(res["error"]), quote=False)
    if res.get("pending_confirmation"):
        return "⏳ Tasdiq tugmasi yuborildi."
    text = sb.clip(str(res.get("text") or "Bajarildi."), 3500)
    body = html.escape(text, quote=False)
    return f"<pre>{body}</pre>" if name in PRE_OPS else body


async def _exec(message: Message, name: str, args: dict) -> None:
    res = await ops.run(name, message.from_user.id, args, bot=message.bot, chat_id=message.chat.id, private=True)
    await message.answer(_fmt(name, res))


def _flag(argv: list[str], flag: str, takes_value: bool = False):
    """argv'dan --flag [qiymat] ni olib tashlab, (qiymat|bool, qolgan argv) qaytaradi."""
    if flag not in argv:
        return (None if takes_value else False), argv
    i = argv.index(flag)
    if takes_value:
        if i + 1 >= len(argv):
            raise GitHubError(f"{flag} uchun qiymat kerak.")
        val = argv[i + 1]
        return val, argv[:i] + argv[i + 2:]
    return True, argv[:i] + argv[i + 1:]


# ── Token ushlagich: ai_chat va boshqa hamma narsadan OLDIN ─────────────────────
@router.message(F.chat.type == "private", F.text.func(lambda t: bool(sb.find_token(t))))
async def private_token(message: Message):
    token = sb.find_token(message.text)
    deleted = True
    try:
        await message.delete()
    except Exception:  # noqa: BLE001
        deleted = False
    try:
        me = await ops.connect(message.bot, message.from_user.id, token)
    except GitHubError as e:
        await message.answer("❌ " + html.escape(sb.redact(str(e), token), quote=False)
                             + ("" if deleted else "\n⚠️ Tokenli xabarni o'zingiz o'chirib qo'ying."))
        return
    lines = [f"✅ GitHub ulandi: <b>{html.escape(me['login'])}</b> ({'classic' if me['classic'] else 'fine-grained'} token)."]
    lines += ["⚠️ " + html.escape(w) for w in me["warnings"]]
    if not deleted:
        lines.append("⚠️ Tokenli xabarni o'chira olmadim — uni o'zingiz o'chirib qo'ying.")
    if len(message.text.strip()) > len(token) + 8:
        lines.append("ℹ️ Xabaringizda token bor edi, shuning uchun u AI'ga yuborilmadi. Boshqa qismini qayta yozing.")
    lines.append("\nBoshlash: /gh repos · /gh clone owner/repo · yoki oddiy suhbatda so'rang. Yordam: /gh")
    await message.answer("\n".join(lines))


@router.message(F.chat.type.in_({"group", "supergroup"}), F.text.func(lambda t: bool(sb.find_token(t))))
async def group_token(message: Message):
    try:
        await message.delete()
        gone = "Xabarni o'chirdim."
    except Exception:  # noqa: BLE001
        gone = "Xabarni o'chira olmadim — o'zingiz o'chiring."
    await message.answer(f"🚨 Guruhga GitHub token yuborildi! {gone} Token OSHKOR bo'ldi hisoblanadi: "
                         f"darhol GitHub → Settings → Developer settings'dan uni o'chirib (revoke) yangisini yarating. "
                         f"Tokenni faqat menga shaxsiy chatda /gh login orqali bering.")


# ── /gh ────────────────────────────────────────────────────────────────────────
@router.message(Command("gh"))
async def gh_cmd(message: Message, command: CommandObject):
    if message.chat.type != "private":
        await message.answer("🔒 GitHub amallari faqat shaxsiy chatda ishlaydi (xavfsizlik uchun). Menga shaxsiy yozing.")
        return
    uid = message.from_user.id
    try:
        argv = shlex.split(command.args or "")
    except ValueError:
        await message.answer("❌ Qo'shtirnoqlar noto'g'ri yopilgan.")
        return
    if not argv or argv[0] in ("help", "yordam"):
        await message.answer(HELP)
        return
    sub, rest = argv[0].lower(), argv[1:]
    try:
        await _dispatch(message, uid, sub, rest)
    except GitHubError as e:
        await message.answer("❌ " + html.escape(str(e), quote=False))


async def _dispatch(message: Message, uid: int, sub: str, a: list[str]) -> None:
    def need(n: int, usage: str):
        if len(a) < n:
            raise GitHubError("Format: " + usage)

    if sub == "login":
        await message.answer(LOGIN_HELP)
    elif sub == "logout":
        if not ops.is_connected(uid) and ops.meta(uid) is None:
            await message.answer("GitHub ulanmagan.")
            return
        await ops.disconnect(message.bot, uid)
        await message.answer("✅ Token va lokal repolar o'chirildi. GitHub'dan tokenni ham revoke qilishni unutmang.")
    elif sub in ("whoami", "status", "holat"):
        await _exec(message, "gh_status", {})
    elif sub == "repos":
        await _exec(message, "gh_list_repos", {"page": a[0] if a else 1})
    elif sub == "clone":
        need(1, "/gh clone owner/repo [branch]")
        await _exec(message, "gh_clone", {"repo": a[0], "branch": a[1] if len(a) > 1 else None})
    elif sub in ("ls", "local"):
        await _exec(message, "gh_local_repos", {})
    elif sub in ("rm", "remove"):
        need(1, "/gh rm repo")
        await _exec(message, "gh_remove_local", {"repo": a[0]})
    elif sub in ("st", "stat"):
        need(1, "/gh st repo")
        await _exec(message, "gh_repo_status", {"repo": a[0]})
    elif sub == "log":
        need(1, "/gh log repo [soni]")
        await _exec(message, "gh_log", {"repo": a[0], "count": a[1] if len(a) > 1 else 10})
    elif sub == "diff":
        need(1, "/gh diff repo [fayl]")
        await _exec(message, "gh_diff", {"repo": a[0], "path": a[1] if len(a) > 1 else None})
    elif sub in ("files", "tree"):
        need(1, "/gh files repo [papka]")
        await _exec(message, "gh_list_files", {"repo": a[0], "path": a[1] if len(a) > 1 else None})
    elif sub in ("cat", "read"):
        need(2, "/gh cat repo fayl")
        await _exec(message, "gh_read_file", {"repo": a[0], "path": a[1]})
    elif sub == "branch":
        need(1, "/gh branch repo [yangi_nom]")
        await _exec(message, "gh_branch", {"repo": a[0], "action": "create" if len(a) > 1 else "list", "name": a[1] if len(a) > 1 else None})
    elif sub == "switch":
        need(2, "/gh switch repo branch")
        await _exec(message, "gh_branch", {"repo": a[0], "action": "switch", "name": a[1]})
    elif sub == "commit":
        need(2, '/gh commit repo "xabar"')
        await _exec(message, "gh_commit", {"repo": a[0], "message": " ".join(a[1:])})
    elif sub == "pull":
        need(1, "/gh pull repo")
        await _exec(message, "gh_pull", {"repo": a[0]})
    elif sub == "fetch":
        need(1, "/gh fetch repo")
        await _exec(message, "gh_fetch", {"repo": a[0]})
    elif sub == "push":
        force, a = _flag(a, "--force")
        need(1, "/gh push repo [branch] [--force]")
        await _exec(message, "gh_push", {"repo": a[0], "branch": a[1] if len(a) > 1 else None, "force": force})
    elif sub == "git":
        need(2, "/gh git repo <git argumentlari>")
        await _exec(message, "gh_git", {"repo": a[0], "args": a[1:]})
    elif sub == "prs":
        need(1, "/gh prs repo")
        await _exec(message, "gh_list_prs", {"repo": a[0]})
    elif sub == "pr":
        base, a = _flag(a, "--base", True)
        head, a = _flag(a, "--head", True)
        body, a = _flag(a, "--body", True)
        draft, a = _flag(a, "--draft")
        need(2, '/gh pr repo "sarlavha" [--base main] [--head branch] [--body "matn"] [--draft]')
        await _exec(message, "gh_create_pr", {"repo": a[0], "title": " ".join(a[1:]), "base": base, "head": head, "body": body, "draft": draft})
    elif sub == "merge":
        need(2, "/gh merge repo raqam [squash|merge|rebase]")
        await _exec(message, "gh_merge_pr", {"repo": a[0], "number": a[1], "method": a[2] if len(a) > 2 else "squash"})
    elif sub == "issues":
        need(1, "/gh issues repo")
        await _exec(message, "gh_list_issues", {"repo": a[0]})
    elif sub == "issue":
        need(2, '/gh issue repo "sarlavha" ["matn"]')
        await _exec(message, "gh_create_issue", {"repo": a[0], "title": a[1], "body": " ".join(a[2:])})
    elif sub == "runs":
        need(1, "/gh runs repo [branch]")
        await _exec(message, "gh_runs", {"repo": a[0], "branch": a[1] if len(a) > 1 else None})
    elif sub == "newrepo":
        public, a = _flag(a, "--public")
        need(1, "/gh newrepo nom [--public]")
        await _exec(message, "gh_create_repo", {"name": a[0], "private": not public, "description": " ".join(a[1:])})
    elif sub == "fork":
        need(1, "/gh fork owner/repo")
        await _exec(message, "gh_fork", {"repo": a[0]})
    else:
        await message.answer("❓ Noma'lum buyruq. Yordam: /gh")


# ── Tasdiq tugmalari ───────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("gh:"))
async def confirm_cb(call: CallbackQuery, bot: Bot):
    parts = (call.data or "").split(":", 2)
    if len(parts) != 3 or parts[1] not in ("ok", "no"):
        await call.answer("Noto'g'ri so'rov", show_alert=True)
        return
    _, act, pid = parts
    uid = call.from_user.id
    if call.message is None or call.message.chat.type != "private" or call.message.chat.id != uid:
        await call.answer("Faqat shaxsiy chatda.", show_alert=True)
        return
    p = ops.pop_pending(pid, uid)      # bir martalik; faqat egasi; muddati o'tmagan
    if p is None:
        await call.answer("Bu so'rov eskirgan yoki allaqachon ishlatilgan.", show_alert=True)
        try:
            await call.message.edit_reply_markup(reply_markup=None)
        except Exception:  # noqa: BLE001
            pass
        return
    if act == "no":
        await call.message.edit_text(f"{p.summary}\n\n❌ <b>Bekor qilindi.</b>")
        await call.answer("Bekor qilindi")
        return
    await call.answer("Bajarilmoqda…")
    await call.message.edit_text(f"{p.summary}\n\n⏳ <i>Bajarilmoqda…</i>")
    res = await ops.execute_pending(bot, uid, p)
    outcome = ("❌ " + html.escape(str(res["error"]), quote=False)) if res.get("error") else \
        "✅ " + html.escape(sb.clip(str(res.get("text") or "Bajarildi."), 1500), quote=False)
    await call.message.edit_text(f"{p.summary}\n\n{outcome}")
