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
import re
import time

import config

logger = logging.getLogger("ai_rotator")

# Ba'zi provayderlar (masalan xKiro kabi tashqi/proxy xizmatlar) AI model
# tool-chaqiruv argumentini noto'g'ri turda yasasa (masalan massiv o'rniga
# string, ya'ni "slides": "[...]" emas "slides": [...] kutilgan joyda),
# XATOLIK (exception) tashlash o'rniga buni oddiy MATN javob (choice.content)
# sifatida qaytarib yuboradi — foydalanuvchiga tushunarsiz texnik matn
# ko'rinishida chiqib ketadi. Shu naqshni aniqlab, RATE-LIMIT bilan bir xil
# yo'l bilan — keyingi provayderga avtomatik o'tib — tuzatamiz.
_TOOL_FAILURE_PATTERNS = re.compile(
    r"could not execute tool|expected (array|object|string|number|boolean),?\s*got|not valid json",
    re.IGNORECASE,
)


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
    def __init__(self, name, arguments, call_id):
        self.function = _FakeFn(name, arguments)
        self.id = call_id


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


def _tools_kw(tools: list[dict] | None) -> dict:
    """tools bo'sh/None bo'lsa 'tools' parametrini UMUMAN yubormaymiz.
    Aks holda OpenAI/Groq SDK so'rovga `"tools": null` yozadi va ko'p OpenAI-mos xizmatlar
    (xKiro, Groq, DeepSeek...) buni 400 xato bilan rad etadi — tool'siz chaqiruvlar
    (suhbat xulosasi, story izohi) shu sabab yiqilardi."""
    return {"tools": tools} if tools else {}


def _to_anthropic_tools(tools: list[dict] | None) -> list[dict]:
    result = []
    for t in tools or []:
        fn = t["function"]
        result.append({"name": fn["name"], "description": fn.get("description", ""), "input_schema": fn["parameters"]})
    return result


