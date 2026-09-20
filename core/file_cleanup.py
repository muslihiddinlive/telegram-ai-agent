"""
Vaqtinchalik fayl/papkalarni tozalash — RAM/disk to'lib, "out of memory"
bo'lib qolmasligi uchun (LibreOffice konvertatsiyasi va rasm generatsiyasi
ancha joy yeydi). DB'dagi yozuvlarga (suhbat tarixi, foydalanuvchi holati va
h.k.) bu HECH QANDAY ta'sir qilmaydi — faqat diskdagi vaqtinchalik fayllar
o'chiriladi.
"""
import asyncio
import logging
import os
import shutil

logger = logging.getLogger("file_cleanup")


def delete_file_now(path: str):
    try:
        if path and os.path.isfile(path):
            os.remove(path)
    except Exception as e:
        logger.warning("Faylni o'chirib bo'lmadi: %s (%s)", path, e)


def delete_dir_now(path: str):
    try:
        if path and os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
    except Exception as e:
        logger.warning("Papkani o'chirib bo'lmadi: %s (%s)", path, e)


def schedule_file_delete(path: str, delay_seconds: int = 900):
    """
    Faylni DARHOL emas, delay_seconds'dan keyin o'chiradi — masalan .pptx
    faylini "🖼 Ko'rish" tugmasi hali bosilmagan bo'lishi mumkinligi uchun
    biroz vaqt beramiz (standart 15 daqiqa).
    """
    async def _worker():
        await asyncio.sleep(delay_seconds)
        delete_file_now(path)
    asyncio.create_task(_worker())


def cleanup_stale_files(root_dir: str, max_age_seconds: int = 3600):
    """
    Bot qayta ishga tushganda chaqiriladi (main.py on_startup) — agar oldingi
    sessiyada bot qulab tushib, schedule_file_delete() bajarilmagan bo'lsa,
    shu funksiya max_age_seconds'dan katta yoshdagi qoldiq fayllarni tozalaydi.
    """
    import time
    if not os.path.isdir(root_dir):
        return
    now = time.time()
    removed = 0
    for dirpath, _, filenames in os.walk(root_dir):
        for name in filenames:
            fpath = os.path.join(dirpath, name)
            try:
                if now - os.path.getmtime(fpath) > max_age_seconds:
                    os.remove(fpath)
                    removed += 1
            except Exception:
                pass
    if removed:
        logger.info("Ishga tushishda %d ta eski vaqtinchalik fayl tozalandi", removed)
