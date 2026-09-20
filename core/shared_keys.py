"""
UMUMIY (bot egasiga tegishli) AI API kalitlari — endi .env fayl ORQALI EMAS,
FAQAT superadmin panelidan (/panel -> 🔑 AI kalitlar) boshqariladi.

Har bir provayder uchun 1 dan 10 tagacha kalit qo'shish mumkin — ai_rotator.py
ularni Round-Robin bilan ishlatadi. Kalitlar DB'da (Telegram-kanal orqali)
shifrlangan holda saqlanadi, superadmin istalgan vaqt qo'shishi/o'chirishi
mumkin — bot qayta ishga tushirilishi shart emas (dinamik).
"""
import core.tgdb as tgdb
from core.crypto_store import encrypt, decrypt

MAX_KEYS_PER_PROVIDER = 10

PROVIDERS = ["xkiro", "groq", "openai", "anthropic", "deepseek"]
PROVIDER_LABELS = {
    "xkiro": "xKiro",
    "groq": "Groq",
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "deepseek": "DeepSeek",
}

# xKiro ko'p modelni bitta API orqali beradi — superadmin qaysi modelni
# ishlatishni panel orqali tanlaydi (masalan "qwen/qwen3.8-max:free").
DEFAULT_XKIRO_MODEL = "qwen/qwen3.8-max:free"


def _bucket() -> dict:
    db = tgdb.get()
    return db.setdefault("shared_keys", {})


def list_keys(provider: str) -> list[str]:
    """Parolini yechilgan (plaintext) kalitlar ro'yxati — faqat ai_rotator ichida ishlatiladi."""
    return [decrypt(k) for k in _bucket().get(provider, [])]


def key_count(provider: str) -> int:
    return len(_bucket().get(provider, []))


async def add_key(bot, provider: str, key: str) -> tuple[bool, str]:
    bucket = _bucket()
    keys = bucket.setdefault(provider, [])
    if len(keys) >= MAX_KEYS_PER_PROVIDER:
        return False, f"Bu provayder uchun eng ko'pi {MAX_KEYS_PER_PROVIDER} ta kalit qo'shish mumkin."
    keys.append(encrypt(key))
    await tgdb.save(bot, force=True)
    return True, ""


async def remove_key(bot, provider: str, index: int):
    keys = _bucket().get(provider, [])
    if 0 <= index < len(keys):
        keys.pop(index)
        await tgdb.save(bot, force=True)


def masked(key: str) -> str:
    if len(key) <= 10:
        return "•" * len(key)
    return key[:6] + "..." + key[-4:]


def get_xkiro_model() -> str:
    db = tgdb.get()
    return db.get("settings", {}).get("xkiro_model", DEFAULT_XKIRO_MODEL)


async def set_xkiro_model(bot, model: str):
    db = tgdb.get()
    db.setdefault("settings", {})["xkiro_model"] = model
    await tgdb.save(bot, force=True)


async def validate_key(provider: str, key: str) -> tuple[bool, str]:
    """Kalitni saqlashdan OLDIN haqiqiy so'rov bilan tekshiradi."""
    try:
        if provider == "xkiro":
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=key, base_url="https://api.xkiro.com/v1")
            await client.chat.completions.create(
                model=get_xkiro_model(),
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=5,
            )
        elif provider == "groq":
            from groq import AsyncGroq
            await AsyncGroq(api_key=key).chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": "hi"}], max_tokens=5,
            )
        elif provider == "openai":
            from openai import AsyncOpenAI
            await AsyncOpenAI(api_key=key).chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "hi"}], max_tokens=5,
            )
        elif provider == "anthropic":
            from anthropic import AsyncAnthropic
            await AsyncAnthropic(api_key=key).messages.create(
                model="claude-3-5-haiku-20241022",
                messages=[{"role": "user", "content": "hi"}], max_tokens=5,
            )
        elif provider == "deepseek":
            from openai import AsyncOpenAI
            await AsyncOpenAI(api_key=key, base_url="https://api.deepseek.com").chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": "hi"}], max_tokens=5,
            )
        else:
            return False, f"Noma'lum provayder: {provider}"
        return True, ""
    except Exception as e:
        return False, str(e)
