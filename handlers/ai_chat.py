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
from aiogram import Router, F
from aiogram.types import Message, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton

from core.ai_rotator import ai
from core.ai_tools import TOOLS, dispatch
from core.thinking_indicator import ThinkingIndicator
import core.topic_sessions as topic_sessions
import core.roles as roles
import core.preview_tokens as preview_tokens

router = Router()


@router.message(F.text)
async def handle_message(message: Message):
    user_id = message.from_user.id

    if not roles.can_use_bot(user_id):
        await message.answer("⏳ Sizning so'rovingiz hali tasdiqlanmagan. Admin tasdiqlashini kuting.")
        return

    if not roles.can_make_request(user_id):
        await message.answer("🚫 Bugungi so'rov limitingiz tugadi. Ertaga qayta urinib ko'ring.")
        return

    ctx = {"bot": message.bot}
    thread_id = message.message_thread_id  # shaxsiy chatdagi topic bo'lsa to'ldiriladi

    # Shu TOPIC'ga tegishli suhbat tarixini olamiz — boshqa topic'lar bilan aralashmaydi
    history = topic_sessions.get_history(user_id, thread_id)
    messages = history + [{"role": "user", "content": message.text}]

    indicator = await ThinkingIndicator(
        bot=message.bot, chat_id=message.chat.id, thread_id=thread_id
    ).start()

    final_text = "..."
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
        else:
            final_text = choice.content or "..."

    except Exception as e:
        final_text = f"⚠️ Xatolik yuz berdi: {e}"

    await indicator.finish(final_text)
    await roles.register_request(message.bot, user_id)

    # Fayl yaratgan tool'lar bo'lsa — statusdan keyin haqiqiy faylларни yuboramiz
    for tool_name, tool_result in tool_outputs:
        if not isinstance(tool_result, dict):
            continue
        file_path = tool_result.get("file_path") or tool_result.get("output_path")
        if file_path and os.path.isfile(file_path):
            kb = None
            if file_path.lower().endswith(".pptx"):
                token = preview_tokens.store(file_path)
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🖼 Slaydlarni ko'rish", callback_data=f"preview:{token}")]
                ])
            await message.answer_document(
                FSInputFile(file_path),
                caption=f"📄 {os.path.basename(file_path)} ({tool_name})",
                message_thread_id=thread_id,
                reply_markup=kb,
            )

    # Shu topic'ning tarixiga user xabari + AI javobini yozib qo'yamiz
    await topic_sessions.append_and_save(message.bot, user_id, thread_id, "user", message.text)
    await topic_sessions.append_and_save(message.bot, user_id, thread_id, "assistant", final_text)


