"""
Ko'p-provayder, ko'p-kalitli AI rotator — tgs-expert-bot/groq_rotator.py
patternidan, lekin bitta provayder (Groq) bilan cheklanmasdan istalgan
provayderga (Groq, OpenAI, Anthropic, ...) umumlashtirilgan.

- Har bir provayder o'z kalitlar ro'yxati bilan Round-Robin ishlaydi.
- 429 (rate limit) yoki quota xatosida avtomatik keyingi kalitga o'tadi,
  xato bergan kalitni vaqtincha "cooldown"ga qo'yadi.
- Provayder darajasida ham fallback qilish mumkin (masalan Groq tugasa → OpenAI).

# TODO: har bir provayder uchun haqiqiy SDK chaqiruvini `_call_*` funksiyalarda
# to'ldiring (hozir Groq uchun to'liq, boshqalar uchun skelet).
"""
from __future__ import annotations
import asyncio
import itertools
import logging
import time
from typing import Any

import config

logger = logging.getLogger("ai_rotator")


class AllKeysExhaustedError(RuntimeError):
    pass


class KeyRotator:
    """Bitta provayder uchun round-robin key rotator (tgs-expert-bot'dagi bilan bir xil)."""

    def __init__(self, provider: str, api_keys: list[str], cooldown_seconds: int = 60):
        self.provider = provider
        self._keys = api_keys
        self._cycle = itertools.cycle(range(len(api_keys))) if api_keys else None
        self._cooldown_until: dict[str, float] = {}
        self._cooldown_seconds = cooldown_seconds
        self._lock = asyncio.Lock()

    @property
    def available(self) -> bool:
        return bool(self._keys)

    async def next_key(self) -> str:
        if not self._keys:
            raise AllKeysExhaustedError(f"{self.provider}: kalit yo'q")
        async with self._lock:
            now = time.time()
            for _ in range(len(self._keys)):
                idx = next(self._cycle)
                key = self._keys[idx]
                if self._cooldown_until.get(key, 0) <= now:
                    return key
            return min(self._keys, key=lambda k: self._cooldown_until.get(k, 0))

    def mark_rate_limited(self, key: str):
        self._cooldown_until[key] = time.time() + self._cooldown_seconds
        logger.warning("%s kalit rate-limit oldi, %ss sovutiladi", self.provider, self._cooldown_seconds)


class MultiProviderAI:
    """
    Bir nechta provayderni birlashtirib, tanlangan (yoki fallback) provayder
    orqali chat-completion + function-calling so'rov yuboradi.
    """

    def __init__(self):
        self.rotators: dict[str, KeyRotator] = {
            "groq": KeyRotator("groq", config.GROQ_API_KEYS),
            "openai": KeyRotator("openai", config.OPENAI_API_KEYS),
            "anthropic": KeyRotator("anthropic", config.ANTHROPIC_API_KEYS),
        }
        # Fallback tartibi: birinchi mavjud bo'lgani ishlatiladi
        self.priority = ["groq", "openai", "anthropic"]

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        preferred_provider: str | None = None,
    ) -> dict:
        """Qaytaradi: {"provider": str, "response": <SDK javobi>}"""
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
                return {"provider": provider, "response": response}
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
            # TODO: from openai import AsyncOpenAI ... (Groq'nikiga o'xshash chat.completions.create)
            raise NotImplementedError("openai provider hali ulanmagan")
        elif provider == "anthropic":
            # TODO: anthropic.AsyncAnthropic().messages.create(...) — ms-file-toolkit/example.py'ga qarang
            raise NotImplementedError("anthropic provider hali ulanmagan")
        raise ValueError(f"Noma'lum provayder: {provider}")


ai = MultiProviderAI()
