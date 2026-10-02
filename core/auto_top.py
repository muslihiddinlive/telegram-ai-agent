"""
/top_faollar_avto on|off — yoqilgan guruhlarda bot HAR KUNI soat 20:00 (Toshkent) da
o'zi /top_faollar natijasini (bot kuzatgan eng faol a'zolarni, BITTA/bir nechta xabarda
tag qilib) avtomatik yuboradi. Ishga tushirish: core/scheduler.py.
"""
import core.tgdb as tgdb


def _bucket() -> dict:
    return tgdb.get().setdefault("auto_top_mode", {})


def is_enabled(chat_id: int) -> bool:
    return bool(_bucket().get(str(chat_id)))


async def set_enabled(bot, chat_id: int, enabled: bool):
    _bucket()[str(chat_id)] = enabled
    await tgdb.save(bot, force=True)


def enabled_chats() -> list[int]:
    return [int(cid) for cid, v in _bucket().items() if v]
