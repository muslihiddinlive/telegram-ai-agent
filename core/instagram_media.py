"""
core/instagram_media.py
-----------------------
Instagram API faylni O'ZI yuklab oladi, shuning uchun media ommaviy HTTPS URL'da
turishi shart. Bu modul ikki ishni qiladi:

1. prepare_image(): rasmni Instagram talabiga moslaydi (JPEG, to'g'ri nisbat,
   story uchun 1080x1920; ortiqcha joy xiralashtirilgan fon bilan to'ldiriladi).
2. expose()/revoke()/register(): faylni tasodifiy, vaqtinchalik token bilan
   `/ig-media/<token>/media.jpg` manzilida beradi. Token e'londan keyin
   o'chiriladi, shuning uchun foydalanuvchi fayllari doimiy ochiq qolmaydi.
"""
from __future__ import annotations

import os
import secrets
import time
import uuid
from typing import Optional

from aiohttp import web

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VIDEO_EXT = {".mp4", ".mov"}
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_VIDEO_BYTES = 300 * 1024 * 1024
FEED_MIN_RATIO = 0.8    # 4:5
FEED_MAX_RATIO = 1.91
FEED_MAX_WIDTH = 1440
STORY_SIZE = (1080, 1920)
DEFAULT_TTL = 1800

ROUTE = "/ig-media/{token}/{name}"


class MediaError(Exception):
    pass


def kind_of(file_name: str) -> Optional[str]:
    ext = os.path.splitext(file_name)[1].lower()
    if ext in IMAGE_EXT:
        return "image"
    if ext in VIDEO_EXT:
        return "video"
    return None


# ── Rasm tayyorlash ────────────────────────────────────────────────────────────
def _fit_canvas(im, cw: int, ch: int):
    from PIL import Image, ImageFilter, ImageOps

    bg = ImageOps.fit(im, (cw, ch), Image.LANCZOS).filter(ImageFilter.GaussianBlur(30))
    fg = ImageOps.contain(im, (cw, ch), Image.LANCZOS)
    bg.paste(fg, ((cw - fg.width) // 2, (ch - fg.height) // 2))
    return bg


def prepare_image(src: str, dst_dir: str, *, story: bool) -> str:
    """Rasmni Instagram uchun JPEG qilib dst_dir'ga yozadi; yangi fayl yo'lini qaytaradi."""
    from PIL import Image, ImageOps

    try:
        with Image.open(src) as raw:
            im = ImageOps.exif_transpose(raw).convert("RGB")
    except Exception as e:
        raise MediaError(f"Rasmni ochib bo'lmadi: {e}") from e

    if story:
        im = _fit_canvas(im, *STORY_SIZE)
    else:
        if im.width > FEED_MAX_WIDTH:
            im = im.resize((FEED_MAX_WIDTH, round(im.height * FEED_MAX_WIDTH / im.width)), Image.LANCZOS)
        ratio = im.width / im.height
        if ratio < FEED_MIN_RATIO:      # juda baland → kenglikni oshiramiz
            im = _fit_canvas(im, int(im.height * FEED_MIN_RATIO) + 1, im.height)
        elif ratio > FEED_MAX_RATIO:    # juda keng → balandlikni oshiramiz
            im = _fit_canvas(im, im.width, int(im.width / FEED_MAX_RATIO) + 1)

    out = os.path.join(dst_dir, f"{uuid.uuid4().hex}.jpg")
    for quality in (92, 80, 65):
        im.save(out, "JPEG", quality=quality, optimize=True)
        if os.path.getsize(out) <= MAX_IMAGE_BYTES:
            return out
    raise MediaError("Rasm juda katta (8 MB dan oshdi)")


def check_video(src: str) -> str:
    if os.path.getsize(src) > MAX_VIDEO_BYTES:
        raise MediaError("Video juda katta (300 MB dan oshdi)")
    return src


# ── Vaqtinchalik ommaviy URL ───────────────────────────────────────────────────
_FILES: dict[str, tuple[str, float]] = {}  # token -> (yo'l, tugash vaqti)


def public_base() -> str:
    base = (
        os.getenv("IG_PUBLIC_BASE_URL")
        or os.getenv("WEBHOOK_URL")
        or os.getenv("PUBLIC_BASE_URL")
        or os.getenv("RENDER_EXTERNAL_URL")
    )
    if not base:
        raise MediaError("Ommaviy manzil topilmadi: IG_PUBLIC_BASE_URL (yoki WEBHOOK_URL) o'rnatilmagan")
    return base.rstrip("/")


def _purge() -> None:
    now = time.time()
    for token in [t for t, (_, exp) in _FILES.items() if exp < now]:
        _FILES.pop(token, None)


def expose(path: str, ttl: int = DEFAULT_TTL) -> str:
    _purge()
    token = secrets.token_urlsafe(24)
    ext = os.path.splitext(path)[1].lower() or ".bin"
    _FILES[token] = (path, time.time() + ttl)
    return f"{public_base()}/ig-media/{token}/media{ext}"


def revoke(url: str) -> None:
    parts = url.rstrip("/").split("/")
    if len(parts) >= 2:
        _FILES.pop(parts[-2], None)


async def _serve(request: web.Request) -> web.StreamResponse:
    entry = _FILES.get(request.match_info["token"])
    if not entry or entry[1] < time.time() or not os.path.isfile(entry[0]):
        raise web.HTTPNotFound()
    return web.FileResponse(entry[0], headers={"Cache-Control": "no-store"})


def register(app: web.Application) -> None:
    """main.py'da: instagram_media.register(app)"""
    app.router.add_get(ROUTE, _serve)
