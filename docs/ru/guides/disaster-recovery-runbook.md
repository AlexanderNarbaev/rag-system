# Runbook аварийного восстановления

**Версия:** v1.0.0
**Последнее обновление:** 2026-06-26
**RTO:** < 30 мин | **RPO:** < 1 час

---

## Обзор

Этот runbook содержит пошаговые процедуры восстановления для всех сценариев отказов в production-развёртывании RAG-системы. Каждый сценарий включает методы обнаружения, оценку влияния, шаги восстановления и критерии проверки.

### Предварительные требования

- Доступ к бакету S3/MinIO для резервных копий (учётные данные в переменных `BACKUP_S3_*`)
- SSH-доступ ко всем узлам (или `kubectl` доступ к K8s-кластеру)
- Скрипты `scripts/backup.sh` и `scripts/restore_all.sh` доступны на административной машине
- Доступ к дашборду мониторинга (Grafana) для верификации

### Расписание резервного копирования

| Компонент | Частота | Хранение | Расположение |
|-----------|---------|----------|-------------|
| Снапшоты Qdrant | Каждые 6 часов | 7 дневных, 4 недельных, 3 месячных | `s3://backup-rag/qdrant/` |
| Дампы Neo4j | Каждые 6 часов | 7 дневных, 4 недельных, 3 месячных | `s3://backup-rag/neo4j/` |
| Redis RDB | Каждый 1 час | 24 часовых, 7 дневных | `s3://backup-rag/redis/` |
| ETL WAL состояние | Каждые 30 мин | 7 дневных | `s3://backup-rag/etl/` |

---

## Сценарии восстановления

### 1. Потеря данных Qdrant

**Обнаружение:**
- Коллекции Qdrant показывают 0 векторов (`curl localhost:6333/collections/<name>`)
- Health check прокси показывает `qdrant: "degraded"` или `"unhealthy"`
- Весь поиск не работает, прокси возвращает пустые контексты
- Prometheus alert: `QdrantUnhealthy` (critical)

**Влияние:** Весь поиск не работает. Прокси возвращает пустые контексты с `rag_confidence: 0`. Пользователи получают ответы "У меня недостаточно информации".

**Шаги восстановления:**

```bash
# 1. Остановить ETL-конвейер, чтобы предотвратить запись неполных данных
systemctl stop rag-etl
# K8s: kubectl scale deployment rag-etl --replicas=0

# 2. Восстановить из последнего снапшота Qdrant
bash scripts/restore_all.sh qdrant --latest

# 3. Проверить восстановление
curl -s localhost:6333/collections | jq '.result.collections[].vectors_count'

# 4. Определить временную метку последнего бэкапа
BACKUP_TS=$(aws s3 ls s3://backup-rag/qdrant/ --recursive | sort | tail -1 | awk '{print $1" "$2}')
echo "Последний бэкап: $BACKUP_TS"

# 5. Перезапустить ETL для дельты с момента последнего бэкапа
python scheduler/run_etl.py --since "$BACKUP_TS" --config config/etl_config.yaml

# 6. Проверить работу поиска
curl -X POST localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"rag","messages":[{"role":"user","content":"тестовый запрос"}]}' | jq '.rag_confidence'

# 7. Перезапустить ETL в обычном режиме
systemctl start rag-etl
```

**RTO:** < 30 мин | **RPO:** < 1 час

---

### 2. Потеря данных Neo4j

**Обнаружение:**
- Neo4j возвращает 0 узлов (`MATCH (n) RETURN count(n)` → 0)
- Health check прокси показывает `neo4j: "degraded"` или `"unhealthy"`
- Графовое расширение выдаёт пустые результаты
- Prometheus alert: `Neo4jUnhealthy` (warning — прокси деградирует грациозно)

**Влияние:** Графовое расширение пропускается. Агентные запросы теряют контекст сущностей (~500 токенов). Неагентные запросы не затронуты. Прокси автоматически пропускает графовое обогащение согласно дизайну graceful degradation.

**Шаги восстановления:**

