"""
pending_input holatidagi matn xabarlarni ushlab, tegishli oqimga yo'naltiradi
(userbot login bosqichlari, kalit-so'z qo'shish, away sozlash).

MUHIM: bu router main.py'da handlers.ai_chat'dan OLDIN ro'yxatdan o'tishi
kerak — aks holda bu xabarlar oddiy AI-suhbat sifatida ketib qoladi.
"""
from aiogram import Router, F
from aiogram.types import Message

import core.pending_input as pending_input
import core.userbot_login as userbot_login
import core.auto_reply as auto_reply
import core.roles as roles
import core.user_api_keys as user_api_keys
import core.shared_keys as shared_keys
import core.ai_persona as ai_persona
from core.userbot_runtime import start_userbot_for_owner
from admin.panel import render_search_results

router = Router()


async def _activate_userbot(message: Message, user_id: int, data: dict):
    """Login tugagach userbot'ni darhol ishga tushiradi (restart kutmasdan)."""
    try:
        await start_userbot_for_owner(message.bot, user_id, data["api_id"], data["api_hash"])
        await message.answer(
            "✅ Userbot muvaffaqiyatli ulandi va ishga tushdi! "
            "Endi /kalitsoz_qoshish bilan avto-javob qoidalarini sozlashingiz mumkin."
        )
    except Exception as e:
        await message.answer(f"✅ Session saqlandi, lekin ishga tushirishda xatolik: {e}")


def _has_pending_state(message: Message) -> bool:
    return message.text is not None and pending_input.get(message.from_user.id) is not None


