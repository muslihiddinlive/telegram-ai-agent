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
            from groq import AsyncGroq
            client = AsyncGroq(api_key=api_key)
            await client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=5,
            )
        elif provider == "openai":
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=api_key)
            await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=5,
            )
        elif provider == "anthropic":
            from anthropic import AsyncAnthropic
            client = AsyncAnthropic(api_key=api_key)
            await client.messages.create(
                model="claude-3-5-haiku-20241022",
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=5,
            )
        elif provider == "deepseek":
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=api_key, base_url="https://api.deepseek.com")
            await client.chat.completions.create(
                model="deepseek-chat",
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
            await client.chat.completions.create(
                model=info["model"],
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=5,
            )
        else:
            return False, f"Noma'lum provayder: {provider}"
        return True, ""
    except Exception as e:
        return False, str(e)
