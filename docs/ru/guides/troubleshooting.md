# Руководство по устранению неполадок

## Прокси не запускается

### Конфликт портов
```bash
# Симптом: "Address already in use" в логах docker
ss -tlnp | grep 8080

# Исправление: завершите конфликтующий процесс или измените PORT в .env
echo "PORT=8081" >> proxy/.env
# Также обновите маппинг портов в docker-compose.yml
```

### Отсутствующие зависимости
```bash
# Симптом: "ModuleNotFoundError: No module named 'fastapi'"
docker logs rag-proxy

# Исправление: пересоберите образ
docker-compose build --no-cache rag-proxy
docker-compose up -d rag-proxy
```

### Ошибки конфигурации
```bash
# Симптом: прокси запускается и сразу завершается
docker logs rag-proxy

# Частые причины:
# - Файл .env не примонтирован или содержит синтаксические ошибки
# - Неверная строка подключения SQLite/Redis
# Исправление:
docker run --rm -v $(pwd)/.env:/app/.env:ro rag-proxy python -c "from app.config import print_config; print_config()"
```

### Не удаётся подключиться к upstream-сервисам
```bash
# Симптом: "Connection refused" к qdrant/neo4j/redis/llm-backend в логах прокси
# Проверьте, что все сервисы запущены:
docker-compose ps

# Проверьте сетевую связность:
docker exec rag-proxy curl -s http://qdrant:6333/health
docker exec rag-proxy curl -s http://llm-backend:8000/health

# Исправление: убедитесь в правильном порядке depends_on, увеличьте start_period
```

## Ошибки подключения к Qdrant

### Проблемы с хостом/портом
```bash
# Симптом: "Failed to connect to Qdrant" в логах прокси
# Проверьте, что Qdrant запущен и доступен:
curl http://localhost:6333/collections
curl http://qdrant:6333/collections  # изнутри сети docker

# Исправление: проверьте, что QDRANT_HOST и QDRANT_PORT в .env соответствуют имени сервиса docker-compose
```

### Коллекция не найдена
```bash
# Симптом: "Collection 'knowledge_base' not found"
# Проверьте существующие коллекции:
curl http://localhost:6333/collections

# Исправление: инициализируйте коллекцию:
python scripts/init_collections.py
```

### Коллекция уже существует
```bash
# Симптом: "Collection 'knowledge_base' already exists" при инициализации
# Исправление: пересоздайте с новой схемой:
python scripts/init_collections.py --qdrant-recreate
# Внимание: это удаляет все векторные данные
```

### Исчерпание памяти
```bash
# Симптом: Qdrant OOM, "memory allocation failed"
docker logs rag-qdrant

# Исправление: ограничьте память Qdrant, добавьте конфигурацию хранилища:
# В сервисе qdrant в docker-compose.yml:
environment:
  - QDRANT__STORAGE__OPTIMIZERS__INDEXING_THRESHOLD=10000
  - QDRANT__STORAGE__OPTIMIZERS__MEMORY_THRESHOLD=20000
```

## Таймаут LLM

### Увеличение таймаута запроса
```bash
# Симптом: "Read timed out" или 504 от LLM-бэкенда
# Проверьте текущую настройку:
grep REQUEST_TIMEOUT proxy/.env

# Исправление: увеличьте таймаут в .env (секунды):
REQUEST_TIMEOUT=300  # 5 минут для длительных генераций
MAX_RETRIES=2
RETRY_DELAY=2.0

# Перезапустите прокси:
docker-compose restart rag-proxy
```

### Проверка статуса LLM-бэкенда
```bash
# Симптом: LLM возвращает пустые ответы или 500
# Проверьте работоспособность LLM-бэкенда:
curl http://localhost:8000/health

# Проверьте логи бэкенда на OOM или ошибки загрузки модели:
docker logs rag-llm-backend --tail 50

# Частые проблемы LLM-бэкенда:
# - Файл модели не найден: проверьте монтирование тома /models
# - GPU out of memory: уменьшите --max-model-len или используйте меньшую квантизацию
```

