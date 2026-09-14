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


DISPATCH: dict[str, Callable[[int, dict, dict], Awaitable[dict]]] = {
    "remember_note": _remember_note,
}


async def dispatch(name: str, user_id: int, args: dict, ctx: dict) -> dict:
    if is_file_tool(name):
        return await file_dispatch(name, user_id, args)
    fn = DISPATCH.get(name)
    if not fn:
        return {"error": f"Noma'lum tool: {name}"}
    return await fn(user_id, args, ctx)
