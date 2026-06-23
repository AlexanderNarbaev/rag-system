# Руководство по развёртыванию прокси

RAG Proxy — это основной обслуживающий слой, приложение FastAPI, предоставляющее OpenAI-совместимый API. Оно подключается к Qdrant (векторный поиск), Neo4j (граф знаний), Redis (кэш) и LLM-бэкенду (vLLM, llama.cpp или любой OpenAI-совместимый эндпоинт).

---

## Предварительные требования

| Компонент | Минимум | Рекомендуется |
|-----------|---------|---------------|
| **Docker** | 24.0+ | 27.0+ |
| **Docker Compose** | v2.20+ | v2.30+ |
| **NVIDIA Driver** | 535+ | 550+ |
| **NVIDIA Container Toolkit** | 1.14+ | 1.17+ |
| **Python** (только bare-metal) | 3.11 | 3.12 |

### Проверка доступа к GPU

```bash
nvidia-smi
docker run --rm --gpus all nvidia/cuda:12.4-base nvidia-smi
```

Если вторая команда не выполняется, установите NVIDIA Container Toolkit:

```bash
# Ubuntu/Debian
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo systemctl restart docker
```

---

## Требования к инфраструктуре

| Ресурс | Минимум | Рекомендуется (Production) |
|--------|---------|----------------------------|
| **CPU** | 8 ядер | 16+ ядер |
| **RAM** | 32 GB | 64+ GB |
| **GPU VRAM** | 24 GB (квантизованный GGUF) | 48+ GB (полная точность) |
| **Диск** | 100 GB SSD | 500+ GB NVMe |
| **Сеть** | 1 Gbps | 10 Gbps (внутренняя) |

**Распределение диска:**
- Векторы Qdrant: ~30 GB
- Граф Neo4j: ~10 GB
- Файлы моделей: ~20 GB
- Сырые данные + чанки: ~20 GB
- Логи: ~10 GB

---

## Быстрый старт (Docker Compose)

```bash
cd proxy

# 1. Настройка окружения
cp .env.example .env
# Отредактируйте .env с вашими настройками (см. раздел Конфигурация ниже)

# 2. Запуск всех сервисов
docker-compose up -d

# 3. Проверка статуса
docker-compose ps
# Ожидается: qdrant, neo4j, redis, llm, rag-proxy, hitl-dashboard — все "Up"

# 4. Проверка работоспособности
curl http://localhost:8080/v1/health
# {"status":"ok","components":{"qdrant":"ok","llm":"ok"}}

# 5. Список моделей
curl http://localhost:8080/v1/models
```

---

## Конфигурация

Все настройки прокси находятся в `proxy/.env`. Скопируйте пример и отредактируйте:

```bash
cp proxy/.env.example proxy/.env
```

### Обязательные настройки

```ini
# Подключение к Qdrant
QDRANT_HOST=qdrant
QDRANT_PORT=6333
COLLECTION_NAME=knowledge_base

# Эндпоинт LLM (vLLM, llama.cpp или любой OpenAI-совместимый бэкенд)
LLM_ENDPOINT=http://llm:8000/v1
LLM_MODEL_NAME=your-model-name
LLM_API_KEY=           # опционально; должен совпадать с --api-key бэкенда, если установлен

# Модель эмбеддингов
EMBEDDER_MODEL=your-embedding-model
EMBEDDER_DEVICE=cpu    # "cpu" или "cuda"

# Реранкер
RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2
RERANKER_MAX_LENGTH=512
RERANKER_BATCH_SIZE=32

# Сервер
HOST=0.0.0.0
PORT=8080
WORKERS=1              # Держите 1 для безопасности общих эмбеддера/кэша
```

### Опциональные флаги возможностей

```ini
# Агентная оркестрация (LangGraph, 7-узловой граф состояний)
USE_LANGGRAPH=true
MAX_RETRIEVAL_LOOPS=3

# Кэширование Redis
USE_REDIS=true
REDIS_URL=redis://redis:6379

# Графовая база знаний
GRAPH_ENABLED=true
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_secure_password
USE_GRAPH_EXPANSION=true

# Ограничение частоты запросов
RATE_LIMIT_ENABLED=true
RATE_LIMIT_PER_MINUTE=60
RATE_LIMIT_BURST=10

# SLM (малая модель для маршрутизации запросов)
SLM_ENDPOINT=http://llm:8000/v1
SLM_MODEL_NAME=your-slm-model-name
SLM_MAX_TOKENS=256
```

