"""
Asosiy AI-suhbat handler — agentic tool-use loop, ms-file-toolkit/example.py
patternidan (u yerda Claude API bilan qilingan edi, bu yerda umumiy
MultiProviderAI orqali amalga oshirilgan).

Qo'shimcha funksiyalar:
  - Shaxsiy chat Topics (Bot API 9.4, 2026-02-09): har bir topic — core/topic_sessions.py
    orqali MUSTAQIL suhbat tarixi/konteksti bilan ishlaydi (bitta umumiy xotira emas).
  - "O'ylab olay..." live-status: AI javob tayyorlagunча ekranda elapsed-time
    bilan yangilanib turadigan xabar ko'rsatiladi (core/thinking_indicator.py).
"""
import json
import os
import re
import logging
from aiogram import Router, F
from aiogram.types import Message, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton

from core.ai_rotator import ai
from core.ai_tools import TOOLS, dispatch, get_user_notes
from core.thinking_indicator import ThinkingIndicator
import core.topic_sessions as topic_sessions
import core.roles as roles
import core.group_permissions as group_permissions
import core.preview_tokens as preview_tokens
import core.file_cleanup as file_cleanup
import core.ai_persona as ai_persona
import core.bot_identity as bot_identity
import core.user_profile as user_profile
import core.bot_loop_guard as bot_loop_guard
import config
from core.markdown_format import markdown_to_telegram_html

GROUP_CHAT_TYPES = ("group", "supergroup")

router = Router()
logger = logging.getLogger("ai_chat")


def _strip_bot_mention(text: str, bot_username: str | None) -> str:
    """'@BotUsername savol' -> 'savol' (AI'ga tozaroq matn borishi uchun)."""
    if not bot_username:
        return text
    return re.sub(rf"@{re.escape(bot_username)}\b", "", text, flags=re.IGNORECASE).strip() or text


