# Руководство по устранению неполадок

**Версия:** v2.0 | **Обновлено:** 2026-07-12

Полный справочник по устранению неполадок RAG Knowledge Assistant. Охватывает запуск, запросы, поиск, LLM, эмбеддинги, аутентификацию, кэш, граф, производительность, развёртывание, федерацию и эволюцию моделей.

---

## Быстрые диагностические команды

Выполните эти команды первыми при возникновении проблем:

```bash
# Проверка состояния прокси (все компоненты)
curl -s http://localhost:8080/v1/health | python3 -m json.tool

# Пробы liveness / readiness (совместимо с K8s)
curl -s http://localhost:8080/v1/health/live
curl -s http://localhost:8080/v1/health/ready

# Статус всех контейнеров
docker-compose -f proxy/docker-compose.yml ps

# Последние логи всех сервисов
docker-compose -f proxy/docker-compose.yml logs --tail=100

# Метрики Prometheus
curl -s http://localhost:8080/metrics | grep -E 'rag_requests_total|circuit_breaker_state|rag_cache_hits_total'

# Проверка PID на порту прокси
ss -tlnp | grep 8080
```

---

## 1. Проблемы запуска

### 1.1 Прокси не запускается — порт уже занят

**Симптом:**
```
OSError: [Errno 98] Address already in use
ERROR:    [Errno 98] error while attempting to bind on address ('0.0.0.0', 8080)
```
```
docker logs rag-proxy | grep -i "address already in use"
```

**Причина:** Другой процесс уже использует порт 8080.

**Решение:**
```bash
# Найдите конфликтующий процесс
ss -tlnp | grep 8080
# или
lsof -i :8080

# Вариант 1: завершите процесс
kill -9 <PID>

# Вариант 2: измените порт прокси
echo "PORT=8081" >> proxy/.env
# Также обновите маппинг портов в docker-compose.yml:
#   ports:
#     - "8081:8080"   # хост:контейнер

# Вариант 3: измените только порт хоста (контейнер остаётся на 8080):
#   ports:
#     - "8081:8080"
docker-compose -f proxy/docker-compose.yml up -d rag-proxy
```

### 1.2 Qdrant — отказ в подключении

**Симптом:**
```
qdrant_client.http.exceptions.ResponseHandlingException: Failed to connect
ConnectionRefusedError: [Errno 111] Connection refused
```
Проверка здоровья прокси: `"qdrant": "unhealthy"`.

**Причина:** Qdrant не запущен, недоступен по настроенному хосту/порту, или `.env` прокси не соответствует имени сервиса Docker.

**Решение:**
```bash
# 1. Убедитесь, что Qdrant запущен
docker ps | grep qdrant
docker logs rag-qdrant --tail 20

# 2. Проверьте доступность с хоста
curl http://localhost:6333/health
curl http://localhost:6333/collections

# 3. Проверьте доступность изнутри контейнера прокси
docker exec rag-proxy curl -s http://qdrant:6333/health

# 4. Убедитесь, что .env соответствует имени сервиса docker-compose
grep QDRANT_HOST proxy/.env
# Должно быть: QDRANT_HOST=qdrant   (имя сервиса docker-compose)

# 5. Подождите завершения загрузки Qdrant (большие сегменты)
docker-compose -f proxy/docker-compose.yml restart qdrant
sleep 10
docker exec rag-proxy curl -s http://qdrant:6333/health
```

### 1.3 Файл модели не найден (LLM-бэкенд)

**Симптом:**
```
vLLM error: model '/models/model.gguf' not found
OSError: [Errno 2] No such file or directory: '/models/model.gguf'
```
`docker logs rag-vllm | tail -20`

**Причина:** Неверный путь к файлу модели, неправильный монтирование тома или модель не загружена.

**Решение:**
```bash
# 1. Проверьте содержимое монтированного тома
docker exec rag-vllm ls -la /models/

# 2. Проверьте MODEL_PATH и MODEL_FILE в .env
grep MODEL_PATH proxy/.env
grep MODEL_FILE proxy/.env

# 3. Загрузите модель (для автономной среды: предварительно загрузите на хосте)
python scripts/download_models_offline.py

# 4. Исправьте монтирование тома в docker-compose.yml
#    - ${MODEL_PATH:-/path/to/models}:/models:ro
#    Левая часть — путь на хосте, должен существовать и содержать модель.
ls -la /path/to/models/

# 5. Для llama.cpp (без GPU), используйте llama-server напрямую:
#    llama-server -m /models/your-model.gguf --port 8000
```

### 1.4 Отказано в доступе — кэш моделей / логи

**Симптом:**
```
PermissionError: [Errno 13] Permission denied: '/app/cache'
PermissionError: [Errno 13] Permission denied: '/app/logs'
```

**Причина:** Пользователь контейнера (UID 1000 по умолчанию) не может записывать в смонтированные директории хоста.

**Решение:**
```bash
# Исправьте права на стороне хоста
sudo chown -R 1000:1000 /path/to/model_cache
sudo chown -R 1000:1000 proxy/logs/

# Или используйте широкие права (менее безопасно, только для разработки)
sudo chmod -R 777 /path/to/model_cache

# Проверьте исправление
docker exec rag-proxy touch /app/logs/test && docker exec rag-proxy rm /app/logs/test
```

### 1.5 Отсутствующие зависимости / ModuleNotFoundError

**Симптом:**
```
ModuleNotFoundError: No module named 'fastapi'
ModuleNotFoundError: No module named 'langgraph'
ModuleNotFoundError: No module named 'qdrant_client'
```

**Причина:** Образ Docker не был пересобран после изменения требований, или `requirements_proxy.txt` устарел.

**Решение:**
```bash
# Пересоберите образ с нуля
docker-compose -f proxy/docker-compose.yml build --no-cache rag-proxy

# При использовании локального venv (не Docker):
pip install -r proxy/requirements_proxy.txt

# Проверьте установленные пакеты в контейнере
docker exec rag-proxy pip list | grep -E 'fastapi|qdrant|langgraph'
```

### 1.6 Ошибки конфигурации — прокси сразу завершается

**Симптом:** Контейнер запускается и завершается менее чем за 5 секунд с кодом выхода 1.
```
docker logs rag-proxy
# KeyError / ValueError при разборе конфигурации
```

**Причина:** Файл `.env` содержит синтаксические ошибки, отсутствуют обязательные переменные или файл не примонтирован.

**Решение:**
```bash
# 1. Выведите конфигурацию (безопасно, секреты замаскированы)
docker run --rm -v $(pwd)/proxy/.env:/app/.env:ro rag-proxy \
  python -c "from app.config import print_config; print_config()"

# 2. Проверьте типичные ошибки .env:
#    - Пробелы вокруг '=' (VAR = value  →  VAR=value)
#    - Отсутствие кавычек для значений со спецсимволами
#    - Комментарии в конце строки работают не у всех парсеров

# 3. Проверьте синтаксис .env
python3 -c "
import os
from dotenv import load_dotenv
load_dotenv('proxy/.env')
print('OK: .env загружен успешно')
"

# 4. Проверьте обязательные переменные
grep -E '^(LLM_ENDPOINT|LLM_MODEL_NAME|EMBEDDER_MODEL)' proxy/.env
```

### 1.7 Ошибка инициализации базы данных (SQLite)

**Симптом:**
```
sqlite3.OperationalError: unable to open database file
sqlite3.OperationalError: database is locked
```

**Причина:** Директория SQLite не существует, нет прав на запись или другой процесс удерживает эксклюзивную блокировку.

**Решение:**
```bash
# 1. Убедитесь, что директория данных существует и доступна для записи
mkdir -p proxy/data
chmod 755 proxy/data

# 2. Проверьте USER_DB_PATH в .env
grep USER_DB_PATH proxy/.env
# По умолчанию: USER_DB_PATH=./data/users.db

# 3. При ошибке "database is locked" проверьте устаревшие файлы блокировок
ls -la proxy/data/users.db*
# Удалите устаревший журнал, если БД не используется
rm -f proxy/data/users.db-journal proxy/data/users.db-wal proxy/data/users.db-shm

# 4. Сбросьте БД пользователей (удаляет всех пользователей, только для разработки)
rm proxy/data/users.db
docker-compose -f proxy/docker-compose.yml restart rag-proxy
```

---

## 2. Проблемы запросов

### 2.1 Пустые результаты / чанки не найдены

**Симптом:**
```json
{"choices":[{"message":{"content":"У меня недостаточно информации для ответа на этот вопрос."}}]}
```
Ответ прокси содержит `rag_confidence: 0` или `rag_sources: []`.

**Причина:** Нет подходящих чанков в Qdrant. Коллекции могут быть пустыми, эмбеддинги не соответствуют запросу или условия фильтрации слишком строгие.

**Решение:**
```bash
# 1. Проверьте, есть ли векторы в коллекции
curl -s http://localhost:6333/collections/knowledge_base | python3 -c "
import sys, json
data = json.load(sys.stdin)
result = data.get('result', data)
print(f\"Векторы: {result.get('vectors_count', 'Н/Д')}\")
print(f\"Сегменты: {result.get('segments_count', 'Н/Д')}\")
"

# 2. Выполните точный поиск для проверки данных
curl -X POST http://localhost:6333/collections/knowledge_base/points/scroll \
  -H 'Content-Type: application/json' \
  -d '{"limit": 5, "with_payload": true}' | python3 -m json.tool | head -40

# 3. Проверьте, индексировал ли ETL какие-либо документы
python3 -c "
import json
with open('etl/wal/etl_wal.json') as f:
    wal = json.load(f)
    print('Завершённые источники:', wal.get('completed_sources', []))
    print('Всего чанков проиндексировано:', wal.get('total_chunks', 'Н/Д'))
"

# 4. Запустите ETL, если коллекции пусты
python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml

# 5. Попробуйте без фильтра версий
curl -X POST http://localhost:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"rag-proxy","messages":[{"role":"user","content":"тестовый запрос"}],"max_tokens":200}'
```

### 2.2 Медленные ответы (> 5 секунд)

**Симптом:** p95 латентность превышает SLO в 5 секунд. Гистограмма `rag_request_duration_seconds` показывает высокие значения.

**Причина:** Перегрузка LLM-бэкенда, узкое место дискового ввода-вывода Qdrant, обработка слишком большого количества чанков реранкером или эмбеддинги на CPU.

