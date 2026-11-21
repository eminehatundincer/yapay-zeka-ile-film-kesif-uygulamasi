# Backend Dockerfile — FastAPI + Asenkron SQLAlchemy + Gemini Ajanları
FROM python:3.11-slim

# Byte-code (.pyc) yazmayı engelle ve logların tamponlanmadan anlık çıkmasını sağla
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8005

WORKDIR /app

# Bağımlılıkları önbelleğe almadan kur (katman önbelleği için önce requirements.txt)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Tüm backend kaynak kodlarını kopyala
COPY . .

EXPOSE 8005

# Uygulamayı bulutta dinamik $PORT, yerelde 8005 portunda broadcast (0.0.0.0) adresinden başlat
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8005}"]
