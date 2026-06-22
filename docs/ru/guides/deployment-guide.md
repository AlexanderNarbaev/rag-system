# Руководство по развёртыванию

## Предварительные требования

| Компонент | Минимум | Рекомендуется |
|-----------|---------|---------------|
| **Docker** | 24.0+ | 27.0+ |
| **Docker Compose** | v2.20+ (плагин) | v2.30+ |
| **NVIDIA Driver** | 535+ | 550+ |
| **NVIDIA Container Toolkit** | 1.14+ | 1.17+ |
| **Python** | 3.11 | 3.12 |

Проверка доступности GPU:
```bash
nvidia-smi
docker run --rm --gpus all nvidia/cuda:12.4-base nvidia-smi
```

## Требования к инфраструктуре

| Ресурс | Минимум | Рекомендуется (prod) |
|--------|---------|----------------------|
| **CPU** | 8 ядер | 16+ ядер |
| **RAM** | 32 GB | 64+ GB |
| **GPU VRAM** | 24 GB (квантизованный GGUF) | 48+ GB (полная точность) |
| **Диск** | 100 GB SSD | 500+ GB NVMe |
| **Сеть** | 1 Gbps | 10 Gbps (внутренняя) |

**Распределение диска**: векторы Qdrant ~30 GB, граф Neo4j ~10 GB, файлы моделей ~20 GB, сырые данные + чанки ~20 GB, логи ~10 GB.

## Автономное развёртывание

В автономной среде загрузите все ресурсы на машине с интернетом, затем перенесите их.

### 1. Загрузка моделей офлайн

```bash
# На машине с интернетом:
cd rag-system
python scripts/download_models_offline.py \
  --output-dir ./offline_models \
  --models embedder reranker spacy_ru spacy_en slm \
  --gguf-url https://huggingface.co/your-org/your-model-GGUF/resolve/main/your-model-Q4_K_M.gguf

# Это загружает:
# - BAAI/bge-m3 (эмбеддер + sparse)
# - cross-encoder/ms-marco-MiniLM-L-6-v2 (реранкер)
# - ru_core_news_sm, en_core_web_sm (spaCy)
# - your-slm-model (SLM)
# - your-llm-model GGUF (LLM)

# Перенос на автономную машину:
tar -czf offline_models.tar.gz offline_models/
scp offline_models.tar.gz user@airgap-machine:/opt/rag-system/
```

### 2. Перенос Docker-образов

```bash
# На машине с интернетом:
docker pull qdrant/qdrant:latest
docker pull neo4j:5-enterprise
docker pull redis:7-alpine
docker pull python:3.11-slim

docker save qdrant/qdrant:latest neo4j:5-enterprise redis:7-alpine \
  python:3.11-slim -o rag-images.tar

# Для LLM-бэкенда (выберите один):
# - vLLM: docker pull vllm/vllm-openai:latest
# - llama.cpp: docker pull ghcr.io/ggerganov/llama.cpp:server
# - Любой OpenAI-совместимый сервер

scp rag-images.tar user@airgap-machine:/opt/rag-system/

# На автономной машине:
docker load -i rag-images.tar
```

### 3. Офлайн pip-пакеты

```bash
# На машине с интернетом:
mkdir pip-offline
pip download -r proxy/requirements_proxy.txt -d pip-offline/
pip download -r etl/requirements_etl.txt -d pip-offline/

tar -czf pip-offline.tar.gz pip-offline/
scp pip-offline.tar.gz user@airgap-machine:/opt/rag-system/
```

## Пошаговое развёртывание

### Шаг 1: Настройка окружения

```bash
cp proxy/.env proxy/.env.bak
# Отредактируйте proxy/.env с вашими настройками:
```

Ключевые переменные для настройки:
```ini
QDRANT_HOST=qdrant
QDRANT_PORT=6333
LLM_ENDPOINT=http://llm-backend:8000/v1
LLM_MODEL_NAME=your-model-name
REQUEST_TIMEOUT=120
USE_REDIS=true
REDIS_URL=redis://redis:6379
USE_LANGGRAPH=true
GRAPH_ENABLED=true
NEO4J_URI=bolt://neo4j:7687
NEO4J_PASSWORD=your_secure_password
```

### Шаг 2: Обновление путей к моделям

В `proxy/docker-compose.yml` обновите том LLM-бэкенда:
```yaml
volumes:
  - /opt/rag-system/offline_models:/models:ro
```
И том rag-proxy:
```yaml
volumes:
  - /opt/rag-system/offline_models/cache:/app/cache:ro
```

