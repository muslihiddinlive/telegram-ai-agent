"""
/antispam on|off — oddiy flood-nazorati: bitta foydalanuvchi QISQA VAQT ICHIDA juda ko'p
xabar yozsa (standart: 8 soniyada 6+ xabar) yoki bitta xabarni ketma-ket takrorlasa
(5+ marta), avtomatik MUTE_MINUTES daqiqaga mute qilinadi. Guruh/bot adminlari TEKSHIRILMAYDI.
"""
import time

import core.tgdb as tgdb

WINDOW_SECONDS = 8
MAX_IN_WINDOW = 6
MAX_REPEATS = 5
MUTE_MINUTES = 10
HISTORY_PER_USER = 10


def _bucket() -> dict:
    return tgdb.get().setdefault("antispam_mode", {})


def is_enabled(chat_id: int) -> bool:
    return bool(_bucket().get(str(chat_id)))


async def set_enabled(bot, chat_id: int, enabled: bool):
    _bucket()[str(chat_id)] = enabled
    await tgdb.save(bot, force=True)


_recent: dict[tuple[int, int], list[tuple[float, str]]] = {}  # (chat_id, user_id) -> [(vaqt, matn)]


def register_and_check(chat_id: int, user_id: int, text: str) -> bool:
    """Xabarni qaydga oladi; flood aniqlansa True qaytaradi (keyin hisoblagich tozalanadi)."""
    key = (chat_id, user_id)
    now = time.time()
    hist = _recent.setdefault(key, [])
    hist.append((now, text))
    if len(hist) > HISTORY_PER_USER:
        del hist[: len(hist) - HISTORY_PER_USER]

    in_window = [t for t, _ in hist if now - t <= WINDOW_SECONDS]
    repeats = 1
    for t, txt in reversed(hist[:-1]):
        if txt == text and now - t <= WINDOW_SECONDS * 3:
            repeats += 1
        else:
            break

    flooded = len(in_window) >= MAX_IN_WINDOW or repeats >= MAX_REPEATS
    if flooded:
        _recent[key] = []
    return flooded
