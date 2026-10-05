"""
core/instagram_scheduler.py
---------------------------
Rejalashtirilgan postlarni vaqti kelganda chop etadi (har 60 soniyada tekshiradi).

Ishonchlilik:
  * Chop etishdan OLDIN status 'publishing' ga o'tadi — server shu paytda qulab
    qayta ishga tushsa, post IKKI MARTA chiqib ketmaydi; 20 daqiqadan oshgan
    'publishing' yozuv 'unknown' deb belgilanib, superadminga "o'zingiz tekshiring" deyiladi.
  * Fayllar diskda (data/ig_scheduled/<id>/) saqlanadi; Render diski tozalansa,
    Telegram'dagi zaxira nusxadan (DB guruhi, ≤20 MB) qayta yuklanadi.
  * Muvaffaqiyat/xato — har doim superadminga xabar.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

import core.instagram_api as ig
import core.instagram_common as common
import core.instagram_media as media
import core.instagram_store as store

logger = logging.getLogger("instagram_scheduler")

CHECK_INTERVAL = 60
STUCK_AFTER = 20 * 60
BACKUP_MAX_BYTES = 20 * 1024 * 1024  # Bot API getFile limiti


async def notify(bot, text: str) -> None:
    try:
        import config
        await bot.send_message(config.SUPERADMIN_ID, text, parse_mode=None)
    except Exception:  # noqa: BLE001
        logger.warning("Superadminga xabar yuborilmadi")


async def backup_to_telegram(bot, path: str) -> Optional[str]:
    """Faylni DB guruhiga jimgina yuklab, file_id qaytaradi (yo'q bo'lsa None)."""
    try:
        if os.path.getsize(path) > BACKUP_MAX_BYTES:
            return None
        import config
        from aiogram.types import FSInputFile
        msg = await bot.send_document(config.DB_GROUP_ID, FSInputFile(path), disable_notification=True)
        return msg.document.file_id
    except Exception:  # noqa: BLE001
        logger.warning("Zaxira nusxa yuklanmadi", exc_info=True)
        return None


async def _ensure_local(bot, item: dict) -> str:
    if os.path.isfile(item["path"]):
        return item["path"]
    if not item.get("tg_file_id"):
        raise media.MediaError("Fayl diskda yo'q va zaxira nusxa ham yo'q")
    os.makedirs(os.path.dirname(item["path"]), exist_ok=True)
    f = await bot.get_file(item["tg_file_id"])
    await bot.download_file(f.file_path, destination=item["path"])
    return item["path"]


async def _publish_one(bot, entry: dict, now: datetime) -> None:
    store.set_status(entry["id"], "publishing", publishing_since=now.isoformat())
    urls: list[str] = []
    label = f"{entry['kind']} · {(entry.get('caption') or '')[:40]}"
    try:
        async with common.LOCK:
            try:
                q = await ig.get_quota()
                if q["used"] is not None and q["total"] and q["used"] >= q["total"]:
                    raise ig.InstagramAPIError(f"24 soatlik limit tugagan ({q['used']}/{q['total']})")
            except ig.InstagramAPIError as e:
                if "limit" in str(e):
                    raise
            ready = []
            for it in entry["items"]:
                path = await _ensure_local(bot, it)
                urls.append(media.expose(path))
                ready.append((urls[-1], it["is_video"]))
            caption = "" if entry["kind"] == "STORY" else entry.get("caption", "")
            result = await ig.publish(entry["kind"], ready, caption)
        store.set_status(entry["id"], "published", result=result, published_at=now.isoformat())
        store.log("scheduled_published", label)
        await notify(bot, f"✅ Rejalashtirilgan post chiqdi: {label}\n{result.get('permalink') or ''}")
        store.delete_files(entry)
    except Exception as e:  # noqa: BLE001
        store.set_status(entry["id"], "failed", error=str(e)[:300])
        store.log("scheduled_failed", f"{label} | {e}")
        await notify(bot, f"❌ Rejalashtirilgan post chiqmadi: {label}\nSabab: {e}\n"
                          f"Fayllarni qayta yuborib, yangidan rejalashtiring.")
        store.delete_files(entry)
    finally:
        for u in urls:
            media.revoke(u)
        store.prune_finished()


async def tick(bot, now: Optional[datetime] = None) -> None:
    now = now or datetime.now(common.TASHKENT)
    for e in store.list_scheduled(["publishing"]):
        since = datetime.fromisoformat(e.get("publishing_since", now.isoformat()))
        if now - since > timedelta(seconds=STUCK_AFTER):
            store.set_status(e["id"], "unknown", error="Server qayta ishga tushgan bo'lishi mumkin")
            store.log("scheduled_unknown", e["id"])
            await notify(bot, f"⚠️ Post holati noma'lum ({e['kind']}, {e['when']}). Instagram'da chiqqan-chiqmaganini "
                              f"o'zingiz tekshiring, takror yubormang.")
    for e in store.due(now):
        await _publish_one(bot, e, now)


async def run_forever(bot) -> None:
    if not ig.is_configured():
        logger.info("Instagram sozlanmagan — scheduler ishga tushmadi")
        return
    logger.info("Instagram scheduler ishga tushdi")
    while True:
        try:
            await tick(bot)
        except Exception:  # noqa: BLE001 — fon tsikli hech qachon to'xtamasin
            logger.exception("Instagram scheduler xatosi")
        await asyncio.sleep(CHECK_INTERVAL)
