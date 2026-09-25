FROM python:3.11-slim

# LibreOffice (writer+calc+impress) — slide_renderer.py (.pptx -> PNG) VA
# ms-file-toolkit'ning convert_docx_to_pdf/convert_xlsx_to_pdf/convert_pptx_to_pdf
# funksiyalari uchun. Faqat "impress" bilan cheklansak, docx/xlsx konvertatsiyasi
# ishlamas edi (test qilib aniqlandi) — shuning uchun barcha uchtasi kerak.
# tesseract-ocr — ms-file-toolkit'ning read_image_text (OCR) funksiyasi uchun.
# Katta (~700MB+), lekin bu funksiyalar uchun shart. Kerak bo'lmasa olib tashlang.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-writer \
    libreoffice-calc \
    libreoffice-impress \
    tesseract-ocr \
    fonts-dejavu \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["python", "main.py"]