**Решение:**
```bash
# 1. Проверьте распределение латентности по метрикам
curl -s http://localhost:8080/metrics | grep -E 'rag_request_duration_seconds|rag_phase'

# 2. Определите узкое место (эмбеддинги vs поиск vs LLM)
#    Проверьте логи на наличие времени выполнения:
docker logs rag-proxy --tail 100 | grep -E 'duration|elapsed|timeout'

# 3. Уменьшите количество чанков для поиска
# В proxy/.env:
MAX_CHUNKS_RETRIEVAL=20    # было 50
MAX_CHUNKS_AFTER_RERANK=5  # было 20

# 4. Переместите эмбеддер на GPU (при наличии)
EMBEDDER_DEVICE=cuda
RERANKER_BATCH_SIZE=8      # уменьшите при OOM

# 5. Используйте SLM для быстрого пути (намерения, декомпозиция)
SLM_ENDPOINT=http://vllm:8000/v1
SLM_MODEL_NAME=your-slm-model

# 6. Проверьте статус оптимизации Qdrant
curl -s http://localhost:6333/collections/knowledge_base | python3 -c "
import sys, json
data = json.load(sys.stdin).get('result', {})
print('Сегменты:', data.get('segments_count'))
print('Проиндексировано векторов:', data.get('indexed_vectors_count', 'Н/Д'))
"

# 7. Принудительная оптимизация сегментов при большом количестве неиндексированных
curl -X POST http://localhost:6333/collections/knowledge_base/optimizers \
  -H 'Content-Type: application/json' \
  -d '{"indexing_threshold": 10000}'
```

### 2.3 Ошибки таймаута (504 / Read Timed Out)

**Симптом:**
```
aiohttp.client_exceptions.ServerTimeoutError
asyncio.TimeoutError
Read timed out
```
Прокси возвращает `{"error": "LLM request failed after 3 attempts: ..."}`.

**Причина:** LLM-бэкенд слишком долго генерирует ответ, `REQUEST_TIMEOUT` слишком короткий или бэкенд перегружен.

**Решение:**
```bash
# 1. Увеличьте таймаут в proxy/.env
REQUEST_TIMEOUT=300   # 5 минут (было 120)
MAX_RETRIES=2

# 2. Проверьте глубину очереди LLM-бэкенда / количество одновременных запросов
docker logs rag-vllm --tail 30 | grep -E 'queue|waiting|pending'

# 3. Уменьшите max_tokens на стороне прокси
curl -X POST http://localhost:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"rag-proxy","messages":[{"role":"user","content":"тест"}],"max_tokens":500}'

# 4. Проверьте здоровье бэкенда напрямую
curl -s http://localhost:8000/health

# 5. Для vLLM уменьшите длину контекста
#    В docker-compose.yml, команда vllm:
#    --max-model-len 32768   (вместо 65536)

# 6. Для llama.cpp проверьте, полностью ли загружена модель:
docker logs rag-vllm | grep -i 'model loaded'
```

### 2.4 Потоковая передача зависает на середине ответа

**Симптом:** SSE-поток останавливается на середине, клиент ожидает бесконечно. `curl -N` зависает.

**Причина:** LLM-бэкенд упал во время генерации, переполнение сетевого буфера или соединение прокси закрылось до завершения потока.

**Решение:**
```bash
# 1. Проверьте LLM-бэкенд на OOM / краш во время генерации
docker logs rag-vllm --tail 50 | grep -iE 'error|killed|oom|segfault'

# 2. Тестируйте потоковую передачу напрямую к бэкенду
curl -N -X POST http://localhost:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"your-model","messages":[{"role":"user","content":"Привет"}],"stream":true,"max_tokens":100}'

# 3. Проверьте конфигурацию SSE прокси
grep -E 'SSE_CHUNK_SIZE|STREAM_BUFFER_SIZE' proxy/.env
# По умолчанию: SSE_CHUNK_SIZE=4, STREAM_BUFFER_SIZE=1
# Увеличьте буфер при ненадёжной сети:
STREAM_BUFFER_SIZE=4

# 4. Проверьте события GPU OOM
nvidia-smi
dmesg | grep -i 'out of memory'

# 5. Перезапустите LLM-бэкенд
docker-compose -f proxy/docker-compose.yml restart vllm
```

### 2.5 Внутренняя ошибка сервера 500

**Симптом:**
```
HTTP 500 Internal Server Error
{"detail": "Internal server error"}
```

**Причина:** Необработанное исключение в коде прокси — часто отсутствующая зависимость, проблема конфигурации или сбой внешнего сервиса.

**Решение:**
```bash
# 1. Получите полный traceback из логов прокси
docker logs rag-proxy --tail 100 | grep -A 20 'Traceback'

# 2. Проверьте частые причины ошибок 500:
#    - Автоматический выключатель (circuit breaker) открыт на зависимости
curl -s http://localhost:8080/metrics | grep circuit_breaker_state
#    Состояние: 0=закрыт, 1=открыт, 2=полуоткрыт

# 3. Проверьте здоровье всех компонентов
curl -s http://localhost:8080/v1/health | python3 -m json.tool

# 4. Сбросьте автоматические выключатели (после устранения основной проблемы)
curl -X POST http://localhost:8080/v1/admin/reset-circuit-breakers

# 5. Проверьте незаданные обязательные параметры конфигурации
docker exec rag-proxy python3 -c "
from app.config import *
required = ['LLM_ENDPOINT','LLM_MODEL_NAME','EMBEDDER_MODEL']
for v in required:
    val = globals().get(v)
    if not val:
        print(f'ОТСУТСТВУЕТ: {v}')
"
```

### 2.6 Превышен лимит запросов (429)

**Симптом:**
```
HTTP 429 Too Many Requests
{"error": "Rate limit exceeded"}
Retry-After: 5
```

**Причина:** Клиент отправляет запросы быстрее, чем允许ет `RATE_LIMIT_PER_MINUTE`.

**Решение:**
```bash
# 1. Увеличьте лимиты в .env
RATE_LIMIT_ENABLED=true
RATE_LIMIT_PER_MINUTE=120   # было 60
RATE_LIMIT_BURST=20         # было 10

# 2. Проверьте, кто получает ограничение
docker logs rag-proxy | grep -i 'rate limit'

# 3. Отключите ограничение скорости (только для разработки)
RATE_LIMIT_ENABLED=false

# 4. Или добавьте IP клиента в белый список (требует изменения кода)
#    См. app/rate_limiter.py — измените _extract_key() для пропуска определённых IP
```

---

## 3. Проблемы поиска

### 3.1 Чанки не найдены, несмотря на наличие данных

**Симптом:** `hybrid_search` возвращает `[]`, но `scroll` показывает наличие векторов.

**Причина:** Несоответствие фильтра версий, изоляция пространства имён фильтрует результаты или RRF-слияние отбрасывает все результаты.

**Решение:**
```bash
# 1. Проверьте, является ли фильтр версий причиной — поиск без него
curl -X POST http://localhost:6333/collections/knowledge_base/points/search \
  -H 'Content-Type: application/json' \
  -d '{"vector": {"name": "dense", "vector": [0.1, 0.2, ...]}, "limit": 5, "with_payload": true}'

# 2. Проверьте фильтрацию пространства имён
grep NAMESPACE_ISOLATION_ENABLED proxy/.env
# Если включено, убедитесь, что пространство имён пользователя соответствует пространству имён документа

# 3. Проверьте поддержку разреженных векторов — поиск только по разреженным
# Проверьте, настроены ли разреженные векторы в коллекции:
curl -s http://localhost:6333/collections/knowledge_base | \
  python3 -c "import sys,json; d=json.load(sys.stdin).get('result',{}); print('Sparse config:', d.get('config',{}).get('params',{}).get('sparse_vectors'))"

# 4. Попробуйте явный поиск только по плотным векторам (пропустите RRF)
#    В коде передайте sparse_vec=None
```

### 3.2 Низкие оценки релевантности

**Симптом:** Чанки возвращаются, но оценки RRF < 0.01, оценки реранкера < -5.

**Причина:** Неправильная модель эмбеддингов, несоответствие языка запроса и документа, несоответствие размерности эмбеддингов или устаревший индекс.

**Решение:**
```bash
# 1. Убедитесь, что модель эмбеддера соответствует созданию коллекции
grep EMBEDDER_MODEL proxy/.env
# Должна быть та же модель, что использовалась при создании коллекции
# например, BAAI/bge-m3 (1024-мерные dense + sparse)

# 2. Проверьте размерность эмбеддингов
python3 -c "
from sentence_transformers import SentenceTransformer
m = SentenceTransformer('BAAI/bge-m3')
v = m.encode('test')
print(f'Размерность: {len(v)}')  # Должна быть 1024 для bge-m3
"

# 3. Проверьте соответствие языка документа языку запроса
#    bge-m3 нативно поддерживает межъязыковой поиск, но проверьте CROSS_LINGUAL_ENABLED:
grep CROSS_LINGUAL_ENABLED proxy/.env

# 4. Настройте параметры HNSW для лучшей полноты
curl -X PATCH http://localhost:6333/collections/knowledge_base \
  -H 'Content-Type: application/json' \
  -d '{
    "hnsw_config": {"m": 32, "ef_construct": 200},
    "optimizers_config": {"indexing_threshold": 10000}
  }'

# 5. Увеличьте EF поиска для лучшей полноты (медленнее)
curl -X POST http://localhost:6333/collections/knowledge_base/points/search \
  -H 'Content-Type: application/json' \
  -d '{"vector": [0.1,...], "limit": 50, "params": {"hnsw_ef": 256}}'

# 6. Перезапустите ETL с правильной моделью эмбеддингов
python scripts/init_collections.py --qdrant-recreate
python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml --full
```

### 3.3 Возвращаются неправильные документы

**Симптом:** Поиск возвращает документы из неправильных проектов, команд или периодов времени.

**Причина:** Неправильные или отсутствующие условия фильтрации, не настроена изоляция пространства имён или фильтр RBAC слишком свободный.

**Решение:**
```bash
# 1. Проверьте RBAC и изоляцию пространства имён
grep -E 'RBAC_ENABLED|NAMESPACE_ISOLATION_ENABLED|AUTH_ENABLED' proxy/.env

# 2. Проверьте контекст пользователя (какое пространство имён/уровень документа применяется)
#    Декодируйте JWT для проверки claims:
python3 -c "
import jwt
token = '$(curl -s -X POST http://localhost:8080/v1/auth/login -H 'Content-Type: application/json' -d '{\"username\":\"test\",\"password\":\"test\"}' | python3 -c 'import sys,json; print(json.load(sys.stdin)[\"access_token\"])')'
print(jwt.decode(token, options={'verify_signature': False}))
"

# 3. Проверьте применяемый фильтр полезной нагрузки
#    Посмотрите логи поиска с уровнем debug:
grep -A3 'filter_conditions' proxy/logs/*.log

# 4. Убедитесь, что полезная нагрузка документа содержит правильное пространство имён/уровень доступа
curl -s http://localhost:6333/collections/knowledge_base/points/scroll \
  -H 'Content-Type: application/json' \
  -d '{"limit": 5, "with_payload": true}' | \
  python3 -c "import sys,json; [print(p['payload'].get('namespace','НЕТ_ПРОСТРАНСТВА_ИМЁН'), '|', p['payload'].get('access_level','НЕТ_УРОВНЯ')) for p in json.load(sys.stdin)['result']['points']]"
```

