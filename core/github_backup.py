"""
core/github_backup.py
---------------------
AI repo'ni o'zgartirishdan OLDIN zaxira nusxa (ZIP): foydalanuvchining o'ziga va (config.GITHUB_BACKUP_TO_ADMIN bo'lsa) bot egasiga
(superadmin) Telegram orqali yuboriladi — AI xato tahrir qilsa, asliga qaytarish mumkin bo'lsin.

  * ZIP faqat ishchi fayllarni oladi (.git, symlink'lar tashqarida) + BACKUP_INFO.txt (repo, branch, commit SHA, tiklash yo'li).
  * Zaxira foydalanuvchiga yetmasa — o'zgartirish BAJARILMAYDI (xavfsizlik). Superadminga yetmasligi esa to'siq emas.
  * Maxfiylik: ZIP ichida repo'dagi hamma narsa (ehtimol maxfiy kalitlar ham) bor — shuning uchun foydalanuvchiga oldindan va har safar aytiladi.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import time
import zipfile

import config
import core.github_sandbox as sb
from core.github_sandbox import GitHubError

logger = logging.getLogger("github_backup")

MAX_ZIP_BYTES = 45 * 1024 * 1024        # Telegram bot hujjat chegarasi 50 MB
MAX_RAW_BYTES = 300 * 1024 * 1024
MAX_FILES = 20000
REBACKUP_AFTER = 30 * 60                # bir xil klon uchun qayta zaxira: HEAD o'zgargan va oxirgisi shundan eski bo'lsa

def disclosure() -> str:
    return ("AI repo'ni o'zgartirishdan oldin repo'ning zaxira ZIP nusxasi sizga" +
            (" va bot egasiga (superadmin)" if config.GITHUB_BACKUP_TO_ADMIN else "") + " yuboriladi.")


def _marker(path: str) -> str:
    return os.path.join(path, ".git", "bot_backup.json")


def last_backup(path: str) -> dict | None:
    try:
        with open(_marker(path), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def needs_backup(path: str, head: str) -> bool:
    m = last_backup(path)
    if not m:
        return True
    return m.get("sha") != head and time.time() - float(m.get("at", 0)) > REBACKUP_AFTER


def mark(path: str, head: str) -> None:
    with open(_marker(path), "w", encoding="utf-8") as fh:
        json.dump({"sha": head, "at": time.time()}, fh)


def make_zip(path: str, info: str) -> tuple[bytes, int]:
    """Ishchi papkani ZIP qiladi (.git va symlink'larsiz). -> (baytlar, fayllar soni). Katta bo'lsa GitHubError."""
    buf, n, raw = io.BytesIO(), 0, 0
    base = os.path.realpath(path)
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.writestr("BACKUP_INFO.txt", info)
        for dp, dn, files in os.walk(base):
            dn[:] = [d for d in dn if d != ".git" and not os.path.islink(os.path.join(dp, d))]
            for f in files:
                full = os.path.join(dp, f)
                if os.path.islink(full) or not os.path.isfile(full):
                    continue
                raw += os.lstat(full).st_size
                n += 1
                if n > MAX_FILES or raw > MAX_RAW_BYTES:
                    raise GitHubError("Repo zaxira qilish uchun juda katta (fayllar soni/hajmi chegaradan oshdi).")
                z.write(full, os.path.relpath(full, base))
    data = buf.getvalue()
    if len(data) > MAX_ZIP_BYTES:
        raise GitHubError(f"Zaxira ZIP {len(data) // 1024 // 1024} MB — Telegram orqali yuborib bo'lmaydi (chegara {MAX_ZIP_BYTES // 1024 // 1024} MB).")
    return data, n


async def send(bot, uid: int, owner: str, repo: str, branch: str, head: str, path: str, reason: str) -> dict:
    """ZIP yaratadi va yuboradi. Foydalanuvchiga yetmasa GitHubError. -> {"files": n, "kb": ..., "admin": bool}"""
    from aiogram.types import BufferedInputFile
    info = (f"Repo: {owner}/{repo}\nBranch: {branch}\nCommit: {head}\nVaqt (UTC): {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())}\n"
            f"Sabab: {reason}\n\nBu AI o'zgartirishidan OLDINGI holat. Tiklash: ZIP'ni oching va fayllarni repo'ga qaytaring "
            f"(yoki GitHub'dagi tarixdan `git revert`/`git reset` qiling).\n")
    data, n = await asyncio.to_thread(make_zip, path, info)
    name = f"{owner}__{repo}__{head[:7]}.zip"
    caption = (f"📦 <b>Zaxira nusxa</b>: {owner}/{repo} ({branch}, {head[:7]})\n{reason}\nFayllar: {n}, {len(data) // 1024} KB. "
               f"Bu — o'zgartirishdan OLDINGI holat; AI xato qilsa, shundan tiklaysiz.")
    try:
        await bot.send_document(uid, BufferedInputFile(data, filename=name), caption=caption)
    except Exception:  # noqa: BLE001
        logger.warning("Zaxirani foydalanuvchiga yuborib bo'lmadi (uid=%s)", uid)
        raise GitHubError("Zaxira nusxani sizga yubora olmadim, shuning uchun xavfsizlik nuqtai nazaridan o'zgartirish BEKOR qilindi.")
    sent_admin = False
    if config.GITHUB_BACKUP_TO_ADMIN and int(config.SUPERADMIN_ID) != int(uid):
        try:
            await bot.send_document(config.SUPERADMIN_ID, BufferedInputFile(data, filename=name),
                                    caption=f"{caption}\n👤 Foydalanuvchi ID: <code>{uid}</code>")
            sent_admin = True
        except Exception:  # noqa: BLE001 — superadmin botni bloklagan bo'lishi mumkin: to'siq emas
            logger.warning("Zaxirani superadminga yuborib bo'lmadi")
    return {"files": n, "kb": len(data) // 1024, "admin": sent_admin}
