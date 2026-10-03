"""
pending_input holatidagi matn xabarlarni ushlab, tegishli oqimga yo'naltiradi
(API kalit kiritish, admin panel sozlamalari va h.k.).

MUHIM: bu router main.py'da handlers.ai_chat'dan OLDIN ro'yxatdan o'tishi
kerak — aks holda bu xabarlar oddiy AI-suhbat sifatida ketib qoladi.
"""
from aiogram import Router, F
from aiogram.types import Message

import core.pending_input as pending_input
import core.roles as roles
import core.user_api_keys as user_api_keys
import core.shared_keys as shared_keys
import core.ai_persona as ai_persona
from admin.panel import render_search_results

router = Router()


def _has_pending_state(message: Message) -> bool:
    # FAQAT shaxsiy chatda. Aks holda foydalanuvchi shaxsiy chatda (masalan API ID) kiritishni boshlab, so'ng
    # GURUHGA yozsa, guruhdagi oddiy xabari ham shu oqim javobi deb olinar edi ("API ID faqat raqam bo'lishi kerak").
    return (
        message.chat.type == "private"
        and message.text is not None
        and pending_input.get(message.from_user.id) is not None
    )


@router.message(_has_pending_state)
async def handle_pending(message: Message):
    user_id = message.from_user.id
    state = pending_input.get(user_id)
    action = state["action"]
    data = state["data"]
    text = message.text.strip()

    # ── Foydalanuvchi limitini o'zgartirish (admin/superadmin) ──
    if action == "set_user_limit":
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

    # ── Rasmiy provayder: model nomini o'zgartirish ixtiyoriy ("-" = standart) ──
    elif action == "apikey_wait_model_optional":
        model = text.strip()
        model = None if model in ("-", "") else model
        pending_input.set(user_id, "apikey_wait_value", {"provider": data["provider"], "model": model})
        label = user_api_keys.PROVIDER_LABELS[data["provider"]]
        await message.answer(f"🔑 Endi {label} API kalitingizni yuboring:")

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
            model_override = data.get("model")
            value_to_save = user_api_keys.pack_value(text, model_override)
            ok, error = await user_api_keys.validate_key(provider, value_to_save)
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

    # ── Superadmin: global qora ro'yxatga so'z qo'shish (panel orqali) ──
    elif action == "add_global_blacklist_word":
        import core.global_blacklist as global_blacklist
        ok = await global_blacklist.add(message.bot, text)
        pending_input.clear(user_id)
        await message.answer(f"✅ «{text.strip()}» qo'shildi." if ok else "⚠️ Bu so'z allaqachon ro'yxatda yoki limit to'ldi.")

    # ── Superadmin: RASM O'QISH (vision) kaliti qo'shish — chat kalitlaridan alohida to'plam ──
    elif action == "add_vision_key":
        provider = data["provider"]
        label = shared_keys.PROVIDER_LABELS[provider]
        status_msg = await message.answer(f"⏳ {label} kaliti rasm bilan tekshirilmoqda...")
        ok, error, used_model = await shared_keys.validate_vision_key(provider, text)
        if not ok:
            await status_msg.edit_text(
                f"❌ Kalit rasm o'qishda ishlamadi: {error}\n\nQaytadan {label} kalitini yuboring, "
                f"yoki /panel bilan bekor qiling."
            )
            return
        added, err2 = await shared_keys.add_key(message.bot, provider, text, purpose="vision")
        pending_input.clear(user_id)
        if not added:
            await status_msg.edit_text(f"⚠️ {err2}")
            return
        # Groq: haqiqatan ishlagan vision modelini saqlab qo'yamiz (standart nomi eskirgan bo'lsa ham)
        if provider == "groq" and used_model and used_model != shared_keys.get_vision_model("groq"):
            await shared_keys.set_vision_model(message.bot, "groq", used_model)
        count = shared_keys.key_count(provider, "vision")
        await status_msg.edit_text(
            f"✅ {label} rasm kaliti qo'shildi! ({count}/{shared_keys.MAX_KEYS_PER_PROVIDER})\n"
            f"Vision modeli: <code>{used_model or shared_keys.get_vision_model(provider)}</code>"
        )

    # ── Superadmin: vision modelini o'zgartirish (mavjud kalit bo'lsa, darrov sinab ko'riladi) ──
    elif action == "set_vision_model":
        provider = data["provider"]
        await shared_keys.set_vision_model(message.bot, provider, text)
        pending_input.clear(user_id)
        keys = shared_keys.list_keys(provider, "vision")
        if not keys:
            await message.answer(f"✅ Vision modeli o'zgartirildi: <code>{text}</code>\n(Sinash uchun avval kalit qo'shing.)")
            return
        import core.vision as vision
        status_msg = await message.answer("⏳ Yangi model mavjud kalit bilan sinalmoqda...")
        ok, error, _ = await vision.test_key(provider, keys[0])
        await status_msg.edit_text(
            f"✅ Model o'zgartirildi va ishlayapti: <code>{text}</code>" if ok
            else f"⚠️ Model saqlandi (<code>{text}</code>), lekin sinovda xato: {error}"
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