### 3.4 Конфликты версий

**Симптом:** Старая версия документа отображается в результатах. Вновь проиндексированные документы не появляются.

**Причина:** Инкрементальная индексация на основе WAL не переиндексировала изменённые документы. Хеш содержимого не изменился из-за изменения только пробелов.

**Решение:**
```bash
# 1. Принудительная полная переиндексация для получения всех изменений
python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml --full

# 2. Проверьте WAL на последний успешный запуск
python3 -c "
import json
wal = json.load(open('etl/wal/etl_wal.json'))
import datetime
ts = wal.get('last_successful_run', 0)
if ts:
    print('Последний запуск:', datetime.datetime.fromtimestamp(ts).isoformat())
print('Источники:', wal.get('completed_sources', []))
"

# 3. Проверьте, был ли проиндексирован конкретный документ
curl -X POST http://localhost:6333/collections/knowledge_base/points/scroll \
  -H 'Content-Type: application/json' \
  -d '{"filter": {"must": [{"key": "doc_id", "match": {"value": "CONF-1234"}}]}, "limit": 5, "with_payload": true}'

# 4. Обходите WAL для переиндексации одного источника
python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml \
  --sources confluence --force
```

### 3.5 Автоматический выключатель Qdrant открыт

**Симптом:**
```
WARNING: Qdrant circuit breaker OPEN — returning empty dense results
CircuitBreakerOpenError: Circuit breaker 'qdrant' is OPEN
```
Prometheus: `circuit_breaker_state{name="qdrant"} 1`

**Причина:** Qdrant вызвал 5+ последовательных сбоев. Проблема сети, OOM Qdrant или повреждение коллекции.

**Решение:**
```bash
# 1. Проверьте здоровье Qdrant напрямую
curl -s http://localhost:6333/health
docker logs rag-qdrant --tail 50 | grep -iE 'error|panic|oom'

# 2. Сначала устраните основную проблему Qdrant, затем закройте выключатель
#    Дождитесь восстановления Qdrant:
curl -s http://localhost:6333/collections/knowledge_base | python3 -m json.tool

# 3. Вручную сбросьте автоматический выключатель
curl -X POST http://localhost:8080/v1/admin/reset-circuit-breakers

# 4. Или дождитесь окончания периода ожидания (по умолчанию 30 сек) — выключатель автоматически перейдёт в полуоткрытое состояние
#    Наблюдайте с помощью:
watch -n 2 'curl -s http://localhost:8080/metrics | grep circuit_breaker_state'
```

---

## 4. Проблемы LLM

### 4.1 LLM — отказ в подключении

**Симптом:**
```
aiohttp.client_exceptions.ClientConnectorError: Cannot connect to host vllm:8000
ConnectionRefusedError: [Errno 111] Connection refused
LLMError: LLM request failed after 3 attempts
```

**Причина:** LLM-бэкенд (vLLM, llama.cpp и т.д.) не запущен или недоступен по адресу `LLM_ENDPOINT`.

**Решение:**
```bash
# 1. Проверьте статус LLM-бэкенда
docker ps | grep vllm
docker logs rag-vllm --tail 30

# 2. Проверьте доступность
curl -s http://localhost:8000/health
curl -s http://localhost:8000/v1/models

# 3. Изнутри контейнера прокси
docker exec rag-proxy curl -s http://vllm:8000/health

# 4. Проверьте LLM_ENDPOINT в .env
grep LLM_ENDPOINT proxy/.env
# Должно соответствовать имени сервиса docker-compose и порту:
#   LLM_ENDPOINT=http://vllm:8000/v1    (Docker DNS)
#   LLM_ENDPOINT=http://localhost:8000/v1  (сеть хоста)

# 5. Дождитесь завершения загрузки модели (может занять минуты)
docker logs rag-vllm -f | grep -i 'model loaded\|ready\|Uvicorn running'

# 6. Переключитесь на альтернативный бэкенд
#    Измените .env: LLM_ENDPOINT=http://localhost:8081/v1
#    Запустите сервер llama.cpp:
#    llama-server -m /models/your-model.gguf --port 8081
```

### 4.2 Превышена длина контекста

**Симптом:**
```
LLM returned 400: This model's maximum context length is 8192 tokens.
However, you requested 12000 tokens.
LLMError: context length exceeded
```

**Причина:** Собранный контекст (системный промпт + найденные чанки + история разговора) превышает `max_model_len` модели.

**Решение:**
```bash
# 1. Уменьшите количество чанков для поиска и сохраняемых после реранкинга
MAX_CHUNKS_RETRIEVAL=20    # было 50
MAX_CHUNKS_AFTER_RERANK=5  # было 20

# 2. Включите оптимизацию токен-бюджета
TOKEN_OPTIMIZER_ENABLED=true
COMPRESSION_STRATEGY=keyword

# 3. Увеличьте окно контекста модели (если позволяет оборудование)
#    В docker-compose.yml, команда vllm:
#    --max-model-len 32768   (вместо 8192)

# 4. Проверьте фактическое использование токенов из метрик
curl -s http://localhost:8080/metrics | grep rag_prompt_tokens

# 5. Включите сжатие контекста (LLMLingua / на основе ключевых слов)
grep COMPRESSION_STRATEGY proxy/.env
# Варианты: "perplexity", "keyword", "none"
```

### 4.3 Неверное имя модели

**Симптом:**
```
LLM returned 400: The model `rag-proxy` does not exist.
LLM returned 404: Model not found
```

**Причина:** `LLM_MODEL_NAME` в `.env` не соответствует ни одной загруженной модели в бэкенде. Прокси передаёт `rag-proxy` как имя модели в LLM-бэкенд.

**Решение:**
```bash
# 1. Перечислите доступные модели в бэкенде
curl -s http://localhost:8000/v1/models | python3 -m json.tool

# 2. Установите LLM_MODEL_NAME в соответствии с доступной моделью
#    В proxy/.env:
LLM_MODEL_NAME=/models/your-model-name
# или короткое имя, которое распознаёт бэкенд

# 3. Проверьте, какую модель фактически загрузил vLLM
docker logs rag-vllm | grep -i 'model'

# 4. Перезапустите прокси после изменения конфигурации
docker-compose -f proxy/docker-compose.yml restart rag-proxy
```

### 4.4 Несоответствие типа провайдера

**Симптом:**
```
Unknown provider type 'xyz', falling back to openai
LLM returned 400: Invalid request format
LLMError: Failed to extract content
```

**Причина:** `LLM_PROVIDER_TYPE` установлен неправильно или адаптер отправляет неправильный формат запроса для бэкенда.

**Решение:**
```bash
# 1. Проверьте текущий тип провайдера
grep LLM_PROVIDER_TYPE proxy/.env

# 2. Поддерживаемые значения:
#    openai   → vLLM, llama.cpp (OpenAI-совместимый API), Ollama, LiteLLM
#    anthropic → Claude API
#    ollama    → Ollama (с небольшими изменениями)
#    generic   → произвольный REST-эндпоинт

# 3. Для vLLM или llama.cpp:
LLM_PROVIDER_TYPE=openai

# 4. Проверьте, что формат сырого эндпоинта соответствует ожиданиям
curl -X POST http://localhost:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "your-model",
    "messages": [{"role": "user", "content": "Привет"}],
    "max_tokens": 50
  }'
```

### 4.5 Нехватка памяти LLM-бэкенда

**Симптом:**
```
docker logs rag-vllm:
CUDA out of memory. Tried to allocate 2.00 GiB
RuntimeError: CUDA out of memory
torch.cuda.OutOfMemoryError
```
Контейнер завершается с кодом 137 (OOMKilled ядром).

**Причина:** Модель + кэш KV превышают доступную VRAM GPU. Большие размеры батчей или длинные окна контекста потребляют слишком много памяти.

**Решение:**
```bash
# 1. Проверьте память GPU
nvidia-smi

# 2. Уменьшите использование памяти GPU в vLLM
#    В docker-compose.yml, команда vllm:
--gpu-memory-utilization 0.70   # было 0.90, оставьте 30% запаса
--max-model-len 16384           # уменьшите окно контекста

# 3. Используйте квантизованную модель (GGUF для llama.cpp, AWQ/GPTQ для vLLM)
#    Меньший размер:
--model /models/model-Q4_K_M.gguf   # 4-битная квантизация

# 4. Для llama.cpp выгрузите меньше слоёв на GPU:
llama-server -m /models/model.gguf --n-gpu-layers 20 --port 8000

# 5. Для эмбеддера принудительно используйте CPU:
EMBEDDER_DEVICE=cpu

# 6. Проверьте наличие утечки памяти (рост со временем)
docker stats rag-vllm --no-stream
# Наблюдайте за столбцом RES при множественных запросах
```

---

## 5. Проблемы эмбеддингов

### 5.1 Файл модели эмбеддингов не найден

**Симптом:**
```
OSError: [Errno 2] No such file or directory: 'BAAI/bge-m3'
OSError: model not found
sentence_transformers.SentenceTransformer.__init__: model not found
```

**Причина:** Модель не загружена. Автономная среда без предварительно кэшированных моделей.

**Решение:**
```bash
# 1. Загрузите модели на машине с доступом в интернет
python scripts/download_models_offline.py

# 2. Проверьте директорию кэша моделей
ls -la /path/to/model_cache/
# Должна содержать: models--BAAI--bge-m3/ (для кэша HuggingFace)

# 3. Проверьте EMBEDDER_MODEL в .env
grep EMBEDDER_MODEL proxy/.env
# Должно быть: EMBEDDER_MODEL=BAAI/bge-m3

# 4. Для автономной среды предварительно скопируйте модели в кэш:
#    На машине с интернетом:
python3 -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-m3')"
cp -r ~/.cache/huggingface/hub/models--BAAI--bge-m3 /path/to/model_cache/

#    Затем смонтируйте в docker-compose:
#    volumes:
#      - /path/to/model_cache:/root/.cache/huggingface/hub:ro

# 5. Используйте удалённый сервис эмбеддингов:
EMBEDDER_ENDPOINT=http://localhost:8081/v1
EMBEDDER_MODEL=BAAI/bge-m3    # имя модели, которое ожидает удалённый сервис
EMBEDDER_FALLBACK_LOCAL=false  # не откатываться на локальный
```

### 5.2 CUDA Out of Memory при эмбеддингах

