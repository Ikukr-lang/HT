FROM python:3.12-slim

# tesseract + русский + все зависимости для Pillow
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-rus \
    libgl1-mesa-glx \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# Самый надёжный запуск для Render
CMD ["sh", "-c", "exec gunicorn \
    --bind 0.0.0.0:${PORT:-5000} \
    --workers 1 \
    --timeout 180 \
    --log-level debug \
    --access-logfile - \
    --error-logfile - \
    app:app"]
