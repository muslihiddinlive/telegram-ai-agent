"""
Guruh uchun UMUMIY suhbat xotirasi + a'zolar indeksi.

MUAMMO (avval): suhbat tarixi (user_id, thread_id) bo'yicha saqlanardi — ya'ni guruhda
HAR BIR ODAMNING o'z alohida tarixi bor edi. Jasur yozsa, Ummu Zaynab bilan
gaplashganingiz bot uchun umuman mavjud emas edi; bot tag/reply qilinmagan xabarlarni
esa umuman ko'rmasdi. Shuning uchun "1-2 xabardan keyin mavzu esdan chiqardi".

ENDI: har bir (guruh, topic) uchun BITTA umumiy log:
  - guruhdagi HAR BIR matnli xabar (bot tag qilinmasa ham) "Ism (@username): matn"
    ko'rinishida jimgina yozib boriladi (core/group_observer.py middleware orqali);
  - bot javoblari ham shu logga tushadi;
  - log MAX_LOG dan oshsa, eng eskilari AI yordamida rolling-summary'ga qo'shiladi.
Bundan tashqari a'zolar indeksi (username -> user_id) yuritiladi: Bot API "@username"
bo'yicha oddiy userni TOPA OLMAYDI — boshqa botlar ham shu indeks orqali topadi.
"""
import logging
import time

import core.tgdb as tgdb
import core.history_summarizer as history_summarizer
import core.nicknames as nicknames

logger = logging.getLogger("group_memory")

MAX_LOG = 60            # so'z-ma-so'z saqlanadigan oxirgi xabarlar
FOLD_BATCH = 20         # shuncha ortiqcha yig'ilgach xulosaga qo'shiladi
HARD_CAP = MAX_LOG + 3 * FOLD_BATCH   # xulosa qilib ulgurilmasa ham shundan oshirmaymiz
MAX_TEXT = 500          # bitta xabar matni (belgi)
MAX_BOT_TEXT = 800
MAX_MEMBERS = 3000      # bitta guruh uchun indeks hajmi
PASSIVE_SAVE_EVERY = 60  # soniya — DB har xabarda emas, kamida shuncha oraliqda flush bo'lsin
                         # (tgdb butun DB'ni Telegram'ga yuklaydi; faol guruhda har 5s'da yuklash xavfli)

_last_passive_save = 0.0


def clean_name(s: str | None, limit: int = 40) -> str:
    return " ".join((s or "").split())[:limit]


def label(name: str | None, username: str | None, user_id: int | None = None) -> str:
    nick = nicknames.get(user_id) if user_id else None
    name = nick or clean_name(name) or "Noma'lum"
    return f"{name} (@{username})" if username else name


# ────────────────────────── log ──────────────────────────

def _key(chat_id: int, thread_id: int | None) -> str:
    return f"{chat_id}:{thread_id if thread_id is not None else 'g'}"


def _mem(chat_id: int, thread_id: int | None) -> dict:
    db = tgdb.get()
    mem = db.setdefault("group_mem", {}).setdefault(_key(chat_id, thread_id), {"log": [], "summary": ""})
    mem.setdefault("summary", "")
    return mem


async def record_human(bot, chat_id: int, thread_id: int | None, message_id: int,
                       user, text: str):
    """Guruhdagi odam xabarini jimgina logga yozadi (javob bermaydi)."""
    global _last_passive_save
    text = (text or "").strip()
    if not text:
        return
    mem = _mem(chat_id, thread_id)
    log = mem["log"]
    if any(e.get("m") == message_id for e in log[-5:]):
        return  # takroriy (masalan, tahrirlangan/ikki marta kelgan) xabar
    log.append({
        "r": "u", "n": clean_name(user.full_name), "u": user.username, "i": user.id,
        "t": text[:MAX_TEXT], "m": message_id,
    })
    if len(log) > HARD_CAP:
        del log[: len(log) - HARD_CAP]
    _bump_stat(chat_id, user)

    now = time.monotonic()
    if now - _last_passive_save >= PASSIVE_SAVE_EVERY:
        _last_passive_save = now
        await tgdb.save(bot)


async def record_bot(bot, chat_id: int, thread_id: int | None, text: str):
    mem = _mem(chat_id, thread_id)
    mem["log"].append({"r": "a", "t": (text or "")[:MAX_BOT_TEXT]})
    if len(mem["log"]) > HARD_CAP:
        del mem["log"][: len(mem["log"]) - HARD_CAP]
    await tgdb.save(bot)


def _as_messages(entries: list[dict], exclude_mid: int | None = None) -> list[dict]:
    """Log yozuvlarini AI xabarlariga aylantiradi (ketma-ket bir xil rol birlashtiriladi)."""
    out: list[dict] = []
    for e in entries:
        if exclude_mid is not None and e.get("m") == exclude_mid:
            continue
        if e.get("r") == "u":
            role, content = "user", f"{label(e.get('n'), e.get('u'), e.get('i'))}: {e.get('t', '')}"
        else:
            role, content = "assistant", e.get("t", "")
        if not content:
            continue
        if out and out[-1]["role"] == role:
            out[-1]["content"] += "\n" + content
        else:
            out.append({"role": role, "content": content})
    return out


def build(chat_id: int, thread_id: int | None, exclude_mid: int | None = None) -> tuple[str, list[dict]]:
    """(eski xulosa, oxirgi xabarlar) — JORIY xabar (exclude_mid) chiqarib tashlanadi."""
    mem = _mem(chat_id, thread_id)
    return mem["summary"], _as_messages(mem["log"][-MAX_LOG:], exclude_mid)


