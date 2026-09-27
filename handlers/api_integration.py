"""
Foydalanuvchi o'zining AI API kalitini ulashi — "🔑 AI API integratsiya"
tugmasi / /apikalit komandasi orqali.

Oqim: provayder tanlaydi (Groq/OpenAI/Anthropic) -> kalitni matn sifatida
yuboradi -> kalit DARHOL test qilinadi (haqiqiy so'rov bilan) -> ishласа
shifrlab saqlanadi, ishlamasa xato ko'rsatiladi va qayta urinish so'raladi.

Ulangandan keyin core/ai_rotator.py avtomatik shu kalitni ustuvor
ishlatadi (umumiy/bot egasining kalitlariga tegmaydi).
"""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

import core.pending_input as pending_input
import core.roles as roles
import core.user_api_keys as user_api_keys

router = Router()


def _menu_kb(user_id: int) -> InlineKeyboardMarkup:
    connected = user_api_keys.list_connected_providers(user_id)
    rows = []
    for provider in user_api_keys.PROVIDERS:
        label = user_api_keys.PROVIDER_LABELS[provider]
        if provider in connected:
            rows.append([InlineKeyboardButton(text=f"✅ {label} — o'chirish", callback_data=f"apikey:remove:{provider}")])
        else:
            rows.append([InlineKeyboardButton(text=f"➕ {label} ulash", callback_data=f"apikey:add:{provider}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("apikalit"))
async def show_menu(message: Message):
    if not roles.can_use_bot(message.from_user.id):
        return
    await _send_menu(message)


@router.callback_query(F.data == "apikey:menu")
async def show_menu_cb(call: CallbackQuery):
    if not roles.can_use_bot(call.from_user.id):
        await call.answer("Ruxsat yo'q", show_alert=True)
        return
    await _send_menu(call.message, user_id=call.from_user.id)
    await call.answer()


async def _send_menu(message: Message, user_id: int | None = None):
    uid = user_id or message.from_user.id
    connected = user_api_keys.list_connected_providers(uid)
    status = ("Ulangan: " + ", ".join(user_api_keys.PROVIDER_LABELS[p] for p in connected)) if connected else "Hozircha hech qanday shaxsiy kalit ulanmagan."
    await message.answer(
        "🔑 <b>AI API integratsiya</b>\n\n"
        f"{status}\n\n"
        "O'z kalitingizni ulasangiz, bot cheksiz (umumiy limitga bog'liq bo'lmagan "
        "holda) sizning hisobingizdan ishlaydi.",
        reply_markup=_menu_kb(uid),
    )


@router.callback_query(F.data.startswith("apikey:add:"))
async def add_key_start(call: CallbackQuery):
    provider = call.data.split(":")[-1]
    if provider == "custom":
        # "Norasmiy"/OpenAI-mos xizmatlar uchun UCH bosqichda so'raladi:
        # base_url -> model -> api_key (handlers/pending_text.py'da davom etadi).
        pending_input.set(call.from_user.id, "apikey_wait_base_url", {"provider": provider})
        await call.message.answer(
            "🌐 Norasmiy/OpenAI-mos API xizmatining BASE URL manzilini yuboring\n"
            "(masalan: <code>https://api.masalan.com/v1</code>):"
        )
    else:
        # Rasmiy provayderlar uchun ham MODEL nomini o'zgartirish ixtiyoriy —
        # standart modelni xohlamasa, masalan Anthropic uchun "claude-opus-5-5"
        # kabi boshqa model kiritishi mumkin.
        pending_input.set(call.from_user.id, "apikey_wait_model_optional", {"provider": provider})
        label = user_api_keys.PROVIDER_LABELS[provider]
        default_model = user_api_keys.DEFAULT_MODELS.get(provider, "standart")
        await call.message.answer(
            f"🧩 {label} uchun MODEL nomini kiriting.\n"
            f"Standart: <code>{default_model}</code> — buni xohlasangiz shunchaki <code>-</code> yuboring."
        )
    await call.answer()


@router.callback_query(F.data.startswith("apikey:remove:"))
async def remove_key(call: CallbackQuery):
    provider = call.data.split(":")[-1]
    await user_api_keys.remove_personal_key(call.bot, call.from_user.id, provider)
    await call.answer("O'chirildi ✅")
    await call.message.edit_reply_markup(reply_markup=_menu_kb(call.from_user.id))
