"""
Function-calling tool registry — tgs-expert-bot/ai_tools.py formatidan
(Groq/OpenAI uslubidagi "tools" ro'yxati), ms-file-toolkit/registry.py'dagi
markazlashgan registry g'oyasi bilan birlashtirilgan.

Yangi tool qo'shish uchun: TOOLS ro'yxatiga yozuv qo'shing va DISPATCH
lug'atiga funksiyani bog'lang. dispatch() AI tanlagan tool'ni chaqiradi.
"""
from __future__ import annotations
from typing import Any, Callable, Awaitable

# ms-file-toolkit'ni submodule/paket sifatida qo'shsangiz shu yerdan import qiling:
# from ms_toolkit import TOOLS as FILE_TOOLS, dispatch as file_dispatch

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
    # TODO: bu yerga ms-file-toolkit'dan TOOLS ni qo'shing (docx/xlsx/pptx/pdf),
    # va o'zingizning agent-specific tool'laringizni (masalan "post_to_channel",
    # "list_my_channels" — core/channels.py bilan bog'liq) qo'shing.
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
    # "generate_docx": file_dispatch ...  # ms-file-toolkit ulanganda
}


async def dispatch(name: str, user_id: int, args: dict, ctx: dict) -> dict:
    fn = DISPATCH.get(name)
    if not fn:
        return {"error": f"Noma'lum tool: {name}"}
    return await fn(user_id, args, ctx)