### Переключение на альтернативный бэкенд
```bash
# Если один бэкенд недоступен, направьте прокси на альтернативный:
LLM_ENDPOINT=http://localhost:8081/v1
# Запустите альтернативный сервер (например, llama.cpp):
llama-server -m /models/your-model.gguf --port 8081
```

## Плохие результаты поиска

### Проверка модели эмбеддингов
```bash
# Симптом: возвращаются нерелевантные или случайные чанки
# Проверьте, что эмбеддер использует правильную модель:
grep EMBEDDER_MODEL proxy/.env
# Должно быть: EMBEDDER_MODEL=BAAI/bge-m3

# Проверьте, что модель загружена корректно:
python -c "from sentence_transformers import SentenceTransformer; m = SentenceTransformer('BAAI/bge-m3'); print(m.encode('test')[:5])"
# Должен вывести ненулевой вектор
```

### Проверка схемы коллекции
```bash
# Проверьте, что плотные + разреженные векторы настроены:
curl http://localhost:6333/collections/knowledge_base | python -m json.tool
# Ищите: "vectors": {"dense": ..., "sparse": ...}

# Если разреженные векторы отсутствуют, пересоздайте коллекцию:
python scripts/init_collections.py --qdrant-recreate
# Затем перезапустите ETL для переиндексации
```

### Настройка параметров HNSW
```bash
# Обновите конфигурацию коллекции для лучшей полноты:
curl -X PATCH http://localhost:6333/collections/knowledge_base \
  -H 'Content-Type: application/json' \
  -d '{"hnsw_config": {"m": 32, "ef_construct": 200}, "optimizers_config": {"indexing_threshold": 10000}}'
```

## Высокое потребление памяти

### Лимиты кэша
```bash
# Симптом: память прокси растёт со временем
# Проверьте память Redis:
docker exec rag-redis redis-cli INFO memory | grep used_memory_human

# Исправление: ограничьте память Redis в docker-compose.yml:
redis:
  command: redis-server --appendonly yes --maxmemory 1gb --maxmemory-policy allkeys-lru
```

### Выгрузка моделей
```bash
# Симптом: GPU OOM при эмбеддинге
# Переведите эмбеддер на CPU и уменьшите батч реранкера:
EMBEDDER_DEVICE=cpu
RERANKER_BATCH_SIZE=8

# Для LLM-бэкенда уменьшите использование памяти:
--max-model-len 32768          # короче окно контекста
--gpu-memory-utilization 0.80  # оставить 20% запаса для других процессов
```

### Уменьшение размера батча
```bash
# Симптом: OOM при пакетном индексировании
# В etl/config/etl_config.yaml:
indexing:
  batch_size: 50   # уменьшить со 100

# Также уменьшите количество поиска:
MAX_CHUNKS_RETRIEVAL=30
MAX_CHUNKS_AFTER_RERANK=10
```

## Сбои ETL

### Восстановление при повреждении WAL
```bash
# Симптом: "WAL file corrupted" или ETL зависает при запуске
# Проверьте целостность WAL:
python -c "import json; json.load(open('etl/wal/etl_wal.json'))"

# Если повреждён, удалите WAL и запустите полную переиндексацию:
rm etl/wal/etl_wal.json
python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml --full
```

### Ограничения скорости API
```bash
# Симптом: "429 Too Many Requests" от Confluence/Jira/GitLab
# Исправление: добавьте задержки между вызовами API. Настройте в etl_config.yaml для каждого источника.
# Или установите переменную окружения:
ETL_RATE_LIMIT_DELAY=1.0  # секунд между запросами

# Для GitLab уменьшите max_commits:
gitlab:
  max_commits_per_project: 100  # было 1000
```

