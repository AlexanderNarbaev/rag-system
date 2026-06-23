# Руководство по эксплуатации и обслуживанию

## Мониторинг

### Справочник метрик Prometheus

Прокси предоставляет метрики на `/metrics` в формате OpenMetrics. Ключевые метрики:

| Метрика | Тип | Описание |
|--------|------|----------|
| `rag_requests_total` | Counter | Всего API-запросов по эндпоинтам |
| `rag_request_duration_seconds` | Histogram | Задержка запросов (p50/p95/p99) |
| `rag_retrieval_chunks` | Histogram | Чанков, найденных за запрос |
| `rag_rerank_duration_seconds` | Histogram | Задержка реранкера |
| `rag_llm_duration_seconds` | Histogram | Задержка генерации LLM |
| `rag_llm_tokens_total` | Counter | Использовано токенов (prompt + completion) |
| `rag_cache_hit_ratio` | Gauge | Коэффициент попадания в кэш Redis |
| `rag_errors_total` | Counter | Количество ошибок по типам |

### Ключевые алерты

```yaml
# Правила алертов Prometheus (prometheus-alerts.yml)
groups:
  - name: rag-system
    rules:
      - alert: HighErrorRate
        expr: rate(rag_errors_total[5m]) > 0.05
        annotations:
          summary: "Частота ошибок RAG >5% в 5-минутном окне"

      - alert: HighLatency
        expr: histogram_quantile(0.95, rate(rag_request_duration_seconds_bucket[5m])) > 10
        annotations:
          summary: "Задержка p95 >10s"

      - alert: LLMDown
        expr: rag_llm_duration_seconds == 0 for 2m
        annotations:
          summary: "LLM не отвечает"

      - alert: LowCacheHitRate
        expr: rag_cache_hit_ratio < 0.3
        annotations:
          summary: "Коэффициент попадания в кэш ниже 30%"

      - alert: DiskNearFull
        expr: node_filesystem_avail_bytes{mountpoint="/data"} / node_filesystem_size_bytes < 0.15
        annotations:
          summary: "Диск заполнен, <15% свободно"
```

### Docker Healthchecks

```yaml
# Добавить в сервисы docker-compose.yml:
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8080/v1/health"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 60s
```

## Резервное копирование и восстановление

### Снапшоты Qdrant

```bash
# Создать снапшот:
curl -X POST http://localhost:6333/collections/knowledge_base/snapshots

# Список снапшотов:
curl http://localhost:6333/collections/knowledge_base/snapshots

# Скачать снапшот:
curl http://localhost:6333/collections/knowledge_base/snapshots/<snapshot_name> \
  -o qdrant_backup.snapshot

# Восстановить (на целевом экземпляре Qdrant):
curl -X PUT http://localhost:6333/collections/knowledge_base/snapshots/upload \
  -F "snapshot=@qdrant_backup.snapshot"

# Автоматическое ежедневное резервное копирование через cron:
0 2 * * * curl -X POST http://localhost:6333/collections/knowledge_base/snapshots
```

### Дампы Neo4j

```bash
# Дамп базы данных:
docker exec rag-neo4j neo4j-admin database dump neo4j --to-path=/backups/
docker cp rag-neo4j:/backups/neo4j.dump ./neo4j_backup_$(date +%Y%m%d).dump

# Восстановление:
docker exec rag-neo4j neo4j-admin database load neo4j \
  --from-path=/backups/ --overwrite-destination=true
```

### Резервное копирование WAL

```bash
# Файлы WAL ETL критичны для инкрементальных обновлений:
cp etl/wal/etl_wal.json ./backups/wal_$(date +%Y%m%d_%H%M%S).json
cp etl/wal/version_wal.json ./backups/version_wal_$(date +%Y%m%d_%H%M%S).json

# Восстановление при повреждении WAL: удалить повреждённый WAL и запустить полную переиндексацию
rm etl/wal/etl_wal.json
python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml --full
```

### Политика хранения резервных копий

| Тип | Ежедневно | Еженедельно | Ежемесячно |
|-----|-----------|-------------|------------|
| Снапшот Qdrant | 7 хранить | 4 хранить | 3 хранить |
| Дамп Neo4j | 7 хранить | 4 хранить | 3 хранить |
| Файлы WAL | 14 хранить | — | — |

## Масштабирование

### Горизонтальное масштабирование прокси

```yaml
# docker-compose.yml — добавить реплики и балансировщик нагрузки:
rag-proxy:
  deploy:
    replicas: 3
  environment:
    - WORKERS=2  # uvicorn воркеров на реплику

# Добавить балансировщик nginx:
nginx:
  image: nginx:alpine
  ports:
    - "8080:8080"
  volumes:
    - ./nginx.conf:/etc/nginx/nginx.conf:ro
```

```nginx
# nginx.conf — round-robin между репликами:
upstream rag_backend {
    server rag-proxy-1:8080;
    server rag-proxy-2:8080;
    server rag-proxy-3:8080;
}
server {
    listen 8080;
    location / {
        proxy_pass http://rag_backend;
        proxy_read_timeout 120s;
    }
}
```

### Шардирование Qdrant

```bash
# Создать шардированную коллекцию при инициализации:
curl -X PUT http://localhost:6333/collections/knowledge_base \
  -H 'Content-Type: application/json' \
  -d '{
    "vectors": {"size": 1024, "distance": "Cosine"},
    "shard_number": 3,
    "replication_factor": 2
  }'
```

### Кластеризация Redis

