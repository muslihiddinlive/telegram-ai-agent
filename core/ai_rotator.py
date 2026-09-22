"""
Ko'p-provayder, ko'p-kalitli AI rotator — tgs-expert-bot/groq_rotator.py
patternidan, lekin bitta provayder (Groq) bilan cheklanmasdan istalgan
provayderga (Groq, OpenAI, Anthropic, ...) umumlashtirilgan.

- Har bir provayder o'z kalitlar ro'yxati bilan Round-Robin ishlaydi.
- 429 (rate limit) yoki quota xatosida avtomatik keyingi kalitga o'tadi,
  xato bergan kalitni vaqtincha "cooldown"ga qo'yadi.
- Provayder darajasida ham fallback qilish mumkin (masalan Groq tugasa → OpenAI).
- Agar foydalanuvchi O'ZINING API kalitini ulagan bo'lsa (core/user_api_keys.py),
  UMUMIY (botning) kalitlari o'rniga FAQAT o'sha shaxsiy kalit ishlatiladi —
  sizning (bot egasining) limitingizga tegmaydi.
"""
from __future__ import annotations
import asyncio
import itertools
import json
import logging
import time

import config

logger = logging.getLogger("ai_rotator")


class AllKeysExhaustedError(RuntimeError):
    pass


class KeyRotator:
    """
    Bitta provayder uchun round-robin key rotator — tgs-expert-bot/groq_rotator.py
    patternidan, LEKIN kalitlar endi ishga tushishda emas, HAR SAFAR DB'dan
    (core/shared_keys.py) JONLI o'qiladi — shuning uchun superadmin panel
    orqali kalit qo'shsa/o'chirsa, bot qayta ishga tushmasdan darhol ta'sir qiladi.

    .env'dagi *_API_KEYS ham fallback sifatida qo'shiladi (ixtiyoriy, legacy).
    """

    def __init__(self, provider: str, env_fallback_keys: list[str] | None = None, cooldown_seconds: int = 60):
        self.provider = provider
        self._env_fallback = env_fallback_keys or []
        self._cursor = 0
        self._cooldown_until: dict[str, float] = {}
        self._cooldown_seconds = cooldown_seconds
        self._lock = asyncio.Lock()

    def _current_keys(self) -> list[str]:
        import core.shared_keys as shared_keys
        try:
            db_keys = shared_keys.list_keys(self.provider)
        except RuntimeError:
            db_keys = []  # DB hali yuklanmagan (masalan validatsiya paytida)
        return db_keys + [k for k in self._env_fallback if k not in db_keys]

    @property
    def available(self) -> bool:
        return bool(self._current_keys())

    async def next_key(self) -> str:
        keys = self._current_keys()
        if not keys:
            raise AllKeysExhaustedError(f"{self.provider}: kalit yo'q")
        async with self._lock:
            now = time.time()
            for _ in range(len(keys)):
                idx = self._cursor % len(keys)
                self._cursor += 1
                key = keys[idx]
                if self._cooldown_until.get(key, 0) <= now:
                    return key
            return min(keys, key=lambda k: self._cooldown_until.get(k, 0))

    def mark_rate_limited(self, key: str):
        self._cooldown_until[key] = time.time() + self._cooldown_seconds
        logger.warning("%s kalit rate-limit oldi, %ss sovutiladi", self.provider, self._cooldown_seconds)


# ── Anthropic javobini Groq/OpenAI (choices[0].message) formatiga moslashtirish ──

class _FakeFn:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class _FakeToolCall:
    def __init__(self, name, arguments):
        self.function = _FakeFn(name, arguments)


class _FakeMessage:
    def __init__(self, content, tool_calls):
        self.content = content
        self.tool_calls = tool_calls


class _FakeChoice:
    def __init__(self, message):
        self.message = message


class _FakeResponse:
    def __init__(self, choices):
        self.choices = choices


def _to_anthropic_tools(tools: list[dict] | None) -> list[dict]:
    result = []
    for t in tools or []:
        fn = t["function"]
        result.append({"name": fn["name"], "description": fn.get("description", ""), "input_schema": fn["parameters"]})
    return result