### Частичная переиндексация
```bash
# Симптом: некоторые документы отсутствуют в результатах поиска после частичного сбоя ETL
# Проверьте WAL на завершённые источники:
python -c "
import json
wal = json.load(open('etl/wal/etl_wal.json'))
print('Completed sources:', wal.get('completed_sources', []))
print('Last successful run:', wal.get('last_successful_run'))
"

# Переиндексируйте только отказавшие источники:
python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml \
  --sources confluence,jira  # пропустить завершённые источники
```

### Переполнение диска при индексации
```bash
# Симптом: "No space left on device" во время ETL
# Проверьте использование диска:
df -h etl/chunks/ etl/hot_chunks/ etl/cold_chunks/

# Очистите холодное хранилище старше 30 дней:
find etl/cold_chunks/ -name "*.parquet" -mtime +30 -delete

# Переместите cold lake на отдельный том:
mkdir -p /mnt/cold_storage/rag_lake
ln -s /mnt/cold_storage/rag_lake etl/cold_lake
```

## Ошибки Neo4j

### Повтор подключения
```bash
# Симптом: "Unable to connect to Neo4j" или "ServiceUnavailable"
# Проверьте, что Neo4j запущен:
docker exec rag-neo4j cypher-shell -u neo4j -p password "RETURN 1"

# Если соединение отклонено, увеличьте retry в конфигурации:
# proxy/.env:
NEO4J_MAX_RETRY_TIME=60  # секунд

# Или в конфигурации ETL (etl/config/etl_config.yaml):
graph:
  neo4j:
    max_connection_lifetime: 3600
    connection_acquisition_timeout: 60
```

### Нарушения ограничений
```bash
# Симптом: "ConstraintViolation: node with property X already exists"
# Это проблема дедупликации — проверьте, ожидаемы ли дубликаты:
MATCH (n:Entity {name: 'duplicate_name'}) RETURN count(n)

# Если безопасно продолжить, используйте MERGE вместо CREATE в загрузчике.
# Иначе удалите и пересоздайте ограничения:
DROP CONSTRAINT entity_name_unique IF EXISTS;
CREATE CONSTRAINT entity_name_unique FOR (n:Entity) REQUIRE n.name IS UNIQUE;
```

### Нехватка памяти
```bash
# Симптом: Neo4j падает с "java.lang.OutOfMemoryError"
# Проверьте текущий heap:
docker exec rag-neo4j cypher-shell -u neo4j -p password \
  "CALL dbms.listConfig() YIELD name, value WHERE name CONTAINS 'memory' RETURN name, value"

# Увеличьте heap в docker-compose.yml:
NEO4J_dbms_memory_heap_initial__size=2G
NEO4J_dbms_memory_heap_max__size=4G
NEO4J_dbms_memory_pagecache_size=2G

# Перезапустите:
docker-compose restart neo4j
```

### Сбои загрузки графа
```bash
# Симптом: шаг построения графа ETL падает с deadlock
# Запустите построение графа с уменьшенной конкурентностью:
# В etl/config/etl_config.yaml:
graph:
  batch_size: 50         # меньшие батчи
  max_concurrency: 1     # однопоточно

# Или временно отключите граф и запустите только индексацию:
graph:
  enabled: false
```

---

## Проблемы потокового ETL (Redis Streams)

### Сбои подключения к Redis Stream

```bash
# Симптом: "Failed to connect to Redis Streams" или вебхук возвращает 503
# Проверьте, что Redis запущен и потоки настроены:
docker exec rag-redis redis-cli PING
docker exec rag-redis redis-cli XINFO STREAM etl:events

# Если поток не существует, создайте его:
docker exec rag-redis redis-cli XADD etl:events * event test

# Проверьте существование групп потребителей:
docker exec rag-redis redis-cli XINFO GROUPS etl:events

# Пересоздайте группы потребителей при отсутствии:
docker exec rag-redis redis-cli XGROUP CREATE etl:events etl-extract $ MKSTREAM
docker exec rag-redis redis-cli XGROUP CREATE etl:events etl-chunk $
docker exec rag-redis redis-cli XGROUP CREATE etl:events etl-embed $
docker exec rag-redis redis-cli XGROUP CREATE etl:events etl-index $
```

