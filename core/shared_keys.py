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
    "gemini": "Gemini",
}

# ── Kalit MAQSADI ──────────────────────────────────────────────────────────────
# "chat"   — oddiy suhbat uchun (AVVAL kiritilgan barcha kalitlar shu; DB'da "shared_keys")
# "vision" — rasm/videoni "ko'rish" uchun alohida kalitlar (DB'da "vision_keys")
# Ikkala to'plam bir-biridan MUSTAQIL: biriga qo'shish/o'chirish ikkinchisiga tegmaydi.
PURPOSES = ("chat", "vision")
_BUCKET_NAME = {"chat": "shared_keys", "vision": "vision_keys"}

# Rasm o'qiy oladigan provayderlar (DeepSeek'ning vision API'si yo'q). Gemini faqat vision uchun.
VISION_PROVIDERS = ["groq", "gemini", "xkiro", "openai", "anthropic"]

# Har bir provayder uchun rasm o'qiy oladigan standart MODEL. Superadmin panelda o'zgartira oladi.
# MUHIM: chat uchun ishlatiladigan model (masalan Groq'ning llama-3.3-70b) rasmni QABUL QILMAYDI —
# shuning uchun vision kaliti har doim shu jadvaldagi VISION modeliga yo'naltiriladi.
# xKiro: qaysi modellar rasm qabul qilishini men bilmayman — superadmin o'zi tanlaydi.
VISION_DEFAULT_MODELS = {
    "groq": "meta-llama/llama-4-scout-17b-16e-instruct",
    "gemini": "gemini-2.5-flash",
    "openai": "gpt-4o-mini",
    "anthropic": "claude-haiku-4-5-20251001",
    "xkiro": "",
}
# Groq'da vision modellari tez-tez almashadi: asosiy model "o'chirilgan/topilmadi" desa, shular sinab ko'riladi.
GROQ_VISION_FALLBACKS = [
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "meta-llama/llama-4-maverick-17b-128e-instruct",
]

# xKiro ko'p modelni bitta API orqali beradi — superadmin qaysi modelni
# ishlatishni panel orqali tanlaydi (masalan "qwen/qwen3.8-max:free").
DEFAULT_XKIRO_MODEL = "qwen/qwen3.8-max:free"


def _bucket(purpose: str = "chat") -> dict:
    db = tgdb.get()
    return db.setdefault(_BUCKET_NAME[purpose], {})


def list_keys(provider: str, purpose: str = "chat") -> list[str]:
    """Parolini yechilgan (plaintext) kalitlar ro'yxati — faqat rotator ichida ishlatiladi."""
    return [decrypt(k) for k in _bucket(purpose).get(provider, [])]


def key_count(provider: str, purpose: str = "chat") -> int:
    return len(_bucket(purpose).get(provider, []))


async def add_key(bot, provider: str, key: str, purpose: str = "chat") -> tuple[bool, str]:
    bucket = _bucket(purpose)
    keys = bucket.setdefault(provider, [])
    if len(keys) >= MAX_KEYS_PER_PROVIDER:
        return False, f"Bu provayder uchun eng ko'pi {MAX_KEYS_PER_PROVIDER} ta kalit qo'shish mumkin."
    keys.append(encrypt(key))
    await tgdb.save(bot, force=True)
    return True, ""


async def remove_key(bot, provider: str, index: int, purpose: str = "chat"):
    keys = _bucket(purpose).get(provider, [])
    if 0 <= index < len(keys):
        keys.pop(index)
        await tgdb.save(bot, force=True)


# ── Vision modeli sozlamasi (provayder bo'yicha) ──

def get_vision_model(provider: str) -> str:
    saved = tgdb.get().get("settings", {}).get("vision_models", {}).get(provider)
    return saved or VISION_DEFAULT_MODELS.get(provider, "")


async def set_vision_model(bot, provider: str, model: str):
    settings = tgdb.get().setdefault("settings", {})
    settings.setdefault("vision_models", {})[provider] = model.strip()
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


async def validate_vision_key(provider: str, key: str) -> tuple[bool, str, str]:
    """Rasm kalitini haqiqiy (kichik rasm bilan) so'rov orqali tekshiradi.
    Qaytaradi: (ok, xato, ishlagan_model). Groq uchun ishlagan model nomi ham qaytadi."""
    import core.vision as vision  # kech import — vision shu modulga tayanadi
    return await vision.test_key(provider, key)


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
