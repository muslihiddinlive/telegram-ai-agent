"""
Live Python Exec — weChat/bot.py (handle_exec) patternidan.

============================== XAVFSIZLIK OGOHLANTIRISHI ==============================
`exec:` buyrug'i CHEKLANMAGAN Remote Code Execution (RCE) imkoniyati beradi —
serverning butun muhitiga (fayllar, DB, .env, tarmoq) to'liq kirish demakdir.

FAQAT superadmin uchun ochiq (admin'lar UCHUN HAM YOPIQ — ular xatolikda butun
serverni boshqarib olishi mumkin). Xavfsizlik quyidagilarga bog'liq:
  1. BOT_TOKEN hech qachon oshkor bo'lmasligi (repo'ga commit qilinmasin).
  2. Sizning shaxsiy Telegram akkountingiz (SUPERADMIN_ID) kompromataciya
     bo'lmasligi — 2FA yoqilgan bo'lishi SHART.
Ikkalasidan biri buzilsa — server ustidan TO'LIQ nazorat qo'lga tushadi.

Foydalanish: xabar sifatida "exec: <python kodi>" yuboring, masalan:
  exec: print(2+2)
  exec: import os; print(os.listdir('.'))
=========================================================================================
"""
import io
import traceback
from contextlib import redirect_stdout
from html import escape as esc_html

from aiogram import Router, F
from aiogram.types import Message

import core.roles as roles

router = Router()

MAX_OUTPUT_LEN = 3500


def _truncate(text: str) -> str:
    return text if len(text) <= MAX_OUTPUT_LEN else text[:MAX_OUTPUT_LEN] + "\n... (kesildi)"


@router.message(F.text.startswith("exec:"))
async def handle_exec(message: Message) -> None:
    if not roles.is_superadmin(message.from_user.id):
        return  # admin va approved userlar uchun ham YOPIQ — javob ham qaytmaydi

    code_str = (message.text or "")[len("exec:"):].strip()
    if not code_str:
        await message.reply("Kod bo'sh bo'lmasligi kerak. Namuna: <code>exec: print(2+2)</code>")
        return

    buf = io.StringIO()
    exec_globals: dict = {"__builtins__": __builtins__}
    result_repr = None
    try:
        with redirect_stdout(buf):
            try:
                compiled = compile(code_str, "<exec>", "eval")
                value = eval(compiled, exec_globals)  # noqa: S307 — ataylab, superadmin-only terminal
                if value is not None:
                    result_repr = repr(value)
            except SyntaxError:
                compiled = compile(code_str, "<exec>", "exec")
                exec(compiled, exec_globals)  # noqa: S102 — ataylab, superadmin-only terminal

        output = buf.getvalue()
        if result_repr is not None:
            output += (("\n" if output else "") + f"=> {result_repr}")
        output = output.strip() or "(natija yo'q, lekin xatosiz bajarildi)"
    except Exception:
        output = "❌ Xatolik:\n" + traceback.format_exc()

    await message.reply(f"<pre>{esc_html(_truncate(output))}</pre>")