**Симптом:**
```
RuntimeError: CUDA out of memory. Tried to allocate 256.00 MiB
torch.cuda.OutOfMemoryError: CUDA out of memory.
```
Эмбеддинги не удаются при массовой индексации или большом пакетном поиске.

**Причина:** Модель эмбеддингов на GPU конкурирует с LLM за VRAM. Большие размеры батчей исчерпывают память.

**Решение:**
```bash
# 1. Переместите эмбеддер на CPU
EMBEDDER_DEVICE=cpu

# 2. Или уменьшите память GPU для эмбеддера, используя половинную точность
#    SentenceTransformer загружается в float32 по умолчанию.
#    Используйте model_kwargs: {"torch_dtype": "float16"}
#    (требует изменения кода в retrieval.py при инициализации эмбеддера)

# 3. Уменьшите размер батча ETL
#    В etl/config/etl_config.yaml:
indexing:
  batch_size: 25    # было 100

# 4. Проверьте распределение памяти GPU
nvidia-smi
# Ищите процессы, использующие память GPU:
#   - vLLM (LLM-бэкенд): использует большую часть VRAM
#   - эмбеддер: ~2-4 ГБ для bge-m3
#   - реранкер: ~500 МБ для MiniLM

# 5. Используйте удалённый эмбеддер на отдельной машине
EMBEDDER_ENDPOINT=http://embedder-host:8081/v1
EMBEDDER_FALLBACK_LOCAL=false
```

### 5.3 Несоответствие размерности

**Симптом:**
```
Qdrant error: Wrong input: Vector dimension 768 does not match collection dimension 1024
qdrant_client.http.exceptions.UnexpectedResponse: dimension mismatch
```

**Причина:** Модель эмбеддингов производит векторы другой размерности, чем та, с которой была создана коллекция Qdrant.

**Решение:**
```bash
# 1. Проверьте текущую размерность векторов коллекции
curl -s http://localhost:6333/collections/knowledge_base | \
  python3 -c "import sys,json; d=json.load(sys.stdin).get('result',{}); print('Размерность dense:', d.get('config',{}).get('params',{}).get('vectors',{}).get('size','Н/Д'))"

# 2. Проверьте размерность выхода модели эмбеддингов
python3 -c "
from sentence_transformers import SentenceTransformer
m = SentenceTransformer('BAAI/bge-m3')
print(f'Размерность: {len(m.encode(\"test\"))}')  # 1024 для bge-m3
"

# 3. Исправление: пересоздайте коллекцию с правильной размерностью или измените модель
#    Вариант A: пересоздайте коллекцию (удаляет все данные)
python scripts/init_collections.py --qdrant-recreate

#    Вариант B: измените модель для соответствия существующей коллекции
EMBEDDER_MODEL=sentence-transformers/all-MiniLM-L6-v2  # 384-мерный
# или
EMBEDDER_MODEL=intfloat/multilingual-e5-large          # 1024-мерный

# 4. Перезапустите ETL после исправления
python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml --full
```

### 5.4 Медленное кодирование / высокая латентность эмбеддингов

**Симптом:** `hybrid_search` занимает > 1 секунды, большая часть времени в `_compute_dense_embedding`.

**Причина:** Модель эмбеддингов на CPU, отсутствие батчинга или свопинг на диск из-за нехватки памяти.

**Решение:**
```bash
# 1. Переместите эмбеддер на GPU
EMBEDDER_DEVICE=cuda

# 2. Используйте кэш для избежания повторного кодирования идентичных запросов
#    Проверьте процент попаданий в кэш:
curl -s http://localhost:8080/metrics | grep rag_cache_hits_total

# 3. Используйте удалённый сервис эмбеддингов для горизонтального масштабирования
EMBEDDER_ENDPOINT=http://embedder-host:8081/v1
#    Удалённый сервис может батчинговать и эффективно использовать GPU.

# 4. Для массового ETL увеличьте размер батча (только GPU)
#    В etl/config/etl_config.yaml:
indexing:
  batch_size: 200    # большие батчи = лучшее использование GPU

# 5. Проверьте, находится ли эмбеддер на медленном диске (HDD вместо SSD)
lsblk -d -o name,rota,size,type | grep disk
# ROTA=1 означает ротационный (HDD) — модели загружаются медленнее
```

---

## 6. Проблемы аутентификации и RBAC

### 6.1 Недействительный токен (401 Unauthorized)

**Симптом:**
```json
{"detail": "Invalid token: Signature verification failed"}
{"detail": "Invalid token: Not enough segments"}
{"detail": "Authentication required"}
```

**Причина:** Токен имеет неправильную форму, подписан неправильным ключом или несоответствие алгоритма (`HS256` vs `RS256`).

**Решение:**
```bash
# 1. Проверьте AUTH_ENABLED и конфигурацию JWT
grep -E 'AUTH_ENABLED|JWT_SECRET|JWT_ALGORITHM|JWT_PUBLIC_KEY' proxy/.env

# 2. Декодируйте токен без верификации для проверки claims
python3 -c "
import jwt
token = '$TOKEN'
try:
    print(jwt.decode(token, options={'verify_signature': False}))
except Exception as e:
    print(f'Токен имеет неправильную форму: {e}')
"

# 3. Проверьте подпись правильным ключом
python3 -c "
import jwt
token = '$TOKEN'
secret = '$(grep JWT_SECRET proxy/.env | cut -d= -f2)'
try:
    payload = jwt.decode(token, secret, algorithms=['HS256'])
    print('Действителен:', payload)
except jwt.InvalidSignatureError:
    print('Несоответствие подписи — неправильный секрет')
except jwt.ExpiredSignatureError:
    print('Токен истёк')
"

# 4. Для Keycloak/RS256 убедитесь, что открытый ключ правильный
grep JWT_PUBLIC_KEY proxy/.env
# Можно оставить пустым для автообнаружения через JWKS

# 5. Тест создания и валидации токена
curl -X POST http://localhost:8080/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"test","password":"test"}'
```

### 6.2 Токен истёк

**Симптом:**
```json
{"detail": "Token has expired"}
```

**Причина:** Истёк TTL токена доступа (`ACCESS_TOKEN_MINUTES`, по умолчанию 60).

**Решение:**
```bash
# 1. Обновите с помощью токена обновления
REFRESH_TOKEN='your-refresh-token'
curl -X POST http://localhost:8080/v1/auth/refresh \
  -H 'Content-Type: application/json' \
  -d "{\"refresh_token\": \"$REFRESH_TOKEN\"}"

# 2. Увеличьте время жизни токенов в .env
ACCESS_TOKEN_MINUTES=120    # 2 часа (было 60)
REFRESH_TOKEN_DAYS=14       # 2 недели (было 7)

# 3. Проверьте, когда истекает токен
python3 -c "
import jwt, datetime
token = '$TOKEN'
payload = jwt.decode(token, options={'verify_signature': False})
exp = datetime.datetime.fromtimestamp(payload['exp'])
now = datetime.datetime.now()
print(f'Истекает: {exp.isoformat()}')
print(f'Осталось: {(exp - now).total_seconds():.0f} сек')
"
```

### 6.3 Сбой обновления токена

**Симптом:**
```json
{"detail": "Invalid refresh token"}
{"detail": "Refresh token not found or already used"}
```

**Причина:** Токен обновления был использован (одноразовый), истёк или запись пользователя была удалена из БД.

**Решение:**
```bash
# 1. Токены обновления одноразовые — получите новую пару повторной аутентификацией
curl -X POST http://localhost:8080/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"your-user","password":"your-password"}'

# 2. Проверьте БД пользователей на наличие сохранённых токенов обновления
sqlite3 proxy/data/users.db "SELECT user_id, substr(token_hash,1,10), created_at, expires_at FROM refresh_tokens WHERE expires_at > datetime('now') LIMIT 5;"

# 3. Если БД пользователей повреждена, пересоздайте её
rm proxy/data/users.db
docker-compose -f proxy/docker-compose.yml restart rag-proxy
# Зарегистрируйте пользователей заново
```

### 6.4 Keycloak недоступен

**Симптом:**
```
WARNING: Failed to fetch JWKS from Keycloak: timed out
WARNING: Failed to fetch JWKS from Keycloak: [Errno 111] Connection refused
```
Валидация токена откатывается на `JWT_PUBLIC_KEY`.

**Причина:** Сервер Keycloak не работает, сеть недоступна или неправильная конфигурация (URL/realm).

**Решение:**
```bash
# 1. Проверьте доступность Keycloak
curl -s http://keycloak:8080/auth/realms/your-realm/.well-known/openid-configuration
# или с хоста:
curl -s "${KEYCLOAK_URL}/realms/${KEYCLOAK_REALM}/.well-known/openid-configuration"

# 2. Проверьте конфигурацию
grep -E 'KEYCLOAK_URL|KEYCLOAK_REALM|KEYCLOAK_CLIENT_ID' proxy/.env

# 3. Если Keycloak постоянно недоступен, переключитесь на локальный режим HS256:
#    Очистите KEYCLOAK_URL и установите JWT_SECRET
KEYCLOAK_URL=
JWT_SECRET=your-256-bit-secret
JWT_ALGORITHM=HS256
AUTH_VALID_USERS='{"alice":{"password":"hash","roles":["admin"]}}'

# 4. Перезапустите прокси
docker-compose -f proxy/docker-compose.yml restart rag-proxy
```

### 6.5 Таймаут LDAP/AD

**Симптом:**
```
LDAP connection timeout (5s)
ldap.SERVER_DOWN: {'desc': "Can't contact LDAP server"}
```

**Причина:** Сервер AD/LDAP недоступен, неправильный URL или сетевая задержка.

**Решение:**
```bash
# 1. Проверьте конфигурацию AD
grep -E 'AD_ENABLED|AD_URL|AD_BASE_DN|AD_USER_DN_TEMPLATE' proxy/.env

# 2. Проверьте доступность LDAP с хоста прокси
ldapsearch -H "$AD_URL" -x -b "$AD_BASE_DN" -D "$AD_USER_DN_TEMPLATE" -w password -l 5

# 3. Увеличьте таймаут (требует изменения кода в ldap_auth.py)
#    Таймаут по умолчанию — 5 сек. Увеличьте в вызове ldap.initialize().

# 4. Отключите AD, если LDAP недоступен
AD_ENABLED=false

# 5. Проверьте сеть из контейнера прокси к AD
docker exec rag-proxy timeout 3 nc -zv ad-server 389
```

### 6.6 Отказано в доступе (403 Forbidden)

**Симптом:**
```json
{"detail": "Role 'user' is not sufficient. Required: 'admin'"}
{"detail": "Role 'read_only' is not sufficient. Required: 'expert'"}
```

