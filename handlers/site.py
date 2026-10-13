"""
/site — saytning frontend'ini o'qish va ko'chirish (guruh va shaxsiy chatda). AI tool'lari bilan BIR XIL core/site_ops.run() orqali ishlaydi
(SSRF himoyasi, kvota, hajm chegaralari bir joyda).

  /site <havola>             — sahifa tuzilishi, texnologiyalar, matn namunasi (nusxalamasdan)
  /site <havola> html        — hammasi ichiga joylangan BITTA .html fayl (offline ochiladi)
  /site <havola> zip         — papka tuzilmasi: index.html + assets/ (+ source map'lar)
  /site cat <havola> [start] — bitta CSS/JS fayl matni
"""
from __future__ import annotations

import html
import logging
import shlex

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

import core.site_ops as ops

logger = logging.getLogger("handlers.site")
router = Router()

HELP = (
    "🌐 <b>Sayt frontend'ini o'qish va ko'chirish</b>\n\n"
    "/site <i>havola</i> — sahifa tuzilishi, texnologiyalar, matn (nusxalamasdan)\n"
    "/site <i>havola</i> html — hammasi ichiga joylangan BITTA .html (offline ochiladi)\n"
    "/site <i>havola</i> zip — papka tuzilmasi: index.html + assets/ (+ source map'lar)\n"
    "/site cat <i>fayl_havolasi</i> [start] — bitta CSS/JS fayl matni\n\n"
    "Oddiy suhbatda ham so'rashingiz mumkin: «shu saytning frontend'ini ko'chirib ber: https://…».\n\n"
    "ℹ️ Faqat server qaytargan HTML olinadi (JS bajarilmaydi): React/Vue/Next saytlarda bundle tushadi, asl manba emas (source map bo'lsa zip'da bor). "
    "Kunlik limit tarifga bog'liq.\n"
    f"⚖️ {ops.LEGAL}"
)


@router.message(Command("site"))
async def site_cmd(message: Message, command: CommandObject):
    try:
        argv = shlex.split(command.args or "")
    except ValueError:
        await message.answer("❌ Qo'shtirnoqlar noto'g'ri yopilgan.")
        return
    if not argv or argv[0] in ("help", "yordam"):
        await message.answer(HELP)
        return
    uid = message.from_user.id
    if argv[0].lower() == "cat":
        if len(argv) < 2:
            await message.answer("Format: /site cat <fayl_havolasi> [start]")
            return
        start = int(argv[2]) if len(argv) > 2 and argv[2].isdigit() else 0
        res = await ops.run("site_resource", uid, {"resource_url": argv[1], "start": start}, bot=message.bot, chat_id=message.chat.id)
    elif len(argv) > 1 and argv[1].lower() in ops.FORMATS:
        res = await ops.run("site_download", uid, {"url": argv[0], "format": argv[1]}, bot=message.bot, chat_id=message.chat.id)
        if res.get("error"):
            await message.answer("❌ " + html.escape(res["error"], quote=False))
        return                                   # muvaffaqiyatda fayl va holat xabari allaqachon yuborilgan
    else:
        res = await ops.run("site_read", uid, {"url": argv[0]}, bot=message.bot, chat_id=message.chat.id)
    if res.get("error"):
        await message.answer("❌ " + html.escape(res["error"], quote=False))
        return
    text = str(res.get("text") or "")
    await message.answer(f"<pre>{html.escape(text[:3500], quote=False)}</pre>")
