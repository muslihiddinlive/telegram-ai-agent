"""
Function-calling tool registry — tgs-expert-bot/ai_tools.py formatidan
(Groq/OpenAI uslubidagi "tools" ro'yxati), ms-file-toolkit/registry.py'dagi
markazlashgan registry g'oyasi bilan birlashtirilgan.

Yangi tool qo'shish uchun: TOOLS ro'yxatiga yozuv qo'shing va DISPATCH
lug'atiga funksiyani bog'lang. dispatch() AI tanlagan tool'ni chaqiradi.
"""
from __future__ import annotations
import json
from typing import Any, Callable, Awaitable

from tools.file_tools import FILE_TOOLS, file_dispatch, is_file_tool
import tools.presentation_builder as ppt_builder
import core.user_profile as user_profile

# ── Tool chaqirilayotganda ThinkingIndicator'da ko'rsatiladigan VAZIYAT
# matni — "Miyamni ishga solyapman..." kabi umumiy iboralar o'rniga,
# HAQIQATDA nima qilinayotganini yozadi (Claude'ning o'zi "Internetdan
# qidirilmoqda..." deb ko'rsatishi bilan bir xil g'oya).
_TOOL_STATUS_LABELS = {
    "search_web": "Internetdan qidirilmoqda",
    "create_presentation": "PPTX taqdimot yaratilmoqda",
    "create_diagram": "Diagramma chizilmoqda",
    "get_user_profile": "Profil ma'lumotlari olinmoqda",
    "lookup_user": "Foydalanuvchi qidirilmoqda",
    "remember_note": "Eslatma saqlanmoqda",
    "fetch_url_text": "Sahifa matni o'qilmoqda",
    "scrape_page_text": "Sahifa o'qilmoqda",
    "extract_page_links": "Sahifadan havolalar olinmoqda",
    "extract_page_images": "Sahifadan rasmlar olinmoqda",
}

_TOOL_STATUS_FORMAT_LABELS = [
    ("pptx", "PPTX"), ("docx", "Word hujjat"), ("xlsx", "Excel jadval"),
    ("pdf", "PDF"), ("csv", "CSV fayl"), ("odt", "ODT hujjat"),
    ("ods", "ODS jadval"), ("odp", "ODP taqdimot"), ("image", "rasm"),
    ("archive", "arxiv"), ("code", "kod fayli"),
]

_TOOL_STATUS_VERB_PREFIXES = [
    ("create_", "yaratilmoqda"), ("generate_", "yaratilmoqda"),
    ("append_", "qo'shilmoqda"), ("add_", "qo'shilmoqda"), ("insert_", "qo'shilmoqda"),
    ("replace_", "tahrirlanmoqda"), ("set_", "sozlanmoqda"), ("format_", "formatlanmoqda"),
    ("freeze_", "sozlanmoqda"), ("merge_", "birlashtirilmoqda"), ("split_", "bo'linmoqda"),
    ("convert_", "aylantirilmoqda"), ("delete_", "o'chirilmoqda"),
    ("crop_", "tahrirlanmoqda"), ("resize_", "tahrirlanmoqda"), ("rotate_", "tahrirlanmoqda"),
    ("download_", "yuklab olinmoqda"), ("fetch_", "o'qilmoqda"), ("scrape_", "o'qilmoqda"),
    ("list_", "ro'yxati olinmoqda"), ("read_", "o'qilmoqda"), ("get_", "olinmoqda"),
    ("extract_", "chiqarib olinmoqda"), ("search_", "qidirilmoqda"),
]


def describe_tool_call(name: str, args: dict) -> str:
    """ThinkingIndicator'ga chiqariladigan qisqa, ANIQ vaziyat matnini
    qaytaradi — masalan "ParadoksHub" haqida PPTX taqdimot yaratilmoqda...".
    Noma'lum/kutilmagan tool nomi uchun ham umumiy, tushunarli matn beradi
    (hech qachon xato tashlamaydi)."""
    if name in _TOOL_STATUS_LABELS:
        base = _TOOL_STATUS_LABELS[name]
    else:
        verb = "bajarilmoqda"
        for prefix, v in _TOOL_STATUS_VERB_PREFIXES:
            if name.startswith(prefix):
                verb = v
                break
        label = next((lbl for key, lbl in _TOOL_STATUS_FORMAT_LABELS if key in name), None)
        base = f"{label} {verb}" if label else verb

    subject = None
    for key in ("title", "topic", "query", "filename", "file_path", "url", "name"):
        val = args.get(key) if isinstance(args, dict) else None
        if isinstance(val, str) and val.strip():
            subject = val.strip()
            break

    if subject and len(subject) < 60:
        return f"\"{subject}\" haqida {base}..."
    return f"{base}..."