**Причина:** Роль пользователя не соответствует минимальному требованию эндпоинта.

**Решение:**
```bash
# 1. Проверьте вашу текущую роль
curl -s http://localhost:8080/v1/auth/me \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# 2. Иерархия ролей:
#    admin     → все эндпоинты (чат, обратная связь, админ конфигурация/метрики, прогрев)
#    expert    → чат + обратная связь + обогащение
#    user      → чат + виджет
#    read_only → список моделей + здоровье

# 3. Убедитесь, что RBAC включён
grep RBAC_ENABLED proxy/.env

# 4. Проверьте маппинг роли эндпоинта в app/rbac.py _PERMISSION_MAP
#    Если для эндпоинта нет маппинга, доступ запрещён по умолчанию.

# 5. Для временного предоставления доступа администратора создайте токен администратора:
python3 -c "
from app.auth import create_mock_token
token = create_mock_token(
    user_id='admin-temp',
    username='admin',
    roles=['admin'],
    access_level='confidential',
)
print(token)
"
```

---

## 7. Проблемы кэша (Redis)

### 7.1 Redis — отказ в подключении

**Симптом:**
```
redis.exceptions.ConnectionError: Error 111 connecting to redis:6379. Connection refused.
Failed to connect to Redis at redis://redis:6379
```
Вызовы кэша молча откатываются на кэш в памяти.

**Причина:** Redis не запущен, неправильный URL или проблема сети.

**Решение:**
```bash
# 1. Проверьте статус Redis
docker ps | grep redis
docker logs rag-redis --tail 20

# 2. Проверьте доступность
redis-cli -h localhost -p 6379 PING
# или изнутри контейнера прокси:
docker exec rag-proxy redis-cli -h redis PING

# 3. Проверьте REDIS_URL в .env
grep -E 'USE_REDIS|REDIS_URL' proxy/.env
# Должно быть: REDIS_URL=redis://redis:6379

# 4. Если Redis не работает, перезапустите его
docker-compose -f proxy/docker-compose.yml restart redis

# 5. Если Redis постоянно недоступен, отключите его:
USE_REDIS=false
# Кэш будет использовать только память (перезапуск очищает кэш)
```

### 7.2 Устаревший кэш / неправильные ответы

**Симптом:** Прокси возвращает кэшированные ответы даже после обновления документов. `rag_force_refresh` не помогает.

**Причина:** TTL кэша слишком длинный, ключ кэша не включает версию/пространство имён или `rag_force_refresh` не учитывается.

**Решение:**
```bash
# 1. Принудительный обход кэша для конкретного запроса
curl -X POST http://localhost:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"rag-proxy","messages":[{"role":"user","content":"запрос"}],"rag_force_refresh":true}'

# 2. Очистите весь кэш Redis
docker exec rag-redis redis-cli FLUSHDB

# 3. Очистите конкретные ключи кэша (кэш эмбеддингов)
docker exec rag-redis redis-cli KEYS "embed:*" | xargs docker exec -i rag-redis redis-cli DEL

# 4. Уменьшите TTL кэша для более быстрой инвалидации
#    В cache.py TTL по умолчанию — 3600 сек (1 час). Уменьшите:
#    cache_manager.set_sync(key, value, ttl=300)  # 5 минут

# 5. Проверьте процент попаданий в кэш
curl -s http://localhost:8080/metrics | grep rag_cache
```

### 7.3 Достигнут лимит памяти Redis

**Симптом:**
```
redis.exceptions.ResponseError: OOM command not allowed when used memory > 'maxmemory'
```
Логи Redis: `Can't save in background: fork: Cannot allocate memory`.

**Причина:** Redis превысил `maxmemory`, а политика вытеснения — `noeviction`.

**Решение:**
```bash
# 1. Проверьте текущее использование памяти
docker exec rag-redis redis-cli INFO memory | grep -E 'used_memory_human|maxmemory_human|maxmemory_policy'

# 2. Установите политику вытеснения (LRU)
docker exec rag-redis redis-cli CONFIG SET maxmemory-policy allkeys-lru

# 3. Увеличьте maxmemory
docker exec rag-redis redis-cli CONFIG SET maxmemory 2gb

# 4. Или в docker-compose.yml постоянно:
#    redis:
#      command: redis-server --appendonly yes --maxmemory 2gb --maxmemory-policy allkeys-lru

# 5. Очистите, если память критически заполнена
docker exec rag-redis redis-cli FLUSHDB

# 6. Проверьте размеры потоков (если потоковый ETL заполняет память)
docker exec rag-redis redis-cli XLEN etl:events
docker exec rag-redis redis-cli XTRIM etl:events MAXLEN ~ 10000
```

### 7.4 Повреждение AOF Redis

**Симптом:**
```
Redis log: Bad file format reading the append only file
Redis log: AOF file is corrupted
Redis не запускается или запускается с пустыми данными.
```

**Причина:** Нечистое завершение, заполнение диска во время записи AOF или повреждение файловой системы.

**Решение:**
```bash
# 1. Проверьте и восстановите файл AOF
docker exec rag-redis redis-check-aof --fix /data/appendonly.aof

# 2. Если восстановление не удалось, начните с нуля (потеря данных)
docker-compose -f proxy/docker-compose.yml stop redis
docker exec rag-redis rm -f /data/appendonly.aof /data/dump.rdb
docker-compose -f proxy/docker-compose.yml start redis

# 3. Перестройте AOF из текущих данных
docker exec rag-redis redis-cli BGREWRITEAOF

# 4. Проверьте размер AOF и последнюю перезапись
docker exec rag-redis redis-cli INFO persistence | grep -E 'aof_current_size|aof_last_rewrite_time'

# 5. Восстановите из резервной копии при наличии
#    См. docs/en/guides/disaster-recovery-runbook.md
```

---

## 8. Проблемы графа (Neo4j)

### 8.1 Neo4j — отказ в подключении

**Симптом:**
```
neo4j.exceptions.ServiceUnavailable: Unable to retrieve routing information
neo4j.exceptions.ServiceUnavailable: Connection to neo4j:7687 refused
WARNING: Neo4j connection failed: ... Graph expansion disabled.
```

**Причина:** Neo4j не запущен, недоступен или неправильные учётные данные.

**Решение:**
```bash
# 1. Проверьте статус Neo4j
docker ps | grep neo4j
docker logs rag-neo4j --tail 30

# 2. Подождите готовности Neo4j (может занять 30-60 сек при первом запуске)
until docker exec rag-neo4j cypher-shell -u neo4j -p password "RETURN 1" 2>/dev/null; do
  echo "Ожидание Neo4j..."
  sleep 5
done

# 3. Проверьте доступность из прокси
docker exec rag-proxy curl -s http://neo4j:7474

# 4. Проверьте учётные данные в .env
grep -E 'GRAPH_ENABLED|NEO4J_URI|NEO4J_USER|NEO4J_PASSWORD' proxy/.env
# По умолчанию: NEO4J_URI=bolt://neo4j:7687

# 5. Измените пароль по умолчанию при первом запуске
docker exec rag-neo4j cypher-shell -u neo4j -p neo4j "ALTER CURRENT USER SET PASSWORD FROM 'neo4j' TO 'newpassword'"
# Затем обновите NEO4J_PASSWORD в .env

# 6. Увеличьте таймаут подключения
#    В docker-compose.yml, окружение neo4j:
#    NEO4J_dbms_connector_bolt_advertised__address=neo4j:7687
```

### 8.2 APOC не установлен

**Симптом:**
```
There is no procedure with the name apoc.meta.graph
Unknown function 'apoc.text.levenshteinSimilarity'
```

**Причина:** Библиотека плагина APOC не установлена в контейнере Neo4j.

**Решение:**
```bash
# 1. Проверьте установленные плагины
docker exec rag-neo4j ls /plugins/

# 2. Загрузите APOC в директорию плагинов
#    На хосте загрузите apoc-5.x.x-core.jar в том neo4j_plugins
docker exec rag-neo4j bash -c '
  cd /plugins && \
  wget https://github.com/neo4j/apoc/releases/download/5.24.0/apoc-5.24.0-core.jar
'

# 3. Включите APOC в neo4j.conf
#    Добавьте в окружение docker-compose.yml neo4j:
NEO4J_dbms_security_procedures_unrestricted=apoc.*
NEO4J_dbms_security_procedures_allowlist=apoc.*

# 4. Перезапустите Neo4j
docker-compose -f proxy/docker-compose.yml restart neo4j

# 5. Убедитесь, что APOC доступен
docker exec rag-neo4j cypher-shell -u neo4j -p password \
  "CALL apoc.help('apoc') YIELD name RETURN name LIMIT 5"
```

### 8.3 Медленное расширение графа

**Симптом:** `graph_expand_query` занимает > 3 секунд. Пайплайн поиска задерживается на шаге графа.

**Причина:** Большой граф, отсутствие индексов или сложные запросы Cypher, сканирующие все узлы.

**Решение:**
```bash
# 1. Проверьте, является ли расширение графа узким местом — временно отключите
USE_GRAPH_EXPANSION=false

# 2. Проверьте существующие индексы
docker exec rag-neo4j cypher-shell -u neo4j -p password \
  "SHOW INDEXES YIELD name, type, labelsOrTypes, properties"

# 3. Создайте отсутствующие индексы
docker exec rag-neo4j cypher-shell -u neo4j -p password "
CREATE INDEX entity_name_idx IF NOT EXISTS FOR (n:Entity) ON (n.name);
CREATE INDEX entity_type_idx IF NOT EXISTS FOR (n:Entity) ON (n.type);
"

# 4. Проверьте количество сущностей
docker exec rag-neo4j cypher-shell -u neo4j -p password \
  "MATCH (n:Entity) RETURN count(n) as total_entities"

# 5. Увеличьте heap Neo4j (при OOM при запросах к графу)
#    В docker-compose.yml:
NEO4J_dbms_memory_heap_initial__size=2G
NEO4J_dbms_memory_heap_max__size=4G
NEO4J_dbms_memory_pagecache_size=2G

# 6. Ограничьте глубину расширения графа
#    В retrieval.py graph_expand_query уменьшите max_entities
```

### 8.4 Сбои извлечения сущностей

**Симптом:**
```
WARNING: Entity extraction returned 0 entities
graph_expand_query returns ""
```

**Причина:** SLM/роутинг-модель не настроена, текст слишком короткий для извлечения сущностей или неанглийский контент.

