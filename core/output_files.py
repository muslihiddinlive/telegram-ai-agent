"""
Tool natijasidan foydalanuvchiga YUBORILADIGAN fayllarni aniqlash.

Oldingi mantiq: natijada "file_path" yoki "output_path" bo'lsa — "fayl yaratildi" deb
hisoblanardi. Bu XATO edi: read_pdf_text/read_qr_code kabi O'QISH tool'lari ham kirish
faylining yo'lini (file_path) qaytaradi. Natijada bot foydalanuvchining o'z faylini
qaytarib yuborar, keyin DISKDAN O'CHIRIB tashlar, AI esa o'qigan narsasi haqida
javob ham bera olmasdi.

To'g'ri qoida: ms-file-toolkit'ning barcha YOZUVCHI tool'lari natijada "status"
qaytaradi (created/merged/split/converted/appended/...), o'qish tool'lari esa yo'q.
"""
import os


def output_files(tool_result) -> list[str]:
    """Tool natijasi bo'yicha yuborilishi kerak bo'lgan (mavjud) fayllar yo'llari ro'yxati.

    Qoida: natijada "status" bo'lsagina (ya'ni YOZUVCHI amal bo'lgandagina) fayl(lar)
    yuboriladi — o'qish tool'lari (read_pdf_text, get_pdf_metadata, read_qr_code, ...)
    "status" qaytarmaydi, faqat ma'lumot uchun "file_path"ni (kirish faylining o'zini)
    ko'rsatadi, holos. Aniq ro'yxat maydonlari ("output_files" — split_pdf/convert_*,
    "images" — extract_pdf_images) bitta "file_path"dan USTUVOR: ular bo'lsa, faqat
    o'shalar ishlatiladi (masalan arxiv ochish natijasidagi "extracted_files" bu yerda
    ATAYLAB e'tiborga olinmaydi — u yuzlab faylni birdan yuborib yubormasin)."""
    if not isinstance(tool_result, dict) or tool_result.get("error") or not tool_result.get("status"):
        return []

    if tool_result.get("output_files"):            # split_pdf, convert_pdf_to_images, convert_xlsx_to_images
        paths = list(tool_result["output_files"])
    elif tool_result.get("images"):                # extract_pdf_images
        paths = [i.get("path") for i in tool_result["images"] if isinstance(i, dict)]
    else:
        paths = [tool_result.get("file_path") or tool_result.get("output_path")]

    return [p for p in paths if isinstance(p, str) and p and os.path.isfile(p)]