### Наблюдаемость

```ini
# Метрики
METRICS_ENABLED=true

# Логирование
LOG_REQUESTS=true
LOG_DIR=./logs
LOG_FORMAT=json              # "json" для структурированного, "text" для человекочитаемого
SENSITIVE_SECRETS=password,token,key
```

### Настройка

```ini
# RAG-конвейер
MAX_CHUNKS_RETRIEVAL=50      # Чанков для извлечения из Qdrant
MAX_CHUNKS_AFTER_RERANK=20   # Чанков после cross-encoder реранкинга

# Взаимодействие с LLM
REQUEST_TIMEOUT=120          # Таймаут запроса к LLM (секунды)
MAX_RETRIES=3                # Попыток повтора при сбое
RETRY_DELAY=1.0              # Задержка между повторами (секунды)

# CORS
CORS_ORIGINS=*              # Разрешённые источники; используйте конкретные домены в production
```

### Полный справочник конфигурации

См. `proxy/app/config.py` для всех 40+ переменных окружения и их значений по умолчанию.

---

## Архитектура сервисов

`docker-compose.yml` определяет следующие сервисы:

```
┌──────────────────────────────────────────────────┐
│                  Docker Network                    │
│                                                   │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐          │
│  │ qdrant   │  │ redis   │  │ neo4j   │          │
│  │ :6333    │  │ :6379   │  │ :7687   │          │
│  └────┬─────┘  └────┬────┘  └────┬────┘          │
│       │              │            │               │
│       └──────────────┼────────────┘               │
│                      │                            │
│               ┌──────┴──────┐                    │
│               │  rag-proxy  │                    │
│               │    :8080    │                    │
│               └──────┬──────┘                    │
│                      │                            │
│               ┌──────┴──────┐                    │
│               │    llm      │                    │
│               │    :8000    │                    │
│               └─────────────┘                    │
│                                                   │
│  ┌──────────────────┐                            │
│  │ hitl-dashboard   │                            │
│  │    :8501         │                            │
│  └──────────────────┘                            │
└──────────────────────────────────────────────────┘
```

### Детали сервисов

| Сервис | Образ | Порт | GPU | Назначение |
|--------|-------|------|-----|------------|
| **qdrant** | `qdrant/qdrant:latest` | 6333, 6334 | Нет | Векторная БД для гибридного поиска |
| **redis** | `redis:7-alpine` | 6379 | Нет | Многоуровневый кэш (эмбеддинги, реранк, ответы) |
| **neo4j** | `neo4j:5-enterprise` | 7474, 7687 | Нет | Граф знаний для связей сущностей |
| **llm** | Пользовательский или `vllm/vllm-openai:latest` | 8000 | **Да** | Инференс-сервер LLM (ваша модель) |
| **rag-proxy** | Пользовательский (FastAPI) | 8080 | Нет | OpenAI-совместимый API с RAG-конвейером |
| **hitl-dashboard** | Пользовательский (Streamlit) | 8501 | Нет | Панель экспертной проверки и обратной связи |

---

## Graceful Degradation

Прокси спроектирован так, чтобы никогда не падать при отказе компонентов. Каждая зависимость отказывает независимо:

| Компонент недоступен | Поведение |
|---------------------|-----------|
| **Qdrant** | Поиск возвращает пустые результаты; LLM отвечает без контекста |
| **Neo4j** | Расширение графа пропускается; поиск ограничивается только векторами |
| **Redis** | Возврат к in-memory кэшу; без сохранения, ниже процент попаданий |
| **LLM backend** | `/v1/health` возвращает 503; все завершения возвращают 503 |
| **Reranker OOM** | Используются сырые гибридные оценки вместо оценок cross-encoder |

Проверка здоровья (`/v1/health`) сообщает статус деградации с деталями по каждому компоненту.

---

## Безопасность

### Обратный прокси с TLS

Разместите nginx или Caddy перед прокси:

```nginx
# /etc/nginx/sites-available/rag-proxy
server {
    listen 443 ssl http2;
    server_name rag-proxy.internal.company.com;

    ssl_certificate     /etc/ssl/certs/rag-proxy.crt;
    ssl_certificate_key /etc/ssl/private/rag-proxy.key;

    # Опционально: Basic auth
    auth_basic "RAG System";
    auth_basic_user_file /etc/nginx/.htpasswd;

    location /v1/ {
        proxy_pass http://localhost:8080;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;  # Для длительных генераций LLM
        proxy_buffering off;      # Требуется для SSE-потоков
    }

    location /metrics {
        # Только внутренний доступ — запретить внешний
        allow 10.0.0.0/8;
        allow 172.16.0.0/12;
        deny all;
        proxy_pass http://localhost:8080;
    }
}
```

