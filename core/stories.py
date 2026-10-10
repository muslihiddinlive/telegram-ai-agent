"""
Foydalanuvchi profiliga STORY qo'yish — Telegram Business orqali (Bot API 9.0: postStory).

Ishlash tartibi:
  1) Foydalanuvchi (Telegram Premium) botni o'z profiliga "chatbot" sifatida ulaydi
     (Sozlamalar -> Telegram Business -> Chatbotlar) va "story'larni boshqarish" ruxsatini beradi.
     Telegram botga `business_connection` update yuboradi -> save_connection() saqlaydi.
  2) Foydalanuvchi bot menyusidan (yoki AI'ga "buni storyga qo'y" deb) rasm/video yuboradi.
  3) Fayl Story talabiga moslanadi (rasm 1080x1920 JPEG <=10MB; video 720x1280 H.265/MP4 <=30MB)
     va post_story() bilan FOYDALANUVCHI NOMIDAN joylanadi.

Eslatma: aiogram'da InputStoryContent*.photo/video maydoni `str` deb tiplangan, lekin Story fayli
FAQAT yangi yuklangan fayl (attach://) bo'lishi mumkin — shuning uchun model_construct bilan
InputFile beramiz (multipart ga to'g'ri o'tishi test qilingan).
"""
import asyncio
import logging
import os
import tempfile
import time

from aiogram.types import FSInputFile, InputStoryContentPhoto, InputStoryContentVideo
from PIL import Image, ImageFilter, ImageOps

import core.tgdb as tgdb

logger = logging.getLogger("stories")

PERIODS = {6: 6 * 3600, 12: 12 * 3600, 24: 24 * 3600, 48: 48 * 3600}  # soat -> soniya (Telegram ruxsat etganlari)
DEFAULT_HOURS = 24

PHOTO_SIZE = (1080, 1920)
VIDEO_SIZE = (720, 1280)
MAX_PHOTO_BYTES = 10 * 1024 * 1024
MAX_VIDEO_BYTES = 30 * 1024 * 1024
MAX_VIDEO_SECONDS = 60
TG_DOWNLOAD_LIMIT = 20 * 1024 * 1024  # Bot API bot uchun fayl yuklab olish chegarasi
MAX_CAPTION = 2048

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".3gp"}


class StoryError(Exception):
    """Foydalanuvchiga ko'rsatiladigan tushunarli xato."""


def work_dir(user_id: int) -> str:
    path = os.path.join(tempfile.gettempdir(), "story_work", str(user_id))
    os.makedirs(path, exist_ok=True)
    return path


def kind_of(filename: str) -> str | None:
    ext = os.path.splitext(filename or "")[1].lower()
    if ext in IMAGE_EXT:
        return "photo"
    if ext in VIDEO_EXT:
        return "video"
    return None


# ───────────────────────── ulanish (business_connection) ─────────────────────────

def _store() -> dict:
    return tgdb.get().setdefault("business", {})


async def save_connection(bot, bc) -> dict:
    """BusinessConnection update'idan ulanish holatini saqlaydi (kalit — hisob egasining user_id'si)."""
    rights = getattr(bc, "rights", None)
    rec = {
        "id": bc.id,
        "chat_id": bc.user_chat_id,
        "enabled": bool(bc.is_enabled),
        "stories": bool(rights and rights.can_manage_stories),
        "t": int(time.time()),
    }
    _store()[str(bc.user.id)] = rec
    await tgdb.save(bot, force=True)
    return rec


def get_connection(user_id: int) -> dict | None:
    return _store().get(str(user_id))


def status(user_id: int) -> str:
    """'none' | 'disabled' | 'no_rights' | 'ready'"""
    rec = get_connection(user_id)
    if not rec:
        return "none"
    if not rec.get("enabled"):
        return "disabled"
    if not rec.get("stories"):
        return "no_rights"
    return "ready"


# ───────────────────────── tayyorlash ─────────────────────────

