"""
Qo'shimcha guruh vositalari:
  /laqab <matn|-o'chir>        — HAR BIR foydalanuvchi o'zining taxallusini o'rnatadi/o'chiradi (hamma joyda)
  /qoida_qoshish <matn>        — AI uchun doimiy qoida qo'shadi (guruh admini/bot admini/superadmin)
  /qoidalar, /qoida_ochir <N>  — qoidalarni ko'rish/o'chirish
  /taqiq_qoshish, /taqiq_ochir, /taqiqlar — taqiqlangan so'zlar ro'yxati (admin)
  /statistika                  — guruh xabar statistikasi (hamma ko'ra oladi)
  /top_faollar                 — eng faol (BOT KUZATGAN) a'zolarni BITTA xabarda tag qiladi (faqat admin)
"""
import html

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

import core.ai_reaction as ai_reaction
import core.antispam as antispam
import core.auto_top as auto_top
import core.banned_words as banned_words
import core.congrats as congrats
import core.global_blacklist as global_blacklist
import core.group_memory as group_memory
import core.group_rules as group_rules
import core.nicknames as nicknames
import core.roles as roles

router = Router()


async def _is_group_admin(message: Message) -> bool:
    if message.chat.type not in ("group", "supergroup"):
        return False
    member = await message.bot.get_chat_member(message.chat.id, message.from_user.id)
    return member.status in ("creator", "administrator")


async def _can_manage(message: Message) -> bool:
    uid = message.from_user.id
    return roles.is_superadmin(uid) or roles.is_admin(uid) or await _is_group_admin(message)


def _arg(message: Message) -> str:
    parts = (message.text or "").split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


# ────────────────────────── /laqab ──────────────────────────

@router.message(Command("laqab"))
async def laqab_cmd(message: Message):
    arg = _arg(message)
    if not arg:
        cur = nicknames.get(message.from_user.id)
        await message.reply(
            (f"Joriy taxallusingiz: <b>{html.escape(cur)}</b>\n\n" if cur else "Hali taxallus o'rnatmagansiz.\n\n")
            + f"O'rnatish: <code>/laqab Yangi Ism</code>\nO'chirish: <code>/laqab -o'chir</code>"
        )
        return
    if arg.lower() in ("-o'chir", "-ochir", "-o'chirish", "off", "0"):
        await nicknames.set(message.bot, message.from_user.id, None)
        await message.reply("✅ Taxallus o'chirildi, endi odatdagi ismingiz ishlatiladi.")
        return
    if len(arg) > nicknames.MAX_LEN:
        await message.reply(f"⚠️ Taxallus {nicknames.MAX_LEN} belgidan oshmasin.")
        return
    await nicknames.set(message.bot, message.from_user.id, arg)
    await message.reply(f"✅ Taxallusingiz o'rnatildi: <b>{html.escape(arg)}</b>")


# ────────────────────────── guruh qoidalari ──────────────────────────

@router.message(Command("qoida_qoshish"), F.chat.type.in_({"group", "supergroup"}))
async def rule_add_cmd(message: Message):
    if not await _can_manage(message):
        await message.reply("⚠️ Bu komandani faqat guruh adminlari, bot adminlari yoki superadmin ishlata oladi.")
        return
    arg = _arg(message)
    if not arg:
        await message.reply("Qoida matnini yozing: <code>/qoida_qoshish har kuni 20:00da salomlashing</code>")
        return
    ok, err = await group_rules.add(message.bot, message.chat.id, arg)
    await message.reply(f"✅ Qoida qo'shildi:\n«{html.escape(arg)}»" if ok else f"⚠️ {err}")


@router.message(Command("qoidalar"), F.chat.type.in_({"group", "supergroup"}))
async def rules_list_cmd(message: Message):
    rules = group_rules.get(message.chat.id)
    if not rules:
        await message.reply("Hozircha qoida qo'shilmagan. Qo'shish: <code>/qoida_qoshish matn</code>")
        return
    listed = "\n".join(f"{i + 1}. {html.escape(r)}" for i, r in enumerate(rules))
    await message.reply(f"📋 Guruh qoidalari (AI uchun):\n{listed}\n\nO'chirish: <code>/qoida_ochir N</code>")