### Чек-лист безопасности для production

- [ ] Смените все пароли по умолчанию (Neo4j, API-ключ Qdrant, если установлен)
- [ ] Установите `LLM_API_KEY` и настройте LLM-бэкенд с `--api-key`
- [ ] Используйте обратный прокси с TLS перед портом 8080
- [ ] Включите файервол: открывайте только 8080 и 8501 для внешнего доступа
- [ ] Установите `LOG_FORMAT=json` для структурированных аудит-логов
- [ ] Настройте `SENSITIVE_SECRETS=password,token,key` для маскирования в логах
- [ ] Ограничьте эндпоинт `/metrics` только внутренними IP
- [ ] Установите `CORS_ORIGINS` на конкретные домены (не `*`)

---

## Автономное (Air-Gapped) развёртывание

### 1. Загрузка моделей

На машине с интернетом:

```bash
cd rag-system

# Загрузите все необходимые модели
python scripts/download_models_offline.py \
  --output-dir ./offline_models \
  --models embedder reranker spacy_ru spacy_en slm \
  --gguf-url https://huggingface.co/your-org/your-model-GGUF/resolve/main/your-model.gguf

# Упаковка
tar -czf offline_models.tar.gz offline_models/
scp offline_models.tar.gz user@airgap-machine:/opt/rag-system/
```

### 2. Перенос Docker-образов

```bash
# На машине с интернетом
docker pull qdrant/qdrant:latest
docker pull neo4j:5-enterprise
docker pull redis:7-alpine
docker pull vllm/vllm-openai:latest  # или ваш образ LLM-бэкенда
docker pull python:3.11-slim

docker save qdrant/qdrant:latest neo4j:5-enterprise redis:7-alpine \
  vllm/vllm-openai:latest python:3.11-slim -o rag-images.tar

scp rag-images.tar user@airgap-machine:/opt/rag-system/

# На автономной машине
docker load -i rag-images.tar
```

### 3. Офлайн pip-пакеты

```bash
# На машине с интернетом
mkdir pip-offline
pip download -r proxy/requirements_proxy.txt -d pip-offline/

tar -czf pip-offline.tar.gz pip-offline/
scp pip-offline.tar.gz user@airgap-machine:/opt/rag-system/
```

### 4. Настройка и запуск

```bash
# На автономной машине
cd /opt/rag-system
tar -xzf offline_models.tar.gz

# Обновите монтирование томов в docker-compose.yml:
#   llm: /opt/rag-system/offline_models:/models:ro
#   rag-proxy: /opt/rag-system/offline_models/cache:/app/cache:ro

# Отредактируйте proxy/.env с вашими настройками
# QDRANT_HOST=qdrant (имя сервиса Docker)
# LLM_ENDPOINT=http://llm:8000/v1

cd proxy
docker-compose up -d
```

---

## Масштабирование

### Вертикальное масштабирование

Увеличьте ресурсы для контейнера LLM:

```yaml
# docker-compose.yml
llm:
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: 2              # Использовать 2 GPU
            capabilities: [gpu]
  command: >
    --model /models/your-model.gguf
    --tensor-parallel-size 2     # Разделить на 2 GPU
    --max-model-len 65536
    --max-num-seqs 16
```

### Горизонтальное масштабирование

```bash
# Масштабирование реплик прокси (требуется Redis для общего состояния)
docker-compose up -d --scale rag-proxy=3

# Разместите балансировщик нагрузки (nginx/HAProxy) перед ними:
#   upstream rag_proxy {
#       server proxy1:8080;
#       server proxy2:8080;
#       server proxy3:8080;
#   }
```

**Примечание:** LLM-бэкенд обрабатывает конкурентность внутренне (до 16 одновременных последовательностей). Прокси может масштабироваться горизонтально, но каждая реплика должна использовать общий Redis для когерентности кэша.

---

## Мониторинг

### Проверки здоровья

```bash
# Здоровье прокси (включает статус зависимостей)
curl http://localhost:8080/v1/health

# Здоровье отдельных сервисов
curl http://localhost:6333/health               # Qdrant
docker exec rag-neo4j cypher-shell -u neo4j -p password "RETURN 1"  # Neo4j
docker exec rag-redis redis-cli PING           # Redis
curl http://localhost:8000/health               # LLM backend
```

