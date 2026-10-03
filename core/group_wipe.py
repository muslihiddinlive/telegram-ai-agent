"""
Guruhning AI xotirasini BUTUNLAY tozalash — DB'dan haqiqatan o'chiradi, AI shunchaki
"unutdim" deb yozib qo'yishi emas.

Ikki daraja (ikkalasi ham FAQAT shu guruh uchun — boshqa guruh/foydalanuvchilarga tegmaydi):
  1) XOTIRA (standart): suhbat jurnali va xulosasi (barcha topic/thread'lar bilan), a'zolar indeksi,
     xabar statistikasi, guruhda aytilgan shaxsiy eslatmalar ("meni Mocci opa deb chaqir" kabi, group_notes).
  2) TO'LIQ RESET (full=True): yuqoridagilar + admin sozlamalari (chatmode/VIP, taqiqlangan so'zlar, guruh
     qoidalari, anti-spam/aireakmode/kunlik-top holati, ruxsatlar, ogohlantirishlar, blacklist strike'lar,
     ro'yxatga olingan kanal yozuvi) — bot go'yo bu guruhga endi qo'shilgandek bo'ladi.
Foydalanuvchining GLOBAL narsalari (rol/limit, shaxsiy chat eslatmalari, /laqab taxallusi) guruhga
tegishli emas — tegilmaydi.

Tozalashdan OLDIN har doim .txt eksport qilinadi (chaqiruvchiga yuboriladi) — zaxira sifatida.
"""
import json
import time

import core.tgdb as tgdb

_MEM_PREFIX_SEP = ":"

# db[<bucket>][str(chat_id)] ko'rinishida saqlanadigan guruh-xotira bucket'lari
_MEMORY_BUCKETS = ("group_members", "group_stats", "group_notes")
# db[<bucket>][str(chat_id)] — admin sozlamalari (faqat full reset'da o'chadi)
_SETTINGS_BUCKETS = ("group_rules", "banned_words", "chat_mode", "auto_top_mode", "antispam_mode",
                     "ai_reaction_mode", "group_settings", "warns", "blacklist_strikes", "channels")


def _group_mem_keys(chat_id: int) -> list[str]:
    prefix = f"{chat_id}{_MEM_PREFIX_SEP}"
    return [k for k in tgdb.get().get("group_mem", {}) if k == str(chat_id) or k.startswith(prefix)]


def build_export(chat_id: int, full: bool = False) -> str:
    """Guruhga oid barcha saqlangan AI-xotirasini .txt ko'rinishida matn qilib qaytaradi.
    full=True bo'lsa admin sozlamalari ham (JSON) qo'shiladi — to'liq reset'dan oldingi zaxira."""
    db = tgdb.get()
    lines = [
        f"PARADOKS AI — GURUH XOTIRASI EKSPORTI",
        f"Chat ID: {chat_id}",
        f"Eksport vaqti: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "=" * 60,
    ]

    members = db.get("group_members", {}).get(str(chat_id), {})
    lines.append(f"\n## A'ZOLAR INDEKSI ({len(members)} kishi, bot kuzatgan)\n")
    for uid, rec in sorted(members.items(), key=lambda kv: -kv[1].get("t", 0)):
        uname = f" @{rec['u']}" if rec.get("u") else ""
        lines.append(f"- ID {uid}: {rec.get('n', '')}{uname}")

    stats = db.get("group_stats", {}).get(str(chat_id), {})
    lines.append(f"\n## XABAR STATISTIKASI ({sum(r.get('n', 0) for r in stats.values())} ta xabar)\n")
    for uid, rec in sorted(stats.items(), key=lambda kv: -kv[1].get("n", 0)):
        lines.append(f"- {rec.get('name', uid)}: {rec.get('n', 0)} ta xabar")

    notes = db.get("group_notes", {}).get(str(chat_id), {})
    lines.append(f"\n## GURUHDA AYTILGAN ESLATMALAR ({sum(len(v) for v in notes.values())} ta)\n")
    for uid, items in notes.items():
        for note in items:
            lines.append(f"- ID {uid}: {note}")

    mem_keys = _group_mem_keys(chat_id)
    lines.append(f"\n## SUHBAT JURNALI ({len(mem_keys)} ta topic/thread)\n")
    for key in mem_keys:
        mem = db["group_mem"][key]
        thread = key.split(_MEM_PREFIX_SEP, 1)[1] if _MEM_PREFIX_SEP in key else "umumiy"
        lines.append(f"\n--- Thread: {thread} ---")
        if mem.get("summary"):
            lines.append(f"[Eski xulosa]: {mem['summary']}")
        for entry in mem.get("log", []):
            if entry.get("r") == "u":
                who = entry.get("n", "?") + (f" (@{entry['u']})" if entry.get("u") else "")
                lines.append(f"{who}: {entry.get('t', '')}")
            else:
                lines.append(f"[AI]: {entry.get('t', '')}")

    if len(mem_keys) == 0 and not members and not stats and not notes:
        lines.append("\n(Bu guruh uchun hali hech qanday xotira saqlanmagan.)")

    if full:
        settings = {b: db[b][str(chat_id)] for b in _SETTINGS_BUCKETS if str(chat_id) in db.get(b, {})}
        lines.append("\n## ADMIN SOZLAMALARI (to'liq reset zaxirasi)\n")
        lines.append(json.dumps(settings, ensure_ascii=False, indent=2, default=str) if settings else "(yo'q)")

    return "\n".join(lines)