### Рост Consumer Lag

```bash
# Симптом: События поставлены в очередь, но не обрабатываются, lag растёт
# Проверьте ожидающие сообщения по потребителям:
docker exec rag-redis redis-cli XPENDING etl:events etl-extract
docker exec rag-redis redis-cli XPENDING etl:events etl-chunk

# Проверьте время простоя потребителя:
docker exec rag-redis redis-cli XINFO CONSUMERS etl:events etl-extract

# Исправление: перезапустите зависшего потребителя:
docker-compose restart rag-etl-extract

# Если события зависли навсегда (3+ неудачных попытки), переместите в DLQ:
docker exec rag-redis redis-cli XCLAIM etl:events etl-extract new-consumer 3600000 <message-id>
```

---

## Проблемы с Redis

### Redis недоступен для потокового ETL

```bash
# Симптом: "Redis connection refused" в логах ETL
# Проверьте статус Redis:
docker exec rag-redis redis-cli PING

# Проверьте переменные окружения:
grep REDIS_STREAMS_URL proxy/.env
# Должно совпадать: redis://redis:6379
```

---

## Сбои проверки вебхуков

### Неверная подпись (Confluence)

```bash
# Симптом: Вебхук Confluence возвращает 401 "Invalid signature"
# Проверьте совпадение WEBHOOK_SECRET на обеих сторонах:
echo $WEBHOOK_SECRET

# Тест генерации подписи:
echo -n '{"event":"test"}' | openssl dgst -sha256 -hmac "$WEBHOOK_SECRET"

# Тест эндпоинта с вычисленной подписью:
SIG=$(echo -n '{"event":"test"}' | openssl dgst -sha256 -hmac "$WEBHOOK_SECRET" | cut -d' ' -f2)
curl -X POST http://localhost:8080/webhook/confluence \
  -H "Content-Type: application/json" \
  -H "X-Confluence-Webhook-Signature: sha256=$SIG" \
  -d '{"event":"test"}'
# Ожидается: 200 с {"status":"accepted"}
```

---

## Проблемы прогрева моделей

### Таймаут прогрева

```bash
# Симптом: POST /v1/admin/warmup зависает или возвращает таймаут
# Проверьте статус компонентов:
curl -s http://localhost:8080/v1/health | jq '.components'

# Типичные причины:
# - Модель эмбеддера всё ещё загружается
# - SLM-эндпоинт недоступен
# - Память GPU исчерпана

# Исправление: пропустите проблемный компонент и повторите:
# Если SLM недоступен: временно отключите SLM (SLM_ENDPOINT="")
# Увеличьте таймаут в .env:
WARMUP_TIMEOUT=120  # секунд (по умолчанию: 60)

# Проверьте логи прогрева:
docker logs rag-proxy --tail 50 | grep warmup
```

---

## Проблемы, связанные со сжатием

### Клиент не может распаковать ответ

```bash
# Симптом: Клиент получает искажённый/бинарный ответ
# Проверьте, отправил ли клиент заголовок Accept-Encoding:
curl -v http://localhost:8080/v1/health 2>&1 | grep -i "Accept-Encoding"

# Если клиент не поддерживает сжатие, отключите его на сервере:
COMPRESSION_ENABLED=false

# Или явно откажитесь от сжатия на клиенте:
curl -H "Accept-Encoding: identity" http://localhost:8080/v1/health
```

### Регрессия производительности сжатия

```bash
# Симптом: Высокая загрузка CPU после включения сжатия
# Проверьте уровень сжатия:
grep COMPRESSION_LEVEL proxy/.env

# Снизьте уровень для меньшей нагрузки CPU:
COMPRESSION_LEVEL=1  # Быстрее, ~58% снижение
```