### Метрики Prometheus

Собирайте `/metrics` с прокси и всех сервисов. Ключевые алерты:

```yaml
# prometheus-alerts.yml
groups:
  - name: rag-system
    rules:
      - alert: HighErrorRate
        expr: rate(rag_errors_total[5m]) > 0.05
        annotations:
          summary: "RAG error rate >5%"

      - alert: HighLatency
        expr: histogram_quantile(0.95, rate(rag_request_duration_seconds_bucket[5m])) > 30
        annotations:
          summary: "P95 latency >30 seconds"

      - alert: LowCacheHitRate
        expr: rag_cache_hit_ratio < 0.3
        annotations:
          summary: "Cache hit ratio below 30%"

      - alert: LLMDown
        expr: up{job="llm"} == 0
        annotations:
          summary: "LLM backend is down"
```

### Здоровье контейнеров

Все контейнеры включают Docker healthchecks:

```bash
# Просмотр статуса здоровья
docker-compose ps

# Просмотр логов конкретного контейнера
docker-compose logs -f rag-proxy
docker-compose logs -f llm --tail 100
```

---

## Резервное копирование

### Снапшоты Qdrant

```bash
# Создать снапшот
curl -X POST http://localhost:6333/collections/knowledge_base/snapshots

# Список снапшотов
curl http://localhost:6333/collections/knowledge_base/snapshots

# Скачать снапшот
curl http://localhost:6333/collections/knowledge_base/snapshots/<snapshot-name> -o qdrant_snapshot.tar
```

Ежедневные снапшоты через cron:

```cron
0 2 * * * curl -X POST http://localhost:6333/collections/knowledge_base/snapshots
```

### Дампы Neo4j

```bash
docker exec rag-neo4j neo4j-admin database dump neo4j --to-path=/backups/
docker cp rag-neo4j:/backups/neo4j.dump ./neo4j_backup_$(date +%Y%m%d).dump
```

### Резервное копирование конфигурации

```bash
# Резервное копирование критических конфигов
tar -czf rag-config-backup.tar.gz \
  proxy/.env \
  proxy/docker-compose.yml \
  etl/config/etl_config.yaml
```

### Политика хранения

- Хранить 7 ежедневных + 4 еженедельных + 3 ежемесячных резервных копий
- Хранить резервные копии на отдельной машине или сетевом хранилище
- Тестировать процедуру восстановления ежеквартально

---

## Устранение неполадок

### Прокси не запускается

```bash
# Проверьте логи
docker-compose logs rag-proxy

# Частые причины:
# 1. Конфликт портов
ss -tlnp | grep 8080
# Исправление: измените PORT в .env

# 2. Отсутствует файл .env
ls -la proxy/.env
# Исправление: cp proxy/.env.example proxy/.env

# 3. Ошибка конфигурации
docker run --rm -v $(pwd)/.env:/app/.env:ro rag-proxy python -c "from app.config import print_config; print_config()"
```

### LLM-бэкенд не запускается

```bash
# Проверьте доступ к GPU
docker run --rm --gpus all vllm/vllm-openai:latest nvidia-smi

# Проверьте файл модели
ls -la /opt/rag-system/offline_models/your-model.gguf

# Проверьте логи
docker-compose logs llm --tail 50

# Частое решение OOM — уменьшить окно контекста:
# Измените команду llm в docker-compose.yml:
#   --max-model-len 32768  (вместо 130000)
```

### OOM (нехватка памяти)

```bash
# OOM LLM-бэкенда: уменьшить контекст модели, использовать меньшую квантизацию
--max-model-len 32768
--gpu-memory-utilization 0.80

# OOM Neo4j: уменьшить heap
NEO4J_dbms_memory_heap_max__size=1G

# OOM Redis: установить лимит памяти
redis-server --maxmemory 1gb --maxmemory-policy allkeys-lru

# OOM прокси: уменьшить размеры батчей
MAX_CHUNKS_RETRIEVAL=30
RERANKER_BATCH_SIZE=8
```

### Плохие результаты поиска

```bash
# Проверьте модель эмбеддера
grep EMBEDDER_MODEL proxy/.env

# Проверьте схему коллекции (dense + sparse)
curl http://localhost:6333/collections/knowledge_base | python -m json.tool

# Пересоздайте коллекцию с правильной схемой
python scripts/init_collections.py --qdrant-recreate
```

См. полное [Руководство по устранению неполадок](guides/troubleshooting.md) для дополнительных проблем и решений.