@router.message(Command("qoida_ochir"), F.chat.type.in_({"group", "supergroup"}))
async def rule_remove_cmd(message: Message):
    if not await _can_manage(message):
        await message.reply("⚠️ Bu komandani faqat guruh adminlari, bot adminlari yoki superadmin ishlata oladi.")
        return
    arg = _arg(message)
    if not arg.isdigit():
        await message.reply("Raqam ko'rsating: <code>/qoida_ochir 2</code> (ro'yxat uchun: /qoidalar)")
        return
    ok = await group_rules.remove(message.bot, message.chat.id, int(arg) - 1)
    await message.reply("✅ O'chirildi." if ok else "⚠️ Shu raqamli qoida topilmadi.")


# ────────────────────────── taqiqlangan so'zlar ──────────────────────────

@router.message(Command("taqiq_qoshish"), F.chat.type.in_({"group", "supergroup"}))
async def banned_add_cmd(message: Message):
    if not await _can_manage(message):
        await message.reply("⚠️ Bu komandani faqat guruh adminlari, bot adminlari yoki superadmin ishlata oladi.")
        return
    arg = _arg(message)
    if not arg:
        await message.reply("So'zni yozing: <code>/taqiq_qoshish so'kinish</code>")
        return
    ok = await banned_words.add(message.bot, message.chat.id, arg)
    await message.reply(f"✅ «{html.escape(arg)}» taqiqlangan so'zlarga qo'shildi." if ok else "⚠️ Bu so'z allaqachon ro'yxatda yoki limit to'ldi.")


@router.message(Command("taqiq_ochir"), F.chat.type.in_({"group", "supergroup"}))
async def banned_remove_cmd(message: Message):
    if not await _can_manage(message):
        await message.reply("⚠️ Bu komandani faqat guruh adminlari, bot adminlari yoki superadmin ishlata oladi.")
        return
    arg = _arg(message)
    ok = await banned_words.remove(message.bot, message.chat.id, arg)
    await message.reply("✅ O'chirildi." if ok else "⚠️ Bu so'z ro'yxatda yo'q.")


@router.message(Command("taqiqlar"), F.chat.type.in_({"group", "supergroup"}))
async def banned_list_cmd(message: Message):
    if not await _can_manage(message):
        await message.reply("⚠️ Bu komandani faqat guruh adminlari, bot adminlari yoki superadmin ishlata oladi.")
        return
    words = banned_words.get(message.chat.id)
    listed = ", ".join(f"«{html.escape(w)}»" for w in words) if words else "(bo'sh)"
    await message.reply(f"🚫 Taqiqlangan so'zlar: {listed}\n\nQo'shish: /taqiq_qoshish, o'chirish: /taqiq_ochir")


# ────────────────────────── statistika ──────────────────────────

@router.message(Command("statistika"), F.chat.type.in_({"group", "supergroup"}))
async def stats_cmd(message: Message):
    if not await _can_manage(message):
        await message.reply("⚠️ Statistikani faqat guruh adminlari, bot adminlari yoki superadmin ko'ra oladi.")
        return
    top = group_memory.top_active(message.chat.id, limit=5)
    total = group_memory.total_messages(message.chat.id)
    if not top:
        await message.reply("Hali statistika yo'q — bot faqat o'zi kuzatgan (tag/reply qilingan yoki /chatmode) xabarlarni hisoblaydi.")
        return
    lines = "\n".join(f"{i + 1}. {n} — {c} ta xabar" for i, (_, n, _, c) in enumerate(top))
    await message.reply(
        f"📊 Guruh statistikasi (bot kuzatgan)\nJami: {total} ta xabar\n\n<b>Eng faol 5 a'zo:</b>\n{lines}"
    )


async def send_top_faollar(bot, chat_id: int, header: str | None = None) -> bool:
    """Bot kuzatgan eng faol a'zolarni BITTA (yoki kerak bo'lsa bir nechta) xabarda tag qiladi.
    FAQAT bot allaqachon ko'rgan/kuzatgan a'zolar — Bot API orqali guruhning HAMMA a'zosini olib bo'lmaydi.
    /top_faollar komandasi va kunlik avto-yuborish (core/scheduler.py) shu funksiyani ishlatadi."""
    top = group_memory.top_active(chat_id, limit=15)
    if not top:
        return False
    mentions = [f'<a href="tg://user?id={uid}">{html.escape(n)}</a>' for uid, n, _, _ in top]
    CHUNK = 20  # bitta xabarga sig'gancha, qolgani keyingisida
    chunks = [mentions[i:i + CHUNK] for i in range(0, len(mentions), CHUNK)]
    await bot.send_message(chat_id, header or f"🏆 Eng faol a'zolar ({len(mentions)} kishi, bot kuzatgani):")
    for chunk in chunks:
        await bot.send_message(chat_id, " ".join(chunk))
    return True


