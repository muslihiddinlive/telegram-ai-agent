"""
Guruhning AI xotirasini BUTUNLAY tozalash — DB'dan haqiqatan o'chiradi, AI shunchaki
"unutdim" deb yozib qo'yishi emas.

Qamrov: shu guruh haqida AI "eslab" turadigan narsalar —
  - suhbat jurnali va xulosasi (barcha topic/thread'lar bilan, core/group_memory.py)
  - a'zolar indeksi (username -> ID, core/group_memory.py)
  - xabar statistikasi (core/group_memory.py)
Bunga KIRMAYDI: admin sozlamalari (chatmode/VIP, taqiqlangan so'zlar, guruh qoidalari,
anti-spam/aireakmode holati, guruh ruxsatlari) — bular "xotira" emas, administratsiya
sozlamasi, shuning uchun tozalashda saqlanib qoladi.

Tozalashdan OLDIN har doim .txt eksport qilinadi (chaqiruvchiga yuboriladi) — zaxira sifatida.
"""
import io
import time

import core.tgdb as tgdb

_MEM_PREFIX_SEP = ":"


def _group_mem_keys(chat_id: int) -> list[str]:
    prefix = f"{chat_id}{_MEM_PREFIX_SEP}"
    return [k for k in tgdb.get().get("group_mem", {}) if k == str(chat_id) or k.startswith(prefix)]


def build_export(chat_id: int) -> str:
    """Guruhga oid barcha saqlangan AI-xotirasini .txt ko'rinishida matn qilib qaytaradi."""
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

    if len(mem_keys) == 0 and not members and not stats:
        lines.append("\n(Bu guruh uchun hali hech qanday xotira saqlanmagan.)")

    return "\n".join(lines)


async def wipe(bot, chat_id: int) -> dict:
    """Guruhning xotira ma'lumotlarini DB'dan BUTUNLAY o'chiradi. Nechta yozuv o'chganini qaytaradi."""
    db = tgdb.get()
    removed = {"mem_threads": 0, "members": 0, "stats": 0}

    for key in _group_mem_keys(chat_id):
        del db["group_mem"][key]
        removed["mem_threads"] += 1

    members = db.get("group_members", {})
    if str(chat_id) in members:
        removed["members"] = len(members.pop(str(chat_id)))

    stats = db.get("group_stats", {})
    if str(chat_id) in stats:
        removed["stats"] = len(stats.pop(str(chat_id)))

    await tgdb.save(bot, force=True)
    return removed


def export_file_bytes(chat_id: int) -> bytes:
    return build_export(chat_id).encode("utf-8")
