"""
"/chatmode on" — guruh admin/egasi yoqsa, bot HAR BIR xabarga (tag/reply
shart emas) javob beradi — masalan kimdir shunchaki "wassup" desa ham.

Ishlatilgan so'rovlar — kim yozganidan qat'iy nazar — shu rejimni YOQQAN
odamning (owner_id) kunlik hisobidan hisoblanadi (core/roles.py). Agar
o'sha odam superadmin/admin bo'lsa, amalda CHEKSIZ davom etadi (ular
umuman limitlanmagan). Chatmode YOQILGAN guruhda kunlik limit UMUMAN
tekshirilmaydi (handlers/ai_chat.py) — faqat hisobga olish uchun yoziladi.

Bundan tashqari, chatmode YOQILGAN guruhda core/bot_loop_guard.py'ning
avtomatik bot-bot zanjir-uzish himoyasi ATAYLAB o'chiriladi — guruh
egasi ongli ravishda "botlar cheksiz gaplashaversin" deb tanlagani uchun.
"""
import core.tgdb as tgdb


def _bucket() -> dict:
    db = tgdb.get()
    return db.setdefault("chat_mode", {})


async def enable(bot, chat_id: int, owner_id: int):
    _bucket()[str(chat_id)] = {"enabled": True, "owner_id": owner_id}
    await tgdb.save(bot, force=True)


async def disable(bot, chat_id: int):
    _bucket().pop(str(chat_id), None)
    await tgdb.save(bot, force=True)


def get(chat_id: int) -> dict | None:
    """None -> bu guruhda chatmode o'chirilgan (standart holat).
    Aks holda {"enabled": True, "owner_id": int} qaytaradi."""
    rec = _bucket().get(str(chat_id))
    if rec and rec.get("enabled"):
        return rec
    return None