**Решение:**
```bash
# 1. Проверьте конфигурацию SLM
grep -E 'SLM_ENDPOINT|SLM_MODEL_NAME' proxy/.env

# 2. Если SLM не настроен, включите эвристическое извлечение сущностей
#    graph_expand_query уже откатывается на извлечение на основе ключевых слов
#    (слова > 3 символов как ключевые слова)

# 3. Для лучшего извлечения разверните лёгкий SLM:
SLM_ENDPOINT=http://vllm:8000/v1
SLM_MODEL_NAME=Qwen2.5-1.5B-Instruct

# 4. Проверьте наличие данных графа
docker exec rag-neo4j cypher-shell -u neo4j -p password \
  "MATCH (n:Entity) RETURN n.name, n.type LIMIT 10"

# 5. Перестройте граф из ETL
python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml --steps graph
```

---

## 9. Проблемы производительности

### 9.1 Высокая латентность (p95 > 5 сек)

**Симптом:** Нарушение SLO. p95 `rag_request_duration_seconds` стабильно выше 5 секунд.

**Причина:** Перегрузка LLM-бэкенда, узкое место дискового ввода-вывода Qdrant, обработка слишком большого количества чанков реранкером или сетевая задержка.

**Решение:**
```bash
# 1. Определите узкое место по времени выполнения фаз
#    Каждая фаза имеет свою метрику. Проверьте:
curl -s http://localhost:8080/metrics | grep -E 'rag_phase.*seconds|rag_retrieval_duration|rag_llm_duration'

# 2. Если генерация LLM — узкое место (> 80% времени):
#    - Уменьшите max_tokens
#    - Используйте меньшую/быструю модель
#    - Включите кэширование префиксов в vLLM (--enable-prefix-caching)

# 3. Если поиск — узкое место:
#    - Уменьшите MAX_CHUNKS_RETRIEVAL
#    - Используйте удалённый эмбеддер
#    - Оптимизируйте параметры HNSW Qdrant

# 4. Если реранкинг — узкое место:
#    - Уменьшите MAX_CHUNKS_AFTER_RERANK
#    - Увеличьте RERANKER_BATCH_SIZE (только GPU)
#    - Отключите ContextReordering (REORDER_ENABLED=false)

# 5. Проверьте сетевую задержку между сервисами
docker exec rag-proxy ping -c 5 qdrant
docker exec rag-proxy ping -c 5 vllm

# 6. Включите сжатие ответов для больших полезных нагрузок
grep COMPRESSION_ENABLED proxy/.env
# Должно быть: COMPRESSION_ENABLED=true
```

### 9.2 Утечка памяти

**Симптом:** Использование памяти прокси/реранкера растёт часами/днями без уменьшения.
```
docker stats rag-proxy  # Наблюдайте за столбцом RES
```

**Причина:** Неограниченный рост кэша эмбеддингов, накопление объектов Python в состоянии LangGraph или невысвобождаемые тензоры GPU.

**Решение:**
```bash
# 1. Проверьте паттерн роста памяти
watch -n 30 'docker stats rag-proxy --no-stream'

# 2. Проверьте размер кэша в памяти
#    InMemoryCache не имеет ограничения размера — ключи накапливаются.
#    Добавьте ограничение максимального размера или уменьшите TTL.

# 3. Включите периодическую очистку кэша (если код поддерживает)
#    Перезапустите прокси для очистки состояния в памяти:
docker-compose -f proxy/docker-compose.yml restart rag-proxy

# 4. Проверьте утечку памяти GPU
nvidia-smi -l 1  # Наблюдайте за памятью со временем

# 5. Уменьшите WORKERS до 1 (общее состояние эмбеддера)
grep WORKERS proxy/.env
# Должно быть: WORKERS=1 (несколько воркеров дублируют эмбеддер в памяти)

# 6. Включите логирование сборщика мусора для отладки
#    Добавьте в код прокси:
#    import gc; gc.set_debug(gc.DEBUG_LEAK)
```

### 9.3 Всплеск CPU

**Симптом:** Использование CPU прокси скачком достигает 100% на продолжительное время.

**Причина:** Плотное кодирование на CPU, обработка больших батчей реранкером или сжатие больших ответов.

**Решение:**
```bash
# 1. Проверьте использование CPU по контейнерам
docker stats --no-stream

# 2. Переместите вычисления на GPU
EMBEDDER_DEVICE=cuda

# 3. Уменьшите уровень сжатия
COMPRESSION_LEVEL=1    # самый быстрый (было 6)
# или отключите для внутреннего трафика
COMPRESSION_MIN_SIZE=50000

# 4. Уменьшите батч реранкера
RERANKER_BATCH_SIZE=8

# 5. Отключите тяжёлые функции (HyDE, рефлексия), если не нужны
HYDE_ENABLED=false
REFLECTION_ENABLED=false

# 6. Ограничьте одновременные запросы (через ограничитель скорости)
RATE_LIMIT_ENABLED=true
RATE_LIMIT_PER_MINUTE=60
```

### 9.4 Насыщение дискового ввода-вывода

**Симптом:** Системный `iowait` > 20%. Оптимизация сегментов Qdrant загружает диск.

**Причина:** Qdrant оптимизирует сегменты, SQLite WAL выполняет чекпоинт или логи заполняют диск.

**Решение:**
```bash
# 1. Проверьте использование диска
iostat -x 1 5

# 2. Проверьте хранилище Qdrant
du -sh /var/lib/docker/volumes/*qdrant*/_data/

# 3. Увеличьте порог индексации Qdrant (оптимизация реже)
curl -X PATCH http://localhost:6333/collections/knowledge_base \
  -H 'Content-Type: application/json' \
  -d '{"optimizers_config": {"indexing_threshold": 50000, "memmap_threshold": 50000}}'

# 4. Переместите хранилище Qdrant на более быстрый диск (NVMe)
#    В docker-compose.yml, привяжите к пути NVMe:
#    volumes:
#      - /mnt/nvme/qdrant:/qdrant/storage

# 5. Ротируйте и сжимайте старые логи
find proxy/logs/ -name "*.log" -mtime +7 -exec gzip {} \;

# 6. Проверьте размер SQLite WAL (может быть большим)
ls -la proxy/data/users.db-wal
# Если большой, выполните VACUUM:
sqlite3 proxy/data/users.db "PRAGMA wal_checkpoint(TRUNCATE); VACUUM;"
```

### 9.5 Слишком много сегментов Qdrant

**Симптом:** `segments_count` в Qdrant > 200. Латентность поиска линейно растёт с количеством сегментов.

**Причина:** Много маленьких сегментных файлов от инкрементальной индексации. Оптимизатор не объединил их.

**Решение:**
```bash
# 1. Проверьте количество сегментов
curl -s http://localhost:6333/collections/knowledge_base | \
  python3 -c "import sys,json; d=json.load(sys.stdin).get('result',{}); print('Сегменты:', d.get('segments_count'), 'Проиндексировано:', d.get('indexed_vectors_count','Н/Д'))"

# 2. Принудительная оптимизация сегментов
curl -X POST http://localhost:6333/collections/knowledge_base/optimizers \
  -H 'Content-Type: application/json' \
  -d '{"indexing_threshold": 5000}'

# 3. Дождитесь завершения оптимизации (наблюдайте за уменьшением количества сегментов)
watch -n 5 'curl -s http://localhost:6333/collections/knowledge_base | python3 -c "import sys,json; print(json.load(sys.stdin).get(\"result\",{}).get(\"segments_count\",\"?\"))"'

# 4. Постоянно увеличьте порог для более агрессивного объединения
curl -X PATCH http://localhost:6333/collections/knowledge_base \
  -H 'Content-Type: application/json' \
  -d '{"optimizers_config": {"indexing_threshold": 20000, "default_segment_number": 2}}'
```

---

## 10. Проблемы развёртывания (Docker / Kubernetes)

### 10.1 Ошибки загрузки образов

**Симптом:**
```
ErrImagePull: pull access denied for rag-proxy
ImagePullBackOff: repository does not exist or may require 'docker login'
```

**Причина:** Docker не может загрузить образ — он только локальный (не отправлен), неправильный тег или приватный реестр требует аутентификации.

**Решение:**
```bash
# 1. Соберите локально вместо загрузки
docker-compose -f proxy/docker-compose.yml build rag-proxy
docker-compose -f proxy/docker-compose.yml up -d

# 2. Проверьте имя/тег образа в docker-compose.yml
grep 'image:' proxy/docker-compose.yml

# 3. Для приватных реестров сначала аутентифицируйтесь
docker login your-registry.example.com
# Или в K8s создайте секрет для загрузки образов:
kubectl create secret docker-registry regcred \
  --docker-server=your-registry.example.com \
  --docker-username=user \
  --docker-password=token

# 4. Убедитесь, что образ существует локально или удалённо
docker images | grep rag-proxy
docker pull your-registry/rag-proxy:v2.0
```

### 10.2 CrashLoopBackOff

**Симптом (K8s):**
```
kubectl get pods
NAME         READY   STATUS             RESTARTS   AGE
rag-proxy-0  0/1     CrashLoopBackOff   6          10m
```

**Причина:** Контейнер сразу завершается после запуска — ошибка конфигурации, отсутствующий том или зависимость не готова.

**Решение:**
```bash
# 1. Получите логи падающего пода
kubectl logs rag-proxy-0 --previous
kubectl describe pod rag-proxy-0

# 2. Типичные причины K8s:
#    - ConfigMap/Secret не примонтирован
#    - PersistentVolumeClaim не привязан
#    - Проба readiness не проходит
#    - Конфликты портов

# 3. Отладка переопределением точки входа
kubectl run debug --rm -it --image=rag-proxy:latest --restart=Never -- sh
# Внутри: проверьте переменные окружения, тома, сеть

# 4. Проверьте события для пространства имён
kubectl get events --sort-by='.lastTimestamp' | tail -20

# 5. Для Docker аналогичный подход:
docker-compose -f proxy/docker-compose.yml up rag-proxy  # запуск на переднем плане для просмотра ошибок
```

### 10.3 OOMKilled

**Симптом:**
```
State: Terminated
  Reason: OOMKilled
  Exit Code: 137
```
Контейнер убит ядерным OOM-killer.

**Причина:** Контейнер превысил лимит памяти. Модель LLM слишком большая, неограниченный кэш эмбеддингов или утечка памяти.

**Решение:**
```bash
# 1. Проверьте лимиты памяти в развёртывании
# K8s:
kubectl describe pod rag-proxy-0 | grep -A5 'Limits\|Requests'
# Docker:
docker inspect rag-proxy | grep -A5 Memory

# 2. Увеличьте лимит памяти
# K8s (в deployment.yaml):
#   resources:
#     limits:
#       memory: "16Gi"   # увеличьте с 8Gi
#     requests:
#       memory: "8Gi"

# 3. Уменьшите использование памяти (см. разделы 4.5 и 9.2)
#    - Переместите эмбеддер на CPU
#    - Уменьшите количество чанков
#    - Используйте меньшие/квантизованные модели

# 4. Мониторьте использование памяти до OOM
kubectl top pod rag-proxy-0
docker stats rag-proxy --no-stream

# 5. Добавьте предупреждение о лимите памяти через Prometheus
#    Оповещение: container_memory_usage_bytes / container_spec_memory_limit_bytes > 0.85
```

