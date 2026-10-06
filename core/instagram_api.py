"""
core/instagram_api.py
---------------------
Meta Graph API (Instagram Content Publishing) uchun yupqa klient.

Qo'llab-quvvatlanadi: rasm POST, KARUSEL (2-10 ta), REEL, STORY (rasm/video).
Highlight Meta API'sida YO'Q — shuning uchun bu yerda ham yo'q.

Barcha HTTP so'rovlar yagona `_request()` orqali o'tadi (token faqat
Authorization sarlavhasida, URL va log'larga tushmaydi).

Kerakli env: IG_USER_ID, IG_ACCESS_TOKEN
Ixtiyoriy : GRAPH_API_VERSION (standart v25.0), IG_GRAPH_HOST (standart graph.facebook.com)
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
from typing import Any, Optional

import httpx

import core.instagram_context as ictx

logger = logging.getLogger("instagram_api")

# 190 (token yaroqsiz/bekor qilingan) bo'lganda chaqiriladi — akkaunt "qayta ulash kerak" deb belgilanadi
auth_error_hook = None


class InstagramAPIError(Exception):
    """Graph API xatosi yoki kutilmagan holat. Xabarda token HECH QACHON bo'lmaydi."""


def env_account() -> Optional[ictx.Account]:
    """env'dagi (IG_USER_ID / IG_ACCESS_TOKEN) egasi akkaunti — bo'lmasa None."""
    uid, tok = os.getenv("IG_USER_ID"), os.getenv("IG_ACCESS_TOKEN")
    if not (uid and tok):
        return None
    return ictx.Account(ig_id=uid, token=tok, host=os.getenv("IG_GRAPH_HOST", "graph.facebook.com"), owner=True)


def is_configured() -> bool:
    """env'dagi egasi akkaunti sozlanganmi (foydalanuvchi akkauntlari bunga bog'liq emas)."""
    return env_account() is not None


def _acct() -> ictx.Account:
    a = ictx.current()
    if a is not None:
        return a
    if not ictx.multi_enabled():       # eski bitta-akkaunt rejimi
        a = env_account()
        if a:
            return a
    raise InstagramAPIError("Instagram akkaunti tanlanmagan (ichki xato).")


def _base(host: Optional[str] = None) -> str:
    host = host or _acct().host
    version = os.getenv("GRAPH_API_VERSION", "v25.0")
    return f"https://{host}/{version}"


def _ig_id() -> str:
    return _acct().ig_id


def _describe_error(method: str, path: str, resp: httpx.Response) -> str:
    try:
        err = resp.json().get("error", {})
        msg = err.get("error_user_msg") or err.get("message") or resp.text[:300]
        code = err.get("code")
        sub = err.get("error_subcode")
        extra = f" (code={code}, subcode={sub})" if code or sub else ""
        return f"{method} {path} -> HTTP {resp.status_code}: {msg}{extra}"
    except Exception:
        return f"{method} {path} -> HTTP {resp.status_code}: {resp.text[:300]}"


def _error_code(resp: httpx.Response) -> Optional[int]:
    try:
        return int((resp.json().get("error") or {}).get("code"))
    except Exception:  # noqa: BLE001
        return None