async def maybe_fold(bot, chat_id: int, thread_id: int | None):
    """Log MAX_LOG+FOLD_BATCH'dan oshsa — eng eskilarini xulosaga qo'shib, logdan olib tashlaydi."""
    mem = _mem(chat_id, thread_id)
    if len(mem["log"]) <= MAX_LOG + FOLD_BATCH:
        return
    overflow = mem["log"][: len(mem["log"]) - MAX_LOG]
    mem["log"] = mem["log"][len(overflow):]
    mem["summary"] = await history_summarizer.summarize(mem["summary"], _as_messages(overflow))
    await tgdb.save(bot)


def tag_current(message, text: str, bot_id: int | None) -> str:
    """Joriy xabarni 'Ism (@user): [javob: ...] matn' ko'rinishiga keltiradi."""
    speaker = label(message.from_user.full_name, message.from_user.username, message.from_user.id)
    quote = ""
    r = message.reply_to_message
    if r is not None and (r.text or r.caption):
        if r.from_user and bot_id is not None and r.from_user.id == bot_id:
            who = "sizning (botning) xabaringiz"
        elif r.from_user:
            who = label(r.from_user.full_name, r.from_user.username, r.from_user.id)
        else:
            who = "noma'lum"
        q = " ".join((r.text or r.caption).split())[:200]
        quote = f"(reply → {who}: «{q}») "
    return f"{speaker}: {quote}{text}"


# ────────────────────────── a'zolar indeksi ──────────────────────────

def record_member(chat_id: int, user) -> bool:
    """Guruh a'zosini (ID + ism + username) indeksga yozadi. O'zgargan bo'lsa True."""
    if user is None or user.is_bot:
        return False
    idx = tgdb.get().setdefault("group_members", {}).setdefault(str(chat_id), {})
    rec = idx.get(str(user.id))
    name, uname = clean_name(user.full_name), user.username
    changed = rec is None or rec.get("n") != name or rec.get("u") != uname
    idx[str(user.id)] = {"n": name, "u": uname, "t": int(time.time())}
    if len(idx) > MAX_MEMBERS:
        for uid, _ in sorted(idx.items(), key=lambda kv: kv[1].get("t", 0))[: len(idx) - MAX_MEMBERS]:
            idx.pop(uid, None)
    return changed


def find_user_id(chat_id: int, username: str) -> tuple[int, str] | None:
    """@username -> (user_id, ism). Avval shu guruh indeksi, keyin botning umumiy foydalanuvchilari."""
    uname = username.lstrip("@").lower()
    if not uname:
        return None
    db = tgdb.get()
    for uid, rec in db.get("group_members", {}).get(str(chat_id), {}).items():
        if (rec.get("u") or "").lower() == uname:
            return int(uid), rec.get("n") or ""
    for uid, rec in db.get("users", {}).items():
        if (rec.get("username") or "").lower() == uname:
            return int(uid), rec.get("name") or ""
    return None


def candidates_by_text(chat_id: int, text: str, limit: int = 5) -> list[tuple[int, str, str | None]]:
    """Xabar matnida ismi/username'i tilga olingan a'zolar (masalan 'Jasurga mute ber')."""
    low = (text or "").lower()
    found = []
    for uid, rec in tgdb.get().get("group_members", {}).get(str(chat_id), {}).items():
        tokens = [t for t in (rec.get("n") or "").lower().split() if len(t) >= 3]
        uname = (rec.get("u") or "").lower()
        # ism o'zbekcha qo'shimchalar bilan kelishi mumkin ("Jasurga") — prefiks bo'yicha
        if any(t[:4] in low for t in tokens) or (uname and uname in low):
            found.append((rec.get("t", 0), int(uid), rec.get("n") or "", rec.get("u")))
    found.sort(reverse=True)
    return [(uid, n, u) for _, uid, n, u in found[:limit]]


# ────────────────────────── statistika (faol a'zolar) ──────────────────────────

def _stats_bucket(chat_id: int) -> dict:
    return tgdb.get().setdefault("group_stats", {}).setdefault(str(chat_id), {})


def _bump_stat(chat_id: int, user):
    rec = _stats_bucket(chat_id).setdefault(str(user.id), {"n": 0})
    rec["n"] = rec.get("n", 0) + 1
    rec["name"], rec["username"] = clean_name(user.full_name), user.username


def top_active(chat_id: int, limit: int = 10) -> list[tuple[int, str, str | None, int]]:
    """Guruhda eng ko'p yozgan (BOT KUZATGAN) a'zolar: [(user_id, ism, username, xabar_soni)]."""
    stats = _stats_bucket(chat_id)
    top = sorted(stats.items(), key=lambda kv: kv[1].get("n", 0), reverse=True)[:limit]
    return [(int(uid), label(r.get("name"), r.get("username"), int(uid)), r.get("username"), r.get("n", 0)) for uid, r in top]


def total_messages(chat_id: int) -> int:
    return sum(r.get("n", 0) for r in _stats_bucket(chat_id).values())


def recent_members(chat_id: int, limit: int = 10) -> list[tuple[int, str, str | None]]:
    idx = tgdb.get().get("group_members", {}).get(str(chat_id), {})
    top = sorted(idx.items(), key=lambda kv: kv[1].get("t", 0), reverse=True)[:limit]
    return [(int(uid), rec.get("n") or "", rec.get("u")) for uid, rec in top]