### Шаг 3: Инициализация коллекций Qdrant

```bash
# Убедитесь, что Qdrant запущен, затем:
python scripts/init_collections.py --qdrant-recreate

# Проверьте:
curl http://localhost:6333/collections/knowledge_base
```

### Шаг 4: Запуск сервисов

```bash
cd proxy
docker-compose up -d

# Проверьте, что все контейнеры работоспособны:
docker-compose ps
# Ожидается: qdrant, neo4j, redis, llm-backend, rag-proxy, hitl-dashboard — все "Up"
```

### Шаг 5: Проверка работоспособности

```bash
# Эндпоинт здоровья прокси:
curl http://localhost:8080/v1/health
# Ответ: {"status": "healthy", "qdrant": "connected", "llm": "available"}

# Список моделей:
curl http://localhost:8080/v1/models
# Ответ: {"data": [{"id": "your-model-name", ...}]}
```

### Шаг 6: Первый запуск ETL-пайплайна

```bash
cd ../etl
# Отредактируйте config/etl_config.yaml с учётными данными источников
python scheduler/run_etl.py --config config/etl_config.yaml

# Или через Docker:
docker build -f Dockerfile.etl -t rag-etl .
docker run --rm --network=host \
  -v $(pwd)/wal:/wal \
  -v $(pwd)/chunks:/chunks \
  rag-etl --config /app/etl/config/etl_config.yaml
```

## Production чек-лист

### Redis Streams для потокового ETL

При `STREAMING_ETL_ENABLED=true` настройте Redis Streams для обработки событий в реальном времени:

```bash
# В proxy/.env:
STREAMING_ETL_ENABLED=true
REDIS_STREAMS_URL=redis://redis:6379

# Конфигурация Redis в docker-compose для потоков:
redis:
  image: redis:7-alpine
  command: redis-server --appendonly yes \
    --maxmemory 2gb \
    --maxmemory-policy allkeys-lru \
    --stream-node-max-bytes 4096 \
    --stream-node-max-entries 100
```

**Структура потоков:**
- Ключ потока: `etl:events`
- Группы потребителей: `etl-extract`, `etl-chunk`, `etl-embed`, `etl-index`
- Dead letter stream: `etl:events:dlq`
- Макс. ожидающих сообщений на потребителя: 1000

**Инициализация групп потребителей** (однократно):
```bash
docker exec rag-redis redis-cli XGROUP CREATE etl:events etl-extract $ MKSTREAM
docker exec rag-redis redis-cli XGROUP CREATE etl:events etl-chunk $
docker exec rag-redis redis-cli XGROUP CREATE etl:events etl-embed $
docker exec rag-redis redis-cli XGROUP CREATE etl:events etl-index $
```

### Настройка вебхуков

#### Вебхук Confluence

1. В Confluence Admin → Webhooks зарегистрируйте:
   - URL: `https://<proxy-host>/webhook/confluence`
   - События: `page_created`, `page_updated`, `page_removed`
   - Секрет: совпадает с `WEBHOOK_SECRET` в `.env`

2. Настройте в `proxy/.env`:
```bash
WEBHOOK_SECRET=ваш-общий-секрет  # Должен совпадать с секретом вебхука Confluence
```

#### Вебхук GitLab

1. В GitLab Project → Settings → Webhooks зарегистрируйте:
   - URL: `https://<proxy-host>/webhook/gitlab`
   - Триггеры: `Push events`, `Merge request events`
   - Secret Token: совпадает с `WEBHOOK_SECRET`

2. Проверка связности:
```bash
curl -X POST https://<proxy-host>/webhook/confluence \
  -H "Content-Type: application/json" \
  -H "X-Confluence-Webhook-Signature: sha256=$(echo -n '{"event":"test"}' | openssl dgst -sha256 -hmac "$WEBHOOK_SECRET" | cut -d' ' -f2)" \
  -d '{"event":"test"}'
```

### Прогрев моделей при запуске

Добавьте прогрев в lifespan прокси для устранения задержки холодного старта:

```yaml
# docker-compose.yml — прогрев после старта:
rag-proxy:
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:8080/v1/health/ready"]
    interval: 15s
    retries: 5
    start_period: 60s  # Время на прогрев + загрузку моделей
```