async def _request(
    method: str,
    path: str,
    *,
    params: Optional[dict[str, Any]] = None,
    json_body: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """path Graph API bazasiga nisbatan, masalan '/1784.../media'."""
    acct = _acct()
    url = f"{_base(acct.host)}{path}"
    headers = {"Authorization": f"Bearer {acct.token}"}
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.request(method, url, params=params, json=json_body, headers=headers)
    if resp.status_code >= 400:
        if _error_code(resp) == 190 and acct.tg_user_id and not acct.owner and auth_error_hook:
            try:
                auth_error_hook(acct)     # token bekor qilingan/eskirgan — egasiga qayta ulashni aytamiz
            except Exception:  # noqa: BLE001
                logger.warning("auth_error_hook xatosi", exc_info=True)
        raise InstagramAPIError(_describe_error(method, path, resp))
    return resp.json() if resp.content else {}


async def _create(body: dict[str, Any]) -> str:
    data = await _request("POST", f"/{_ig_id()}/media", json_body=body)
    return data["id"]


async def wait_until_ready(container_id: str, *, max_wait: int = 300, poll_every: int = 4) -> None:
    """Container FINISHED bo'lguncha kutadi (video uchun bir necha daqiqa ketishi mumkin)."""
    waited = 0
    while True:
        data = await _request(
            "GET", f"/{container_id}", params={"fields": "status_code,status"}
        )
        code = data.get("status_code", "UNKNOWN")
        if code in ("FINISHED", "PUBLISHED"):
            return
        if code in ("ERROR", "EXPIRED"):
            raise InstagramAPIError(
                f"Media qayta ishlanmadi: {code} — {data.get('status', 'sabab ko`rsatilmagan')}"
            )
        if waited >= max_wait:
            raise InstagramAPIError("Media qayta ishlash vaqti tugadi (timeout)")
        await asyncio.sleep(poll_every)
        waited += poll_every


async def _publish_container(container_id: str) -> str:
    data = await _request(
        "POST", f"/{_ig_id()}/media_publish", json_body={"creation_id": container_id}
    )
    return data["id"]


async def get_permalink(media_id: str) -> Optional[str]:
    try:
        data = await _request("GET", f"/{media_id}", params={"fields": "permalink"})
        return data.get("permalink")
    except InstagramAPIError:
        logger.info("permalink olinmadi (story'larda bo'lmasligi mumkin)")
        return None


async def get_quota() -> dict[str, Optional[int]]:
    """24 soatlik chop etish limiti: {'used': N, 'total': 100}."""
    data = await _request(
        "GET", f"/{_ig_id()}/content_publishing_limit", params={"fields": "config,quota_usage"}
    )
    row = (data.get("data") or [{}])[0]
    return {
        "used": row.get("quota_usage"),
        "total": (row.get("config") or {}).get("quota_total"),
    }


async def publish(kind: str, items: list[tuple[str, bool]], caption: str = "") -> dict[str, Any]:
    """
    kind : POST | CAROUSEL | REEL | STORY
    items: [(ommaviy_url, is_video), ...]
    Qaytaradi: {'media_id': ..., 'permalink': ... | None}
    """
    kind = kind.upper()
    if not items:
        raise InstagramAPIError("Media ro'yxati bo'sh")

    if kind == "POST":
        url, is_video = items[0]
        if is_video:
            raise InstagramAPIError("POST uchun faqat rasm; video uchun REEL ishlating")
        container = await _create({"image_url": url, "caption": caption})

    elif kind == "REEL":
        url, is_video = items[0]
        if not is_video:
            raise InstagramAPIError("REEL uchun video kerak")
        container = await _create(
            {"media_type": "REELS", "video_url": url, "caption": caption, "share_to_feed": True}
        )

    elif kind == "STORY":
        url, is_video = items[0]
        body: dict[str, Any] = {"media_type": "STORIES"}
        body["video_url" if is_video else "image_url"] = url
        container = await _create(body)

    elif kind == "CAROUSEL":
        if not 2 <= len(items) <= 10:
            raise InstagramAPIError("Karusel 2 dan 10 tagacha elementdan iborat bo'lishi kerak")
        child_ids: list[str] = []
        for url, is_video in items:  # tartib saqlanishi uchun ketma-ket
            body = {"is_carousel_item": True}
            if is_video:
                body.update({"media_type": "VIDEO", "video_url": url})
            else:
                body["image_url"] = url
            child_ids.append(await _create(body))
        for child in child_ids:
            await wait_until_ready(child)
        container = await _create(
            {"media_type": "CAROUSEL", "children": ",".join(child_ids), "caption": caption}
        )

    else:
        raise InstagramAPIError(f"Noma'lum tur: {kind}")

    await wait_until_ready(container)
    media_id = await _publish_container(container)
    return {"media_id": media_id, "permalink": await get_permalink(media_id)}


# ── Statistika ─────────────────────────────────────────────────────────────────
_MEDIA_FIELDS = "id,caption,media_product_type,media_type,timestamp,permalink,like_count,comments_count"
INSIGHT_METRICS = ("reach", "views", "saved", "shares", "total_interactions")


async def get_account() -> dict[str, Any]:
    return await _request(
        "GET", f"/{_ig_id()}",
        params={"fields": "username,followers_count,follows_count,media_count"},
    )


async def list_media(limit: int = 10) -> list[dict[str, Any]]:
    data = await _request(
        "GET", f"/{_ig_id()}/media", params={"fields": _MEDIA_FIELDS, "limit": max(1, min(limit, 25))}
    )
    return data.get("data", [])


async def get_media(media_id: str) -> dict[str, Any]:
    return await _request("GET", f"/{media_id}", params={"fields": _MEDIA_FIELDS})


async def get_insights(media_id: str) -> dict[str, Any]:
    """Metrikalarni alohida so'raydi: Meta ba'zi media turlarida ayrimlarini bermaydi — o'tkazib yuboramiz."""
    out: dict[str, Any] = {}
    for metric in INSIGHT_METRICS:
        try:
            data = await _request("GET", f"/{media_id}/insights", params={"metric": metric})
        except InstagramAPIError:
            continue
        for row in data.get("data", []):
            values = row.get("values") or []
            if values:
                out[row["name"]] = values[0].get("value")
            elif isinstance(row.get("total_value"), dict):
                out[row["name"]] = row["total_value"].get("value")
    return out


# ── Izohlar ────────────────────────────────────────────────────────────────────
async def list_comments(media_id: str, limit: int = 25) -> list[dict[str, Any]]:
    data = await _request(
        "GET", f"/{media_id}/comments",
        params={"fields": "id,text,username,timestamp,like_count,hidden", "limit": max(1, min(limit, 50))},
    )
    return data.get("data", [])


async def get_comment(comment_id: str) -> dict[str, Any]:
    return await _request("GET", f"/{comment_id}", params={"fields": "id,text,username,hidden"})


async def reply_to_comment(comment_id: str, message: str) -> str:
    """Ommaviy javob — komment ostida hamma ko'radi."""
    data = await _request("POST", f"/{comment_id}/replies", json_body={"message": message})
    return data["id"]


async def hide_comment(comment_id: str, hide: bool = True) -> None:
    await _request("POST", f"/{comment_id}", json_body={"hide": hide})


async def delete_comment(comment_id: str) -> None:
    await _request("DELETE", f"/{comment_id}")


async def send_private_reply(comment_id: str, message: str) -> dict[str, Any]:
    """
    Kommentga DM orqali javob. Meta cheklovlari: bitta commentga FAQAT BIR marta,
    komment yaratilganidan keyin 7 kun ichida. instagram_manage_messages ruxsati kerak.
    """
    body = {"recipient": {"comment_id": comment_id}, "message": {"text": message}}
    return await _request("POST", f"/{_ig_id()}/messages", json_body=body)


# ── Webhook imzosi ─────────────────────────────────────────────────────────────
def verify_signature(payload: bytes, header: Optional[str]) -> bool:
    """X-Hub-Signature-256 ni META_APP_SECRET yoki IG_APP_SECRET bilan solishtiradi (doimiy vaqtli taqqoslash)."""
    import core.instagram_settings as settings
    secrets = [x for x in (os.getenv("META_APP_SECRET", ""), settings.app_secret()) if x]
    if not secrets or not header or not header.startswith("sha256="):
        return False
    given = header.split("=", 1)[1]
    return any(hmac.compare_digest(hmac.new(x.encode(), payload, hashlib.sha256).hexdigest(), given)
               for x in secrets)


async def subscribe_webhooks(fields: str = "comments,messages") -> dict:
    """Joriy akkauntni ilovaning webhook'lariga yozadi (Instagram Login'da har akkaunt uchun alohida kerak)."""
    return await _request("POST", f"/{_ig_id()}/subscribed_apps", params={"subscribed_fields": fields})


# ── Direct (DM) ────────────────────────────────────────────────────────────────
async def send_dm(recipient_id: str, text: str) -> Optional[str]:
    """
    Mijozga DM. Faqat mijoz yozganidan keyingi 24 soat ichida ishlaydi (Meta qoidasi).
    Human Agent teg'i FAQAT haqiqiy odam uchun — bot undan foydalana olmaydi.
    Qaytaradi: message_id (echo'ni tanish uchun).
    """
    data = await _request(
        "POST", f"/{_ig_id()}/messages",
        json_body={"recipient": {"id": recipient_id}, "message": {"text": text}},
    )
    return data.get("message_id") or data.get("id")


async def typing_on(recipient_id: str) -> None:
    """'Yozyapti...' belgisi; xato bersa e'tiborsiz."""
    try:
        await _request("POST", f"/{_ig_id()}/messages",
                       json_body={"recipient": {"id": recipient_id}, "sender_action": "typing_on"})
    except InstagramAPIError:
        pass
