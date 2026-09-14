"""
"🖼 Slaydlarni ko'rish" tugmasi bosilganda — groq-pptx-bot/slide_renderer.py
orqali .pptx faylining har bir slaydini PNG rasmga aylantirib, media-group
(albom) sifatida yuboradi. LibreOffice talab qilinadi (agar o'rnatilmagan
bo'lsa, foydalanuvchiga tushunarli xabar chiqadi).
"""
import asyncio
from aiogram import Router, F
from aiogram.types import CallbackQuery, InputMediaPhoto, FSInputFile

import core.preview_tokens as preview_tokens
import tools.slide_renderer as slide_renderer

router = Router()


@router.callback_query(F.data.startswith("preview:"))
async def show_slide_preview(call: CallbackQuery):
    token = call.data.split(":", 1)[1]
    file_path = preview_tokens.resolve(token)
    if not file_path:
        await call.answer("Bu tugma eskirgan — faylni qaytadan so'rang.", show_alert=True)
        return

    await call.answer("Slaydlar tayyorlanmoqda...")
    try:
        image_paths = await asyncio.to_thread(slide_renderer.render_slides_to_images, file_path)
    except slide_renderer.RenderError as e:
        await call.message.answer(f"⚠️ {e}")
        return

    # Telegram media-group'da bittada 10 tagacha rasm bo'ladi — kerak bo'lsa bo'laklarga bo'lamiz
    for i in range(0, len(image_paths), 10):
        chunk = image_paths[i:i + 10]
        media = [InputMediaPhoto(media=FSInputFile(p)) for p in chunk]
        await call.message.answer_media_group(media)
