"""
core/instagram_webhook.py
-------------------------
Instagram webhook: `messages` (DM → core/instagram_dm.py) va `comments`.
Izoh kelganda
  1) taqiqlangan so'z bor bo'lsa → izoh YASHIRILADI (o'chirilmaydi, qaytarish mumkin);
  2) kalit so'z trigger'ga mos kelsa → izoh egasiga DM (private reply) yuboriladi.

DIQQAT — Meta'da bitta ilova uchun BITTA callback URL bor. Agar `weChat` servisi
hozir shu URL'ni qabul qilayotgan bo'lsa, ikkalasini birdaniga yoqmang: DM ikki
marta ketadi. Bu modul faqat IG_WEBHOOK_ENABLED=1 bo'lsa ulanadi.

Himoyalar: HMAC imzo tekshiruvi, takroriy yetkazib berishdan himoya (seen),
o'z izohlariga javob bermaslik, soatiga DM limiti (IG_MAX_DMS_PER_HOUR, standart 60).
"""
from __future__ import annotations

import asyncio
import collections
import logging
import os
import time

from aiohttp import web

import core.instagram_api as ig
import core.instagram_context as ictx
import core.instagram_dm as dm
import core.instagram_scheduler as scheduler
import core.instagram_settings as settings
import core.instagram_store as store

logger = logging.getLogger("instagram_webhook")

PATH = "/webhook/instagram"
_tasks: set[asyncio.Task] = set()
_dm_times: dict[str, list[float]] = collections.defaultdict(list)   # akkaunt bo'yicha
_limit_notified: dict[str, float] = {}


def enabled() -> bool:
    flag = os.getenv("IG_WEBHOOK_ENABLED", "").lower() in ("1", "true", "yes")
    return flag and bool(os.getenv("META_APP_SECRET") or settings.app_secret()) and bool(os.getenv("WEBHOOK_VERIFY_TOKEN")) \
        and (ig.is_configured() or ictx.multi_enabled())


def _dm_budget_ok() -> bool:
    limit = int(os.getenv("IG_MAX_DMS_PER_HOUR", "60"))
    cutoff = time.time() - 3600
    lst = _dm_times[ictx.account_key()]
    lst[:] = [t for t in lst if t > cutoff]
    return len(lst) < limit


async def handle_comment(bot, value: dict) -> None:
    ak = ictx.account_key()
    comment_id = value.get("comment_id") or value.get("id")
    text = (value.get("text") or "").strip()
    sender = value.get("from") or {}
    username = sender.get("username", "noma'lum")
    media_id = (value.get("media") or {}).get("id")
    if not comment_id or not text:
        return
    me = ictx.current()
    if str(sender.get("id", "")) == (me.ig_id if me else os.getenv("IG_USER_ID", "-")):
        return  # o'z izohimiz (o'zimizga javob berib sikl hosil qilmaslik)
    plan = ictx.current_plan()
    if plan is not None and not plan.allows("automation"):
        return  # tarifda avtomatlashtirish yo'q (sinov/tarif tugagan)
    if not store.mark_seen(comment_id):
        return  # takroriy yetkazib berish

    word = store.match_banned(text, plan.max_banned if plan else None)
    if word:
        try:
            await ig.hide_comment(comment_id, True)
            store.log("comment_hidden", f"@{username}: {text[:60]}")
            await scheduler.notify(bot, f"🚫 Izoh yashirildi (@{username}, «{word}»):\n{text[:120]}")
        except ig.InstagramAPIError as e:
            logger.warning("Izohni yashirib bo'lmadi: %s", e)
            await scheduler.notify(bot, f"⚠️ Izohni yashirib bo'lmadi (@{username}): {e}")
        return

    trig = store.match_trigger(text, media_id, plan.max_triggers if plan else None)
    if not trig:
        return
    if not _dm_budget_ok():
        if time.time() - _limit_notified.get(ak, 0.0) > 3600:
            _limit_notified[ak] = time.time()
            await scheduler.notify(bot, "⚠️ Soatlik DM limiti to'ldi — qolgan triggerlar o'tkazib yuborilmoqda.")
        return
    try:
        await ig.send_private_reply(comment_id, trig["reply"])
        _dm_times[ak].append(time.time())
        store.hit_trigger(trig["id"])
        store.log("dm_sent", f"@{username} | {trig['keyword']}")
        await scheduler.notify(bot, f"📩 DM yuborildi (@{username}), trigger: «{trig['keyword']}»")
    except ig.InstagramAPIError as e:
        logger.warning("Private reply xatosi: %s", e)
        await scheduler.notify(bot, f"⚠️ DM yuborilmadi (@{username}): {e}")


