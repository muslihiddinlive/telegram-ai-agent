"""
Function-calling tool registry — tgs-expert-bot/ai_tools.py formatidan
(Groq/OpenAI uslubidagi "tools" ro'yxati), ms-file-toolkit/registry.py'dagi
markazlashgan registry g'oyasi bilan birlashtirilgan.

Yangi tool qo'shish uchun: TOOLS ro'yxatiga yozuv qo'shing va DISPATCH
lug'atiga funksiyani bog'lang. dispatch() AI tanlagan tool'ni chaqiradi.
"""
from __future__ import annotations
from typing import Any, Callable, Awaitable

from tools.file_tools import FILE_TOOLS, file_dispatch, is_file_tool
import tools.presentation_builder as ppt_builder

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
                "Foydalanuvchi biror narsani botga 'eslab qol' desa yoki muhim "
                "ma'lumot bersa, shu tool orqali DB'ga yoziladi."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "note": {"type": "string", "description": "Eslab qolinadigan matn"},
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
                },
                "required": ["diagram_type", "title"],
            },
        },
    },
    # TODO: o'zingizning agent-specific tool'laringizni (masalan "post_to_channel",
    # "list_my_channels" — core/channels.py bilan bog'liq) shu yerga qo'shing.
]


async def _remember_note(user_id: int, args: dict, ctx: dict) -> dict:
    import core.tgdb as tgdb
    db = tgdb.get()
    notes = db["users"].setdefault(str(user_id), {}).setdefault("notes", [])
    notes.append(args["note"])
    await tgdb.save(ctx["bot"])
    return {"status": "saqlandi"}


async def _create_presentation(user_id: int, args: dict, ctx: dict) -> dict:
    import asyncio
    try:
        path = await asyncio.to_thread(ppt_builder.build_presentation, user_id, args)
        return {"file_path": path, "status": "created", "slide_count": len(args.get("slides", [])) + 1}
    except Exception as e:
        return {"error": str(e)}


async def _create_diagram(user_id: int, args: dict, ctx: dict) -> dict:
    import asyncio
    try:
        path = await asyncio.to_thread(ppt_builder.build_diagram, user_id, args)
        return {"file_path": path, "status": "created"}
    except Exception as e:
        return {"error": str(e)}


DISPATCH: dict[str, Callable[[int, dict, dict], Awaitable[dict]]] = {
    "remember_note": _remember_note,
    "create_presentation": _create_presentation,
    "create_diagram": _create_diagram,
}


async def dispatch(name: str, user_id: int, args: dict, ctx: dict) -> dict:
    if is_file_tool(name):
        return await file_dispatch(name, user_id, args)
    fn = DISPATCH.get(name)
    if not fn:
        return {"error": f"Noma'lum tool: {name}"}
    return await fn(user_id, args, ctx)