def _prepare_photo_sync(src: str, dst: str):
    W, H = PHOTO_SIZE
    try:
        with Image.open(src) as raw:
            im = ImageOps.exif_transpose(raw).convert("RGB")
    except Exception as e:  # noqa: BLE001
        raise StoryError(f"Rasmni o'qib bo'lmadi: {e}") from e
    # Orqa fon: rasmning o'zi xiralashtirilgan holda (qora chiziqlar o'rniga), ustida — to'liq rasm
    bg = ImageOps.fit(im, (W, H), Image.LANCZOS).filter(ImageFilter.GaussianBlur(40))
    bg = Image.blend(bg, Image.new("RGB", (W, H), (0, 0, 0)), 0.25)
    fg = ImageOps.contain(im, (W, H), Image.LANCZOS)
    bg.paste(fg, ((W - fg.width) // 2, (H - fg.height) // 2))
    for quality in (92, 85, 75, 60):
        bg.save(dst, "JPEG", quality=quality, optimize=True)
        if os.path.getsize(dst) <= MAX_PHOTO_BYTES:
            return
    raise StoryError("Rasm juda katta bo'lib qoldi (10 MB dan oshdi).")


async def prepare_photo(src: str, dst: str):
    await asyncio.to_thread(_prepare_photo_sync, src, dst)


async def _run(*cmd: str, timeout: int) -> str:
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
    except FileNotFoundError as e:
        raise StoryError("Serverda ffmpeg o'rnatilmagan — video qayta ishlanmaydi.") from e
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise StoryError("Videoni qayta ishlash juda uzoq davom etdi — qisqaroq video yuboring.")
    if proc.returncode != 0:
        logger.warning("%s xato: %s", cmd[0], err.decode(errors="ignore")[-400:])
        raise StoryError("Videoni qayta ishlab bo'lmadi (format qo'llab-quvvatlanmaydi bo'lishi mumkin).")
    return out.decode(errors="ignore")


async def prepare_video(src: str, dst: str) -> float:
    """Story talabi: 720x1280, H.265, MPEG4, har soniyada key frame, <=30MB. Davomiylik qaytariladi."""
    out = await _run("ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=nw=1:nk=1", src, timeout=30)
    try:
        total = float(out.strip())
    except ValueError as e:
        raise StoryError("Video davomiyligini aniqlab bo'lmadi.") from e
    duration = min(total, MAX_VIDEO_SECONDS)
    W, H = VIDEO_SIZE
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
          f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps=30")
    for crf in (28, 34):
        await _run(
            "ffmpeg", "-y", "-i", src, "-t", str(MAX_VIDEO_SECONDS),
            "-map", "0:v:0", "-map", "0:a:0?", "-vf", vf,
            "-c:v", "libx265", "-preset", "veryfast", "-crf", str(crf), "-tag:v", "hvc1",
            "-x265-params", "keyint=30:min-keyint=30:scenecut=0:log-level=error",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", dst,
            timeout=600,
        )
        if os.path.getsize(dst) <= MAX_VIDEO_BYTES:
            return duration
    raise StoryError("Video 30 MB dan kichik qilib siqilmadi — qisqaroq video yuboring.")


async def prepare(kind: str, src: str, dst_dir: str) -> tuple[str, float | None]:
    """(tayyor fayl yo'li, video davomiyligi) qaytaradi."""
    if kind == "photo":
        dst = os.path.join(dst_dir, "story.jpg")
        await prepare_photo(src, dst)
        return dst, None
    dst = os.path.join(dst_dir, "story.mp4")
    return dst, await prepare_video(src, dst)


# ───────────────────────── joylash / o'chirish ─────────────────────────

def _friendly(e: Exception) -> str:
    text = str(e)
    low = text.lower()
    if "rights" in low or "forbidden" in low or "not enough" in low or "can_manage_stories" in low:
        return ("Botda story boshqarish ruxsati yo'q. Telegram → Sozlamalar → Telegram Business → Chatbotlar "
                "bo'limida bot ruxsatlaridan story'larni yoqing.")
    if "premium" in low:
        return "Story qo'yish uchun hisobingizda Telegram Premium bo'lishi kerak."
    if "connection" in low:
        return "Business ulanish topilmadi yoki o'chirilgan — botni profilga qayta ulang."
    return text


async def post(bot, user_id: int, kind: str, path: str, hours: int = DEFAULT_HOURS,
               caption: str | None = None, entities=None, duration: float | None = None,
               is_animation: bool = False, protect_content: bool = False, post_to_chat_page: bool = True,
               areas=None):
    """Tayyor faylni foydalanuvchi profiliga story qilib joylaydi. Story obyektini qaytaradi.
    protect_content — storyni saqlash/forward qilishni taqiqlaydi; post_to_chat_page — muddat tugagach profilda qoladimi;
    areas — bosiladigan maydonlar (havola/reaksiya, core/story_areas)."""
    st = status(user_id)
    if st != "ready":
        raise StoryError({
            "none": "Bot hali profilingizga ulanmagan.",
            "disabled": "Business ulanish o'chirilgan — botni profilga qayta ulang.",
            "no_rights": "Botga story boshqarish ruxsati berilmagan.",
        }[st])
    conn = get_connection(user_id)
    period = PERIODS.get(hours, PERIODS[DEFAULT_HOURS])

    if kind == "photo":
        content = InputStoryContentPhoto.model_construct(type="photo", photo=FSInputFile(path))
    else:
        content = InputStoryContentVideo.model_construct(
            type="video", video=FSInputFile(path), duration=duration or 0.0,
            cover_frame_timestamp=None, is_animation=is_animation,
        )
    caption = (caption or "").strip() or None
    if caption and len(caption) > MAX_CAPTION:
        caption, entities = caption[:MAX_CAPTION], None  # kesilsa entity ofsetlari buzilishi mumkin

    try:
        story = await bot.post_story(
            business_connection_id=conn["id"], content=content, active_period=period,
            caption=caption, caption_entities=entities if caption else None,
            parse_mode=None, post_to_chat_page=post_to_chat_page,
            protect_content=True if protect_content else None, areas=areas or None,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("post_story xato (user %s): %s", user_id, e)
        raise StoryError(_friendly(e)) from e
    remember_post(user_id, getattr(story, "id", None), kind, caption, hours)
    return story


# ── Joylangan storylar tarixi (Bot API storylar ro'yxatini bermaydi: o'zimiz yozib boramiz) ──
HISTORY_LIMIT = 20


def remember_post(user_id: int, story_id, kind: str, caption: str | None, hours: int) -> None:
    """Yangi story yozuvi (eng yangisi birinchi). DB yo'q/xato bo'lsa — jim o'tadi (joylash bunga bog'liq emas)."""
    if story_id is None:
        return
    try:
        import core.tgdb as tgdb
        import time
        lst = tgdb.get().setdefault("story_posts", {}).setdefault(str(user_id), [])
        lst.insert(0, {"id": int(story_id), "t": int(time.time()), "h": hours, "k": kind, "c": (caption or "")[:60]})
        del lst[HISTORY_LIMIT:]
        tgdb.mark_dirty()
    except Exception:  # noqa: BLE001
        logger.warning("Story tarixiga yozib bo'lmadi", exc_info=True)


def list_posts(user_id: int) -> list[dict]:
    """Hali faol (muddati tugamagan) storylar, eng yangisi birinchi."""
    try:
        import core.tgdb as tgdb
        import time
        now = time.time()
        return [p for p in tgdb.get().get("story_posts", {}).get(str(user_id), []) if p["t"] + p["h"] * 3600 > now]
    except Exception:  # noqa: BLE001
        return []


def forget_post(user_id: int, story_id: int) -> None:
    try:
        import core.tgdb as tgdb
        lst = tgdb.get().get("story_posts", {}).get(str(user_id), [])
        lst[:] = [p for p in lst if p["id"] != story_id]
        tgdb.mark_dirty()
    except Exception:  # noqa: BLE001
        pass


async def delete(bot, user_id: int, story_id: int):
    conn = get_connection(user_id)
    if not conn:
        raise StoryError("Business ulanish topilmadi.")
    try:
        await bot.delete_story(business_connection_id=conn["id"], story_id=story_id)
    except Exception as e:  # noqa: BLE001
        raise StoryError(_friendly(e)) from e
    forget_post(user_id, story_id)


def cleanup(*paths: str | None):
    for p in paths:
        if p:
            try:
                os.remove(p)
            except OSError:
                pass
