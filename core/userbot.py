"""
Userbot (Telethon) — FAQAT O'QISH. Bot API ko'rmaydigan narsalarni AI uchun o'qiydi:
guruh a'zolari ro'yxati (admin bo'lmaganlar ham), profil (ism/username/bio), profil rasmlari,
story'lar (faol + mahkamlangan), ochiq kanal postlari.

Xavfsizlik qarorlari:
  - Session/API_ID/API_HASH faqat ENV'da (USERBOT_*). DB'ga, loglarga yoki guruhdagi db.json'ga YOZILMAYDI.
  - Faqat o'qiydi: xabar yubormaydi, story'ni "ko'rildi" qilib belgilamaydi (ReadStories chaqirilmaydi),
    guruhga qo'shilmaydi. Telegram'ning o'z maxfiylik sozlamalari (yashirin bio/story/a'zolar) o'z-o'zidan
    amal qiladi — akkaunt ko'rmagan narsani biz ham ko'rmaymiz.
  - O'sha session boshqa joyda (masalan boshqa userbot yoki ikkinchi nusxa) bir vaqtda ishlatilsa Telegram
    uni bekor qiladi (AUTH_KEY_DUPLICATED) — shunda funksiya o'zini o'chirib qo'yadi, bot ishlashda davom etadi.
  - Soatiga so'rov limiti (admin/superadmin'dan tashqari) va FloodWait himoyasi.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass

import config

logger = logging.getLogger("userbot")

MAX_MEMBERS = 5000
MAX_PHOTOS = 10
MAX_STORIES = 10
MAX_POSTS = 10
MAX_VIDEO_BYTES = 45 * 1024 * 1024  # Bot API yuklash limiti 50MB
MAX_FLOOD_SLEEP = 30  # shundan uzoq FloodWait bo'lsa kutib o'tirmaymiz

_client = None
_disabled_reason: str | None = None
_rate: dict[int, deque] = defaultdict(deque)

# @username -> (id, ism): qisqa muddatli xotira keshi. Username boshqa odamga o'tib ketishi mumkin,
# shuning uchun TTL qisqa va kesh faqat RAMda (diskka/DB'ga yozilmaydi).
USERNAME_CACHE_TTL = 600
USERNAME_CACHE_MAX = 500
_username_cache: dict[str, tuple[float, int, str]] = {}


class UserbotError(Exception):
    """Foydalanuvchiga ko'rsatsa bo'ladigan, tushunarli xato."""


@dataclass
class MediaItem:
    kind: str  # "photo" | "video"
    data: bytes
    caption: str = ""
    meta: str = ""


# ── holat ────────────────────────────────────────────────────────────────

def is_configured() -> bool:
    return bool(config.USERBOT_API_ID and config.USERBOT_API_HASH and config.USERBOT_SESSION)


def is_enabled() -> bool:
    return _client is not None and _disabled_reason is None


def disabled_reason() -> str | None:
    return _disabled_reason


async def start() -> bool:
    """Bot ishga tushganda chaqiriladi. Muvaffaqiyatsiz bo'lsa bot yiqilmaydi — funksiya o'chiriladi."""
    global _client, _disabled_reason
    if not is_configured():
        logger.info("Userbot sozlanmagan (USERBOT_API_ID/HASH/SESSION yo'q) — o'chiq.")
        return False
    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
    except ImportError:
        _disabled_reason = "telethon o'rnatilmagan"
        logger.warning("Userbot: %s", _disabled_reason)
        return False

    client = TelegramClient(
        StringSession(config.USERBOT_SESSION), config.USERBOT_API_ID, config.USERBOT_API_HASH,
        receive_updates=False,  # faqat so'rov-javob: update oqimi kerak emas
    )
    try:
        await client.connect()
        if not await client.is_user_authorized():
            raise UserbotError("session yaroqsiz yoki akkauntdan chiqarilgan")
        me = await client.get_me()
        await client.get_dialogs(limit=200)  # entity keshi (guruhlarni topish uchun)
    except Exception as e:  # noqa: BLE001
        _disabled_reason = f"ulanmadi: {type(e).__name__}"
        logger.warning("Userbot ulanmadi: %s", e)
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass
        return False
    _client = client
    _disabled_reason = None
    logger.info("Userbot ulandi (akkaunt id=%s).", getattr(me, "id", "?"))
    return True


async def stop() -> None:
    global _client
    if _client is not None:
        try:
            await _client.disconnect()
        finally:
            _client = None


def _require():
    if _client is None or _disabled_reason is not None:
        raise UserbotError("Userbot ulanmagan yoki o'chirilgan.")
    return _client


# ── limit / xatolarni boshqarish ─────────────────────────────────────────

def rate_limit_wait(user_id: int, limit: int | None = None, now: float | None = None) -> int:
    """Limit oshgan bo'lsa necha soniya kutish kerakligini qaytaradi (0 — mumkin). Mumkin bo'lsa hisoblaydi."""
    limit = config.USERBOT_RATE_PER_HOUR if limit is None else limit
    now = time.time() if now is None else now
    q = _rate[user_id]
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) >= limit:
        return int(3600 - (now - q[0])) + 1
    q.append(now)
    return 0


async def _call(factory):
    """Telethon so'rovini FloodWait/sessiya xatolaridan himoya qilib bajaradi. factory — har safar yangi coroutine."""
    global _disabled_reason
    from telethon import errors

    for attempt in range(2):
        try:
            return await factory()
        except errors.FloodWaitError as e:
            if attempt == 0 and e.seconds <= MAX_FLOOD_SLEEP:
                await asyncio.sleep(e.seconds + 1)
                continue
            raise UserbotError(f"Telegram {e.seconds} soniya kutishni so'radi (FloodWait). Birozdan keyin urinib ko'ring.")
        except (errors.AuthKeyDuplicatedError, errors.AuthKeyUnregisteredError,
                errors.SessionRevokedError, errors.UserDeactivatedError, errors.UserDeactivatedBanError) as e:
            _disabled_reason = f"session bekor bo'ldi: {type(e).__name__}"
            logger.error("Userbot o'chirildi: %s", _disabled_reason)
            raise UserbotError("Userbot sessiyasi bekor qilingan — egasi yangi session kiritishi kerak.")
        except errors.ChatAdminRequiredError:
            raise UserbotError("Bu guruhda a'zolar ro'yxati yashirin (faqat adminlar ko'ra oladi).")
        except (errors.ChannelPrivateError, errors.ChatForbiddenError):
            raise UserbotError("Userbot akkaunti bu chatga/kanalga a'zo emas yoki kirish yopiq.")
        except (errors.UsernameNotOccupiedError, errors.UsernameInvalidError):
            raise UserbotError("Bunday username topilmadi.")
        except errors.RPCError as e:
            raise UserbotError(f"Telegram xatosi: {type(e).__name__}")
    raise UserbotError("Telegram javob bermadi.")


