# Руководство по развёртыванию

**Версия:** v2.0.0 | **Обновлено:** 2026-07-12

Полный справочник по развёртыванию RAG Knowledge Assistant. Охватывает Docker Compose для разработки и односерверного
развёртывания, Kubernetes с Helm для продакшна, автономные среды, настройку LLM-бэкенда, федерацию, модельную эволюцию,
безопасность, мониторинг и резервное копирование.

---

## 1. Предварительные требования

### Аппаратное обеспечение

| Ресурс       | Минимум                     | Рекомендуется (продакшн) |
|--------------|-----------------------------|--------------------------|
| **CPU**      | 8 ядер                      | 16+ ядер                 |
| **RAM**      | 16 ГБ                       | 64+ ГБ                   |
| **GPU VRAM** | 12 ГБ (квантизованный GGUF) | 48+ ГБ (полная точность) |
| **Диск**     | 20 ГБ SSD                   | 500+ ГБ NVMe             |
| **Сеть**     | 1 Гбит/с                    | 10 Гбит/с (внутренняя)   |

**Распределение диска для продакшна:**

| Компонент                                         | Типичный размер |
|---------------------------------------------------|-----------------|
| Векторы Qdrant                                    | ~30 ГБ          |
| Граф Neo4j                                        | ~10 ГБ          |
| Файлы моделей (эмбеддер, реранкер, LLM, SLM)      | ~20 ГБ          |
| Сырые данные + чанки (холодное хранилище Parquet) | ~20 ГБ          |
| Персистентность Redis (RDB + AOF)                 | ~5 ГБ           |
| Логи                                              | ~10 ГБ          |
| **Итого**                                         | **~100 ГБ**     |

### Программное обеспечение

| Компонент                    | Минимум         | Рекомендуется |
|------------------------------|-----------------|---------------|
| **Docker**                   | 24.0+           | 27.0+         |
| **Docker Compose**           | v2.20+ (плагин) | v2.30+        |
| **NVIDIA Driver**            | 535+            | 550+          |
| **NVIDIA Container Toolkit** | 1.14+           | 1.17+         |
| **Python**                   | 3.11            | 3.12          |
| **kubectl** (K8s)            | 1.28+           | 1.30+         |
| **Helm** (K8s)               | 3.14+           | 3.16+         |

### Проверка GPU

```bash
# Проверка драйвера
nvidia-smi

# Проверка доступа Docker к GPU
docker run --rm --gpus all nvidia/cuda:12.4-base nvidia-smi
```

### Проверка портов

RAG-система использует следующие порты — убедитесь, что они свободны:

| Порт       | Сервис                        |
|------------|-------------------------------|
| 6333, 6334 | Qdrant (HTTP, gRPC)           |
| 6379       | Redis                         |
| 7474, 7687 | Neo4j (HTTP, Bolt)            |
| 8000       | LLM-бэкенд (vLLM / llama.cpp) |
| 8080       | RAG Proxy (FastAPI)           |
| 8081       | Federation Proxy              |
| 8082       | MCP Server                    |
| 8501       | HITL Dashboard (Streamlit)    |
| 9000, 9001 | MinIO (S3 API, Консоль)       |
| 5000       | MLflow Tracking Server        |

```bash
# Проверка конфликтов портов
ss -tlnp | grep -E '6333|6379|7687|8000|808[0-2]|8501|900[01]|5000'
```

---

## 2. Быстрое развёртывание с setup.sh

Самый быстрый способ запустить RAG-систему. Интерактивный мастер настройки проверяет зависимости, создаёт конфигурацию,
запускает Docker Compose и проверяет работоспособность.

### 2.1 Минимальные требования

| Требование         | Минимум                |
|--------------------|------------------------|
| **Docker**         | 20.10+                 |
| **Docker Compose** | v2 (плагин)            |
| **RAM**            | 4 ГБ                   |
| **Диск**           | 10 ГБ свободного места |

