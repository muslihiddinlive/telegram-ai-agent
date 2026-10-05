FROM python:3.11-slim

# LibreOffice (writer+calc+impress) — slide_renderer.py (.pptx -> PNG) VA
# ms-file-toolkit'ning convert_docx_to_pdf/convert_xlsx_to_pdf/convert_pptx_to_pdf
# funksiyalari uchun. Faqat "impress" bilan cheklansak, docx/xlsx konvertatsiyasi
# ishlamas edi (test qilib aniqlandi) — shuning uchun barcha uchtasi kerak.
# tesseract-ocr — ms-file-toolkit'ning read_image_text (OCR) funksiyasi uchun.
# ffmpeg — Story uchun videoni H.265/720x1280 formatiga o'tkazish (core/stories.py).
# Katta (~700MB+), lekin bu funksiyalar uchun shart. Kerak bo'lmasa olib tashlang.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-writer \
    libreoffice-calc \
    libreoffice-impress \
    tesseract-ocr \
    ffmpeg \
    fonts-dejavu \
    && rm -rf /var/lib/apt/lists/*

# Root bo'lmagan foydalanuvchi: konteyner buzilsa (masalan superadmin `exec:` orqali)
# tizim darajasidagi zarar kamayadi. HOME — LibreOffice profili uchun yoziladigan papka kerak.
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin app

WORKDIR /app

# requirements.lock — aniq (pinned) versiyalar: build har safar bir xil natija beradi.
# Yangilash: uv pip compile requirements.txt --python-version 3.11 --python-platform linux --no-header -o requirements.lock
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock

# data/ (db.json, user_files) ilova tomonidan yoziladi — egasi `app` bo'lishi shart.
COPY --chown=app:app . .
RUN mkdir -p /app/data && chown -R app:app /app/data

USER app
ENV HOME=/home/app

EXPOSE 8080

CMD ["python", "main.py"]