def parse_target(raw: str):
    """'@ali', 'https://t.me/ali', 'ali', '12345' -> str username yoki int ID."""
    s = (raw or "").strip()
    if not s:
        raise UserbotError("Foydalanuvchi/kanal ko'rsatilmagan.")
    s = re.sub(r"^https?://(t\.me|telegram\.me)/", "", s, flags=re.I).split("/")[0].split("?")[0]
    s = s.lstrip("@").strip()
    if re.fullmatch(r"-?\d{5,15}", s):
        return int(s)
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,31}", s):
        return s
    raise UserbotError("Noto'g'ri username/ID formati.")


def display_name(user) -> str:
    name = " ".join(p for p in (getattr(user, "first_name", None), getattr(user, "last_name", None)) if p)
    return name or getattr(user, "title", None) or "(ismsiz)"


def usernames_of(user) -> list[str]:
    result = []
    if getattr(user, "username", None):
        result.append(user.username)
    for u in getattr(user, "usernames", None) or []:
        if getattr(u, "active", True) and getattr(u, "username", None) and u.username not in result:
            result.append(u.username)
    return result


# ── foydalanuvchini topish ───────────────────────────────────────────────

async def resolve_user(target: str, chat_id: int | None = None):
    from telethon import types

    client = _require()
    value = parse_target(target)
    entity = None
    try:
        entity = await _call(lambda: client.get_entity(value))
    except UserbotError:
        raise
    except (ValueError, TypeError):
        entity = None
    if entity is None and isinstance(value, int) and chat_id is not None:
        # raqamli ID access_hash'siz topilmaydi — shu guruh a'zolari orasidan qidiramiz (keshga tushadi)
        group = await _call(lambda: client.get_entity(chat_id))
        members = await _call(lambda: client.get_participants(group, limit=MAX_MEMBERS))
        entity = next((m for m in members if m.id == value), None)
    if entity is None:
        raise UserbotError("Foydalanuvchi topilmadi (username yoki shu guruhdagi ID bering).")
    if not isinstance(entity, types.User):
        raise UserbotError("Bu foydalanuvchi emas (kanal yoki guruh).")
    return entity