def reply_text(mode: str) -> str:
    """Tozalashdan keyin foydalanuvchiga yuboriladigan TAYYOR matn (AI'ga yozdirilmaydi — u eski kontekstni eslatib yuborishi mumkin)."""
    if mode == "full":
        return "🧹 Tayyor — bu guruh sozlamalari bilan butunlay reset qilindi, men uni yangi guruhdek ko'raman."
    return "🧹 Tayyor — bu guruh haqidagi barcha xotira o'chirildi, men hech narsani eslamayman."


def _clear_runtime(chat_id: int) -> None:
    """Jarayon xotirasidagi (DB'da emas) shu guruhga oid keshlar — aks holda reset'dan keyin ham qolib turadi."""
    import core.antispam as antispam
    import core.bot_loop_guard as bot_loop_guard
    import core.moderation as moderation

    for key in [k for k in antispam._recent if k[0] == chat_id]:
        antispam._recent.pop(key, None)
    for key in [k for k in moderation._access_cache if k[0] == chat_id]:
        moderation._access_cache.pop(key, None)
    bot_loop_guard._chain_counts.pop(chat_id, None)
    bot_loop_guard._warned_chats.discard(chat_id)


async def wipe(bot, chat_id: int, full: bool = False) -> dict:
    """Guruh ma'lumotlarini DB'dan BUTUNLAY o'chiradi (faqat shu chat_id). full=True — admin sozlamalari ham.
    Nechta yozuv o'chganini qaytaradi."""
    db = tgdb.get()
    removed = {"mem_threads": 0, "members": 0, "stats": 0, "notes": 0}

    for key in _group_mem_keys(chat_id):
        del db["group_mem"][key]
        removed["mem_threads"] += 1

    for bucket, label in (("group_members", "members"), ("group_stats", "stats")):
        removed[label] = len(db.get(bucket, {}).pop(str(chat_id), {}))
    removed["notes"] = sum(len(v) for v in db.get("group_notes", {}).pop(str(chat_id), {}).values())

    if full:
        removed["settings"] = sum(1 for b in _SETTINGS_BUCKETS if db.get(b, {}).pop(str(chat_id), None) is not None)

    _clear_runtime(chat_id)
    await tgdb.save(bot, force=True)
    return removed


def export_file_bytes(chat_id: int, full: bool = False) -> bytes:
    return build_export(chat_id, full).encode("utf-8")
