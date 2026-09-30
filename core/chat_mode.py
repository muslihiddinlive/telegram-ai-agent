"""
Guruhda "chat rejimi" — bot HAR BIR xabarga (tag/reply shart emas) javob beradi.

Ikki xil rejim:
  1) /chatmode on   — oddiy. Hisob-kitob tartibi (core/roles.py -> resolve_chatmode_payer):
        a) avvalo rejimni YOQQAN odamning (owner_id) kunlik limitidan ketadi;
        b) uniki tugasa — har bir xabar YOZGAN odamning O'Z limitidan ketadi;
        c) ikkalasi ham tugagan bo'lsa — bot javob bermaydi.
     Yoqish/o'chirish: guruh egasi/adminlari, botning adminlari, superadmin.
  2) /vipchatmode on — FAQAT superadmin. Shu guruhda CHEKSIZ: hech kimning
     limiti tekshirilmaydi va hisoblanmaydi. Faqat superadmin o'chira oladi.

Chatmode yoqilgan guruhda core/bot_loop_guard.py'ning bot-bot zanjir-uzish
himoyasi ATAYLAB o'chiriladi — guruh egasi ongli tanlagani uchun.
"""
import core.tgdb as tgdb


def _bucket() -> dict:
    db = tgdb.get()
    return db.setdefault("chat_mode", {})


async def enable(bot, chat_id: int, owner_id: int, vip: bool = False):
    _bucket()[str(chat_id)] = {"enabled": True, "owner_id": owner_id, "vip": vip}
    await tgdb.save(bot, force=True)


async def disable(bot, chat_id: int):
    _bucket().pop(str(chat_id), None)
    await tgdb.save(bot, force=True)


def get(chat_id: int) -> dict | None:
    """None -> bu guruhda chatmode o'chirilgan (standart holat).
    Aks holda {"enabled": True, "owner_id": int, "vip": bool} qaytaradi."""
    rec = _bucket().get(str(chat_id))
    if rec and rec.get("enabled"):
        return rec
    return None


def is_vip(chat_id: int) -> bool:
    rec = get(chat_id)
    return bool(rec and rec.get("vip"))