async def find_user_by_username(username: str, now: float | None = None) -> tuple[int, str] | None:
    """@username -> (user_id, ism). MTProto orqali OCHIQ username'ni topadi — odam botga/guruhga hali
    hech narsa yozmagan bo'lsa ham (Bot API buni qila olmaydi). Moderatsiya (mute/ban) uchun nishonni
    aniqlashda zaxira yo'l sifatida ishlatiladi.

    None qaytaradi: userbot o'chiq/ulanmagan, username yo'q yoki yashirin, yoki u odam emas
    (kanal, guruh, bot, o'chirilgan akkaunt). Xatolar (FloodWait va h.k.) bu yerda yutiladi —
    chaqiruvchi shunchaki «topilmadi» yo'liga tushadi.
    """
    if not is_enabled():
        return None
    try:
        value = parse_target(username)
    except UserbotError:
        return None
    if not isinstance(value, str):  # raqamli ID — bu funksiya faqat username uchun
        return None

    now = time.time() if now is None else now
    key = value.lower()
    hit = _username_cache.get(key)
    if hit and now - hit[0] < USERNAME_CACHE_TTL:
        return hit[1], hit[2]

    try:
        user = await resolve_user(value)
    except UserbotError as e:
        logger.info("Username topilmadi (@%s): %s", value, e)
        return None
    if getattr(user, "bot", False) or getattr(user, "deleted", False):
        return None

    name = display_name(user)
    if len(_username_cache) >= USERNAME_CACHE_MAX:
        for k, _ in sorted(_username_cache.items(), key=lambda kv: kv[1][0])[: USERNAME_CACHE_MAX // 5]:
            _username_cache.pop(k, None)
    _username_cache[key] = (now, user.id, name)
    return user.id, name


# ── o'qish funksiyalari ──────────────────────────────────────────────────

async def list_members(chat_id: int, limit: int = MAX_MEMBERS) -> dict:
    client = _require()
    limit = max(1, min(int(limit), MAX_MEMBERS))
    group = await _call(lambda: client.get_entity(chat_id))
    members = await _call(lambda: client.get_participants(group, limit=limit))
    rows = []
    for m in members:
        rows.append({
            "id": m.id,
            "name": display_name(m),
            "username": (usernames_of(m) or [None])[0],
            "bot": bool(getattr(m, "bot", False)),
            "deleted": bool(getattr(m, "deleted", False)),
        })
    total = getattr(members, "total", len(rows)) or len(rows)
    return {"total": total, "members": rows}


async def get_profile(target: str, chat_id: int | None = None) -> dict:
    from telethon.tl import functions

    client = _require()
    user = await resolve_user(target, chat_id)
    full = await _call(lambda: client(functions.users.GetFullUserRequest(user)))
    fu = full.full_user
    photos = await _call(lambda: client.get_profile_photos(user, limit=1))
    info = {
        "id": user.id,
        "name": display_name(user),
        "usernames": usernames_of(user),
        "bio": getattr(fu, "about", None) or "",
        "photos_count": getattr(photos, "total", len(photos)),
        "premium": bool(getattr(user, "premium", False)),
        "bot": bool(getattr(user, "bot", False)),
        "verified": bool(getattr(user, "verified", False)),
        "scam_or_fake": bool(getattr(user, "scam", False) or getattr(user, "fake", False)),
    }
    pc = getattr(fu, "personal_channel_id", None)
    if pc:
        try:
            ch = await _call(lambda: client.get_entity(pc))
            info["personal_channel"] = {"title": getattr(ch, "title", None), "username": getattr(ch, "username", None)}
        except UserbotError:
            pass
    return info


async def get_profile_photos(target: str, limit: int = 1, chat_id: int | None = None) -> list[MediaItem]:
    client = _require()
    limit = max(1, min(int(limit), MAX_PHOTOS))
    user = await resolve_user(target, chat_id)
    photos = await _call(lambda: client.get_profile_photos(user, limit=limit))
    items = []
    for p in photos:
        data = await _call(lambda p=p: client.download_media(p, file=bytes))
        if data:
            items.append(MediaItem("photo", data, meta=f"profil rasmi, {p.date:%Y-%m-%d}"))
    return items


def _media_kind(media) -> str | None:
    from telethon import types

    if isinstance(media, types.MessageMediaPhoto):
        return "photo"
    if isinstance(media, types.MessageMediaDocument) and media.document is not None:
        mime = getattr(media.document, "mime_type", "") or ""
        if mime.startswith("video/"):
            return "video"
    return None


def _media_size(media) -> int:
    doc = getattr(media, "document", None)
    return int(getattr(doc, "size", 0) or 0)


async def get_stories(target: str, include_pinned: bool = True, limit: int = MAX_STORIES,
                      chat_id: int | None = None) -> list[MediaItem]:
    """Faol (24 soatlik) va mahkamlangan story'lar. ReadStories CHAQIRILMAYDI — egasiga 'ko'rildi' bildirilmaydi."""
    from telethon import types
    from telethon.tl import functions

    client = _require()
    limit = max(1, min(int(limit), MAX_STORIES))
    user = await resolve_user(target, chat_id)
    peer = await _call(lambda: client.get_input_entity(user))

    stories = []
    active = await _call(lambda: client(functions.stories.GetPeerStoriesRequest(peer=peer)))
    stories += [s for s in active.stories.stories if isinstance(s, types.StoryItem)]
    if include_pinned:
        pinned = await _call(lambda: client(functions.stories.GetPinnedStoriesRequest(peer=peer, offset_id=0, limit=limit)))
        seen = {s.id for s in stories}
        stories += [s for s in pinned.stories if isinstance(s, types.StoryItem) and s.id not in seen]

    items: list[MediaItem] = []
    for s in stories[:limit]:
        kind = _media_kind(s.media)
        if kind is None:
            continue
        if kind == "video" and _media_size(s.media) > MAX_VIDEO_BYTES:
            continue  # Bot API orqali yuborib bo'lmaydi
        data = await _call(lambda s=s: client.download_media(s.media, file=bytes))
        if data:
            items.append(MediaItem(kind, data, caption=(s.caption or ""),
                                   meta=f"story, {s.date:%Y-%m-%d %H:%M}" + (", mahkamlangan" if s.pinned else "")))
    return items


async def get_channel_posts(channel: str, limit: int = 5, with_media: bool = True) -> list[dict]:
    """Ochiq kanal (yoki a'zo bo'lingan kanal) so'nggi postlari. Matn + (ixtiyoriy) rasm/video baytlari."""
    from telethon import types

    client = _require()
    limit = max(1, min(int(limit), MAX_POSTS))
    ent = await _call(lambda: client.get_entity(parse_target(channel)))
    if not isinstance(ent, types.Channel):
        raise UserbotError("Bu kanal emas.")
    msgs = await _call(lambda: client.get_messages(ent, limit=limit))
    posts = []
    for m in msgs:
        kind = _media_kind(m.media) if m.media else None
        post = {
            "id": m.id,
            "date": f"{m.date:%Y-%m-%d %H:%M}",
            "text": (m.message or "")[:700],
            "link": f"https://t.me/{ent.username}/{m.id}" if ent.username else None,
            "media": kind or ("fayl" if m.media else None),
            "_data": None,
        }
        if with_media and kind and not (kind == "video" and _media_size(m.media) > MAX_VIDEO_BYTES):
            post["_data"] = await _call(lambda m=m: client.download_media(m.media, file=bytes))
        posts.append(post)
    return posts