@router.message(_has_pending_state)
async def handle_pending(message: Message):
    user_id = message.from_user.id
    state = pending_input.get(user_id)
    action = state["action"]
    data = state["data"]
    text = message.text.strip()

    # ── Userbot login oqimi ──
    if action == "userbot_wait_api_id":
        if not text.isdigit():
            await message.answer("API ID faqat raqamlardan iborat bo'lishi kerak. Qayta yozing:")
            return
        data["api_id"] = int(text)
        pending_input.set(user_id, "userbot_wait_api_hash", data)
        await message.answer("Endi <b>API HASH</b>ni yuboring:")

    elif action == "userbot_wait_api_hash":
        data["api_hash"] = text
        pending_input.set(user_id, "userbot_wait_phone", data)
        await message.answer("Telefon raqamingizni xalqaro formatda yuboring (masalan: +998901234567):")

    elif action == "userbot_wait_phone":
        try:
            await userbot_login.start_login(user_id, data["api_id"], data["api_hash"], text)
            await message.answer("📩 Telegram'ga tasdiqlash kodi yuborildi. Kodni shu yerga yozing:")
        except Exception as e:
            pending_input.clear(user_id)
            await message.answer(f"⚠️ Xatolik: {e}\nQaytadan /userbot bilan urinib ko'ring.")

    elif action == "userbot_wait_code":
        result = await userbot_login.submit_code(user_id, text)
        if result == "need_password":
            await message.answer("🔒 Ikki bosqichli parolingizni yuboring:")
        elif result == "success":
            await userbot_login.finalize_login(message.bot, user_id)
            await _activate_userbot(message, user_id, data)
        elif result == "invalid_code":
            await message.answer("❌ Kod noto'g'ri. Qaytadan yozing:")
        else:
            await message.answer("⚠️ Sessiya topilmadi, /userbot bilan qaytadan boshlang.")

    elif action == "userbot_wait_password":
        result = await userbot_login.submit_password(user_id, text)
        if result == "success":
            await userbot_login.finalize_login(message.bot, user_id)
            await _activate_userbot(message, user_id, data)
        else:
            await message.answer("❌ Parol noto'g'ri. Qaytadan yozing:")

    # ── Kalit-so'z qo'shish oqimi ──
    elif action == "keyword_wait_trigger":
        data["trigger"] = text
        pending_input.set(user_id, "keyword_wait_response", data)
        await message.answer(f"\"{text}\" so'ziga qanday javob berilsin?")

    elif action == "keyword_wait_response":
        await auto_reply.add_keyword(message.bot, user_id, data["trigger"], text)
        pending_input.clear(user_id)
        await message.answer(f"✅ Qo'shildi: \"{data['trigger']}\" → \"{text}\"")

    # ── Away-delay sozlash ──
    elif action == "away_wait_seconds":
        if not text.isdigit():
            await message.answer("Faqat raqam kiriting (soniyada):")
            return
        await auto_reply.set_away_delay(user_id, message.bot, int(text))
        pending_input.clear(user_id)
        await message.answer(f"✅ Away vaqti {text} soniyaga o'rnatildi.")

    # ── Foydalanuvchi limitini o'zgartirish (admin/superadmin) ──
    elif action == "set_user_limit":
        if not text.isdigit():
            await message.answer("Faqat raqam kiriting:")
            return
        target_uid = int(data["target_uid"])
        await roles.set_user_limit(message.bot, target_uid, int(text))
        pending_input.clear(user_id)
        await message.answer(f"✅ Foydalanuvchi {target_uid} uchun kunlik limit {text} ga o'rnatildi.")

    # ── Yangi admin qo'shish (faqat superadmin) ──
    elif action == "add_admin_wait_id":
        if not text.isdigit():
            await message.answer("Faqat foydalanuvchi ID (raqam) kiriting:")
            return
        new_admin_id = int(text)
        await roles.add_admin(message.bot, new_admin_id)
        pending_input.clear(user_id)
        await message.answer(f"✅ {new_admin_id} endi admin.")
        try:
            import core.bot_commands as bot_commands
            await bot_commands.register_admin_commands(message.bot, new_admin_id)
            await message.bot.send_message(new_admin_id, "🛡 Sizga admin huquqi berildi.")
        except Exception:
            pass

    # ── Foydalanuvchi qidirish (ID yoki ism) ──
    elif action == "search_users_query":
        pending_input.clear(user_id)
        matches = roles.search_users(text)
        kb = render_search_results(matches)
        if not kb:
            await message.answer(f"\"{text}\" bo'yicha hech narsa topilmadi.")
        else:
            await message.answer(f"🔍 \"{text}\" bo'yicha natijalar:", reply_markup=kb)

    # ── Norasmiy/OpenAI-mos API: 1-bosqich (base_url) ──
    elif action == "apikey_wait_base_url":
        base_url = text.strip()
        pending_input.set(user_id, "apikey_wait_model", {"provider": "custom", "base_url": base_url})
        await message.answer("🧩 Endi MODEL nomini yuboring (masalan: <code>gpt-4o-mini</code>):")

    # ── Norasmiy/OpenAI-mos API: 2-bosqich (model) ──
    elif action == "apikey_wait_model":
        model = text.strip()
        pending_input.set(user_id, "apikey_wait_value", {
            "provider": "custom", "base_url": data["base_url"], "model": model,
        })
        await message.answer("🔑 Endi API kalitingizni yuboring:")

    # ── Shaxsiy AI API kalitini ulash (validatsiya bilan) ──
    elif action == "apikey_wait_value":
        provider = data["provider"]
        label = user_api_keys.PROVIDER_LABELS[provider]
        status_msg = await message.answer(f"⏳ {label} kaliti tekshirilmoqda...")
        if provider == "custom":
            # base_url+model+api_key BITTA JSON qatorga yig'iladi (accounts_store
            # faqat bitta STRING'ni shifrlab saqlay oladi).
            combined = user_api_keys.pack_custom(data["base_url"], data["model"], text)
            ok, error = await user_api_keys.validate_key("custom", combined)
            value_to_save = combined
        else:
            ok, error = await user_api_keys.validate_key(provider, text)
            value_to_save = text
        if ok:
            await user_api_keys.save_personal_key(message.bot, user_id, provider, value_to_save)
            pending_input.clear(user_id)
            await status_msg.edit_text(f"✅ {label} kaliti muvaffaqiyatli ulandi va tasdiqlandi!")
        else:
            await status_msg.edit_text(
                f"❌ Kalit ishlamadi: {error}\n\nQaytadan {label} kalitingizni yuboring, "
                f"yoki /apikalit bilan bekor qiling."
            )

    # ── Superadmin: umumiy (bot egasiga tegishli) AI kalit qo'shish ──
    elif action == "add_shared_key":
        provider = data["provider"]
        label = shared_keys.PROVIDER_LABELS[provider]
        status_msg = await message.answer(f"⏳ {label} kaliti tekshirilmoqda...")
        ok, error = await shared_keys.validate_key(provider, text)
        if ok:
            added, err2 = await shared_keys.add_key(message.bot, provider, text)
            pending_input.clear(user_id)
            if added:
                count = shared_keys.key_count(provider)
                await status_msg.edit_text(f"✅ {label} kaliti qo'shildi! ({count}/{shared_keys.MAX_KEYS_PER_PROVIDER})")
            else:
                await status_msg.edit_text(f"⚠️ {err2}")
        else:
            await status_msg.edit_text(
                f"❌ Kalit ishlamadi: {error}\n\nQaytadan {label} kalitini yuboring, "
                f"yoki /panel bilan bekor qiling."
            )

    # ── Superadmin: xKiro faol modelini o'zgartirish ──
    elif action == "set_xkiro_model":
        await shared_keys.set_xkiro_model(message.bot, text)
        pending_input.clear(user_id)
        await message.answer(f"✅ Model o'zgartirildi: <code>{text}</code>")

    # ── Superadmin: AI shaxsiyati (system prompt) ──
    elif action == "set_system_prompt":
        await ai_persona.set_system_prompt(message.bot, text)
        pending_input.clear(user_id)
        await message.answer("✅ AI shaxsiyati yangilandi! Endi shu bo'yicha javob beradi.")

    else:
        pending_input.clear(user_id)
