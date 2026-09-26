"""
Foydalanuvchi profili haqida ma'lumot — username/ID/ism kabi asosiylari HAR
XABARDA avtomatik AI kontekstiga qo'shiladi (handlers/ai_chat.py), bio va
profil rasmi esa alohida AI tool orqali (kerak bo'lgandagina so'raladi —
har xabarda qo'shimcha so'rov yubormaslik uchun).
"""
from aiogram import Bot
import core.roles as roles


def basic_info_line(message) -> str:
    """Har bir xabarga qo'shiladigan qisqa ma'lumot qatori (qo'shimcha so'rovsiz)."""
    u = message.from_user
    parts = [f"ID={u.id}"]
    if u.username:
        parts.append(f"username=@{u.username}")
    name = u.first_name or ""
    if u.last_name:
        name += f" {u.last_name}"
    if name:
        parts.append(f"ism=\"{name}\"")
    return "Xabar yuboruvchi haqida: " + ", ".join(parts)


async def get_bio(bot: Bot, user_id: int) -> str | None:
    """
    Bio faqat bot bilan SHAXSIY chatni boshlagan foydalanuvchilar uchun
    olinadi (Telegram API cheklovi — guruh a'zoligi orqali emas).
    """
    try:
        chat = await bot.get_chat(user_id)
        return getattr(chat, "bio", None)
    except Exception:
        return None


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