### 10.4 Проблемы привязки PVC

**Симптом (K8s):**
```
Warning: FailedScheduling: pod has unbound immediate PersistentVolumeClaims
Warning: ProvisioningFailed: storageclass.storage.k8s.io "fast-ssd" not found
```

**Причина:** PersistentVolumeClaim не может быть привязан — нет подходящего PV, неправильный класс хранения или несоответствие режима доступа.

**Решение:**
```bash
# 1. Проверьте статус PVC
kubectl get pvc
kubectl describe pvc qdrant-data

# 2. Убедитесь, что класс хранения существует
kubectl get storageclass

# 3. Проверьте доступные PV
kubectl get pv

# 4. Исправьте имя класса хранения в PVC
#    При использовании hostPath (только для разработки):
#    storageClassName: ""   # пустая строка = без динамического обеспечения

# 5. Для Docker-томов проверьте место на диске:
df -h /var/lib/docker/volumes/
docker system df
```

### 10.5 Ошибки Ingress 502/504

**Симптом:** Nginx/Ingress возвращает 502 Bad Gateway или 504 Gateway Timeout.

**Причина:** Под прокси не готов, отказ в подключении или таймаут запроса.

**Решение:**
```bash
# 1. Проверьте статус пода прокси
kubectl get pods -l app=rag-proxy
kubectl logs -l app=rag-proxy --tail 20

# 2. Проверьте конечные точки сервиса
kubectl get endpoints rag-proxy-service

# 3. Увеличьте таймаут прокси ingress (Nginx Ingress)
#    Добавьте аннотации в Ingress:
#    nginx.ingress.kubernetes.io/proxy-read-timeout: "300"
#    nginx.ingress.kubernetes.io/proxy-send-timeout: "300"
#    nginx.ingress.kubernetes.io/proxy-connect-timeout: "30"

# 4. Проверьте пробы здоровья
curl http://<ingress-ip>/v1/health/live
curl http://<ingress-ip>/v1/health/ready

# 5. Проверьте логи контроллера ingress
kubectl logs -n ingress-nginx -l app.kubernetes.io/name=ingress-nginx --tail 50
```

---

## 11. Проблемы федерации

### 11.1 Силос недоступен

**Симптом:**
```
FederationError: Silo 'europe-west' is unreachable
ConnectionError: Failed to connect to silo at http://rag-eu-west.example.com
```

**Причина:** Удалённый экземпляр RAG не работает, сбой разрешения DNS или сетевой раздел.

**Решение:**
```bash
# 1. Проверьте здоровье силоса
curl -s http://rag-eu-west.example.com/v1/health
curl -s http://rag-eu-west.example.com/v1/health/ready

# 2. Проверьте разрешение DNS
nslookup rag-eu-west.example.com
dig rag-eu-west.example.com

# 3. Проверьте доступность из прокси
docker exec rag-proxy curl -s --connect-timeout 5 http://rag-eu-west.example.com/v1/health

# 4. Проверьте конфигурацию федерации
grep -E 'FEDERATION|SILO' proxy/.env

# 5. Если силос постоянно недоступен, удалите его из конфигурации федерации
#    или помечьте как неактивный для пропуска при запросах
```

### 11.2 Автоматический выключатель силоса открыт

**Симптом:**
```
FederationCircuitBreakerError: Circuit breaker for silo 'europe-west' is OPEN
All silos returned errors — federated query failed
```

**Причина:** Силос вызвал 5+ последовательных сбоев. Автоматический выключатель защищает систему от каскадных сбоев.

**Решение:**
```bash
# 1. Проверьте доступность силоса
curl -s http://rag-eu-west.example.com/v1/health

# 2. Подождите окончания периода ожидания (по умолчанию 30 сек) — выключатель автоматически перейдёт в полуоткрытое состояние

# 3. Сбросьте автоматический выключатель после устранения проблемы силоса
curl -X POST http://localhost:8080/v1/admin/reset-circuit-breakers

# 4. Проверьте метрики автоматического выключателя
curl -s http://localhost:8080/metrics | grep circuit_breaker_state

# 5. Увеличьте допуск (не рекомендуется, если силос нестабилен)
#    Настройте пороговые значения для каждого брокера в circuit_breaker.py:
#    failure_threshold=10  (было 5)
```

### 11.3 Слияние федерации вернуло 0 чанков

**Симптом:**
```
WARNING: Federation merge returned 0 chunks from 3 silos
Question answered with "I don't have enough information"
```

**Причина:** Все силосы вернули пустые результаты. Запрос может не иметь совпадений или все силосы имеют пустые коллекции.

**Решение:**
```bash
# 1. Проверьте каждый силос отдельно
for silo in rag-us rag-eu rag-asia; do
  echo "=== $silo ==="
  curl -s "http://$silo.example.com/v1/chat/completions" \
    -H 'Content-Type: application/json' \
    -d '{"model":"rag-proxy","messages":[{"role":"user","content":"тестовый запрос"}],"max_tokens":50}' \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('choices',[{}])[0].get('message',{}).get('content','НЕТ ОТВЕТА')[:100])"
done

# 2. Проверьте коллекции на каждом силосе
for silo in rag-us rag-eu rag-asia; do
  echo "=== $silo ==="
  curl -s "http://$silo.example.com:6333/collections/knowledge_base" | \
    python3 -c "import sys,json; print(json.load(sys.stdin).get('result',{}).get('vectors_count','0'), 'векторов')"
done

# 3. Проверьте, не вызывает ли фильтрация пространства имён пустые результаты
#    Федерация может передавать контекст пользователя; проверьте, соответствует ли пространство имён данным силоса.
```

### 11.4 Сбой извлечения JWT

**Симптом:**
```
AuthError: Failed to extract user context from JWT in federated request
Authorization header missing in forwarded request to silo
```

**Причина:** Токен JWT не пересылается в удалённые силосы или силос не может его валидировать.

**Решение:**
```bash
# 1. Проверьте, пересылается ли заголовок Authorization
#    Прокси федерации должен включать:
#    Authorization: Bearer <token>
#    при выполнении запросов к силосам.

# 2. Убедитесь, что открытый ключ JWT / JWKS согласован во всех силосах
#    Все силосы должны доверять одному издателю / ключу подписи.

# 3. Для HS256 убедитесь, что JWT_SECRET идентичен во всех силосах

# 4. Для RS256 (Keycloak) убедитесь, что во всех силосах настроен KEYCLOAK_URL

# 5. Тест валидации токена на каждом силосе
TOKEN='your-jwt'
for silo in rag-us rag-eu; do
  echo "=== $silo ==="
  curl -s "http://$silo.example.com/v1/auth/me" \
    -H "Authorization: Bearer $TOKEN"
done
```

---

## 12. Проблемы эволюции моделей

### 12.1 Задача обучения зависла

**Симптом:**
```
POST /v1/admin/models/train returns 202
GET /v1/admin/models/status/{job_id}: status "running" for > 1 hour
```

**Причина:** Процесс обучения завис, сбой выделения GPU или загрузка данных застряла.

**Решение:**
```bash
# 1. Проверьте статус задачи обучения
curl -s http://localhost:8080/v1/admin/models/status/<job_id> | python3 -m json.tool

# 2. Ищите ошибки в MLflow
curl -s http://localhost:5000/api/2.0/mlflow/runs/search \
  -H 'Content-Type: application/json' \
  -d '{"experiment_ids": ["0"], "max_results": 5}'

# 3. Проверьте логи контейнера обучения (если запущен как отдельный процесс)
#    Docker:
docker logs rag-training 2>&1 | tail -50
#    K8s:
kubectl logs -l job=rag-training --tail 50

# 4. Проверьте доступность GPU
nvidia-smi
# Если GPU занят другой задачей, подождите или остановите её

# 5. Вручную отмените задачу
curl -X POST http://localhost:8080/v1/admin/models/cancel/<job_id>

# 6. Проверьте OOM при обучении
dmesg | grep -i 'out of memory' | tail -5
```

### 12.2 MLflow недоступен

**Симптом:**
```
requests.exceptions.ConnectionError: Failed to connect to mlflow:5000
MLflow tracking URI http://localhost:5000 is not reachable
```

**Причина:** Сервер MLflow не работает, неправильный URI или зависимость MinIO не здорова.

**Решение:**
```bash
# 1. Проверьте статус MLflow
docker ps | grep mlflow
docker logs rag-mlflow --tail 30

# 2. Проверьте доступность MLflow
curl -s http://localhost:5000/health
curl -s http://localhost:5000/api/2.0/mlflow/experiments/list

# 3. Проверьте MinIO (зависимость хранилища артефактов)
docker ps | grep minio
curl -s http://localhost:9000/minio/health/live

# 4. Проверьте MLFLOW_TRACKING_URI в .env
grep MLFLOW_TRACKING_URI proxy/.env
# Должно быть: MLFLOW_TRACKING_URI=http://mlflow:5000

# 5. Перезапустите MLflow
docker-compose -f proxy/docker-compose.yml restart mlflow
docker-compose -f proxy/docker-compose.yml restart minio  # при необходимости
```

### 12.3 Отказано в доступе MinIO

**Симптом:**
```
botocore.exceptions.ClientError: AccessDenied
S3 operation error: The Access Key Id you provided does not exist
```

**Причина:** Неправильные учётные данные MinIO, bucket не существует или политика IAM ограничивает доступ.

**Решение:**
```bash
# 1. Проверьте учётные данные MinIO
grep -E 'MINIO_ACCESS_KEY|MINIO_SECRET_KEY|MINIO_ENDPOINT|MINIO_BUCKET' proxy/.env
# По умолчанию: minioadmin / minioadmin

# 2. Тест доступа к MinIO
docker exec rag-minio mc alias set local http://localhost:9000 minioadmin minioadmin
docker exec rag-minio mc ls local/rag-artifacts

# 3. Создайте bucket при отсутствии
docker exec rag-minio mc mb local/rag-artifacts

# 4. Проверьте логи MinIO
docker logs rag-minio --tail 30

# 5. Тест S3 API напрямую
curl -s http://localhost:9000/rag-artifacts \
  -H "Authorization: AWS $(echo -n 'GET\n\n\n\n/rag-artifacts' | openssl dgst -sha1 -hmac 'minioadmin' -binary | base64)"

# 6. Сбросьте учётные данные MinIO (удаляет данные)
docker-compose -f proxy/docker-compose.yml down -v minio
docker-compose -f proxy/docker-compose.yml up -d minio minio-create-bucket
```