```bash
# 1. Остановить ETL-конвейер
systemctl stop rag-etl

# 2. Восстановить из последнего дампа Neo4j
bash scripts/restore_all.sh neo4j --latest

# 3. Проверить восстановление
cypher-shell -u neo4j -p "$NEO4J_PASSWORD" "MATCH (n) RETURN count(n) AS node_count;"

# 4. Перезапустить ETL для дельты
python scheduler/run_etl.py --since "$BACKUP_TS" --config config/etl_config.yaml

# 5. Перезапустить ETL
systemctl start rag-etl
```

**RTO:** < 30 мин | **RPO:** < 1 час

---

### 3. Потеря данных Redis

**Обнаружение:**
- `redis-cli DBSIZE` → 0
- Health check прокси показывает `redis: "degraded"`
- Коэффициент попаданий в кэш падает до 0
- Prometheus alert: `RedisDown` (warning)

**Влияние:** Только промахи кэша. Данные не теряются — всё перевычислимо. Временно увеличивается задержка (перевычисление эмбеддингов, повторный поиск в Qdrant). Ошибок для пользователей нет. Прокси автоматически переключается на in-memory кэш.

**Восстановление:**
- **Восстановление не требуется.** Redis используется только для кэширования. Прокси автоматически переключается на in-memory LRU-кэш.
- Кэш самовосстановится при обычном трафике.
- Для ускорения: запустить прогрев `curl -X POST localhost:8080/v1/admin/warmup`

```bash
# Проверить восстановление кэша
curl -s localhost:8080/metrics | grep rag_cache_hit_ratio
```

**RTO:** 0 мин (автовосстановление) | **RPO:** Н/Д (только кэш)

---

### 4. Отказ узла (вычислительного)

**Обнаружение:**
- Узел недоступен по SSH/kubectl
- Kubernetes: статус пода `Pending` или `CrashLoopBackOff`
- Prometheus alert: `NodeDown` (critical)
- Grafana: метрики CPU/памяти узла на нуле

**Влияние (K8s):** Минимальное. Поды автоматически перераспределяются планировщиком Kubernetes. Кратковременное прерывание при перераспределении (< 30с).

**Влияние (Docker Compose):** Полный отказ сервисов на отказавшем узле. Требуется ручной перезапуск.

**Восстановление (Kubernetes):**

```bash
# 1. Проверить перераспределение подов
kubectl get pods -n rag-system -o wide

# 2. Проверить застрявшие поды
kubectl get pods -n rag-system --field-selector=status.phase=Pending

# 3. Если поды застряли в Terminating (узел потерян без drain):
kubectl delete pod <pod-name> -n rag-system --force --grace-period=0

# 4. Проверить здоровье всех сервисов
kubectl exec -it deploy/rag-proxy -n rag-system -- curl -s localhost:8080/v1/health

# 5. Проверить HPA
kubectl get hpa -n rag-system
```

**Восстановление (Docker Compose):**

```bash
# 1. SSH на запасной узел
# 2. Запустить сервисы
cd rag-system/proxy && docker-compose up -d

# 3. Проверить здоровье
curl localhost:8080/v1/health
```

**RTO:** < 1 мин (K8s) / < 5 мин (Docker Compose)

---

### 5. Разделение сети (Network Partition)

**Обнаружение:**
- Прокси не может достичь Qdrant/Neo4j/Redis (connection refused или timeout)
- Health check показывает компоненты как `"unhealthy"`
- Prometheus alerts: `QdrantUnhealthy` (critical), `Neo4jUnhealthy` (warning)
- Логи показывают `ConnectionError` или `TimeoutError` для внутренних сервисов

**Влияние:** Включается graceful degradation:
- Qdrant недоступен → 503 на `/v1/chat/completions`
- Neo4j недоступен → пропуск графового расширения
- Redis недоступен → переключение на in-memory кэш

**Шаги восстановления:**

