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
from aiogram import Router, F
from aiogram.types import Message

from core.ai_rotator import ai
from core.ai_tools import TOOLS, dispatch
from core.thinking_indicator import ThinkingIndicator
import core.topic_sessions as topic_sessions

router = Router()


@router.message(F.text)
async def handle_message(message: Message):
    ctx = {"bot": message.bot}
    user_id = message.from_user.id
    thread_id = message.message_thread_id  # shaxsiy chatdagi topic bo'lsa to'ldiriladi

    # Shu TOPIC'ga tegishli suhbat tarixini olamiz — boshqa topic'lar bilan aralashmaydi
    history = topic_sessions.get_history(user_id, thread_id)
    messages = history + [{"role": "user", "content": message.text}]

    indicator = await ThinkingIndicator(
        bot=message.bot, chat_id=message.chat.id, thread_id=thread_id
    ).start()

    try:
        result = await ai.chat(messages, tools=TOOLS)
        response = result["response"]
        choice = response.choices[0].message

        if choice.tool_calls:
            outputs = []
            for tool_call in choice.tool_calls:
                args = json.loads(tool_call.function.arguments)
                tool_result = await dispatch(
                    tool_call.function.name, user_id, args, ctx
                )
                outputs.append(f"[{tool_call.function.name}]: {tool_result}")
            final_text = "\n".join(outputs)
        else:
            final_text = choice.content or "..."

    except Exception as e:
        final_text = f"⚠️ Xatolik yuz berdi: {e}"

    await indicator.finish(final_text)

    # Shu topic'ning tarixiga user xabari + AI javobini yozib qo'yamiz
    await topic_sessions.append_and_save(message.bot, user_id, thread_id, "user", message.text)
    await topic_sessions.append_and_save(message.bot, user_id, thread_id, "assistant", final_text)