class MultiProviderAI:
    """
    Bir nechta provayderni birlashtirib, tanlangan (yoki fallback) provayder
    orqali chat-completion + function-calling so'rov yuboradi.
    """

    def __init__(self):
        self.rotators: dict[str, KeyRotator] = {
            "xkiro": KeyRotator("xkiro"),  # faqat superadmin panelidan — .env fallback yo'q
            "groq": KeyRotator("groq", config.GROQ_API_KEYS),
            "openai": KeyRotator("openai", config.OPENAI_API_KEYS),
            "anthropic": KeyRotator("anthropic", config.ANTHROPIC_API_KEYS),
            "deepseek": KeyRotator("deepseek", config.DEEPSEEK_API_KEYS),
        }
        # xKiro birinchi ustuvorlikda — bu joriy deploy uchun asosiy model manbai
        self.priority = ["xkiro", "groq", "openai", "anthropic", "deepseek"]

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        preferred_provider: str | None = None,
        user_id: int | None = None,
    ) -> dict:
        """Qaytaradi: {"provider": str, "response": <SDK javobi>, "personal": bool}"""

        # 1) Foydalanuvchining shaxsiy kaliti bo'lsa — FAQAT shuni ishlatamiz
        if user_id is not None:
            import core.user_api_keys as user_api_keys
            found = user_api_keys.get_any_personal_key(user_id)
            if found:
                personal_provider, personal_key = found
                try:
                    response = await self._call(personal_provider, personal_key, messages, tools)
                    return {"provider": personal_provider, "response": response, "personal": True}
                except Exception as e:
                    raise AllKeysExhaustedError(
                        f"Sizning {personal_provider} kalitingiz ishlamadi: {e}"
                    )

        # 2) Aks holda — umumiy (bot egasining) kalitlari, rotator + fallback bilan
        order = [preferred_provider] if preferred_provider else []
        order += [p for p in self.priority if p != preferred_provider]

        last_err: Exception | None = None
        for provider in order:
            rotator = self.rotators.get(provider)
            if not rotator or not rotator.available:
                continue
            try:
                key = await rotator.next_key()
                response = await self._call(provider, key, messages, tools)
                return {"provider": provider, "response": response, "personal": False}
            except Exception as e:  # rate-limit/quota/boshqa xato
                last_err = e
                if 'rotator' in locals() and 'key' in locals():
                    rotator.mark_rate_limited(key)
                continue

        raise AllKeysExhaustedError(f"Barcha provayderlar ishlamadi: {last_err}")

    async def _call(self, provider: str, key: str, messages: list[dict], tools: list[dict] | None):
        if provider == "groq":
            from groq import AsyncGroq
            client = AsyncGroq(api_key=key)
            return await client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                tools=tools,
                max_tokens=1500,
            )

        elif provider == "openai":
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=key)
            return await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                tools=tools,
                max_tokens=1500,
            )

        elif provider == "deepseek":
            # DeepSeek API OpenAI SDK bilan mos — faqat base_url o'zgaradi
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=key, base_url="https://api.deepseek.com")
            return await client.chat.completions.create(
                model="deepseek-chat",
                messages=messages,
                tools=tools,
                max_tokens=1500,
            )

        elif provider == "xkiro":
            # xKiro ham OpenAI-mos (xkiro-test-v7.html'dan tasdiqlandi:
            # /chat/completions, standart choices[0].message formati)
            import core.shared_keys as shared_keys
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=key, base_url="https://api.xkiro.com/v1")
            return await client.chat.completions.create(
                model=shared_keys.get_xkiro_model(),
                messages=messages,
                tools=tools,
                max_tokens=1500,
            )

        elif provider == "anthropic":
            # Anthropic'ning o'ziga xosligi: "system" messages ro'yxati ICHIDA
            # emas, alohida `system=` parametr sifatida berilishi kerak —
            # aks holda API xato qaytaradi. Shuning uchun ajratib olamiz.
            system_texts = [m["content"] for m in messages if m.get("role") == "system"]
            non_system_messages = [m for m in messages if m.get("role") != "system"]

            from anthropic import AsyncAnthropic
            client = AsyncAnthropic(api_key=key)
            resp = await client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=1500,
                system="\n\n".join(system_texts) if system_texts else None,
                messages=non_system_messages,
                tools=_to_anthropic_tools(tools) or None,
            )
            text_parts, tool_calls = [], []
            for block in resp.content:
                if block.type == "text":
                    text_parts.append(block.text)
                elif block.type == "tool_use":
                    tool_calls.append(_FakeToolCall(block.name, json.dumps(block.input)))
            message = _FakeMessage("\n".join(text_parts), tool_calls or None)
            return _FakeResponse([_FakeChoice(message)])

        raise ValueError(f"Noma'lum provayder: {provider}")


ai = MultiProviderAI()