Для масштабирования кэша за пределы одного узла:
```bash
# Запустить Redis в режиме кластера (3 master + 3 replica)
redis-cli --cluster create \
  redis-1:6379 redis-2:6379 redis-3:6379 \
  redis-4:6379 redis-5:6379 redis-6:6379 \
  --cluster-replicas 1
```

## Обновления

### Матрица совместимости версий

| Компонент | Совместимые версии | Путь обновления |
|-----------|-------------------|-----------------|
| Qdrant | 1.7.x → 1.10.x | Последовательный перезапуск |
| Neo4j | 5.x → 5.x | Скрипт миграции базы данных |
| Redis | 6.x → 7.x | Проверка совместимости AOF |
| vLLM | 0.4.x → 0.6.x | Может потребоваться перезагрузка модели |
| Python | 3.11 → 3.12 | Переустановка requirements |

### Шаги миграции

```bash
# 1. Остановить сервисы:
docker-compose down

# 2. Создать резервную копию всего (см. раздел Резервное копирование выше)

# 3. Загрузить новые образы или собрать из обновлённых Dockerfiles:
docker-compose build --no-cache rag-proxy

# 4. Выполнить миграцию коллекции, если схема изменилась:
python scripts/init_collections.py  # с обновлённой схемой

# 5. Запустить с новой версией:
docker-compose up -d

# 6. Проверить:
curl http://localhost:8080/v1/health

# 7. При проблемах — откат:
docker-compose down
docker-compose -f docker-compose.yml.bak up -d
```

## Аварийное восстановление

| Цель | RPO | RTO |
|------|-----|-----|
| Векторы Qdrant | 24 часа | 2 часа |
| Граф Neo4j | 24 часа | 1 час |
| Состояние WAL | 1 час | 30 минут |
| Конфигурация прокси | Немедленно (git) | 15 минут |

### Процедуры восстановления

**Сценарий: Полная потеря данных**
```bash
# 1. Развернуть чистую инфраструктуру:
docker-compose up -d qdrant neo4j redis

# 2. Восстановить последний снапшот Qdrant:
curl -X PUT http://localhost:6333/collections/knowledge_base/snapshots/upload \
  -F "snapshot=@latest_qdrant.snapshot"

# 3. Восстановить дамп Neo4j:
docker cp latest_neo4j.dump rag-neo4j:/backups/
docker exec rag-neo4j neo4j-admin database load neo4j --from-path=/backups/ --overwrite=true

# 4. Восстановить файлы WAL, запустить инкрементальный ETL:
cp backups/latest_wal.json etl/wal/etl_wal.json
python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml --incremental

# 5. Запустить прокси:
docker-compose up -d rag-proxy
curl http://localhost:8080/v1/health
```

**Сценарий: ETL повреждён на середине**
```bash
# Удалить чекпоинт и перезапустить:
rm etl/wal/etl_wal.json
python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml --full
```

## Настройка производительности

### Параметры HNSW (Qdrant)

```json
{
  "hnsw_config": {
    "m": 32,
    "ef_construct": 200,
    "ef": 128
  },
  "optimizers_config": {
    "indexing_threshold": 20000
  }
}
```

### Размер кэша

```ini
# proxy/.env — настройка в зависимости от рабочей нагрузки:
MAX_CHUNKS_RETRIEVAL=50       # уменьшить при ограниченной памяти
MAX_CHUNKS_AFTER_RERANK=10    # меньше чанков = быстрее вызов LLM

# Redis maxmemory (в docker-compose.yml):
redis:
  command: redis-server --appendonly yes --maxmemory 2gb --maxmemory-policy allkeys-lru
```

### Размеры батчей

```yaml
# etl/config/etl_config.yaml:
indexing:
  batch_size: 100     # диапазон 50-200; меньше при OOM, больше для пропускной способности

# proxy/.env:
RERANKER_BATCH_SIZE=16  # диапазон 8-32; меньше снижает пики памяти
```

### Настройка LLM

```yaml
# Команда vLLM в docker-compose.yml:
--max-model-len 65536       # баланс контекста и VRAM
--gpu-memory-utilization 0.90  # оставить запас
--max-num-seqs 16           # конкурентных запросов
```

## Управление логами

### Ротация логов

```yaml
# Конфигурация logrotate (/etc/logrotate.d/rag-system):
/opt/rag-system/proxy/logs/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
}
```

### Docker Log Driver

```yaml
# docker-compose.yml — ограничить логи контейнеров:
services:
  rag-proxy:
    logging:
      driver: "json-file"
      options:
        max-size: "100m"
        max-file: "3"
  vllm:
    logging:
      driver: "json-file"
      options:
        max-size: "200m"
        max-file: "2"
```

### Агрегация логов

```bash
# Отправка в Loki/Grafana через promtail:
# Конфигурация promtail для сбора логов:
scrape_configs:
  - job_name: rag-system
    static_configs:
      - targets: [localhost]
        labels:
          job: rag-proxy
          __path__: /opt/rag-system/proxy/logs/*.log
```

### Политика хранения

| Тип логов | Хранение | Хранилище |
|-----------|----------|-----------|
| Логи запросов прокси | 7 дней | Локальный диск + Loki |
| Логи vLLM | 3 дня | Локально + Loki |
| Логи запусков ETL | 30 дней | Локальный диск |
| Логи обратной связи HITL | 90 дней | База данных |
| Логи Docker-контейнеров | 3 ротации по 100 MB | Локально |
