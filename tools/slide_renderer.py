"""
.pptx faylining har bir slaydini alohida PNG rasmga aylantiradi.

Ishlash tartibi:
  1) LibreOffice (soffice) yordamida .pptx -> .pdf ga aylantiriladi.
  2) PyMuPDF (fitz) yordamida PDF'ning har bir sahifasi PNG rasmga aylantiriladi
     (bu qadam uchun qo'shimcha binary — masalan Poppler — shart emas, sof
     Python kutubxonasi orqali ishlaydi, shu sabab Windows'da ham muammosiz).

TALAB: LibreOffice tizimda o'rnatilgan bo'lishi kerak (bepul):
  https://www.libreoffice.org/download/download/
Windows'da odatiy o'rnatish yo'li avtomatik topiladi. Boshqa joyga
o'rnatgan bo'lsangiz, .env fayliga quyidagini qo'shing:
  SOFFICE_PATH=C:\\Program Files\\LibreOffice\\program\\soffice.exe
"""
import os
import platform
import shutil
import subprocess
import tempfile


class RenderError(Exception):
    """Slaydlarni rasmga aylantirishda yuz bergan xatolik (masalan LibreOffice topilmadi)."""


def _import_fitz():
    """PyMuPDF'ni faqat shu funksiya chaqirilganda import qiladi (lazy import).
    Shu tariqa, agar PyMuPDF o'rnatishda muammo bo'lsa (masalan Windows'da DLL
    xatosi), bu FAQAT 'rasm ko'rish' funksiyasiga ta'sir qiladi — botning asosiy
    qismi (prezentatsiya/diagramma yaratish) baribir ishlayveradi."""
    try:
        import fitz  # PyMuPDF
        return fitz
    except ImportError as e:
        raise RenderError(
            "PyMuPDF kutubxonasi yuklanmadi (rasm ko'rish funksiyasi uchun kerak).\n"
            "Buni tuzatish uchun terminalda quyidagini bajaring:\n"
            "  pip uninstall pymupdf -y\n"
            "  pip install pymupdf==1.24.14\n"
            "Agar yordam bermasa, 'Microsoft Visual C++ Redistributable (x64)'ni "
            "o'rnating: https://aka.ms/vs/17/release/vc_redist.x64.exe\n"
            f"(texnik tafsilot: {e})"
        ) from e


def _find_soffice() -> str:
    """LibreOffice'ning bajariladigan (soffice) faylini tizimdan qidirib topadi."""
    candidates = []

    env_path = os.getenv("SOFFICE_PATH", "").strip()
    if env_path:
        candidates.append(env_path)

    found_in_path = shutil.which("soffice") or shutil.which("soffice.exe")
    if found_in_path:
        candidates.append(found_in_path)

    system = platform.system()
    if system == "Windows":
        candidates += [
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        ]
    elif system == "Darwin":
        candidates.append("/Applications/LibreOffice.app/Contents/MacOS/soffice")
    else:
        candidates += ["/usr/bin/soffice", "/usr/local/bin/soffice"]

    for path in candidates:
        if path and os.path.exists(path):
            return path

    raise RenderError(
        "LibreOffice (soffice) topilmadi. Slaydlarni rasm qilib ko'rsatish uchun "
        "LibreOffice'ni bepul o'rnating: https://www.libreoffice.org/download/download/\n"
        "O'rnatgandan keyin botni qayta ishga tushiring. Agar boshqa joyga "
        "o'rnatgan bo'lsangiz, .env fayliga SOFFICE_PATH=\"to'liq\\yo'l\\soffice.exe\" qo'shing."
    )


def render_slides_to_images(pptx_path: str, dpi: int = 110) -> list[str]:
    """
    Berilgan .pptx faylining har bir slaydini alohida PNG faylga aylantiradi.

    :param pptx_path: .pptx faylining to'liq yo'li
    :param dpi: chiqish rasm sifati (110 — Telegram uchun yetarli va tez)
    :return: PNG fayllar yo'llari ro'yxati, slaydlar tartibida
    """
    if not os.path.exists(pptx_path):
        raise RenderError(f"Fayl topilmadi: {pptx_path}")

    soffice = _find_soffice()
    out_dir = tempfile.mkdtemp(prefix="slides_")

    # 1) pptx -> pdf
    try:
        result = subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf", "--outdir", out_dir, pptx_path],
            capture_output=True, text=True, timeout=120,
        )
    except subprocess.TimeoutExpired as e:
        raise RenderError("LibreOffice konvertatsiyasi vaqt chegarasidan oshib ketdi.") from e

    if result.returncode != 0:
        raise RenderError(f"LibreOffice PDF konvertatsiyasida xatolik:\n{result.stderr or result.stdout}")

    pdf_name = os.path.splitext(os.path.basename(pptx_path))[0] + ".pdf"
    pdf_path = os.path.join(out_dir, pdf_name)
    if not os.path.exists(pdf_path):
        raise RenderError("PDF fayl yaratilmadi — LibreOffice konvertatsiyasi muvaffaqiyatsiz bo'ldi.")

    # 2) pdf -> png (har bir sahifa)
    image_paths = []
    fitz = _import_fitz()  # RenderError bo'lsa, aniq xabar bilan shu yerda to'xtaydi
    try:
        doc = fitz.open(pdf_path)
        zoom = dpi / 72  # PDF standart 72 dpi hisoblanadi
        matrix = fitz.Matrix(zoom, zoom)
        for i, page in enumerate(doc, start=1):
            pix = page.get_pixmap(matrix=matrix)
            img_path = os.path.join(out_dir, f"slide-{i:02d}.png")
            pix.save(img_path)
            image_paths.append(img_path)
        doc.close()
    except Exception as e:  # noqa: BLE001
        raise RenderError(f"PDF'ni rasmga aylantirishda xatolik: {e}") from e

    if not image_paths:
        raise RenderError("Hech qanday slayd rasmga aylantirilmadi.")

    return image_paths

