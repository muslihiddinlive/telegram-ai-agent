"""
Token hisobi va kunlik hisobot (superadminga, har kuni 00:00 UTC da — kechagi kun uchun).

Hisob BITTA joyda yuritiladi: core/ai_rotator.py (chat, tool, xulosa, reaksiya, story) va core/vision.py (rasm o'qish) har bir MUVAFFAQIYATLI
AI chaqiruvidan keyin record() chaqiradi. "Kim/qayerda/nima uchun" — ContextVar orqali (har bir Telegram update o'z asyncio task'ida ishlaydi,
shuning uchun kontekst aralashmaydi): handlers/ai_chat.py chat/foydalanuvchi/guruhni belgilaydi, fon vazifalar (reaksiya, xulosa, vision, story) o'z
maqsadini qo'shadi.

Nima yoziladi (kun bo'yicha, UTC): jami kirish/chiqish tokenlari va so'rovlar; provayder|model; maqsad (chat/vision/summary/reaction/story_caption);
guruh yoki shaxsiy; guruhlar va foydalanuvchilar kesimi; AI so'ragan tool'lar (shu so'rovning tokeni tool'lar o'rtasida teng bo'linadi — taxminiy).
Foydalanuvchining O'Z kaliti bilan ketgan tokenlar ALOHIDA ("personal") — bot egasining hisobiga kirmaydi.

Aniqlik: provayder usage bermasa, token matn uzunligidan baholanadi (~4 belgi = 1 token) va hisobotda "taxminiy" deb ko'rsatiladi.
Xotira: faqat oxirgi RETENTION_DAYS kun, kuniga guruh/foydalanuvchi kesimi cheklangan (qolgani "boshqalar"ga yig'iladi) — DB (db.json) bo'sh o'smasin.
"""
from __future__ import annotations

import contextlib
import contextvars
import datetime as dt
import html
import json
import logging

import config
import core.tgdb as tgdb

logger = logging.getLogger("token_usage")

RETENTION_DAYS = 8
MAX_CHATS_PER_DAY = 100
MAX_USERS_PER_DAY = 150
OTHERS = "_boshqalar"
REPORT_ATTEMPTS = 5
PURPOSE_LABELS = {
    "chat": "💬 Suhbat (AI javoblari)",
    "vision": "👁 Rasm/video o'qish",
    "summary": "🗜 Suhbat xulosasi (xotira)",
    "reaction": "😀 Avto-reaksiya",
    "story_caption": "📝 Story izohi tahlili",
    "other": "❔ Boshqa",
}

_ctx: contextvars.ContextVar[dict] = contextvars.ContextVar("token_usage_ctx", default={})
_report_attempts: dict[str, int] = {}


# ── kontekst (kim / qayerda / nima uchun) ────────────────────────────────

def set_context(**fields) -> None:
    """Joriy task kontekstini YANGILAYDI (mavjudiga qo'shib). handlers/ai_chat.py shuni chaqiradi."""
    _ctx.set({**_ctx.get(), **{k: v for k, v in fields.items() if v is not None}})


@contextlib.contextmanager
def scope(**fields):
    """Vaqtincha kontekst qo'shadi (masalan purpose="vision"), chiqishda avvalgisini tiklaydi."""
    token = _ctx.set({**_ctx.get(), **{k: v for k, v in fields.items() if v is not None}})
    try:
        yield
    finally:
        _ctx.reset(token)


def current() -> dict:
    return dict(_ctx.get())


# ── yozish ───────────────────────────────────────────────────────────────

def _day(now: dt.datetime | None = None) -> str:
    return (now or dt.datetime.now(dt.timezone.utc)).strftime("%Y-%m-%d")


def _new_agg() -> dict:
    return {"r": 0, "p": 0, "c": 0, "est": 0, "model": {}, "purpose": {}, "scope": {}, "chat": {}, "user": {}, "tool": {}}