def _resolve_entry(entry_id):
    """Webhook yozuvi qaysi akkauntga tegishli: (Account, Plan) yoki (None, None).
    Eski rejimda (ko'p-akkauntlik o'chiq) hamma narsa env'dagi akkauntga tegishli."""
    import core.instagram_accounts as accounts
    import core.instagram_plans as plans
    env = ig.env_account()
    if not ictx.multi_enabled():
        return (env, None) if env else (None, None)
    if env and str(entry_id) == env.ig_id:
        return env, plans.OWNER
    acct = accounts.by_ig_id(str(entry_id))
    if acct is None:
        return None, None            # noma'lum yoki token yaroqsiz akkaunt — hodisa e'tiborsiz
    return acct, plans.plan_for(acct.tg_user_id, acct)


async def _process_entry(bot, entry: dict) -> None:
    for ev in entry.get("messaging") or []:  # DM: standart format
        await dm.handle_messaging(bot, ev)
    for change in entry.get("changes", []):
        field = change.get("field")
        if field == "comments":
            await handle_comment(bot, change.get("value", {}))
        elif field == "messages":  # DM: changes ko'rinishi
            await dm.handle_messaging(bot, change.get("value", {}))


async def process_payload(bot, payload: dict) -> None:
    for entry in payload.get("entry", []):
        try:
            acct, plan = _resolve_entry(entry.get("id"))
            if acct is None:
                if ictx.multi_enabled():
                    logger.info("Webhook: noma'lum akkaunt (%s) — e'tiborsiz", entry.get("id"))
                    continue
                await _process_entry(bot, entry)     # (env sozlanmagan eski holat)
                continue
            if not ictx.multi_enabled():
                await _process_entry(bot, entry)
                continue
            with ictx.use(acct, plan):               # shu akkaunt egasining holati, tarifi va xabarnomasi
                await _process_entry(bot, entry)
        except Exception:  # noqa: BLE001
            logger.exception("Webhook payload xatosi")


async def _verify(request: web.Request) -> web.Response:
    q = request.query
    if q.get("hub.mode") == "subscribe" and q.get("hub.verify_token") == os.getenv("WEBHOOK_VERIFY_TOKEN"):
        return web.Response(text=q.get("hub.challenge", ""))
    return web.Response(text="Verification failed", status=403)


def _make_receiver(bot):
    async def receive(request: web.Request) -> web.Response:
        raw = await request.read()
        if not ig.verify_signature(raw, request.headers.get("X-Hub-Signature-256")):
            logger.warning("Webhook imzosi noto'g'ri — rad etildi")
            return web.Response(status=403)
        try:
            payload = await request.json()
        except Exception:  # noqa: BLE001
            return web.Response(status=400)
        task = asyncio.create_task(process_payload(bot, payload))  # Meta 20 s ichida 200 kutadi
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
        return web.Response(status=200)

    return receive


def register(app: web.Application, bot) -> bool:
    if not enabled():
        logger.info("Instagram webhook o'chiq (IG_WEBHOOK_ENABLED / META_APP_SECRET / WEBHOOK_VERIFY_TOKEN)")
        return False
    app.router.add_get(PATH, _verify)
    app.router.add_post(PATH, _make_receiver(bot))
    logger.info("Instagram webhook ulandi: %s", PATH)
    return True