def _openai_messages_to_anthropic(messages: list[dict]) -> list[dict]:
    """
    Bizning ichki xabar formatimiz OpenAI uslubida (assistant.tool_calls,
    role="tool" + tool_call_id) — bu Anthropic Messages API'da UMUMAN yo'q
    tushunchalar. Tool natijalarini AI'ga QAYTA yuborish (handlers/ai_chat.py'dagi
    agentic-loop) endi Anthropic uchun ham ishlashi kerak, shuning uchun bu
    yerda mos ravishda konvertatsiya qilinadi:

    - assistant + tool_calls  -> assistant xabari, content'da {"type":"tool_use", ...} bloklari
    - role="tool"             -> user xabari, content'da {"type":"tool_result", ...} bloki
      (ketma-ket kelgan bir nechta "tool" xabari BITTA user xabariga yig'iladi —
      Anthropic bir AI-navbatiga tegishli barcha tool_result'larni shunday kutadi)
    - oddiy matn xabarlar     -> o'zgarishsiz (Anthropic ularni ham qabul qiladi)
    """
    result = []
    i = 0
    while i < len(messages):
        m = messages[i]
        role = m.get("role")

        if role == "assistant" and m.get("tool_calls"):
            content = []
            if m.get("content"):
                content.append({"type": "text", "text": m["content"]})
            for tc in m["tool_calls"]:
                try:
                    tool_input = json.loads(tc["function"]["arguments"])
                except (ValueError, TypeError):
                    tool_input = {}
                content.append({
                    "type": "tool_use",
                    "id": tc["id"],
                    "name": tc["function"]["name"],
                    "input": tool_input,
                })
            result.append({"role": "assistant", "content": content})
            i += 1
            continue

        if role == "tool":
            content = []
            while i < len(messages) and messages[i].get("role") == "tool":
                tm = messages[i]
                content.append({
                    "type": "tool_result",
                    "tool_use_id": tm.get("tool_call_id"),
                    "content": tm.get("content") or "",
                })
                i += 1
            result.append({"role": "user", "content": content})
            continue

        result.append(m)
        i += 1

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

                # Yuqoridagi izohga qarang: tool-argument turi xato bo'lib,
                # provayder buni matn sifatida qaytarsa — keyingi provayderga
                # o'tamiz (aks holda foydalanuvchi xom texnik xabar ko'radi).
                msg = response.choices[0].message
                if tools and not msg.tool_calls and msg.content and _TOOL_FAILURE_PATTERNS.search(msg.content):
                    logger.warning(
                        "%s tool-argument xatosi qaytardi, keyingi provayderga o'tildi: %s",
                        provider, msg.content[:200],
                    )
                    last_err = RuntimeError(msg.content)
                    continue

                return {"provider": provider, "response": response, "personal": False}
            except Exception as e:  # rate-limit/quota/boshqa xato
                last_err = e
                if 'rotator' in locals() and 'key' in locals():
                    rotator.mark_rate_limited(key)
                continue

        raise AllKeysExhaustedError(f"Barcha provayderlar ishlamadi: {last_err}")

    async def _call(self, provider: str, key: str, messages: list[dict], tools: list[dict] | None):
        # Ba'zi kalitlar (shaxsiv, core/user_api_keys.py orqali ulangan)
        # ICHIDA o'zgartirilgan MODEL nomini ham olib yurishi mumkin
        # (masalan Anthropic uchun "claude-opus-5-5"). unpack_value() buni
        # ochadi; umumiy (ADMIN) kalitlar oddiy STRING bo'lgani uchun
        # xavfsiz — o'zgarishsiz qaytadi, model=None (standart ishlatiladi).
        # "custom" BUNDAN MUSTASNO — u butunlay boshqa (base_url+model+
        # api_key) formatda, pastda o'zining unpack_custom()'i bilan ochiladi.
        model_override = None
        if provider != "custom":
            import core.user_api_keys as user_api_keys
            key, model_override = user_api_keys.unpack_value(key)

        if provider == "groq":
            from groq import AsyncGroq
            client = AsyncGroq(api_key=key)
            return await client.chat.completions.create(
                model=model_override or "llama-3.3-70b-versatile",
                messages=messages,
                **_tools_kw(tools),
                max_tokens=1500,
            )

        elif provider == "openai":
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=key)
            return await client.chat.completions.create(
                model=model_override or "gpt-4o-mini",
                messages=messages,
                **_tools_kw(tools),
                max_tokens=1500,
            )

        elif provider == "deepseek":
            # DeepSeek API OpenAI SDK bilan mos — faqat base_url o'zgaradi
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=key, base_url="https://api.deepseek.com")
            return await client.chat.completions.create(
                model=model_override or "deepseek-chat",
                messages=messages,
                **_tools_kw(tools),
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
                **_tools_kw(tools),
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
                model=model_override or "claude-3-5-sonnet-20241022",
                max_tokens=1500,
                system="\n\n".join(system_texts) if system_texts else None,
                messages=_openai_messages_to_anthropic(non_system_messages),
                tools=_to_anthropic_tools(tools) or None,
            )
            text_parts, tool_calls = [], []
            for block in resp.content:
                if block.type == "text":
                    text_parts.append(block.text)
                elif block.type == "tool_use":
                    tool_calls.append(_FakeToolCall(block.name, json.dumps(block.input), block.id))
            message = _FakeMessage("\n".join(text_parts), tool_calls or None)
            return _FakeResponse([_FakeChoice(message)])

        elif provider == "custom":
            # Foydalanuvchi o'zi ulagan norasmiy/OpenAI-mos API (core/user_api_keys.py,
            # pack_custom() — base_url+model+api_key BITTA JSON qatorga yig'ilgan holda
            # keladi). Faqat SHAXSIY kalit sifatida ishlatiladi (umumiy rotatorda yo'q).
            import core.user_api_keys as user_api_keys
            info = user_api_keys.unpack_custom(key)
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=info["api_key"], base_url=info["base_url"])
            resp = await client.chat.completions.create(
                model=info["model"],
                messages=messages,
                **_tools_kw(tools),
                max_tokens=1500,
            )
            # Ba'zi "norasmiy" xizmatlar to'liq OpenAI sxemasiga rioya
            # qilmaydi (masalan Anthropic'ning ASL API'si — u OpenAI-mos
            # EMAS, boshqa endpoint/format ishlatadi). Shunday holatda tushunarsiz
            # "'str' object has no attribute 'choices'" o'rniga ANIQ xabar beramiz.
            if not hasattr(resp, "choices") or not resp.choices:
                raise RuntimeError(
                    "Bu API 'choices' maydonini qaytarmadi — ya'ni to'liq OpenAI-mos "
                    "emas (masalan, Anthropic'ning RASMIY api.anthropic.com manzili "
                    "OpenAI formatida ISHLAMAYDI — buning uchun 'Anthropic (Claude) ulash' "
                    f"tugmasidan foydalaning). Xom javob: {str(resp)[:300]}"
                )
            return resp

        raise ValueError(f"Noma'lum provayder: {provider}")


ai = MultiProviderAI()