def _add(entry: dict, p: int, c: int) -> None:
    entry["r"] = entry.get("r", 0) + 1
    entry["p"] = entry.get("p", 0) + p
    entry["c"] = entry.get("c", 0) + c


def _add_capped(table: dict, key: str, cap: int, p: int, c: int, name: str | None = None) -> None:
    if key not in table and len(table) >= cap:
        key, name = OTHERS, "Boshqalar"
    entry = table.setdefault(key, {})
    _add(entry, p, c)
    if name:
        entry["n"] = name


def estimate_tokens(text: str | None) -> int:
    return max(0, len(text or "") // 4)


def record(provider: str, model: str | None, prompt: int, completion: int, *, personal: bool = False,
           estimated: bool = False, tools: list[str] | None = None, purpose: str | None = None,
           now: dt.datetime | None = None) -> None:
    """Bitta muvaffaqiyatli AI chaqiruvini hisobga qo'shadi. Hech qachon asosiy oqimni buzmaydi (xato yutiladi)."""
    try:
        prompt, completion = max(0, int(prompt or 0)), max(0, int(completion or 0))
        ctx = _ctx.get()
        purpose = purpose or ctx.get("purpose") or "other"
        day = _day(now)
        root = tgdb.get().setdefault("token_usage", {})
        agg = root.setdefault(day, {}).setdefault("personal" if personal else "shared", _new_agg())
        _add(agg, prompt, completion)
        agg["est"] += 1 if estimated else 0
        _add(agg["model"].setdefault(f"{provider}|{model or '?'}", {}), prompt, completion)
        _add(agg["purpose"].setdefault(purpose, {}), prompt, completion)
        chat_id = ctx.get("chat_id")
        scope_name = "group" if ctx.get("chat_type") in ("group", "supergroup") else ("private" if chat_id is not None else "system")
        _add(agg["scope"].setdefault(scope_name, {}), prompt, completion)
        if chat_id is not None:
            _add_capped(agg["chat"], str(chat_id), MAX_CHATS_PER_DAY, prompt, completion, ctx.get("chat_title"))
        if ctx.get("user_id") is not None:
            _add_capped(agg["user"], str(ctx["user_id"]), MAX_USERS_PER_DAY, prompt, completion, ctx.get("user_name"))
        if tools:
            share_p, share_c = prompt // len(tools), completion // len(tools)
            for name in tools:
                _add(agg["tool"].setdefault(str(name)[:60], {}), share_p, share_c)
        _prune(root, now)
        tgdb.mark_dirty()
    except Exception:  # noqa: BLE001
        logger.exception("Token hisobiga yozib bo'lmadi (asosiy oqim davom etadi)")


def _prune(root: dict, now: dt.datetime | None = None) -> None:
    if len(root) <= RETENTION_DAYS:
        return
    for old in sorted(root)[:-RETENTION_DAYS]:
        root.pop(old, None)


def usage_from_response(resp) -> tuple[int, int, bool]:
    """(kirish, chiqish, taxminiymi) — OpenAI/Groq/xKiro (prompt_tokens/completion_tokens) va Anthropic (input/output_tokens) uchun."""
    u = getattr(resp, "usage", None)
    if u is None and isinstance(resp, dict):
        u = resp.get("usage")
    if u is None:
        return 0, 0, True

    def pick(*names):
        for n in names:
            v = u.get(n) if isinstance(u, dict) else getattr(u, n, None)
            if isinstance(v, (int, float)):
                return int(v)
        return None

    p, c = pick("prompt_tokens", "input_tokens"), pick("completion_tokens", "output_tokens")
    if p is None and c is None:
        total = pick("total_tokens")
        return (total or 0), 0, total is None
    return p or 0, c or 0, False


def record_response(provider: str, resp, *, model: str | None = None, personal: bool = False, purpose: str | None = None,
                    est_prompt_text: str | None = None, est_completion_text: str | None = None,
                    tools: list[str] | None = None) -> None:
    """SDK javobidan usage'ni oladi; yo'q bo'lsa matn uzunligidan baholaydi."""
    p, c, est = usage_from_response(resp)
    if est:
        p, c = estimate_tokens(est_prompt_text), estimate_tokens(est_completion_text)
    record(provider, model or getattr(resp, "model", None), p, c, personal=personal, estimated=est, tools=tools, purpose=purpose)


def messages_text(messages: list[dict], tools: list[dict] | None = None) -> str:
    """Taxminiy baholash uchun so'rov matni (usage kelmagan holatda)."""
    parts = [str(m.get("content") or "") for m in messages]
    if tools:
        parts.append(json.dumps(tools, ensure_ascii=False))
    return "\n".join(parts)


# ── hisobot ──────────────────────────────────────────────────────────────

def day_data(day: str) -> dict:
    return tgdb.get().get("token_usage", {}).get(day, {})


def _tot(agg: dict | None) -> int:
    return (agg or {}).get("p", 0) + (agg or {}).get("c", 0)


def _n(x: int) -> str:
    return f"{x:,}".replace(",", " ")


def _pct(part: int, whole: int) -> str:
    return f"{part * 100 / whole:.0f}%" if whole else "0%"


def _top(table: dict, limit: int, total: int, label) -> list[str]:
    rows = sorted(table.items(), key=lambda kv: _tot(kv[1]), reverse=True)[:limit]
    return [f"  {i}. {label(k, v)} — <b>{_n(_tot(v))}</b> ({_pct(_tot(v), total)}) · {v.get('r', 0)} so'rov"
            for i, (k, v) in enumerate(rows, 1)]


def _chat_label(key: str, v: dict) -> str:
    if key == OTHERS:
        return "Boshqalar"
    name = html.escape(v.get("n") or "?")
    kind = "👥" if str(key).startswith("-") else "👤"
    return f"{kind} {name} (<code>{key}</code>)"


def _user_label(key: str, v: dict) -> str:
    return "Boshqalar" if key == OTHERS else f"{html.escape(v.get('n') or '?')} (<code>{key}</code>)"


def build_report(day: str, prev_day: str | None = None, partial: bool = False) -> list[str]:
    """Hisobot matni (HTML), Telegram limiti uchun bir necha bo'lakka bo'lingan ro'yxat."""
    data = day_data(day)
    shared, personal = data.get("shared"), data.get("personal")
    title = f"📊 <b>Token hisoboti — {day} (UTC)</b>" + (" · <i>bugun, hozirgacha</i>" if partial else "")
    if not shared and not personal:
        return [f"{title}\n\nBu kun AI so'rovlari bo'lmagan."]
    lines = [title, ""]
    if shared:
        total = _tot(shared)
        lines.append(f"🔢 <b>Jami: {_n(total)} token</b> (kirish {_n(shared['p'])} · chiqish {_n(shared['c'])}) · {_n(shared['r'])} so'rov")
        if shared["r"]:
            lines.append(f"   o'rtacha: {_n(total // shared['r'])} token/so'rov")
        prev_total = _tot((day_data(prev_day) or {}).get("shared")) if prev_day else 0
        if prev_day and prev_total:
            diff = total - prev_total
            arrow = "▲" if diff > 0 else ("▼" if diff < 0 else "▬")
            lines.append(f"   {prev_day} ga nisbatan: {arrow} {abs(diff) * 100 // prev_total}% ({'+' if diff >= 0 else '-'}{_n(abs(diff))})")
        if shared.get("est"):
            lines.append(f"   ⚠️ {shared['est']} ta so'rovda provayder token bermadi — ular taxminiy hisoblangan")
        lines += ["", "🏭 <b>Qaysi provayder/model:</b>"]
        lines += _top(shared["model"], 6, total, lambda k, v: f"<code>{html.escape(k.replace('|', ' · '))}</code>")
        lines += ["", "🎯 <b>Nimaga ketdi:</b>"]
        lines += _top(shared["purpose"], 6, total, lambda k, v: PURPOSE_LABELS.get(k, html.escape(k)))
        scopes = shared["scope"]
        lines += ["", "📍 <b>Qayerda:</b> " + " · ".join(
            f"{ {'group': '👥 guruhlar', 'private': '👤 shaxsiy chat', 'system': '⚙️ tizim/fon'}.get(k, k) } {_pct(_tot(v), total)} ({_n(_tot(v))})"
            for k, v in sorted(scopes.items(), key=lambda kv: _tot(kv[1]), reverse=True))]
        chats = {k: v for k, v in shared["chat"].items()}
        if chats:
            top_key = max(chats, key=lambda k: _tot(chats[k]) if k != OTHERS else -1)
            top = chats[top_key]
            lines += ["", f"🏆 <b>Eng ko'p sarflangan joy:</b> {_chat_label(top_key, top)} — <b>{_n(_tot(top))}</b> ({_pct(_tot(top), total)})"]
            lines += ["", "👥 <b>Top guruh/chatlar:</b>"] + _top(chats, 5, total, _chat_label)
        if shared["user"]:
            lines += ["", "🙋 <b>Eng ko'p ishlatgan foydalanuvchilar:</b>"] + _top(shared["user"], 5, total, _user_label)
        if shared["tool"]:
            lines += ["", "🛠 <b>AI chaqirgan tool'lar</b> <i>(shu so'rovlar tokeni, taxminiy bo'lingan)</i>:"]
            lines += _top(shared["tool"], 6, total, lambda k, v: f"<code>{html.escape(k)}</code>")
    if personal and personal.get("r"):
        lines += ["", f"🔑 <b>Shaxsiy kalitlar</b> (foydalanuvchilarning o'z hisobi, sizniki emas): {_n(_tot(personal))} token · {personal['r']} so'rov"]
    return _split("\n".join(lines))


def _split(text: str, limit: int = 3800) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > limit and cur:
            chunks.append(cur)
            cur = ""
        cur += line + "\n"
    return chunks + ([cur] if cur.strip() else [])


# ── 00:00 UTC da yuborish ────────────────────────────────────────────────

def _meta() -> dict:
    return tgdb.get().setdefault("token_usage_meta", {})


def due_day(now: dt.datetime | None = None) -> str | None:
    """Yuborilishi kerak bo'lgan kun (kecha, UTC) yoki None. Birinchi ishga tushishda faqat belgi qo'yiladi — bo'sh hisobot ketmasin."""
    now = now or dt.datetime.now(dt.timezone.utc)
    yesterday = _day(now - dt.timedelta(days=1))
    last = _meta().get("last_report")
    if last is None:
        _meta()["last_report"] = yesterday
        tgdb.mark_dirty()
        return None
    return yesterday if last < yesterday else None


async def send_daily_report(bot, now: dt.datetime | None = None) -> bool:
    """Scheduler har daqiqa chaqiradi. Kecha uchun hisobot hali yuborilmagan bo'lsa superadminga yuboradi.
    Bot 00:00 da o'chiq bo'lsa ham keyin yetkazadi (belgi DB'da). Xato bo'lsa REPORT_ATTEMPTS martagacha qayta uriniladi."""
    now = now or dt.datetime.now(dt.timezone.utc)
    day = due_day(now)
    if day is None:
        return False
    prev = _day(dt.datetime.strptime(day, "%Y-%m-%d") - dt.timedelta(days=1))
    try:
        for chunk in build_report(day, prev):
            await bot.send_message(config.SUPERADMIN_ID, chunk)
    except Exception as e:  # noqa: BLE001
        _report_attempts[day] = _report_attempts.get(day, 0) + 1
        logger.warning("Token hisoboti yuborilmadi (%s), urinish %d/%d", type(e).__name__, _report_attempts[day], REPORT_ATTEMPTS)
        if _report_attempts[day] < REPORT_ATTEMPTS:
            return False
        logger.error("Token hisoboti %s uchun tashlab ketildi", day)
    _meta()["last_report"] = day
    tgdb.mark_dirty()
    return True
