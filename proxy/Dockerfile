# proxy/Dockerfile
# Docker-образ для RAG-прокси (OpenAI-совместимый сервер с Qdrant, реранкингом, LangGraph)

FROM python:3.11-slim

# Установка системных зависимостей (необходимы для некоторых Python-пакетов)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копирование зависимостей и их установка
COPY requirements_proxy.txt .
RUN pip install --no-cache-dir -r requirements_proxy.txt

# Копирование исходного кода прокси
COPY proxy/app /app/app
# Если есть дополнительные файлы (например, .env.example), можно скопировать
COPY proxy/.env.example /app/.env.example

# ── Опционально: поддержка GPU для дообучения моделей ──
# Для использования GPU раскомментировать следующие строки и пересобрать образ
# COPY proxy/requirements_proxy_gpu.txt /app/requirements_proxy_gpu.txt
# RUN pip install --no-cache-dir -r /app/requirements_proxy_gpu.txt
# После сборки добавить в docker run: --gpus all

# Создание директорий для логов и кэша (опционально, будут переопределены томами)
RUN mkdir -p /app/logs /app/cache

# Переменные окружения для кэширования моделей Hugging Face (можно переопределить при запуске)
ENV HF_HOME=/app/cache/huggingface
ENV TRANSFORMERS_CACHE=/app/cache/huggingface/transformers
ENV SENTENCE_TRANSFORMERS_HOME=/app/cache/huggingface/sentence-transformers

# Отключаем байткод и буферизацию логов
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Порт, который слушает сервер (по умолчанию 8080)
EXPOSE 8080

# Graceful shutdown signal
STOPSIGNAL SIGTERM

# Health check for orchestration
HEALTHCHECK --interval=5s --timeout=3s --retries=3 CMD curl -f http://localhost:8080/v1/health/live || exit 1

# Команда запуска через uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