@router.message(Command("top_faollar"), F.chat.type.in_({"group", "supergroup"}))
async def top_active_cmd(message: Message):
    if not await _can_manage(message):
        await message.reply("⚠️ Bu komandani faqat guruh adminlari, bot adminlari yoki superadmin ishlata oladi.")
        return
    if not await send_top_faollar(message.bot, message.chat.id):
        await message.reply("Hali faol a'zo kuzatilmagan.")


@router.message(Command("top_faollar_avto"), F.chat.type.in_({"group", "supergroup"}))
async def top_active_auto_cmd(message: Message):
    """Har kuni soat 20:00 (Toshkent) da /top_faollar natijasi avtomatik yuborilsinmi."""
    if not await _can_manage(message):
        await message.reply("⚠️ Bu komandani faqat guruh adminlari, bot adminlari yoki superadmin ishlata oladi.")
        return
    arg = _arg(message).lower()
    if arg not in ("on", "off"):
        cur = "YOQILGAN ✅" if auto_top.is_enabled(message.chat.id) else "O'CHIRILGAN ⛔"
        await message.reply(
            f"Joriy holat: {cur}\n\nYoqish: <code>/top_faollar_avto on</code>\nO'chirish: <code>/top_faollar_avto off</code>"
        )
        return
    await auto_top.set_enabled(message.bot, message.chat.id, arg == "on")
    await message.reply("✅ Har kuni soat 20:00da (Toshkent) avtomatik yuboriladi." if arg == "on" else "✅ Avtomatik yuborish o'chirildi.")


# ────────────────────────── /aireakmode ──────────────────────────

@router.message(F.text.regexp(r"(?i)^/aireakmode\b"), F.chat.type.in_({"group", "supergroup"}))
async def aireakmode_cmd(message: Message):
    """AI avtomatik reaksiya rejimi: yoqilsa, bot mos xabarlarga (javob yozmasdan) emoji bosadi."""
    if not await _can_manage(message):
        await message.reply("⚠️ Bu komandani faqat guruh adminlari, bot adminlari yoki superadmin ishlata oladi.")
        return
    arg = _arg(message).lower().lstrip(":").strip()
    if arg not in ("on", "off"):
        cur = "YOQILGAN ✅" if ai_reaction.is_enabled(message.chat.id) else "O'CHIRILGAN ⛔"
        await message.reply(
            f"AI reaksiya rejimi: {cur}\n\nYoqish: <code>/aireakmode: on</code>\nO'chirish: <code>/aireakmode: off</code>"
        )
        return
    await ai_reaction.set_enabled(message.bot, message.chat.id, arg == "on")
    await message.reply(
        "✅ AI reaksiya rejimi YOQILDI — bot mos xabarlarga (javob yozmasdan) emoji bilan reaksiya beradi."
        if arg == "on" else "✅ AI reaksiya rejimi O'CHIRILDI."
    )


# ────────────────────────── /antispam ──────────────────────────

@router.message(Command("antispam"), F.chat.type.in_({"group", "supergroup"}))
async def antispam_cmd(message: Message):
    if not await _can_manage(message):
        await message.reply("⚠️ Bu komandani faqat guruh adminlari, bot adminlari yoki superadmin ishlata oladi.")
        return
    arg = _arg(message).lower()
    if arg not in ("on", "off"):
        cur = "YOQILGAN ✅" if antispam.is_enabled(message.chat.id) else "O'CHIRILGAN ⛔"
        await message.reply(
            f"Anti-spam: {cur}\n\n"
            f"Qoida: {antispam.WINDOW_SECONDS} soniyada {antispam.MAX_IN_WINDOW}+ xabar yoki bir xil xabarni "
            f"{antispam.MAX_REPEATS}+ marta takrorlash — {antispam.MUTE_MINUTES} daqiqaga avtomatik mute.\n\n"
            "Yoqish: <code>/antispam on</code>\nO'chirish: <code>/antispam off</code>"
        )
        return
    await antispam.set_enabled(message.bot, message.chat.id, arg == "on")
    await message.reply("✅ Anti-spam YOQILDI." if arg == "on" else "✅ Anti-spam O'CHIRILDI.")


