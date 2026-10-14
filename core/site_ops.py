"""
core/site_ops.py
----------------
Sayt frontend'ini O'QISH va KO'CHIRISH amallarining yagona kirish nuqtasi (AI tool'lari shu yerdan o'tadi).

  site_read      — sahifa tuzilishi/texnologiyalari/matni (nusxalamasdan)
  site_resource  — bitta CSS/JS/HTML faylning matni (sahifalab)
  site_download  — butun frontend: bitta HTML yoki ZIP; Telegram'ga HUJJAT sifatida yuboriladi (diskka yozilmaydi)

Xavfsizlik: hamma tarmoq so'rovi core/site_fetch.py (SSRF-xavfsiz). Kvota: tariffs.KIND_SITE (har amal 1; xato sanalmaydi).
Bir vaqtda ko'pi bilan 3 ta sayt ishi (server RAM/CPU'ni himoya qilish) va foydalanuvchiga 1 ta.
"""
from __future__ import annotations

import asyncio
import html
import logging

import core.site_pack as pack
import core.tariffs as tariffs
from core.site_fetch import SiteError

logger = logging.getLogger("site_ops")

_GLOBAL = asyncio.Semaphore(3)
_user_locks: dict[int, asyncio.Lock] = {}
FORMATS = {"single": "single", "html": "single", "bitta": "single", "zip": "zip", "papka": "zip"}
LEGAL = "Faqat o'zingizga tegishli yoki nusxalashga ruxsat berilgan saytlar uchun; mualliflik huquqiga rioya qiling."


def normalize_url(raw: str) -> str:
    u = (raw or "").strip().strip("<>\"'")
    if not u:
        raise SiteError("Sayt havolasi kerak.")
    if "://" not in u:
        u = "https://" + u
    return u


async def _say(bot, chat_id, text):
    if bot is None or chat_id is None:
        return None
    try:
        return await bot.send_message(chat_id, text)
    except Exception:  # noqa: BLE001
        return None


async def _edit(bot, chat_id, msg, text):
    if msg is None:
        return
    try:
        await bot.edit_message_text(text, chat_id=chat_id, message_id=msg.message_id)
    except Exception:  # noqa: BLE001
        pass


def quota_error(uid: int) -> dict:
    limit = tariffs.quota_limit(uid, tariffs.KIND_SITE)
    return {"error": f"Bugungi sayt o'qish/ko'chirish limiti tugadi ({limit}/{limit}). Ertaga yangilanadi; ko'proq kerak bo'lsa "
                     f"Plus/Pro tarifi (💳 Tariflar).", "kvota_tugadi": "site"}


async def op_read(uid, args, bot, chat_id) -> dict:
    url = normalize_url(args.get("url"))
    page = await pack.fetch_page(url)
    a = pack.analyze(page.body, page.url)
    text = pack.render_analysis(a)
    return {"ok": True, "text": text, "analysis": a, "eslatma": pack.UNTRUSTED_NOTE}


async def op_resource(uid, args, bot, chat_id) -> dict:
    url = normalize_url(args.get("resource_url") or args.get("url"))
    res = await pack.read_resource(url, args.get("start") or 0, args.get("length") or 8000)
    if res.get("text") is None:
        return {"ok": True, "text": f"{res['url']} — {res['content_type']}, {res['size']} bayt. {res['note']}", "resource": res}
    head = f"{res['url']} ({res['content_type']}, {res['chars']} belgi, {res['lines']} qator; {res['start']}–{res['start'] + len(res['text'])})"
    more = "\n… davomi bor: start=" + str(res["start"] + len(res["text"])) if res["more"] else ""
    note = "\n(minify qilingan ko'rinadi — o'qish qiyin)" if res["minified"] else ""
    return {"ok": True, "text": f"{head}{note}\n{res['text']}{more}", "resource": res, "eslatma": pack.UNTRUSTED_NOTE}


async def op_download(uid, args, bot, chat_id) -> dict:
    if bot is None or chat_id is None:
        raise SiteError("Faylni yuborib bo'lmaydi (chat noma'lum).")
    fmt = FORMATS.get(str(args.get("format") or "single").lower())
    if not fmt:
        raise SiteError("Format: single (bitta HTML) yoki zip.")
    url = normalize_url(args.get("url"))
    progress = await _say(bot, chat_id, f"⏳ <b>{html.escape(url, quote=False)}</b> yuklanmoqda (HTML, CSS, JS, rasmlar)…")
    try:
        res = await pack.archive(url, fmt)
    except SiteError as e:
        await _edit(bot, chat_id, progress, f"❌ {html.escape(str(e), quote=False)}")
        raise
    from aiogram.types import BufferedInputFile
    caption = (f"🌐 {html.escape(url, quote=False)}\nFormat: {'bitta HTML (hammasi ichida)' if fmt == 'single' else 'ZIP (index.html + assets/)'} · "
               f"{res.files} fayl, {len(res.data) // 1024} KB\n<i>{LEGAL}</i>")
    try:
        await bot.send_document(chat_id, BufferedInputFile(res.data, filename=res.filename), caption=caption)
    except Exception:  # noqa: BLE001
        await _edit(bot, chat_id, progress, "❌ Faylni yuborib bo'lmadi.")
        raise SiteError("Faylni Telegram'ga yuborib bo'lmadi.")
    await _edit(bot, chat_id, progress, f"✅ Tayyor: {res.files} fayl, {len(res.data) // 1024} KB" + (f" ({len(res.failed)} ta resurs yuklanmadi)" if res.failed else ""))
    text = (f"✅ {url} nusxalandi va fayl sifatida yuborildi ({res.filename}, {res.files} fayl, {len(res.data) // 1024} KB, format: {fmt})."
            + (f" Yuklanmagan resurslar: {len(res.failed)}." if res.failed else "") + (" " + " ".join(res.notes) if res.notes else ""))
    return {"ok": True, "text": text, "filename": res.filename, "files": res.files, "failed": len(res.failed), "notes": res.notes}


OPS = {"site_read": op_read, "site_resource": op_resource, "site_download": op_download}


async def run(name: str, uid: int, args: dict | None, *, bot=None, chat_id: int | None = None) -> dict:
    """Hech qachon istisno tashlamaydi: {"ok": True, ...} yoki {"error": ...}."""
    fn = OPS.get(name)
    if fn is None:
        return {"error": f"Noma'lum amal: {name}"}
    args = args if isinstance(args, dict) else {}
    try:
        async with _user_locks.setdefault(int(uid), asyncio.Lock()):
            if not tariffs.quota_available(uid, tariffs.KIND_SITE):
                return quota_error(uid)
            async with _GLOBAL:
                res = await fn(uid, args, bot, chat_id)
            if res.get("ok"):
                await tariffs.consume(bot, uid, tariffs.KIND_SITE)
            return res
    except SiteError as e:
        return {"error": str(e)}
    except Exception:  # noqa: BLE001
        logger.exception("Sayt amali kutilmagan xatoga uchradi")
        return {"error": "Kutilmagan ichki xato yuz berdi. Keyinroq qayta urinib ko'ring."}