!!! note
Это абсолютный минимум для CPU-only режима разработки с небольшой моделью. Для продакшн-нагрузок с GPU-инференсом
см. [полные требования](#1-предварительные-требования) (16+ ГБ RAM, 8+ ядер, GPU рекомендуется).

### 2.2 Быстрый старт

```bash
# Клонирование репозитория
git clone https://github.com/AlexanderNarbaev/rag-system.git
cd rag-system

# Запуск интерактивного мастера настройки
./setup.sh
```

Мастер проведёт вас через:

1. **Проверку зависимостей** — проверяет Docker, Docker Compose, Python и доступные порты
2. **Конфигурацию** — создаёт `proxy/.env` из значений по умолчанию, запрашивает LLM-эндпоинт и имя модели
3. **Запуск Docker Compose** — собирает и запускает Qdrant, Redis, Neo4j и RAG-прокси
4. **Инициализацию коллекций** — создаёт коллекции Qdrant с правильной схемой векторов
5. **Проверку работоспособности** — запускает проверки `/v1/health`, `/v1/health/live` и `/v1/health/ready`

### 2.3 Команды setup.sh

```bash
./setup.sh              # Интерактивное меню (по умолчанию)
./setup.sh install      # Чистая установка (неинтерактивная)
./setup.sh configure    # Изменение существующей конфигурации
./setup.sh expand       # Добавление компонентов (Neo4j, Redis, SLM и т.д.)
./setup.sh status       # Показать текущий статус всех сервисов
./setup.sh test         # Запустить тесты и проверки
./setup.sh docker       # Управление контейнерами (старт/стоп/перезапуск)
./setup.sh build        # Собрать Docker-образ прокси
./setup.sh etl          # Запустить ETL-пайплайн
```

### 2.4 Проверка после настройки

```bash
# Проверка состояния прокси
curl http://localhost:8080/v1/health

# Список моделей
curl http://localhost:8080/v1/models

# Тест генерации
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "rag-proxy",
    "messages": [{"role": "user", "content": "Что эта система делает?"}],
    "max_tokens": 50
  }'
```

---

## 3. Быстрое развёртывание Docker Compose (разработка / односервер)

Развёртывание всех сервисов на одной машине для разработки или небольших продакшн-нагрузок.

### 2.1 Клонирование и настройка

```bash
# Клонирование репозитория
git clone https://github.com/AlexanderNarbaev/rag-system.git /opt/rag-system
cd /opt/rag-system

# Создание .env из шаблона
cp .env.example proxy/.env
```

### 2.2 Редактирование proxy/.env

Установите только обязательные переменные; остальные имеют безопасные значения по умолчанию:

```ini
# ── ОБЯЗАТЕЛЬНО ────────────────────────────────────────
QDRANT_HOST=qdrant
QDRANT_PORT=6333
COLLECTION_NAME=knowledge_base

# Модель эмбеддингов
EMBEDDER_MODEL=BAAI/bge-m3
EMBEDDER_DEVICE=cpu

# Модель реранкера
RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2
RERANKER_MAX_LENGTH=512
RERANKER_BATCH_SIZE=32

# LLM-бэкенд — любой OpenAI-совместимый эндпоинт
LLM_ENDPOINT=http://vllm:8000/v1
LLM_MODEL_NAME=your-model-name   # ← УСТАНОВИТЕ
LLM_API_KEY=                     # Только если бэкенд требует
REQUEST_TIMEOUT=120

# SLM — оставьте пустым для отключения (эвристический фолбэк)
SLM_ENDPOINT=
SLM_MODEL_NAME=

# ── ОПЦИОНАЛЬНО (включено по умолчанию в docker-compose) ──
USE_REDIS=true
REDIS_URL=redis://redis:6379
USE_LANGGRAPH=true
MAX_RETRIEVAL_LOOPS=3
GRAPH_ENABLED=true
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=change-this-password   # ← СМЕНИТЕ
USE_GRAPH_EXPANSION=true

# ── ПРОДАКШН ───────────────────────────────────────────
RATE_LIMIT_ENABLED=true
METRICS_ENABLED=true
LOG_FORMAT=json
LOG_LEVEL=INFO
MAX_CONTEXT_TOKENS=8000
RERANK_TOP_K=20
WORKERS=1

# ── AUTH (опционально) ─────────────────────────────────
AUTH_ENABLED=false
JWT_SECRET=       # Генерация: openssl rand -hex 32
RBAC_ENABLED=false
```

### 2.3 Запуск сервисов

```bash
cd proxy

# Запуск всех сервисов (фоновый режим)
docker compose up -d

# Наблюдение за логами запуска
docker compose logs -f --tail=20

# Проверка здоровья всех контейнеров
docker compose ps
# Ожидается: qdrant, neo4j, redis, rag-proxy, minio — все "Up" и "healthy"
```

### 2.4 Инициализация коллекций Qdrant

```bash
# После запуска Qdrant (подождите ~15 сек):
python scripts/init_collections.py --qdrant-recreate

# Проверка коллекции
curl http://localhost:6333/collections/knowledge_base
```

### 2.5 Проверка работоспособности

```bash
# Проверка здоровья прокси
curl http://localhost:8080/v1/health
# → {"status": "healthy", "qdrant": "connected", "llm": "available"}

# Зонды Kubernetes
curl http://localhost:8080/v1/health/live    # Процесс жив → 200
curl http://localhost:8080/v1/health/ready   # Все зависимости готовы → 200

# Список моделей
curl http://localhost:8080/v1/models

# Тест генерации
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "rag-proxy",
    "messages": [{"role": "user", "content": "Что это за система?"}],
    "max_tokens": 50
  }'
```

### 2.6 Первый запуск ETL

```bash
cd /opt/rag-system

# Редактирование конфигурации ETL с учётными данными источников
cp etl/config/etl_config.yaml etl/config/etl_config.local.yaml
# Отредактируйте etl_config.local.yaml — укажите URL и токены Confluence, Jira, GitLab

# Запуск ETL
cd etl
python scheduler/run_etl.py --config config/etl_config.local.yaml

# Или через Docker:
docker build -f Dockerfile.etl -t rag-etl .
docker run --rm --network proxy_rag-network \
  -v "$(pwd)/etl/wal:/wal" \
  -v "$(pwd)/etl/cold_chunks:/chunks" \
  -e QDRANT_HOST=qdrant \
  -e QDRANT_PORT=6333 \
  rag-etl --config /app/config/etl_config.yaml
```

### 2.7 Остановка сервисов

```bash
cd proxy
docker compose down       # Остановка без удаления томов
docker compose down -v    # Остановка С удалением томов (⚠ уничтожает данные)
```

---

## 4. Продакшн Docker

### 4.1 Продакшн Docker Compose

Используйте `docker-compose.standalone.yml` для автономного продакшн-развёртывания с лимитами ресурсов, проверками
здоровья и nginx:

```bash
cd proxy

# Развёртывание с GPU
COMPOSE_PROFILES=gpu docker compose -f docker-compose.standalone.yml up -d

# Развёртывание только на CPU (llama.cpp)
COMPOSE_PROFILES=cpu docker compose -f docker-compose.standalone.yml up -d
```

### 3.2 Лимиты ресурсов

| Сервис      | Лимит CPU | Лимит RAM | Обоснование                         |
|-------------|-----------|-----------|-------------------------------------|
| Qdrant      | 4 ядра    | 4 ГБ      | Обход графа HNSW, индексация sparse |
| Neo4j       | 2 ядра    | 2 ГБ      | Обход графа, кэш страниц            |
| Redis       | 1 ядро    | 2 ГБ      | Кэш ключ-значение, AOF              |
| vLLM бэкенд | 16 ядер   | 48 ГБ     | GPU; CPU для токенизатора           |
| RAG Proxy   | 4 ядра    | 8 ГБ      | Эмбеддер + реранкер в процессе      |
| nginx       | 0.5 ядра  | 256 МБ    | Статический обратный прокси         |

### 3.3 Стратегия томов

```bash
# Создание директорий с правильными правами
mkdir -p /data/{qdrant,neo4j,redis,minio,mlflow}
chown -R 1000:1000 /data/{qdrant,neo4j,redis,minio,mlflow}
chmod 755 /data/{qdrant,neo4j,redis,minio,mlflow}
```

### 3.4 Лимиты логирования Docker

```yaml
services:
  rag-proxy:
    logging:
      driver: "json-file"
      options:
        max-size: "100m"
        max-file: "3"
```

---

## 5. Развёртывание Kubernetes с Helm

### 4.1 Быстрое развёртывание

```bash
# 1. Создание namespace
kubectl create namespace rag-system

# 2. Создание секретов
kubectl create secret generic rag-secrets -n rag-system \
  --from-literal=jwt-secret=$(openssl rand -hex 32) \
  --from-literal=llm-api-key=your-llm-api-key \
  --from-literal=neo4j-password=$(openssl rand -hex 16) \
  --from-literal=minio-access-key=CHANGE_ME \
  --from-literal=minio-secret-key=$(openssl rand -hex 16)

# 3. Установка Helm-чарта
cd infra/helm
helm upgrade --install rag-system ./rag-system \
  -n rag-system \
  -f values.yaml \
  -f values-prod.yaml \
  --set proxy.replicas=3 \
  --set qdrant.persistence.size=100Gi \
  --wait \
  --timeout 10m

# 4. Проверка
kubectl get pods,svc,hpa,ing -n rag-system

# 5. Проверка здоровья
kubectl exec -it deploy/rag-proxy -n rag-system -- curl -s localhost:8080/v1/health
```

### 4.2 Зонды Kubernetes

| Зонд          | Эндпоинт           | Назначение       | Начальная задержка | Период |
|---------------|--------------------|------------------|--------------------|--------|
| **startup**   | `/v1/health/live`  | Загрузка моделей | 0s                 | 5s     |
| **liveness**  | `/v1/health/live`  | Процесс жив      | 30s                | 10s    |
| **readiness** | `/v1/health/ready` | Все зависимости  | 60s                | 15s    |

### 4.3 Zero-Downtime деплой

```bash
# Стандартное rolling-обновление
kubectl set image deployment/rag-proxy rag-proxy=rag-proxy:v2.0.1 -n rag-system

# Мониторинг
kubectl rollout status deployment/rag-proxy -n rag-system

# Откат при необходимости
kubectl rollout undo deployment/rag-proxy -n rag-system
```

---

## 6. Автономное развёртывание

Для сред без доступа в интернет — предварительно загрузите все ресурсы.

### 5.1 Загрузка моделей офлайн

```bash
# На машине с интернетом:
python scripts/download_models_offline.py \
  --output-dir ./offline_models \
  --models embedder reranker spacy_ru spacy_en slm \
  --gguf-url https://huggingface.co/your-org/your-model-GGUF/resolve/main/your-model-Q4_K_M.gguf
```

### 5.2 Перенос ресурсов

```bash
# Упаковка моделей
tar -czf offline_models.tar.gz offline_models/
scp offline_models.tar.gz admin@airgap-host:/opt/rag-system/

# Перенос Docker-образов
docker save qdrant/qdrant:v1.12.1 neo4j:5-community redis:7-alpine \
  python:3.11-slim -o rag-images.tar
scp rag-images.tar admin@airgap-host:/opt/rag-system/

# Перенос pip-пакетов
mkdir pip-offline
pip download -r proxy/requirements_proxy.txt -d pip-offline/
tar -czf pip-offline.tar.gz pip-offline/
scp pip-offline.tar.gz admin@airgap-host:/opt/rag-system/
```

### 5.3 Настройка путей к моделям

```bash
# proxy/.env
MODEL_CACHE_DIR=/opt/rag-system/offline_models
EMBEDDER_MODEL=/opt/rag-system/offline_models/bge-m3
RERANKER_MODEL=/opt/rag-system/offline_models/ms-marco-MiniLM-L-6-v2
```

Для локального SLM (без внешнего API):

```bash
SLM_LOCAL_ENABLED=true
SLM_LOCAL_BINARY=/usr/local/bin/llama-server
SLM_LOCAL_MODEL_PATH=/opt/rag-system/offline_models/slm-model.gguf
SLM_LOCAL_CONTEXT_SIZE=4096
SLM_LOCAL_THREADS=4
SLM_LOCAL_PORT=8081
```

---

## 7. Настройка LLM-бэкенда

Прокси работает с ЛЮБЫМ OpenAI-совместимым эндпоинтом `/v1/chat/completions`.

### 6.1 vLLM

```yaml
vllm:
  image: vllm/vllm-openai:v0.6.4
  volumes:
    - /opt/models:/models:ro
  ports:
    - "8000:8000"
  command: >
    --model /models/Llama-3.1-70B-Instruct
    --port 8000
    --max-model-len 65536
    --gpu-memory-utilization 0.90
    --tensor-parallel-size 2
    --enable-prefix-caching
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: 2
            capabilities: [gpu]
```

### 6.2 llama.cpp (CPU)

```yaml
llama-cpp:
  image: ghcr.io/ggerganov/llama.cpp:server
  volumes:
    - /opt/models:/models:ro
  ports:
    - "8000:8000"
  command: >
    --model /models/llama-3.1-8b-instruct-Q4_K_M.gguf
    --host 0.0.0.0
    --port 8000
    --ctx-size 65536
    --n-gpu-layers 0
    --threads 16
```

### 6.3 Любой OpenAI-совместимый эндпоинт

```bash
# Ollama
LLM_ENDPOINT=http://localhost:11434/v1
LLM_MODEL_NAME=llama3.1:70b
LLM_PROVIDER_TYPE=generic

# OpenAI API
LLM_ENDPOINT=https://api.openai.com/v1
LLM_MODEL_NAME=gpt-4o
LLM_API_KEY=sk-...
```

---

## 8. Настройка мониторинга

### 7.1 Prometheus

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'rag-proxy'
    metrics_path: '/metrics'
    static_configs:
      - targets: ['rag-proxy:8080']
```

### 7.2 Ключевые метрики

| Метрика                        | Тип       | Описание                     |
|--------------------------------|-----------|------------------------------|
| `rag_requests_total`           | Counter   | Всего запросов по эндпоинтам |
| `rag_request_duration_seconds` | Histogram | Латентность (p50/p95/p99)    |
| `rag_cache_hit_ratio`          | Gauge     | Коэффициент попаданий в кэш  |
| `rag_errors_total`             | Counter   | Количество ошибок по типам   |

### 7.3 Алерты

```yaml
groups:
  - name: rag-critical
    rules:
      - alert: RAGProxyDown
        expr: up{job="rag-proxy"} == 0
        for: 1m
        labels:
          severity: critical

      - alert: HighErrorRate
        expr: rate(rag_errors_total[5m]) > 0.05
        for: 5m
        labels:
          severity: critical

      - alert: HighLatency
        expr: histogram_quantile(0.95, rate(rag_request_duration_seconds_bucket[5m])) > 10
        for: 5m
        labels:
          severity: critical
```

---

## 9. Резервное копирование

### 8.1 Расписание

| Компонент       | Частота        | Хранение              | Метод                             |
|-----------------|----------------|-----------------------|-----------------------------------|
| Снапшоты Qdrant | Каждые 6 часов | 7 дн., 4 нед., 3 мес. | `POST /collections/.../snapshots` |
| Дампы Neo4j     | Каждые 6 часов | 7 дн., 4 нед., 3 мес. | `neo4j-admin database dump`       |
| Redis RDB       | Каждый час     | 24 час., 7 дн.        | `redis-cli BGSAVE`                |
| WAL ETL         | Каждые 30 мин  | 7 дн.                 | Копирование файла                 |

### 8.2 Снапшоты Qdrant

```bash
# Создание снапшота
curl -X POST http://localhost:6333/collections/knowledge_base/snapshots

# Список снапшотов
curl http://localhost:6333/collections/knowledge_base/snapshots

# Скачивание
SNAPSHOT_NAME=$(curl -s http://localhost:6333/collections/knowledge_base/snapshots | jq -r '.result[-1].name')
curl "http://localhost:6333/collections/knowledge_base/snapshots/${SNAPSHOT_NAME}" \
  -o qdrant_backup_$(date +%Y%m%d_%H%M).snapshot
```

### 8.3 Дампы Neo4j

```bash
# Создание дампа
docker exec rag-neo4j neo4j-admin database dump neo4j --to-path=/backups/
docker cp rag-neo4j:/backups/neo4j.dump ./neo4j_backup_$(date +%Y%m%d).dump

# Восстановление
docker stop rag-neo4j
docker exec rag-neo4j neo4j-admin database load neo4j \
  --from-path=/backups/ --overwrite-destination=true
docker start rag-neo4j
```

### 8.4 Скрипт резервного копирования

```bash
#!/bin/bash
# scripts/backup.sh
set -euo pipefail

BACKUP_DIR="/tmp/rag-backup-$(date +%Y-%m-%d-%H%M)"
S3_BUCKET="s3://rag-backups"
mkdir -p "$BACKUP_DIR"

# Qdrant
curl -s -X POST "localhost:6333/collections/knowledge_base/snapshots"
sleep 10

# Neo4j
docker exec rag-neo4j neo4j-admin database dump neo4j --to-path=/backups/
docker cp rag-neo4j:/backups/neo4j.dump "$BACKUP_DIR/neo4j.dump"

# Redis
docker exec rag-redis redis-cli BGSAVE
sleep 5
docker cp rag-redis:/data/dump.rdb "$BACKUP_DIR/redis.rdb"

# Загрузка в S3
aws s3 cp "$BACKUP_DIR" "$S3_BUCKET/$(date +%Y-%m-%d-%H%M)/" --recursive
rm -rf "$BACKUP_DIR"
echo "Резервное копирование завершено."
```

---

## 10. Безопасность

### 9.1 Чек-лист безопасности

- [ ] Смените ВСЕ пароли по умолчанию (Neo4j, Redis, MinIO)
- [ ] Установите `LLM_API_KEY` и ограничьте LLM-бэкенд
- [ ] Используйте nginx/Ingress с TLS перед портом 8080
- [ ] Включите файервол: только 80/443 снаружи
- [ ] Откажитесь от всех Linux capabilities в контейнерах
- [ ] Используйте read-only root filesystems
- [ ] Запускайте от non-root (UID 1000)
- [ ] Установите `LOG_FORMAT=json` и `AUDIT_ENABLED=true`
- [ ] Маскируйте секреты в логах через `SENSITIVE_SECRETS`
- [ ] Включите rate limiting (`RATE_LIMIT_ENABLED=true`)
- [ ] Ротируйте логи контейнеров (макс 100 МБ × 3 файла)

### 9.2 Ротация секретов

```bash
# Docker Compose
vim proxy/.env
docker compose restart rag-proxy

# Kubernetes
kubectl create secret generic rag-secrets -n rag-system \
  --from-literal=jwt-secret=$(openssl rand -hex 32) \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl rollout restart deployment/rag-proxy -n rag-system
```

---

## 11. Устранение типовых проблем

### 10.1 Нехватка памяти (OOM)

```bash
# LLM-бэкенд: уменьшить контекст
--max-model-len 32768   # вместо 65536

# Neo4j: уменьшить heap
NEO4J_dbms_memory_heap_max__size=1G

# Прокси: уменьшить лимиты чанков
MAX_CHUNKS_RETRIEVAL=20
RERANKER_BATCH_SIZE=8
```

### 10.2 Конфликты портов

```bash
ss -tlnp | grep -E '6333|6379|7687|8000|8080'
# Переопределите в docker-compose.yml или .env
```

### 10.3 Qdrant недоступен

```bash
docker ps | grep qdrant
curl http://localhost:6333/health
docker exec rag-proxy curl -s http://qdrant:6333/health
# Проверьте QDRANT_HOST=qdrant (не localhost) в .env
```

### 10.4 Модель не найдена

```bash
ls -la /opt/models/model-name/
docker exec rag-vllm ls -la /models/
```

### 10.5 Дисковое пространство

```bash
docker system prune -a --volumes -f
find etl/cold_chunks/ -name "*.parquet" -mtime +30 -delete
find proxy/logs/ -name "*.log" -mtime +7 -delete
```

### 10.6 GPU не обнаружен

```bash
nvidia-container-cli info
docker run --rm --gpus all nvidia/cuda:12.4-base nvidia-smi
```

---

## Связанные документы

| Документ                                                | Описание                                         |
|---------------------------------------------------------|--------------------------------------------------|
| [Справочник конфигурации](configuration-reference.md)   | Все переменные .env и etl_config.yaml            |
| [Руководство по эксплуатации](operations-guide.md)      | Ежедневные операции, мониторинг, масштабирование |
| [Сценарии восстановления](disaster-recovery-runbook.md) | Пошаговые процедуры восстановления               |
| [Устранение проблем](troubleshooting.md)                | Дополнительные типовые проблемы                  |
| [Примеры API](api-examples.md)                          | curl, Python, JavaScript примеры                 |
