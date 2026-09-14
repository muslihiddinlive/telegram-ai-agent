"""
ms-file-toolkit (PyPI, v0.4.0) haqiqiy integratsiyasi.

Muhim: ms_toolkit.TOOLS formati Claude/Anthropic uslubida
(`input_schema`), bizning core/ai_tools.py esa Groq/OpenAI uslubida
(`parameters`) ishlaydi — shuning uchun schema konvertatsiya qilinadi.

ms_toolkit.dispatch() sinxron (async emas) — asyncio.to_thread() bilan
event loop'ni bloklamasdan chaqiramiz.

Xavfsizlik: har bir foydalanuvchi faqat o'ziga tegishli papkada fayl
yarata/o'qiy oladi (base_dir orqali cheklangan — ms_toolkit/security.py
path-traversal'dan himoya qiladi).
"""
import asyncio
import os
import ms_toolkit

USER_FILES_ROOT = os.path.join(os.path.dirname(__file__), "..", "data", "user_files")


def _to_groq_format(tool: dict) -> dict:
    """Claude-uslub ({name, description, input_schema}) -> Groq/OpenAI-uslub."""
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["input_schema"],
        },
    }


FILE_TOOLS: list[dict] = [_to_groq_format(t) for t in ms_toolkit.TOOLS]

_FILE_TOOL_NAMES = {t["function"]["name"] for t in FILE_TOOLS}


def is_file_tool(name: str) -> bool:
    return name in _FILE_TOOL_NAMES


def _user_dir(user_id: int) -> str:
    path = os.path.join(USER_FILES_ROOT, str(user_id))
    os.makedirs(path, exist_ok=True)
    return path


_PATH_KEYS = ("file_path", "image_path", "output_path")
_PATH_LIST_KEYS = ("file_paths",)


def _resolve_into(path: str, base_dir: str) -> str:
    """
    AI odatda 'file_path' sifatida oddiy nom beradi (masalan "hisobot.docx"),
    ms_toolkit esa buni base_dir ICHIDAGI absolyut yo'l deb talab qiladi.
    Agar AI chetga chiquvchi/absolyut yo'l bersa ham, faqat fayl nomini
    olib, foydalanuvchining o'z papkasiga joylaymiz (xavfsizlik).
    """
    base_abs = os.path.abspath(base_dir)
    abs_path = os.path.abspath(path)
    try:
        if os.path.commonpath([abs_path, base_abs]) == base_abs:
            return abs_path
    except ValueError:
        pass
    return os.path.join(base_abs, os.path.basename(path))


def _normalize_args(args: dict, base_dir: str) -> dict:
    args = dict(args)
    for k in _PATH_KEYS:
        if k in args and isinstance(args[k], str) and args[k]:
            args[k] = _resolve_into(args[k], base_dir)
    for k in _PATH_LIST_KEYS:
        if k in args and isinstance(args[k], list):
            args[k] = [_resolve_into(p, base_dir) for p in args[k]]
    return args


async def file_dispatch(name: str, user_id: int, args: dict) -> dict:
    base_dir = _user_dir(user_id)
    safe_args = _normalize_args(args, base_dir)
    return await asyncio.to_thread(ms_toolkit.dispatch, name, safe_args, base_dir)