# tools/diagrams.py rang-temasi MODUL DARAJASIDA global (set_theme() orqali
# almashtiriladi) — shuning uchun bir vaqtning o'zida ikki xil temadagi
# prezentatsiya qurilishining oldini olish uchun bu lock bilan ketma-ket
# (serial) qilib qo'yilgan. Personal/kichik jamoa boti uchun bu yetarli;
# juda yuqori concurrency kerak bo'lsa, diagrams.py'ni har chaqiruvda
# explicit theme-parametr qabul qiladigan qilib qayta yozish kerak bo'ladi.
import asyncio
_presentation_build_lock = asyncio.Lock()

_PRESENTATION_SLIDE_TYPES_DOC = (
    "Har bir slide obyekti 'type' maydoniga ega bo'lishi shart. Turlari va kerakli maydonlar:\n"
    "- content: {title, bullets: [str,...]}\n"
    "- chart: {title, chart_type: 'bar'|'line'|'pie'|'donut', categories: [str,...], series_name, values: [number,...]}\n"
    "- flowchart: {title, steps: [str,...]} (ketma-ket qadamlar, o'qlar bilan bog'lanadi)\n"
    "- orgchart: {title, root: str, children: [str,...]}\n"
    "- venn: {title, set_a, set_b, overlap} (2 doiraviy diagramma)\n"
    "- timeline: {title, events: [{date, label}, ...] yoki [str,...]}\n"
    "- section: {title, subtitle} (bo'lim ajratuvchi slayd)\n"
    "- stat: {title, stats: [{number, label}, ...]}\n"
    "- quote: {quote, author}\n"
    "- comparison: {title, left_title, left_items: [str,...], right_title, right_items: [str,...]}"
)

TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "remember_note",
            "description": (
                "Foydalanuvchi haqida DOIMIY eslab qolinishi kerak bo'lgan narsani "
                "saqlaydi — masalan ismi/laqabi ('meni Falonchi aka deb chaqir'), "
                "tili/uslubi bo'yicha afzalligi, takrorlanadigan konteksti. Bu "
                "eslatma KEYINGI BARCHA suhbatlarga (hatto boshqa topic/kunlarda "
                "ham) avtomatik qo'shiladi — vaqtinchalik suhbat tarixidan farqli "
                "o'laroq (u faqat ~20 xabardan keyin unutiladi), bu DOIMIY saqlanadi. "
                "Foydalanuvchi 'eslab qol', 'meni ... deb chaqir', 'har doim ... qil' "
                "kabi so'zlar bilan iltimos qilganda shu tool'ni chaqiring."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "note": {"type": "string", "description": "Eslab qolinadigan matn, foydalanuvchining o'z so'zlari bilan"},
                },
                "required": ["note"],
            },
        },
    },
    *FILE_TOOLS,  # ms-file-toolkit: docx/xlsx/pptx/pdf — 36 ta tool
    {
        "type": "function",
        "function": {
            "name": "create_presentation",
            "description": (
                "To'liq, ko'p-slaydli PowerPoint prezentatsiya yaratadi — grafiklar, "
                "flowchart, org-chart, Venn, timeline va h.k. bilan (groq-pptx-bot "
                "patternidan, ms-file-toolkit'ning oddiy create_pptx'idan ancha boyroq). "
                "Foydalanuvchi \"prezentatsiya tayyorla\", \"slaydlar yasab ber\" desa shuni ishlating.\n\n"
                "STANDART SIFAT — MUHIM: agar foydalanuvchi prezentatsiya qanday bo'lishi "
                "kerakligini (uslub, uzunlik, oddiy/qisqa) ANIQ tasvirlamagan bo'lsa, "
                "STANDART HOLATDA \"PRO\"/PREMIUM darajada tuzing: kamida 6-10 ta mazmunli "
                "slayd, har birida yetarlicha ma'lumot va detal (2-3 so'zli bullet emas, "
                "to'liq gaplar), imkon qadar turli slayd turlaridan (chart/stat/comparison/"
                "quote/timeline) foydalaning — faqat 'content' turidagi oddiy bullet-slaydlar "
                "bilan cheklanmang, buni qiziqarli va taassurot qoldiradigan qilib tuzing. "
                "Foydalanuvchi aniq \"qisqa\", \"oddiy\" yoki \"2-3 slayd\" desagina, shunga mos "
                "kichikroq/soddaroq variant tuzing.\n\n"
                + _PRESENTATION_SLIDE_TYPES_DOC
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Prezentatsiya sarlavhasi"},
                    "subtitle": {"type": "string", "description": "Sarlavha slaydidagi kichik matn (ixtiyoriy)"},
                    "slides": {
                        "type": "array",
                        "description": "Slaydlar ro'yxati — har biri yuqoridagi turlardan biri",
                        "items": {"type": "object"},
                    },
                    "dark_theme": {
                        "type": "boolean",
                        "description": (
                            "Prezentatsiya rangi. STANDART: true (to'q/premium ko'rinish) — "
                            "foydalanuvchi aniq \"och/light/oq fon\" demasa, TRUE qo'yiladi."
                        ),
                    },
                },
                "required": ["title", "slides"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_diagram",
            "description": (
                "Bitta alohida diagramma (grafik/flowchart/orgchart/venn/timeline) "
                "yaratadi — to'liq prezentatsiya emas, faqat bitta slayd kerak bo'lganda."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "diagram_type": {
                        "type": "string",
                        "enum": ["chart", "flowchart", "orgchart", "venn", "timeline"],
                    },
                    "title": {"type": "string"},
                    "chart_type": {"type": "string", "enum": ["bar", "line", "pie", "donut"]},
                    "categories": {"type": "array", "items": {"type": "string"}},
                    "series_name": {"type": "string"},
                    "values": {"type": "array", "items": {"type": "number"}},
                    "steps": {"type": "array", "items": {"type": "string"}},
                    "root": {"type": "string"},
                    "children": {"type": "array", "items": {"type": "string"}},
                    "set_a": {"type": "string"},
                    "set_b": {"type": "string"},
                    "overlap": {"type": "string"},
                    "events": {"type": "array", "items": {"type": "object"}},
                    "dark_theme": {
                        "type": "boolean",
                        "description": "STANDART: true (to'q/premium ko'rinish), agar user 'light/och' demasa.",
                    },
                },
                "required": ["diagram_type", "title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_profile",
            "description": (
                "Foydalanuvchining profil RASMINI oladi (to'g'ridan-to'g'ri chatga "
                "yuboradi). Username/ID/ism/BIO kabi ma'lumotlar ALLAQACHON sizga "
                "har xabarda berilgan — buni FAQAT profil rasmi kerak bo'lganda "
                "(yoki boshqa birovning bio'sini qayta tekshirish uchun) chaqiring. "
                "Boshqa birovning (o'zi emas) profilini so'rash FAQAT admin/"
                "superadmin uchun ruxsat etilgan."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target_user_id": {
                        "type": "integer",
                        "description": "Kimning profilini olish kerak — berilmasa, so'ragan odamning o'zi.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_user",
            "description": (
                "Botga yozgan foydalanuvchilar orasidan ism, username yoki ID "
                "bo'yicha qidiradi (masalan admin 'Azizbek kim edi?' yoki "
                "'@ali qanday foydalanyapti?' desa). FAQAT admin/superadmin "
                "uchun ishlaydi — oddiy foydalanuvchi so'rasa, bu tool'dan "
                "foydalanmang va boshqalar haqida ma'lumot bermang."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Qidiruv so'zi — ism, @username, yoki ID"},
                },
                "required": ["query"],
            },
        },
    },
    # TODO: o'zingizning agent-specific tool'laringizni (masalan "post_to_channel",
    # "list_my_channels" — core/channels.py bilan bog'liq) shu yerga qo'shing.
]


MAX_NOTES_PER_USER = 30  # foydalanuvchi boshiga eng ko'pi (eskirgan/keraksiz to'planib ketmasin)


async def _remember_note(user_id: int, args: dict, ctx: dict) -> dict:
    import core.tgdb as tgdb
    db = tgdb.get()
    notes = db["users"].setdefault(str(user_id), {}).setdefault("notes", [])
    notes.append(args["note"])
    notes[:] = notes[-MAX_NOTES_PER_USER:]  # eng oxirgi N tasi qoladi
    await tgdb.save(ctx["bot"])
    return {"status": "saqlandi"}


def get_user_notes(user_id: int) -> list[str]:
    """Superadmin panel VA ai_chat.py (kontekstga qaytarish uchun) ishlatadi."""
    import core.tgdb as tgdb
    db = tgdb.get()
    return db["users"].get(str(user_id), {}).get("notes", [])


async def clear_user_notes(bot, user_id: int):
    """Superadmin — maxfiylik/nazorat maqsadida foydalanuvchi eslatmalarini tozalash."""
    import core.tgdb as tgdb
    db = tgdb.get()
    rec = db["users"].get(str(user_id))
    if rec and "notes" in rec:
        rec["notes"] = []
        await tgdb.save(bot, force=True)


async def _create_presentation(user_id: int, args: dict, ctx: dict) -> dict:
    try:
        async with _presentation_build_lock:
            path = await asyncio.to_thread(ppt_builder.build_presentation, user_id, args)
        return {"file_path": path, "status": "created", "slide_count": len(args.get("slides", [])) + 1}
    except Exception as e:
        return {"error": str(e)}


async def _create_diagram(user_id: int, args: dict, ctx: dict) -> dict:
    try:
        async with _presentation_build_lock:
            path = await asyncio.to_thread(ppt_builder.build_diagram, user_id, args)
        return {"file_path": path, "status": "created"}
    except Exception as e:
        return {"error": str(e)}


async def _get_user_profile(user_id: int, args: dict, ctx: dict) -> dict:
    target_id = args.get("target_user_id") or user_id
    return await user_profile.get_full_profile(
        ctx["bot"], requester_id=user_id, target_user_id=target_id,
        chat_id=ctx["chat_id"], thread_id=ctx["thread_id"],
    )


async def _lookup_user(user_id: int, args: dict, ctx: dict) -> dict:
    import core.roles as roles
    if not (roles.is_superadmin(user_id) or roles.is_admin(user_id)):
        return {"error": "Bu ma'lumot faqat admin/superadmin uchun mavjud."}

    matches = roles.search_users(args["query"])
    if not matches:
        return {"result": "Hech narsa topilmadi."}

    return {
        "matches": [
            {
                "id": uid,
                "name": rec.get("name"),
                "username": rec.get("username"),
                "role": rec.get("role"),
                "daily_limit": rec.get("daily_limit"),
                "requests_today": rec.get("requests_today", 0),
            }
            for uid, rec in list(matches.items())[:10]
        ]
    }


DISPATCH: dict[str, Callable[[int, dict, dict], Awaitable[dict]]] = {
    "remember_note": _remember_note,
    "create_presentation": _create_presentation,
    "create_diagram": _create_diagram,
    "get_user_profile": _get_user_profile,
    "lookup_user": _lookup_user,
}


def _unstringify_json(value):
    """
    Ba'zi AI modellar (ayniqsa ochiq-og'irlikdagi modellar) ichma-ich
    array/object'larni JSON-STRING sifatida yuboradi — masalan
    {"slides": "[{...}, {...}]"} to'g'ri {"slides": [{...}, {...}]}
    o'rniga. Bu — juda keng tarqalgan, hujjatlashtirilgan LLM
    function-calling xatosi (ko'plab agentic frameworklarda uchraydi,
    "double-encoded JSON" deb ataladi).

    HAR bir tool chaqiruvida avtomatik tuzatiladi: agar qiymat '[' yoki
    '{' bilan boshlanadigan STRING bo'lsa va json.loads muvaffaqiyatli
    bo'lsa — natija ishlatiladi (rekursiv, ichkarida ham tekshiradi).
    Aks holda qiymat o'zgarishsiz qoldiriladi (xato yashirilmaydi).
    """
    if isinstance(value, str):
        stripped = value.strip()
        if stripped[:1] in ("[", "{"):
            try:
                parsed = json.loads(stripped)
            except (ValueError, TypeError):
                return value
            return _unstringify_json(parsed)
        return value
    if isinstance(value, list):
        return [_unstringify_json(v) for v in value]
    if isinstance(value, dict):
        return {k: _unstringify_json(v) for k, v in value.items()}
    return value


async def dispatch(name: str, user_id: int, args: dict, ctx: dict) -> dict:
    # Yuqoridagi izohga qarang — AI ba'zan array/object'ni JSON-string
    # sifatida yuboradi, buni avtomatik tuzatamiz.
    args = _unstringify_json(args)
    if is_file_tool(name):
        return await file_dispatch(name, user_id, args)
    fn = DISPATCH.get(name)
    if not fn:
        return {"error": f"Noma'lum tool: {name}"}
    return await fn(user_id, args, ctx)
