FROM python:3.11-slim

# LibreOffice - slide_renderer.py uchun (.pptx -> PNG). Katta (~600MB+), lekin
# "🖼 Slaydlarni ko'rish" funksiyasi uchun shart. Kerak bo'lmasa olib tashlang.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-impress \
    fonts-dejavu \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["python", "main.py"]
