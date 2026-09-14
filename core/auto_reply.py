"""
Kalit-so'z auto-reply + "away" tizimi — StokerDownloader/find_keyword_response,
add_keyword, get_away_delay, mark_owner_activity, owner_replied_since patternidan.

Egasi (userbot orqali ulangan foydalanuvchi) shaxsiy kontaktlariga turlicha
avtomatik javob qoidalarini sozlaydi: "salom" desa -> "band bo'lsam ham tez
javob beraman" kabi. Away-delay: agar egasi ma'lum vaqt (masalan 5 daqiqa)
javob bermasa, avto-javob ishga tushadi — doim emas, faqat egasi band bo'lsa.
"""
import time
import core.tgdb as tgdb


def _owner_bucket(owner_id: int) -> dict:
    db = tgdb.get()
    return db.setdefault("auto_reply", {}).setdefault(str(owner_id), {
        "keywords": [],       # [{"id": int, "trigger": str, "response": str}]
        "away_delay": 300,    # soniya — standart 5 daqiqa
        "last_owner_activity": {},  # chat_id(str) -> timestamp (egasi shu chatga oxirgi qachon o'zi yozgan)
    })


def get_keywords(owner_id: int) -> list[dict]:
    return _owner_bucket(owner_id)["keywords"]


async def add_keyword(bot, owner_id: int, trigger: str, response: str):
    bucket = _owner_bucket(owner_id)
    new_id = (max([k["id"] for k in bucket["keywords"]], default=0)) + 1
    bucket["keywords"].append({"id": new_id, "trigger": trigger.lower(), "response": response})
    await tgdb.save(bot)


async def delete_keyword(bot, owner_id: int, kw_id: int):
    bucket = _owner_bucket(owner_id)
    bucket["keywords"] = [k for k in bucket["keywords"] if k["id"] != kw_id]
    await tgdb.save(bot)


def find_keyword_response(owner_id: int, text: str) -> str | None:
    """Kiruvchi xabar matnida trigger so'z bor-yo'qligini tekshiradi (oddiy 'contains')."""
    text_lower = text.lower()
    for kw in get_keywords(owner_id):
        if kw["trigger"] in text_lower:
            return kw["response"]
    return None


def get_away_delay(owner_id: int) -> int:
    return _owner_bucket(owner_id)["away_delay"]


async def set_away_delay(owner_id: int, bot, seconds: int):
    _owner_bucket(owner_id)["away_delay"] = seconds
    await tgdb.save(bot)


async def mark_owner_activity(bot, owner_id: int, chat_id: int):
    """Egasi shu kontakt bilan chatga O'ZI yozganda chaqiriladi (userbot event orqali)."""
    _owner_bucket(owner_id)["last_owner_activity"][str(chat_id)] = time.time()
    await tgdb.save(bot)


def owner_replied_since(owner_id: int, chat_id: int, since_ts: float) -> bool:
    last = _owner_bucket(owner_id)["last_owner_activity"].get(str(chat_id), 0)
    return last >= since_ts


def should_auto_reply(owner_id: int, chat_id: int) -> bool:
    """
    away_delay muddati o'tganmi (egasi shu kontaktga away_delay ichida
    o'zi javob bermaganmi) — shunda avto-javob yuborish mumkin.
    """
    last = _owner_bucket(owner_id)["last_owner_activity"].get(str(chat_id), 0)
    return (time.time() - last) >= get_away_delay(owner_id)
