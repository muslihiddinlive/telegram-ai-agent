"""
Foydalanuvchi profili haqida ma'lumot — username/ID/ism VA bio HAR XABARDA
avtomatik AI kontekstiga qo'shiladi (handlers/ai_chat.py). Profil RASMI esa
alohida AI tool orqali (get_user_profile — kerak bo'lgandagina so'raladi,
chunki rasm yuborish alohida amal, matn kontekstiga yozib bo'lmaydi).
"""
import time
from aiogram import Bot
import core.roles as roles

_bio_cache: dict[int, tuple[float, str | None]] = {}  # user_id -> (vaqt, bio)
_BIO_CACHE_TTL = 600  # 10 daqiqa — HAR xabarda Telegram API'ga murojaat qilmaslik uchun


async def basic_info_line(bot: Bot, message) -> str:
    """Har bir xabarga qo'shiladigan qisqa ma'lumot qatori. Endi BIO ham
    shu yerda avtomatik o'qiladi (avval faqat alohida tool orqali so'ralar
    edi) — foydalanuvchi buni har safar AI'dan so'ramasdan, kontekstda
    doim tayyor bo'lishini xohladi."""
    u = message.from_user
    parts = [f"ID={u.id}"]
    if u.username:
        parts.append(f"username=@{u.username}")
    name = u.first_name or ""
    if u.last_name:
        name += f" {u.last_name}"
    if name:
        parts.append(f"ism=\"{name}\"")

    bio = await get_bio(bot, u.id)
    if bio:
        parts.append(f"bio=\"{bio}\"")

    return "Xabar yuboruvchi haqida: " + ", ".join(parts)


async def get_bio(bot: Bot, user_id: int) -> str | None:
    """
    Bio faqat bot bilan SHAXSIY chatni boshlagan foydalanuvchilar uchun
    olinadi (Telegram API cheklovi — guruh a'zoligi orqali emas).

    10 daqiqalik KESH bilan — chatmode/guruhda HAR xabarda Telegram'ga
    qo'shimcha so'rov yubormaslik uchun (rate-limit xavfini kamaytiradi).
    """
    now = time.monotonic()
    cached = _bio_cache.get(user_id)
    if cached and now - cached[0] < _BIO_CACHE_TTL:
        return cached[1]
    try:
        chat = await bot.get_chat(user_id)
        bio = getattr(chat, "bio", None)
    except Exception:
        bio = None
    _bio_cache[user_id] = (now, bio)
    return bio


async def send_profile_photo(bot: Bot, user_id: int, chat_id: int, thread_id: int | None) -> bool:
    """Eng so'nggi profil rasmini (eng katta o'lchamda) shu chatga yuboradi."""
    try:
        photos = await bot.get_user_profile_photos(user_id, limit=1)
        if photos.total_count == 0:
            return False
        largest = photos.photos[0][-1]
        await bot.send_photo(chat_id, largest.file_id, message_thread_id=thread_id)
        return True
    except Exception:
        return False


async def get_full_profile(bot: Bot, requester_id: int, target_user_id: int, chat_id: int, thread_id: int | None) -> dict:
    """
    Boshqa birovning profilini so'rash — FAQAT admin/superadmin uchun
    (maxfiylik). O'zining profilini har kim so'rashi mumkin.
    """
    if target_user_id != requester_id and not (roles.is_superadmin(requester_id) or roles.is_admin(requester_id)):
        return {"error": "Boshqa foydalanuvchi profilini faqat admin so'rashi mumkin."}

    bio = await get_bio(bot, target_user_id)
    photo_sent = await send_profile_photo(bot, target_user_id, chat_id, thread_id)

    result = {"user_id": target_user_id, "bio": bio or "(bio o'rnatilmagan yoki mavjud emas)"}
    result["profile_photo"] = "Yuborildi ✅" if photo_sent else "Profil rasmi topilmadi"
    return result
