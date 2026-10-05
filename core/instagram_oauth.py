"""
core/instagram_oauth.py
-----------------------
"Business Login for Instagram" (Meta): har bir foydalanuvchi O'Z Instagram akkauntini ulaydi.

Oqim:  /instagram -> [Ulash] tugmasi (imzolangan `state` bilan) -> instagram.com/oauth/authorize
       -> /ig/callback?code=..&state=.. -> code -> qisqa token -> 60 kunlik token -> profil -> saqlash.

Xavfsizlik:
  * `state` — HMAC bilan imzolangan, 10 daqiqalik, BIR MARTALIK (CSRF/replay'dan himoya); ichida Telegram ID bor,
    shuning uchun boshqa odamning akkauntini "o'zimniki" qilib ulab bo'lmaydi.
  * Token, client_secret va code HECH QACHON logga/xatoga/Telegram xabariga tushmaydi.
  * Meta talablari: /ig/deauth, /ig/data-deletion (imzolangan so'rov tekshiriladi), /ig/privacy sahifasi.

Env: IG_APP_ID, IG_APP_SECRET (Meta'dagi *Instagram* ilovasi: Instagram > API setup with Instagram login),
     redirect URI Meta'da AYNAN `<ommaviy manzil>/ig/callback` bo'lishi kerak.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import logging
import os
import secrets
import time
from typing import Optional
from urllib.parse import urlencode

import httpx
from aiohttp import web

import core.instagram_accounts as accounts
import core.instagram_api as ig
import core.instagram_context as ictx
import core.instagram_media as media
import core.instagram_plans as plans

logger = logging.getLogger("instagram_oauth")

AUTH_URL = "https://www.instagram.com/oauth/authorize"
TOKEN_URL = "https://api.instagram.com/oauth/access_token"
GRAPH = "https://graph.instagram.com"
SCOPES = ("instagram_business_basic", "instagram_business_content_publish", "instagram_business_manage_comments",
          "instagram_business_manage_messages", "instagram_business_manage_insights")
STATE_TTL = 600
CALLBACK_PATH, DEAUTH_PATH, DELETE_PATH, DELETE_STATUS_PATH, PRIVACY_PATH = (
    "/ig/callback", "/ig/deauth", "/ig/data-deletion", "/ig/data-deletion-status", "/ig/privacy")


class OAuthError(Exception):
    """Foydalanuvchiga ko'rsatsa bo'ladigan xato (sir/token ichida YO'Q). permanent — qayta urinish foydasiz."""
    def __init__(self, msg: str, permanent: bool = False):
        super().__init__(msg)
        self.permanent = permanent


# ── sozlama ────────────────────────────────────────────────────────────────────
def _app_id() -> str:
    return os.getenv("IG_APP_ID", "")


def _app_secret() -> str:
    return os.getenv("IG_APP_SECRET", "")


def redirect_uri() -> str:
    return media.public_base() + CALLBACK_PATH


# ── imzolangan state ───────────────────────────────────────────────────────────
_used_states: dict[str, float] = {}


def _state_key() -> bytes:
    import config
    return hashlib.sha256(b"ig-oauth-state:" + config.ENCRYPTION_KEY.encode()).digest()


def _sign(body: str) -> str:
    return hmac.new(_state_key(), body.encode(), hashlib.sha256).hexdigest()[:32]


def make_state(tg_uid: int, now: Optional[float] = None) -> str:
    body = f"{int(tg_uid)}.{int(time.time() if now is None else now)}.{secrets.token_hex(6)}"
    return f"{body}.{_sign(body)}"


def verify_state(state: Optional[str], now: Optional[float] = None) -> Optional[int]:
    """Telegram ID yoki None (soxta / eskirgan / ishlatilgan)."""
    now = time.time() if now is None else now
    try:
        uid, ts, nonce, sig = (state or "").split(".")
        if not hmac.compare_digest(sig, _sign(f"{uid}.{ts}.{nonce}")):
            return None
        if not (0 <= now - int(ts) <= STATE_TTL):
            return None
    except (ValueError, TypeError):
        return None
    for k in [k for k, t in _used_states.items() if now - t > STATE_TTL]:
        _used_states.pop(k, None)
    if state in _used_states:
        return None                      # takroriy (replay)
    _used_states[state] = now
    return int(uid)


def authorize_url(tg_uid: int, now: Optional[float] = None) -> str:
    return AUTH_URL + "?" + urlencode({
        "client_id": _app_id(), "redirect_uri": redirect_uri(), "response_type": "code",
        "scope": ",".join(SCOPES), "state": make_state(tg_uid, now), "force_reauth": "true",
    })


def can_connect(tg_uid: int) -> tuple[bool, str]:
    """Ulashga ruxsatmi? Pullik tarif — doim; bepul — faqat sinov hali ishlatilmagan bo'lsa."""
    plan = plans.plan_for(tg_uid)
    if plan.code != "none" or not accounts.trial_used(tg_uid):
        return True, ""
    return False, plans.deny_text(plan, "publish")


# ── Meta so'rovlari (testlarda almashtiriladi) ─────────────────────────────────
async def _http(method: str, url: str, *, data: Optional[dict] = None, params: Optional[dict] = None) -> dict:
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            resp = await c.request(method, url, data=data, params=params)
    except httpx.HTTPError:
        raise OAuthError("Instagram bilan aloqa o'rnatilmadi. Birozdan keyin qayta urining.")
    if resp.status_code >= 400:
        permanent = resp.status_code in (400, 401, 403)
        raise OAuthError("Instagram so'rovni rad etdi (kod eskirgan yoki ruxsat bekor qilingan).", permanent)
    try:
        return resp.json()
    except ValueError:
        raise OAuthError("Instagram kutilmagan javob qaytardi.")


async def exchange_code(code: str) -> tuple[str, str, list[str]]:
    d = await _http("POST", TOKEN_URL, data={
        "client_id": _app_id(), "client_secret": _app_secret(), "grant_type": "authorization_code",
        "redirect_uri": redirect_uri(), "code": code})
    if isinstance(d.get("data"), list) and d["data"]:
        d = d["data"][0]
    perms = d.get("permissions") or []
    if isinstance(perms, str):
        perms = [p.strip() for p in perms.split(",") if p.strip()]
    if not d.get("access_token") or not d.get("user_id"):
        raise OAuthError("Instagram token bermadi.")
    return d["access_token"], str(d["user_id"]), list(perms)


async def to_long_lived(short_token: str) -> tuple[str, int]:
    d = await _http("GET", f"{GRAPH}/access_token", params={
        "grant_type": "ig_exchange_token", "client_secret": _app_secret(), "access_token": short_token})
    if not d.get("access_token"):
        raise OAuthError("Uzoq muddatli token olinmadi.")
    return d["access_token"], int(d.get("expires_in", 60 * 86400))


async def refresh_token(token: str) -> tuple[str, int]:
    d = await _http("GET", f"{GRAPH}/refresh_access_token", params={
        "grant_type": "ig_refresh_token", "access_token": token})
    if not d.get("access_token"):
        raise OAuthError("Token yangilanmadi.")
    return d["access_token"], int(d.get("expires_in", 60 * 86400))


async def fetch_profile(token: str) -> dict:
    return await _http("GET", f"{GRAPH}/{os.getenv('GRAPH_API_VERSION', 'v25.0')}/me",
                       params={"fields": "user_id,username,account_type", "access_token": token})


# ── Ulanishni yakunlash ────────────────────────────────────────────────────────
async def complete_connection(bot, tg_uid: int, code: str) -> tuple[bool, str]:
    """(muvaffaqiyat, foydalanuvchiga xabar). Hech qachon token/kodni xabarga qo'shmaydi."""
    ok, why = can_connect(tg_uid)
    if not ok:
        return False, why
    try:
        short, token_uid, perms = await exchange_code(code)
        token, expires = await to_long_lived(short)
        prof = await fetch_profile(token)
    except OAuthError as e:
        return False, str(e)
    if prof.get("account_type") not in ("BUSINESS", "MEDIA_CREATOR"):
        return False, "Faqat Instagram Business yoki Creator akkaunt ulanadi (oddiy shaxsiy akkaunt emas)."
    ig_id = str(prof.get("user_id") or token_uid)
    username = prof.get("username") or ""
    ok, why = accounts.connect(tg_uid, ig_id, username, token, expires, perms)
    if not ok:
        return False, why

    # Webhook'ga yozish (faqat webhook yoqilgan bo'lsa) — xato bo'lsa ulanish baribir saqlanadi
    import core.instagram_webhook as webhook
    if webhook.enabled():
        acct = accounts.account_for(tg_uid)
        try:
            with ictx.use(acct):
                await ig.subscribe_webhooks()
        except Exception as e:  # noqa: BLE001
            logger.warning("Webhook obunasi o'tmadi (tg=%s): %s", tg_uid, type(e).__name__)

    plan = plans.plan_for(tg_uid, accounts.account_for(tg_uid))
    extra = (f"\n⏳ Bepul sinov: {plans.trial_text(accounts.trial_seconds_left(tg_uid))} (bir martalik)."
             if plan.code == "trial" else f"\nTarif: {plan.label}.")
    msg = f"✅ Instagram ulandi: @{username}{extra}\nEndi menga \"postga rasm qo'y\", \"statistikani ko'rsat\" kabi yozing."
    try:
        await bot.send_message(tg_uid, msg, parse_mode=None)
    except Exception:  # noqa: BLE001
        pass
    return True, msg


# ── Tokenni yangilash ──────────────────────────────────────────────────────────
async def refresh_due(bot=None) -> int:
    """Tugashiga yaqin tokenlarni yangilaydi; yaroqsizlari 'qayta ulash kerak' deb belgilanadi."""
    n = 0
    for uid in accounts.due_for_refresh():
        acct = accounts.account_for(uid)
        if not acct:
            continue
        try:
            token, expires = await refresh_token(acct.token)
            accounts.update_token(uid, token, expires)
            n += 1
        except OAuthError as e:
            if e.permanent and accounts.mark_reauth(uid):
                accounts._pending_reauth_notice.add(uid)
            logger.info("IG token yangilanmadi (tg=%s, doimiy=%s)", uid, e.permanent)
    for uid in accounts.expired():
        if accounts.mark_reauth(uid):
            accounts._pending_reauth_notice.add(uid)
    if bot is not None:
        await flush_reauth_notices(bot)
    return n


async def flush_reauth_notices(bot) -> None:
    while accounts._pending_reauth_notice:
        uid = accounts._pending_reauth_notice.pop()
        try:
            await bot.send_message(uid, "⚠️ Instagram ulanishingiz eskirdi yoki bekor qilindi. Rejalashtirilgan postlar "
                                        "va avtomatik javoblar to'xtatildi. /instagram orqali qayta ulang.",
                                   parse_mode=None)
        except Exception:  # noqa: BLE001
            logger.info("Qayta ulash xabari yuborilmadi (tg=%s)", uid)


# ── Meta: signed_request (deauth / data deletion) ──────────────────────────────
def parse_signed_request(signed: str, secret: str) -> Optional[dict]:
    try:
        sig_b64, payload_b64 = signed.split(".", 1)
        pad = lambda x: x + "=" * (-len(x) % 4)  # noqa: E731
        sig = base64.urlsafe_b64decode(pad(sig_b64))
        expected = hmac.new(secret.encode(), payload_b64.encode(), hashlib.sha256).digest()
        if not secret or not hmac.compare_digest(sig, expected):
            return None
        return json.loads(base64.urlsafe_b64decode(pad(payload_b64)))
    except Exception:  # noqa: BLE001
        return None


# ── Web sahifalar ──────────────────────────────────────────────────────────────
def _page(title: str, body: str, status: int = 200) -> web.Response:
    doc = (f"<!doctype html><html lang='uz'><head><meta charset='utf-8'><meta name='viewport' "
           f"content='width=device-width,initial-scale=1'><title>{html.escape(title)}</title>"
           f"<style>body{{font-family:system-ui,sans-serif;max-width:640px;margin:12vh auto;padding:0 20px;"
           f"line-height:1.55;color:#222}}h1{{font-size:1.4rem}}</style></head><body><h1>{html.escape(title)}</h1>"
           f"{body}</body></html>")
    return web.Response(text=doc, status=status, content_type="text/html")


def _make_callback(bot):
    async def callback(request: web.Request) -> web.Response:
        q = request.query
        if q.get("error"):
            return _page("Ruxsat berilmadi", "<p>Instagram ulanishi bekor qilindi. Telegram'ga qaytib, "
                                             "/instagram orqali qayta urinishingiz mumkin.</p>")
        code = (q.get("code") or "").split("#")[0]
        uid = verify_state(q.get("state"))
        if not code or uid is None:
            return _page("Havola yaroqsiz", "<p>Havola eskirgan yoki allaqachon ishlatilgan. Telegram'da "
                                            "/instagram buyrug'idan yangi havola oling.</p>", 400)
        ok, msg = await complete_connection(bot, uid, code)
        if ok:
            return _page("Instagram ulandi ✅", "<p>Telegram'ga qaytishingiz mumkin — bot sizga xabar yubordi.</p>")
        return _page("Ulanmadi", f"<p>{html.escape(msg)}</p>", 400)
    return callback


async def _signed_user(request: web.Request) -> Optional[str]:
    form = await request.post()
    data = parse_signed_request(str(form.get("signed_request", "")), _app_secret())
    return str(data.get("user_id")) if data and data.get("user_id") else None


def _make_deauth(bot):
    async def deauth(request: web.Request) -> web.Response:
        ig_id = await _signed_user(request)
        if not ig_id:
            return web.Response(status=400)
        uid = accounts.owner_of(ig_id)
        if uid is not None:
            accounts.disconnect(uid)
            try:
                await bot.send_message(uid, "ℹ️ Instagram'da botga berilgan ruxsat bekor qilindi — akkaunt va "
                                            "barcha ma'lumotlar o'chirildi.", parse_mode=None)
            except Exception:  # noqa: BLE001
                pass
        return web.Response(status=200)
    return deauth


def _make_delete(bot):
    async def delete(request: web.Request) -> web.Response:
        ig_id = await _signed_user(request)
        if not ig_id:
            return web.Response(status=400)
        uid = accounts.owner_of(ig_id)
        if uid is not None:
            accounts.disconnect(uid)
        code = secrets.token_hex(8)
        import core.instagram_accounts as acc
        dels = acc._db().setdefault("ig_deletions", {})
        dels[code] = int(time.time())
        for k in sorted(dels, key=dels.get)[:-200]:
            dels.pop(k, None)
        acc._dirty()
        return web.json_response({"url": f"{media.public_base()}{DELETE_STATUS_PATH}?code={code}",
                                  "confirmation_code": code})
    return delete


async def _delete_status(request: web.Request) -> web.Response:
    code = request.query.get("code", "")
    done = code in accounts._db().get("ig_deletions", {})
    return _page("Ma'lumotlarni o'chirish", "<p>Ma'lumotlaringiz o'chirildi.</p>" if done
                 else "<p>Bunday so'rov topilmadi.</p>", 200 if done else 404)


async def _privacy(request: web.Request) -> web.Response:
    contact = html.escape(os.getenv("IG_PRIVACY_CONTACT", "botdagi yordam (support) bo'limi"))
    return _page("Maxfiylik siyosati / Privacy Policy", f"""
<p><b>Nima saqlanadi.</b> Instagram akkauntingiz ID'si va username'i, shifrlangan kirish tokeni, siz bot orqali
joylashni so'ragan kontent (vaqtincha), rejalashtirilgan postlar, avtomatik javob qoidalari. DM'da AI yoqilgan bo'lsa —
mijozlar yozishmalarining oxirgi qismi (<b>7 kun</b>dan keyin avtomatik o'chadi).</p>
<p><b>Nima uchun.</b> Faqat siz so'ragan amallarni (joylash, statistika, izohlar, DM) o'z akkauntingizda bajarish uchun.
Ma'lumotlar sotilmaydi va reklama uchun ishlatilmaydi.</p>
<p><b>O'chirish.</b> Telegram'da /instagram &rarr; «Uzish» — token va barcha ma'lumotlar darhol o'chadi. Instagram
sozlamalaridan ruxsatni bekor qilsangiz ham o'chadi. Aloqa: {contact}.</p>
<hr><p><b>English.</b> We store your Instagram account ID/username, an encrypted access token, content you ask the bot
to publish, scheduled posts, automation rules and (if AI DM is on) recent conversation text for 7 days. Data is used only
to perform the actions you request on your own account and is never sold. Disconnect via /instagram in Telegram, or
remove the app in Instagram settings, and everything is deleted. Contact: {contact}.</p>""")


def register(app: web.Application, bot) -> bool:
    if not ictx.multi_enabled():
        logger.info("Instagram ulash (OAuth) o'chiq — IG_APP_ID / IG_APP_SECRET yo'q")
        return False
    app.router.add_get(CALLBACK_PATH, _make_callback(bot))
    app.router.add_post(DEAUTH_PATH, _make_deauth(bot))
    app.router.add_post(DELETE_PATH, _make_delete(bot))
    app.router.add_get(DELETE_STATUS_PATH, _delete_status)
    app.router.add_get(PRIVACY_PATH, _privacy)
    logger.info("Instagram OAuth ulandi: %s", CALLBACK_PATH)
    return True