**Ручной запуск:**
```bash
# Прогрев всех моделей (требуется токен admin при AUTH_ENABLED=true):
curl -X POST http://localhost:8080/v1/admin/warmup \
  -H "Authorization: Bearer <admin-токен>"

# Прогрев включая LLM:
curl -X POST http://localhost:8080/v1/admin/warmup \
  -H "Authorization: Bearer <admin-токен>" \
  -d '{"warmup_llm": true}'
```

**Kubernetes post-start hook:**
```yaml
lifecycle:
  postStart:
    exec:
      command:
        - /bin/sh
        - -c
        - |
          until curl -sf http://localhost:8080/v1/health/live; do sleep 1; done
          curl -sf -X POST http://localhost:8080/v1/admin/warmup
```

### Сжатие ответов

Включите сжатие gzip/brotli для всех ответов:

```bash
# В proxy/.env:
COMPRESSION_ENABLED=true       # Включить сжатие (по умолчанию: true)
COMPRESSION_MIN_SIZE=1000      # Сжимать ответы > 1KB (по умолчанию: 1000)
COMPRESSION_LEVEL=6            # Уровень gzip 1-9 (по умолчанию: 6)
```

**Обратный прокси Nginx** — убедитесь, что заголовки сжатия пробрасываются:
```nginx
location /v1/ {
    proxy_pass http://127.0.0.1:8080;
    proxy_set_header Accept-Encoding $http_accept_encoding;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_read_timeout 180s;
    proxy_buffering off;  # Необходимо для SSE-стриминга
}
```

**Бенчмарки** (измерено на JSON-ответах):
- gzip уровень 6: снижение на 65-72%, <5ms накладных расходов CPU
- brotli уровень 4: снижение на 68-75%, <15ms накладных расходов CPU
- Потоковые SSE-ответы НЕ сжимаются (используется chunked transfer encoding)

### Безопасность
- [ ] Смените ВСЕ пароли по умолчанию (Neo4j, API-ключ Qdrant, если установлен)
- [ ] Установите `LLM_API_KEY` и ограничьте LLM-бэкенд с помощью `--api-key`
- [ ] Используйте обратный прокси (nginx/Caddy) с TLS перед портом 8080
- [ ] Включите файервол: открывайте только 8080 и 8501 для внешнего доступа
- [ ] Установите `LOG_REQUESTS=true`, но маскируйте `SENSITIVE_SECRETS` в конфигурации

### Мониторинг
- [ ] Настройте Prometheus для сбора `/metrics` со всех сервисов
- [ ] Настройте алерты: диск >80%, RAM >85%, утилизация GPU >95%, частота 5xx прокси
- [ ] Включите Docker healthchecks для всех контейнеров

### Резервное копирование
- [ ] Запланируйте ежедневные снапшоты Qdrant: `POST /collections/knowledge_base/snapshots`
- [ ] Запланируйте ежедневные дампы Neo4j: `neo4j-admin database dump`
- [ ] Резервируйте `wal/etl_wal.json` и `wal/version_wal.json` после каждого запуска ETL
- [ ] Храните 7 ежедневных + 4 еженедельных + 3 ежемесячных резервных копий

## Устранение типовых проблем

### OOM (нехватка памяти)
```bash
# OOM LLM-бэкенда: уменьшить контекст, использовать квантизованную модель
# Для vLLM измените команду бэкенда в docker-compose.yml:
--max-model-len 65536  # вместо 130000
--tensor-parallel-size 1

# OOM Neo4j: уменьшить heap
NEO4J_dbms_memory_heap_max__size=1G  # вместо 2G
```

### Конфликты портов
```bash
# Проверьте, что используют порты:
ss -tlnp | grep -E '6333|6379|7687|8000|8080|8501'

# Переопределите в docker-compose.yml или .env
```

### Дисковое пространство
```bash
# Очистите неиспользуемые данные Docker:
docker system prune -a --volumes -f

# Очистите старые холодные чанки ETL:
find etl/cold_chunks/ -name "*.parquet" -mtime +30 -delete

# Ротируйте логи:
find proxy/logs/ -name "*.log" -mtime +7 -delete
```

### LLM-бэкенд не запускается
```bash
# Проверьте доступ к GPU:
docker run --rm --gpus all your-llm-backend-image nvidia-smi

# Проверьте существование файла модели:
ls -la /opt/rag-system/offline_models/your-model.gguf

# Проверьте логи бэкенда:
docker logs rag-llm-backend
```