@router.message(F.text)
async def handle_message(message: Message):
    user_id = message.from_user.id
    is_group = message.chat.type in GROUP_CHAT_TYPES
    user_text = message.text

    if is_group:
        # GURUHDA faqat IKKI yo'l bilan murojaat qilinadi: (1) botni tag
        # qilish, (2) botning O'Z xabariga reply qilish. Boshqa har qanday
        # xabar — hatto Group Privacy o'chirilgan bo'lsa ham — E'TIBORSIZ
        # qoldiriladi (himoya sifatida, Telegram sozlamasiga tayanmasdan).
        bot_username = bot_identity.get_username()
        is_mentioned = bool(bot_username) and f"@{bot_username.lower()}" in (message.text or "").lower()
        is_reply_to_bot = (
            message.reply_to_message is not None
            and message.reply_to_message.from_user is not None
            and message.reply_to_message.from_user.id == bot_identity.get_id()
        )
        if not (is_mentioned or is_reply_to_bot):
            return

        # Bot-to-Bot Communication Mode yoqilgani uchun endi guruhda BOSHQA
        # botlardan ham xabar kelishi mumkin — ular bir-birini cheksiz
        # "tag"lab, RUNAWAY tsiklga tushib qolishi mumkin (Telegram BotFather
        # ham shu haqda ochiq ogohlantiradi). Ketma-ket N martadan ortiq
        # bot-javob bo'lsa, zanjir jimgina uziladi; haqiqiy INSON yozishi
        # bilan hisoblagich qayta nolga tushadi.
        is_from_bot = bool(message.from_user.is_bot)
        if not bot_loop_guard.register_incoming(message.chat.id, is_from_bot):
            if bot_loop_guard.should_warn_once(message.chat.id):
                try:
                    await message.bot.send_message(
                        config.SUPERADMIN_ID,
                        "⚠️ Bot-bot cheksiz tsikl xavfi aniqlandi va to'xtatildi.\n"
                        f"Guruh: {message.chat.title or message.chat.id} (ID: <code>{message.chat.id}</code>)\n"
                        f"Boshqa bot: @{message.from_user.username or message.from_user.full_name}",
                    )
                except Exception:
                    logger.exception("Superadminga bot-loop ogohlantirishini yuborib bo'lmadi")
            return

        # Botga chindan MUROJAAT qilgan (tag/reply) HAR BIR foydalanuvchining
        # ID+ism+username'i sukut bo'yicha, sezilmasdan yangilanadi — admin
        # keyinchalik AI orqali "Falonchi kim edi?" deb topa olishi uchun.
        await roles.touch_user_identity(message.bot, user_id, message.from_user.full_name, message.from_user.username)

        # Guruh admini /guruh_ruxsat bilan ro'yxat o'rnatgan bo'lsa, ro'yxatda
        # yo'q foydalanuvchilarga bot BUTUNLAY jim qoladi
        if not group_permissions.is_allowed_in_group(message.chat.id, message.from_user.username):
            return

        # GURUHDA global tasdiqlash (role="approved") SHART EMAS — faqat
        # kunlik limit tekshiriladi (avtomatik 20/kun bilan boshlanadi)
        if not roles.can_use_in_group(user_id):
            await message.reply("🚫 Bugungi so'rov limitingiz tugadi. Ertaga qayta urinib ko'ring.")
            return

        user_text = _strip_bot_mention(message.text, bot_username)

    else:
        # SHAXSIY chatda yozgan HAR BIR foydalanuvchining ID+ism+username'i
        # ham sukut bo'yicha yangilanadi (hatto hali tasdiqlanmagan bo'lsa ham)
        await roles.touch_user_identity(message.bot, user_id, message.from_user.full_name, message.from_user.username)

        # SHAXSIY chatda — global tasdiqlash SHART
        if not roles.can_use_bot(user_id):
            await message.answer("⏳ Sizning so'rovingiz hali tasdiqlanmagan. Admin tasdiqlashini kuting.")
            return
        if not roles.can_make_request(user_id):
            await message.answer("🚫 Bugungi so'rov limitingiz tugadi. Ertaga qayta urinib ko'ring.")
            return

    ctx = {"bot": message.bot, "chat_id": message.chat.id, "thread_id": message.message_thread_id}
    thread_id = message.message_thread_id  # shaxsiy chatdagi topic bo'lsa to'ldiriladi

    # Shu TOPIC'ga tegishli suhbat tarixini olamiz — boshqa topic'lar bilan aralashmaydi
    history = topic_sessions.get_history(user_id, thread_id)
    system_prompt = ai_persona.get_full_system_prompt()
    system_prompt += f"\n\n{user_profile.basic_info_line(message)}"
    # DOIMIY eslatmalar (remember_note orqali saqlangan) — topic tarixidan farqli
    # o'laroq, bular HAR DOIM (20-xabar chegarasidan tashqari ham) qo'shiladi.
    saved_notes = get_user_notes(user_id)
    if saved_notes:
        notes_block = "\n".join(f"- {n}" for n in saved_notes)
        system_prompt += f"\n\nBu foydalanuvchi haqida siz avval eslab qolgan narsalar:\n{notes_block}"

    messages = [{"role": "system", "content": system_prompt}] + history + [{"role": "user", "content": user_text}]

    indicator = await ThinkingIndicator(
        bot=message.bot, chat_id=message.chat.id, thread_id=thread_id,
        reply_to_message_id=message.message_id,
    ).start()

    final_text = "..."       # Telegram'ga YUBORILADIGAN (HTML'ga o'girilgan) matn
    raw_text_for_history = "..."  # suhbat tarixiga SAQLANADIGAN asl (markdown) matn —
                                    # HTML teglarini tarixga saqlasak, AI keyingi safar
                                    # o'sha teglarni o'zi ham qaytara boshlashi mumkin edi
    tool_outputs: list[tuple[str, dict]] = []

    try:
        result = await ai.chat(messages, tools=TOOLS, user_id=user_id)
        response = result["response"]
        choice = response.choices[0].message

        if choice.tool_calls:
            for tool_call in choice.tool_calls:
                args = json.loads(tool_call.function.arguments)
                tool_result = await dispatch(tool_call.function.name, user_id, args, ctx)
                tool_outputs.append((tool_call.function.name, tool_result))

            has_file = any(
                isinstance(r, dict) and (r.get("file_path") or r.get("output_path"))
                for _, r in tool_outputs
            )
            final_text = "Tayyor ✅" if has_file else "\n".join(
                f"[{n}]: {r}" for n, r in tool_outputs
            )
            raw_text_for_history = final_text
        else:
            raw_text_for_history = choice.content or "..."
            final_text = markdown_to_telegram_html(choice.content) if choice.content else "..."

    except Exception as e:
        final_text = f"⚠️ Xatolik yuz berdi: {e}"
        raw_text_for_history = final_text

    await indicator.finish(final_text)

    # Fayl/prezentatsiya/diagramma yaratish — 3x qimmatroq (guruhda ham,
    # shaxsiy chatda ham bir xil qoida)
    has_file_result = any(
        isinstance(r, dict) and (r.get("file_path") or r.get("output_path"))
        for _, r in tool_outputs
    )
    weight = roles.FILE_GENERATION_WEIGHT if has_file_result else 1
    await roles.register_request(message.bot, user_id, weight=weight)

    # Fayl yaratgan tool'lar bo'lsa — statusdan keyin haqiqiy faylларni yuboramiz
    for tool_name, tool_result in tool_outputs:
        if not isinstance(tool_result, dict):
            continue
        file_path = tool_result.get("file_path") or tool_result.get("output_path")
        if not file_path:
            continue

        if not os.path.isfile(file_path):
            logger.warning("Tool '%s' file_path qaytardi, lekin fayl diskda topilmadi: %s", tool_name, file_path)
            await message.reply(f"⚠️ Fayl yaratildi deb ko'rsatildi, lekin topilmadi: {os.path.basename(file_path)}")
            continue

        try:
            kb = None
            if file_path.lower().endswith(".pptx"):
                token = preview_tokens.store(file_path)
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🖼 Slaydlarni ko'rish", callback_data=f"preview:{token}")]
                ])
            # message_thread_id BERILMAYDI — aiogram buni message.is_topic_message
            # orqali o'zi avtomatik to'g'ri biriktiradi; qo'lda ham berilsa,
            # "got multiple values for keyword argument" xatosi chiqadi.
            # reply_document — foydalanuvchi/botning ASL xabariga REPLY qilib
            # yuboradi (kim so'ragani aniq bo'lishi uchun, guruhda bir nechta
            # AI-bot bir-biriga javob berayotganda ham aralashib ketmasin).
            await message.reply_document(
                FSInputFile(file_path),
                caption=f"📄 {os.path.basename(file_path)} ({tool_name})",
                reply_markup=kb,
                allow_sending_without_reply=True,
            )
        except Exception as e:
            # ENG MUHIMI: avval bu yerda xatolik jimgina yutilib ketardi (foydalanuvchi
            # "Tayyor" degan xabardan keyin hech narsa ko'rmasdi). Endi xato ko'rinadi.
            logger.exception("Faylni yuborishda xatolik: %s", file_path)
            await message.reply(f"⚠️ Faylni yuborishda xatolik: {e}")
            continue

        # Telegram faylni allaqachon qabul qildi — diskda saqlashning hojati yo'q.
        # .pptx uchun "🖼 Ko'rish" tugmasi bosilishi mumkinligi uchun 15 daqiqa
        # kutamiz, qolganlarini (docx/xlsx/pdf) DARHOL o'chiramiz.
        if kb is not None:
            file_cleanup.schedule_file_delete(file_path, delay_seconds=900)
        else:
            file_cleanup.delete_file_now(file_path)

    # Shu topic'ning tarixiga user xabari + AI javobini yozib qo'yamiz
    await topic_sessions.append_and_save(message.bot, user_id, thread_id, "user", user_text)
    await topic_sessions.append_and_save(message.bot, user_id, thread_id, "assistant", raw_text_for_history)


