"""
Guruh uchun erkin matnli "algoritm" qoidalari — admin/superadmin yozib qo'ygan ko'rsatmalar
("manabundan so'kinishsa tozala", "har kuni eng faol userlarni belgilab bor" kabi) AI'ning
shu guruhdagi system prompt'iga doimiy qo'shiladi, shunda AI ularga har safar amal qiladi.

Faqat shu guruhning admin/egasi, bot adminlari yoki superadmin qo'sha/o'chira oladi.
"""
import core.tgdb as tgdb

MAX_RULES = 20
MAX_RULE_LEN = 300


def _bucket(chat_id: int) -> list:
    return tgdb.get().setdefault("group_rules", {}).setdefault(str(chat_id), [])


def get(chat_id: int) -> list[str]:
    return _bucket(chat_id)


async def add(bot, chat_id: int, rule: str) -> tuple[bool, str]:
    rule = " ".join(rule.split())[:MAX_RULE_LEN]
    if not rule:
        return False, "Bo'sh qoida bo'lmaydi."
    rules = _bucket(chat_id)
    if len(rules) >= MAX_RULES:
        return False, f"Eng ko'pi {MAX_RULES} ta qoida qo'shish mumkin — avval birini o'chiring."
    rules.append(rule)
    await tgdb.save(bot, force=True)
    return True, ""


async def remove(bot, chat_id: int, index: int) -> bool:
    rules = _bucket(chat_id)
    if 0 <= index < len(rules):
        rules.pop(index)
        await tgdb.save(bot, force=True)
        return True
    return False


def as_prompt_block(chat_id: int) -> str:
    rules = get(chat_id)
    if not rules:
        return ""
    lines = "\n".join(f"{i + 1}. {r}" for i, r in enumerate(rules))
    return (
        "\n\nGURUH ADMINI O'RNATGAN DOIMIY QOIDALAR (har doim amal qiling, zid ko'rsatma bo'lmasa):\n"
        f"{lines}"
    )
