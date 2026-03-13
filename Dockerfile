FROM python:3.12-slim

# Устанавливаем Tesseract + русский язык (т.к. у тебя lang="eng+rus")
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-rus \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Устанавливаем Python-зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Запуск (Render сам подставит PORT)
CMD ["python", "app.py"]