### 12.4 OOM при обучении

**Симптом:**
```
torch.cuda.OutOfMemoryError: CUDA out of memory. Tried to allocate 2.00 GiB
RuntimeError: CUDA out of memory
```
Обучение завершается с ошибкой, запуск MLflow помечен как `FAILED`.

**Причина:** Размер батча обучения слишком велик для доступной памяти GPU или модель + оптимизатор + градиенты превышают VRAM.

**Решение:**
```bash
# 1. Уменьшите размер батча обучения
#    В конфигурации обучения (через API-запрос или env):
curl -X POST http://localhost:8080/v1/admin/models/train \
  -H 'Content-Type: application/json' \
  -d '{
    "trainer_type": "llm",
    "config": {
      "batch_size": 1,
      "max_seq_length": 256,
      "use_qlora": true,
      "load_in_4bit": true
    }
  }'

# 2. Используйте QLoRA (4-битная квантизация) для обучения LLM:
#    use_qlora: true
#    load_in_4bit: true

# 3. Используйте LoRA (не полную тонкую настройку) для уменьшения памяти:
#    use_lora: true
#    lora_r: 4       (было 8)

# 4. Используйте контрольную точку градиента (включите в коде тренера)

# 5. Используйте выгрузку на CPU (медленнее, но использует меньше VRAM)
#    Установите TRAINING_PROFILE=dev, который использует настройки с меньшим потреблением памяти

# 6. Проверьте доступную память GPU перед обучением
nvidia-smi --query-gpu=memory.free --format=csv
```

### 12.5 Порог EvalGate не достигнут

**Симптом:**
```
EvalGateError: Training failed quality gate
  - LLM BERTScore 0.65 < minimum 0.70
  - Reranker MRR 0.68 < minimum 0.75
```
Модель не может быть продвинута,因为她 не соответствует пороговым значениям качества.

**Причина:** Запуск обучения произвёл модель с более низким качеством, чем базовая версия.

**Решение:**
```bash
# 1. Проверьте, какие пороговые значения не пройдены
curl -s http://localhost:8080/v1/admin/models/status/<job_id> | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d.get('eval_results',{}), indent=2))"

# 2. Настройте пороговые значения (только если новая модель действительно приемлема)
#    В .env:
EVAL_GATE_LLM_BERTSCORE_MIN=0.65    # было 0.70
EVAL_GATE_RERANKER_MRR_MIN=0.65     # было 0.75

# 3. Или обучите на большем количестве эпох
curl -X POST http://localhost:8080/v1/admin/models/train \
  -H 'Content-Type: application/json' \
  -d '{"trainer_type": "llm", "config": {"epochs": 5}}'

# 4. Проверьте метрики базовой модели для сравнения
curl -s http://localhost:8080/v1/admin/models | python3 -m json.tool

# 5. Принудительное продвижение (обход ворот — не рекомендуется для продакшна)
curl -X POST http://localhost:8080/v1/admin/models/promote \
  -H 'Content-Type: application/json' \
  -d '{"model_version": "<version>", "force": true}'
```

### 12.6 Сбой горячей перезагрузки адаптера

**Симптом:**
```
AdapterError: Failed to load adapter from /models/adapters/checkpoint-1000
AdapterError: Version mismatch — adapter requires base model v3 but v2 is loaded
```

**Причина:** Контрольная точка адаптера несовместима с текущей загруженной базовой моделью.

**Решение:**
```bash
# 1. Проверьте текущий активный адаптер
curl -s http://localhost:8080/v1/admin/models | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print('Активные адаптеры:', d.get('active_adapters',{}))"

# 2. Проверьте совместимость адаптера
#    Адаптеры привязаны к конкретной базовой модели — убедитесь, что базовая модель не изменилась.

# 3. Вручную перезагрузите адаптер
curl -X POST http://localhost:8080/v1/admin/models/hot-reload \
  -H 'Content-Type: application/json' \
  -d '{"adapter_path": "/models/adapters/checkpoint-1000"}'

# 4. Если горячая перезагрузка не удалась, перезапустите прокси с новым адаптером
docker-compose -f proxy/docker-compose.yml restart rag-proxy
# Затем запустите прогрев:
curl -X POST http://localhost:8080/v1/admin/warmup

# 5. Проверьте интервал горячей перезагрузки (фоновый наблюдатель)
grep -E 'HOT_RELOAD_ENABLED|HOT_RELOAD_WATCH_INTERVAL' proxy/.env
# Если включено, адаптеры автоматически перезагружаются каждые HOT_RELOAD_WATCH_INTERVAL секунд
```

### 12.7 Канареечное развёртывание зависло

**Симптом:**
```
CanaryController: Phase 25% not progressing — waiting for metric validation
CanaryController: Cooldown active — cannot advance phase
```

**Причина:** Метрики канарейки не стабилизировались, частота ошибок повышена или период ожидания не истёк.

**Решение:**
```bash
# 1. Проверьте статус канарейки
curl -s http://localhost:8080/v1/admin/models/canary/status | python3 -m json.tool

# 2. Мониторьте метрики канарейки vs базовой версии
curl -s http://localhost:8080/metrics | grep -E 'canary|baseline'

# 3. Вручную продвиньте фазу
curl -X POST http://localhost:8080/v1/admin/models/canary/advance \
  -H 'Content-Type: application/json' \
  -d '{"phase": "50"}'

# 4. Если модель канарейки проблематична, немедленно откатите
curl -X POST http://localhost:8080/v1/admin/models/rollback

# 5. Проверьте конфигурацию периода ожидания канарейки
grep -E 'CANARY_PHASE_DURATION|CANARY_COOLDOWN|CANARY_ENABLED' proxy/.env

# 6. Полностью отключите канарейку
CANARY_ENABLED=false
docker-compose -f proxy/docker-compose.yml restart rag-proxy
```

---

## Приложение A: Конфигурация логирования

### Включение отладочного логирования

```bash
# В .env:
LOG_LEVEL=DEBUG
LOG_FORMAT=json    # структурированное логирование для агрегации

# Перезапустите прокси
docker-compose -f proxy/docker-compose.yml restart rag-proxy

# Просмотр с фильтрацией
docker logs rag-proxy -f 2>&1 | grep -E 'ERROR|WARN|duration'
```

### Маскирование секретов в логах

```bash
# Дополнительные секреты для маскирования (через запятую):
SENSITIVE_SECRETS=API_KEY,PERSONAL_TOKEN,PRIVATE_KEY
```

### Аудит-логирование

```bash
# Включите аудит-логирование
AUDIT_ENABLED=true

# Аудит-логи хранятся в LOG_DIR/audit/
ls proxy/logs/audit/
```

---

## Приложение B: Полезные однострочники для диагностики

```bash
# Полное резюме состояния системы
echo "=== Прокси ===" && curl -s http://localhost:8080/v1/health | python3 -m json.tool
echo "=== Qdrant ===" && curl -s http://localhost:6333/collections/knowledge_base | python3 -c "import sys,json; d=json.load(sys.stdin).get('result',{}); print(f'Векторы: {d.get(\"vectors_count\",\"?\")} | Сегменты: {d.get(\"segments_count\",\"?\")}')"
echo "=== Neo4j ===" && docker exec rag-neo4j cypher-shell -u neo4j -p password "MATCH (n) RETURN count(n) as total_nodes" 2>/dev/null || echo "Neo4j: НЕДОСТУПЕН"
echo "=== Redis ===" && docker exec rag-redis redis-cli PING 2>/dev/null && docker exec rag-redis redis-cli INFO memory | grep used_memory_human
echo "=== LLM ===" && curl -s http://localhost:8000/health 2>/dev/null || echo "LLM: НЕДОСТУПЕН"
echo "=== GPU ===" && nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv,noheader 2>/dev/null || echo "GPU: Н/Д"
echo "=== Диск ===" && df -h /var/lib/docker/volumes/ | tail -n +2
echo "=== CB ===" && curl -s http://localhost:8080/metrics | grep circuit_breaker_state && echo "" || echo "Нет метрик автоматического выключателя"

# Последние ошибки от всех сервисов
docker-compose -f proxy/docker-compose.yml logs --tail=100 2>&1 | grep -iE 'error|exception|traceback|fatal|panic|oom' | tail -20

# Потребители памяти с наибольшим потреблением
docker stats --no-stream --format "table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}"

# История перезапусков сервисов
docker ps -a --format "table {{.Names}}\t{{.Status}}" | grep rag-
```

---

## Приложение C: Быстрая справка по типовым исправлениям

| Проблема | Симптом | Быстрое исправление |
|----------|---------|---------------------|
| Прокси не запускается | `Address already in use` | `kill $(lsof -ti:8080)` или измените PORT |
| Qdrant недоступен | `Connection refused` | `docker-compose up -d qdrant` |
| Пустые результаты поиска | `0 чанков` | Запустите ETL: `python etl/scheduler/run_etl.py` |
| Медленные запросы (>5 сек) | Высокая p95 латентность | Уменьшите `MAX_CHUNKS_RETRIEVAL` до 20 |
| Таймаут LLM | `Read timed out` | Увеличьте `REQUEST_TIMEOUT` до 300 |
| CUDA OOM | `OutOfMemoryError` | Установите `EMBEDDER_DEVICE=cpu` |
| 401 Unauthorized | `Invalid token` | Проверьте `JWT_SECRET` или войдите заново |
| 403 Forbidden | `Role not sufficient` | Запросите более высокую роль у администратора |
| 429 Rate limited | `Rate limit exceeded` | Подождите или увеличьте `RATE_LIMIT_PER_MINUTE` |
| Redis — отказ в подключении | `Error 111` | `docker-compose restart redis` |
| Neo4j недоступен | `ServiceUnavailable` | Подождите загрузки Neo4j, проверьте учётные данные |
| Много сегментов Qdrant | `segments_count > 200` | Уменьшите `indexing_threshold` для объединения |
| ImagePullBackOff | `pull access denied` | `docker-compose build` вместо загрузки |
| CrashLoopBackOff | Повторные перезапуски | `kubectl logs <pod> --previous` |
| OOMKilled | Код выхода 137 | Увеличьте лимит памяти или уменьшите использование |
| Обучение зависло | Статус "running" > 1 ч | Проверьте GPU: `nvidia-smi` |
| MLflow недоступен | Отказ в подключении | `docker-compose restart mlflow` |
| MinIO — отказано в доступе | `AccessDenied` | Проверьте учётные данные, создайте bucket |
| Устаревший кэш | Старые результаты | `docker exec rag-redis redis-cli FLUSHDB` |
| Автоматический выключатель открыт | Состояние `OPEN` | Устраните основную проблему, затем сбросьте |