# ────────────────────────── kalendar tabriklari ──────────────────────────

@router.message(Command("tabrik_qoshish"), F.chat.type.in_({"group", "supergroup"}))
async def congrats_add_cmd(message: Message):
    if not await _can_manage(message):
        await message.reply("⚠️ Bu komandani faqat guruh adminlari, bot adminlari yoki superadmin ishlata oladi.")
        return
    arg = _arg(message)
    if not arg:
        await message.reply("Format: <code>/tabrik_qoshish 08-03 Xotin-qizlar bayrami bilan!</code>")
        return
    ok, err = await congrats.add(message.bot, message.chat.id, arg)
    await message.reply("✅ Qo'shildi. Har yili soat 09:00da (Toshkent) avtomatik yuboriladi." if ok else f"⚠️ {err}")


@router.message(Command("tabriklar"), F.chat.type.in_({"group", "supergroup"}))
async def congrats_list_cmd(message: Message):
    items = congrats.get(message.chat.id)
    if not items:
        await message.reply("Hozircha tabrik qo'shilmagan. Qo'shish: <code>/tabrik_qoshish DD-MM matn</code>")
        return
    listed = "\n".join(f"{i + 1}. {it['day']:02d}-{it['month']:02d}: {html.escape(it['text'])}" for i, it in enumerate(items))
    await message.reply(f"🎉 Kalendar tabriklari:\n{listed}\n\nO'chirish: <code>/tabrik_ochir N</code>")


@router.message(Command("tabrik_ochir"), F.chat.type.in_({"group", "supergroup"}))
async def congrats_remove_cmd(message: Message):
    if not await _can_manage(message):
        await message.reply("⚠️ Bu komandani faqat guruh adminlari, bot adminlari yoki superadmin ishlata oladi.")
        return
    arg = _arg(message)
    if not arg.isdigit():
        await message.reply("Raqam ko'rsating: <code>/tabrik_ochir 1</code>")
        return
    ok = await congrats.remove(message.bot, message.chat.id, int(arg) - 1)
    await message.reply("✅ O'chirildi." if ok else "⚠️ Shu raqamli tabrik topilmadi.")


# ────────────────────────── GLOBAL qora ro'yxat (faqat superadmin, hamma guruhda) ──────────────────────────

@router.message(Command("qora_qoshish"))
async def global_blacklist_add_cmd(message: Message):
    if not roles.is_superadmin(message.from_user.id):
        return
    arg = _arg(message)
    if not arg:
        await message.reply("So'zni yozing: <code>/qora_qoshish so'z</code>")
        return
    ok = await global_blacklist.add(message.bot, arg)
    await message.reply(f"✅ «{html.escape(arg)}» GLOBAL qora ro'yxatga (hamma guruhda) qo'shildi." if ok else "⚠️ Bu so'z allaqachon ro'yxatda yoki limit to'ldi.")


@router.message(Command("qora_ochir"))
async def global_blacklist_remove_cmd(message: Message):
    if not roles.is_superadmin(message.from_user.id):
        return
    ok = await global_blacklist.remove(message.bot, _arg(message))
    await message.reply("✅ O'chirildi." if ok else "⚠️ Bu so'z ro'yxatda yo'q.")


@router.message(Command("qoralar"))
async def global_blacklist_list_cmd(message: Message):
    if not roles.is_superadmin(message.from_user.id):
        return
    words = global_blacklist.get()
    listed = ", ".join(f"«{html.escape(w)}»" for w in words) if words else "(bo'sh)"
    await message.reply(
        f"🌐 GLOBAL qora ro'yxat (hamma guruhda): {listed}\n\n"
        f"Eskalatsiya: {global_blacklist.MUTE_AT}-marta — {global_blacklist.MUTE_MINUTES} daqiqa mute, "
        f"{global_blacklist.BAN_AT}-marta — ban.\n"
        "Qo'shish: /qora_qoshish, o'chirish: /qora_ochir"
    )