```bash
# 1. Проверить сетевую связность между компонентами
ping <qdrant-host>
nc -zv <qdrant-host> 6333
nc -zv <neo4j-host> 7687
nc -zv <redis-host> 6379

# 2. Проверить файрволы
iptables -L -n | grep -E "6333|7687|6379"
# K8s: kubectl describe networkpolicy -n rag-system

# 3. Проверить DNS
nslookup qdrant.<namespace>.svc.cluster.local

# 4. Перезапустить затронутые компоненты при необходимости
# K8s: kubectl rollout restart deployment/<component> -n rag-system
# Docker: docker-compose restart <service>

# 5. Проверить восстановление
curl localhost:8080/v1/health | jq '.components'
```

**RTO:** < 10 мин | **RPO:** Н/Д

---

### 6. Полный отказ (все сервисы)

**Обнаружение:**
- Все сервисы недоступны
- `/v1/health` возвращает 503 или connection refused
- Все Prometheus-алерты срабатывают одновременно
- Grafana показывает 0 запросов, 0 метрик

**Влияние:** Полная недоступность сервиса. Все API-эндпоинты возвращают ошибки.

**Шаги восстановления (полное восстановление из S3):**

```bash
# === ФАЗА 1: Восстановление данных (15-20 мин) ===

# 1. Восстановить Qdrant из последнего снапшота
bash scripts/restore_all.sh qdrant --latest

# 2. Восстановить Neo4j из последнего дампа
bash scripts/restore_all.sh neo4j --latest

# 3. Проверить целостность данных
curl -s localhost:6333/collections | jq '.result.collections[].vectors_count'
cypher-shell -u neo4j -p "$NEO4J_PASSWORD" "MATCH (n) RETURN count(n);"

# === ФАЗА 2: Запуск сервисов (5 мин) ===

# 4. Сначала инфраструктурные сервисы
docker-compose up -d qdrant neo4j redis
# K8s: kubectl apply -f infra/

# 5. Дождаться готовности
until curl -s localhost:6333/health | grep -q ok; do sleep 2; done
until curl -s localhost:7474 | grep -q neo4j; do sleep 2; done
until redis-cli ping | grep -q PONG; do sleep 2; done

# 6. Запустить прокси
docker-compose up -d proxy
# K8s: kubectl apply -f proxy/

# === ФАЗА 3: Проверка (5 мин) ===

# 7. Проверить все компоненты
curl localhost:8080/v1/health | jq '.'
# Ожидается: {"status":"ok","qdrant":"healthy","neo4j":"healthy","redis":"healthy","llm":"healthy"}

# 8. Тестовый поиск
curl -X POST localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "rag",
    "messages": [{"role": "user", "content": "Какой процесс развёртывания?"}]
  }' | jq '{confidence: .rag_confidence, sources: .rag_sources | length}'

# 9. Запустить ETL (дельта с последнего бэкапа)
systemctl start rag-etl

# 10. Проверить расписание бэкапов
systemctl status rag-backup.timer
kubectl get cronjob -n rag-system | grep backup
```

**RTO:** < 30 мин | **RPO:** < 1 час

---

### 7. Отказ LLM-бэкенда

**Обнаружение:**
- Сервер инференса LLM недоступен (connection refused / timeout)
- Health check прокси показывает `llm: "unhealthy"`
- `/v1/chat/completions` возвращает 503
- Prometheus alert: `LLMDown` (critical)

**Влияние:** Генерация невозможна. Все запросы chat completion возвращают 503. Health и metrics эндпоинты остаются доступны.

**Шаги восстановления:**

```bash
# 1. Проверить статус LLM-бэкенда
curl $LLM_ENDPOINT/health  # vLLM
curl $LLM_ENDPOINT/health  # llama.cpp
# OpenAI-совместимый: curl $LLM_ENDPOINT/models

# 2. Перезапустить LLM-бэкенд
# vLLM:
systemctl restart vllm
# K8s: kubectl rollout restart deployment/vllm -n rag-system

# 3. Дождаться загрузки модели (1-5 мин)
until curl -s $LLM_ENDPOINT/models | grep -q "$LLM_MODEL_NAME"; do
  echo "Ожидание загрузки LLM..."
  sleep 10
done

# 4. Прогрев модели
curl -X POST localhost:8080/v1/admin/warmup -d '{"warmup_llm": true}'

# 5. Проверка
curl localhost:8080/v1/health | jq '.llm'
```

