"""
Foydalanuvchining O'ZI kiritgan AI API kaliti — mavjud accounts_store.py
(shifrlash) ustiga qurilgan, lekin provayderlarga xos qulay funksiyalar bilan.

Nega kerak: umumiy core/ai_rotator.py kalitlari sizga (botning egasiga) tegishli
va limitlangan/pullik. Foydalanuvchi o'z kalitini bersa — botni cheksiz va
o'z hisobidan ishlata oladi, sizning balansingizga tegmaydi.
"""
from aiogram import Bot
from core.accounts_store import save_user_secret, get_user_secret, remove_user_secret
import json

PROVIDERS = ["groq", "openai", "anthropic", "deepseek", "custom"]
PROVIDER_LABELS = {
    "groq": "Groq",
    "openai": "OpenAI",
    "anthropic": "Anthropic (Claude)",
    "deepseek": "DeepSeek",
    "custom": "Boshqa (norasmiy/OpenAI-mos)",
}


DEFAULT_MODELS = {
    "groq": "llama-3.3-70b-versatile",
    "openai": "gpt-4o-mini",
    "anthropic": "claude-3-5-haiku-20241022",
    "deepseek": "deepseek-chat",
}


def pack_value(api_key: str, model: str | None) -> str:
    """Rasmiy provayderlar (groq/openai/anthropic/deepseek) uchun: agar
    foydalanuvchi standart model o'rniga BOSHQA model kiritgan bo'lsa
    (masalan Anthropic uchun "claude-opus-5-5"), api_key+model'ni JSON'ga
    yig'amiz. Model berilmasa — ORQAGA MOSLIK uchun oddiy api_key STRING
    qaytariladi (eski saqlangan kalitlar bilan bir xil format)."""
    api_key = api_key.strip()
    if model:
        return json.dumps({"api_key": api_key, "model": model.strip()})
    return api_key


def unpack_value(value: str) -> tuple[str, str | None]:
    """pack_value() teskarisi: (api_key, model_yoki_None) qaytaradi.
    Oddiy (JSON bo'lmagan) qator kelsa — u to'g'ridan-to'g'ri api_key
    hisoblanadi va model=None (standart model ishlatiladi)."""
    stripped = value.strip()
    if stripped[:1] == "{":
        try:
            data = json.loads(stripped)
            return data["api_key"], data.get("model")
        except (ValueError, KeyError, TypeError):
            pass
    return value, None


def pack_custom(base_url: str, model: str, api_key: str) -> str:
    """"custom" provayder uchun base_url+model+api_key BITTA qatorga (JSON) yig'iladi —
    accounts_store bitta STRING'ni shifrlab saqlaydi, shuning uchun uchalasini
    birga jamlab yuboramiz."""
    return json.dumps({"base_url": base_url.strip(), "model": model.strip(), "api_key": api_key.strip()})


def unpack_custom(value: str) -> dict:
    """{"base_url", "model", "api_key"} qaytaradi."""
    return json.loads(value)


def _key_name(provider: str) -> str:
    return f"own_{provider}_key"


async def save_personal_key(bot: Bot, user_id: int, provider: str, api_key: str):
    await save_user_secret(bot, user_id, _key_name(provider), api_key)


def get_personal_key(user_id: int, provider: str) -> str | None:
    return get_user_secret(user_id, _key_name(provider))


async def remove_personal_key(bot: Bot, user_id: int, provider: str):
    await remove_user_secret(bot, user_id, _key_name(provider))


def get_any_personal_key(user_id: int) -> tuple[str, str] | None:
    """Foydalanuvchining istalgan provayderdagi kalitini qaytaradi (birinchi topilgani)."""
    for provider in PROVIDERS:
        key = get_personal_key(user_id, provider)
        if key:
            return provider, key
    return None


def list_connected_providers(user_id: int) -> list[str]:
    return [p for p in PROVIDERS if get_personal_key(user_id, p)]


async def validate_key(provider: str, api_key: str) -> tuple[bool, str]:
    """Kalitni saqlashdan OLDIN haqiqatan ishlashini tekshiradi (kichik test so'rov)."""
    try:
        if provider == "groq":
            real_key, model = unpack_value(api_key)
            from groq import AsyncGroq
            client = AsyncGroq(api_key=real_key)
            await client.chat.completions.create(
                model=model or DEFAULT_MODELS["groq"],
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=5,
            )
        elif provider == "openai":
            real_key, model = unpack_value(api_key)
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=real_key)
            await client.chat.completions.create(
                model=model or DEFAULT_MODELS["openai"],
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=5,
            )
        elif provider == "anthropic":
            real_key, model = unpack_value(api_key)
            from anthropic import AsyncAnthropic
            client = AsyncAnthropic(api_key=real_key)
            await client.messages.create(
                model=model or DEFAULT_MODELS["anthropic"],
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=5,
            )
        elif provider == "deepseek":
            real_key, model = unpack_value(api_key)
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=real_key, base_url="https://api.deepseek.com")
            await client.chat.completions.create(
                model=model or DEFAULT_MODELS["deepseek"],
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=5,
            )
        elif provider == "custom":
            # Bu yerda `api_key` parametri aslida pack_custom() bilan yig'ilgan
            # JSON qator (base_url+model+api_key birga) — chunki bu funksiya
            # bitta STRING qabul qiladi.
            info = unpack_custom(api_key)
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=info["api_key"], base_url=info["base_url"])
            resp = await client.chat.completions.create(
                model=info["model"],
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=5,
            )
            if not hasattr(resp, "choices") or not resp.choices:
                return False, (
                    "Bu API 'choices' maydonini qaytarmadi — to'liq OpenAI-mos emas "
                    "(masalan, Anthropic'ning RASMIY manzili OpenAI formatida ishlamaydi — "
                    "buning uchun 'Anthropic (Claude) ulash' tugmasidan foydalaning)."
                )
        else:
            return False, f"Noma'lum provayder: {provider}"
        return True, ""
    except Exception as e:
        return False, str(e)
