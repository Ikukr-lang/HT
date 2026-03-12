FROM python:3.12-slim-bookworm

# Установка Tesseract
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-rus \
    && rm -rf /var/lib/apt/lists/*

COPY . /app
WORKDIR /app

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 10000
# Главный фикс: используем $PORT + таймаут 90 сек (для OCR)
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:$PORT --timeout 90 app:app"]