**RTO:** < 5 мин (модель в памяти) / < 10 мин (холодный старт)

---

### 8. Переполнение диска

**Обнаружение:**
- Prometheus alert: `DiskNearFull` (warning на 85%, critical на 95%)
- Дашборд Grafana показывает рост использования диска
- Ошибки записи Qdrant: "No space left on device"
- Логи прокси: `OSError: [Errno 28] No space left on device`

**Влияние:** Сервисы прекращают запись. Qdrant upserts падают. ETL останавливается.

**Шаги восстановления:**

```bash
# 1. Определить использование диска
df -h
du -sh /data/* | sort -rh | head -10

# 2. Очистить старые данные
# Удалить старые снапшоты Qdrant (>7 дней)
find /data/qdrant/snapshots -name "*.snapshot" -mtime +7 -delete

# Удалить старые бэкапы Neo4j
find /data/neo4j/backups -name "*.dump" -mtime +7 -delete

# Удалить старые Redis RDB
find /data/redis/backups -name "*.rdb" -mtime +3 -delete

# Очистить Docker артефакты
docker system prune -af --volumes

# 3. Очистка холодного хранилища
python scripts/cleanup_cold_storage.py --keep-versions 3

# 4. Ротация логов
logrotate -f /etc/logrotate.d/rag-system

# 5. Проверить освобождённое место
df -h /data/

# 6. Перезапустить затронутые сервисы
systemctl restart rag-etl
```

**RTO:** < 15 мин

---

## Чек-лист проверки

После любой процедуры восстановления выполните этот чек-лист:

- [ ] Коллекция Qdrant имеет ожидаемое количество векторов: `curl localhost:6333/collections | jq '.result.collections[].vectors_count'`
- [ ] Neo4j имеет ожидаемое количество узлов: `cypher-shell "MATCH (n) RETURN count(n)"`
- [ ] Redis принимает соединения: `redis-cli PING` → `PONG`
- [ ] Health check прокси возвращает 200: `curl -s -o /dev/null -w "%{http_code}" localhost:8080/v1/health`
- [ ] Все компоненты здоровы: `curl localhost:8080/v1/health | jq '.components | to_entries | map(select(.value != "healthy"))'` → `[]`
- [ ] Тестовый запрос возвращает confidence > 0.5: `curl -X POST localhost:8080/v1/chat/completions -H "Content-Type: application/json" -d '{"model":"rag","messages":[{"role":"user","content":"Что такое RAG-система?"}]}' | jq '.rag_confidence'`
- [ ] Prometheus метрики доступны: `curl -s localhost:8080/metrics | grep rag_cache_hit_ratio`
- [ ] Дашборд Grafana показывает здоровые метрики
- [ ] Расписание бэкапов активно: `systemctl status rag-backup.timer` или `kubectl get cronjob rag-backup`
- [ ] ETL-конвейер работает: `systemctl status rag-etl` или `kubectl get pods -l app=rag-etl`

---

## Экстренные контакты

| Роль | Контакт | Эскалация |
|------|---------|-----------|
| Основной дежурный | См. расписание PagerDuty | Через 15 мин: вторичный |
| DevOps лид | См. список команды | Через 30 мин: руководитель разработки |
| Инфраструктура | См. список команды | Через 45 мин: CTO |

---

## Расписание DR-тренировок

| Частота | Объём | Целевая длительность |
|---------|-------|---------------------|
| Ежемесячно | Отказ одного компонента (восстановление Qdrant или Neo4j) | < 1 час |
| Ежеквартально | Полное восстановление из S3-бэкапов | < 2 часа |
| Ежегодно | Симуляция полного отказа ЦОД | < 4 часа |
