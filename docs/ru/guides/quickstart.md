# Быстрый старт

**Версия:** v2.0.0 | **Обновлено:** 2026-07-10

Запустите корпоративный ассистент знаний RAG за 5 минут. Руководство охватывает локальную настройку для разработки с использованием Docker Compose.

---

## Предварительные требования

| Требование | Версия | Примечание |
|------------|--------|------------|
| **Docker** | 24.0+ | С плагином Compose v2 |
| **Python** | 3.11+ | Для ETL и локальной разработки |
| **RAM** | 16 ГБ минимум | 32 ГБ рекомендуется |
| **Диск** | 20 ГБ свободно | SSD настоятельно рекомендуется |
| **GPU** | Опционально | Режим только CPU подходит для тестирования |

!!! tip "Ускорение на GPU"
    NVIDIA GPU с 12+ ГБ VRAM рекомендуется для генерации LLM. Без GPU система работает в режиме CPU с значительно меньшей скоростью ответов. Также можно указать удалённую LLM-конечную точку.

---

## Шаг 1 — Клонирование репозитория

```bash
git clone https://github.com/AlexanderNarbaev/rag-system.git
cd rag-system
```

Ожидаемый вывод:

```
Cloning into 'rag-system'...
remote: Enumerating objects: ...
Receiving objects: 100% (...)
```

---

## Шаг 2 — Настройка окружения

```bash
# Скопировать пример файла окружения
cp proxy/.env.example proxy/.env

# Отредактировать с вашими настройками (минимум — указать LLM-эндпоинт)
nano proxy/.env
```

### Минимальная конфигурация

Как минимум, задайте эти переменные в `proxy/.env`:

```bash
# Qdrant (использует имя сервиса Docker по умолчанию)
QDRANT_HOST=qdrant

# LLM-бэкенд — выберите один вариант:

# Вариант A: Локальный vLLM (требуется GPU)
LLM_ENDPOINT=http://vllm:8000/v1
LLM_MODEL_NAME=your-model-name
LLM_PROVIDER=vllm

# Вариант B: Сервер llama.cpp
LLM_ENDPOINT=http://llama-cpp:8080/v1
LLM_MODEL_NAME=your-model-name
LLM_PROVIDER=llama_cpp

# Вариант C: Любая OpenAI-совместимая конечная точка
LLM_ENDPOINT=https://your-api.example.com/v1
LLM_MODEL_NAME=your-model-name
LLM_PROVIDER=openai_compatible
```

!!! warning "Нет LLM-эндпоинта?"
    Если у вас ещё нет LLM-бэкенда, система запустится, но запросы на генерацию будут возвращать ошибки. Можно проверить эндпоинты состояния и изучить API. Инструкции по настройке LLM см. в [Руководстве по развёртыванию](deployment-guide.md).

---

## Шаг 3 — Запуск сервисов

```bash
# Запустить всю инфраструктуру (Qdrant + Redis + Neo4j + Proxy)
cd proxy && docker compose up -d
```

Ожидаемый вывод:

```
[+] Running 5/5
 ✔ Network proxy_default    Created
 ✔ Container qdrant         Started
 ✔ Container redis          Started
 ✔ Container neo4j          Started
 ✔ Container rag-proxy      Started
```

!!! note "Первый запуск"
    Первый запуск занимает 1-2 минуты, пока загружаются образы Docker. Последующие запуски занимают ~10 секунд.

### Проверка сервисов

```bash
# Проверить, что все контейнеры запущены
docker compose ps

# Проверить здоровье прокси
curl http://localhost:8080/v1/health
```

Ожидаемый ответ health:

```json
{
  "status": "healthy",
  "qdrant": "connected",
  "llm": "connected",
  "version": "2.0.0"
}
```

---

## Шаг 4 — Тестирование API

### Простой запрос чата

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "rag-proxy",
    "messages": [
      {"role": "user", "content": "Что такое RAG?"}
    ]
  }'
```

### Потоковый ответ

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "rag-proxy",
    "messages": [
      {"role": "user", "content": "Объясни гибридный поиск в RAG-системах"}
    ],
    "stream": true
  }'
```

### Использование Python

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8080/v1",
    api_key="not-needed",  # Аутентификация отключена по умолчанию
)

response = client.chat.completions.create(
    model="rag-proxy",
    messages=[
        {"role": "user", "content": "Что такое RAG?"}
    ],
    stream=True,
)

for chunk in response:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")
```

### Использование JavaScript

```javascript
const response = await fetch("http://localhost:8080/v1/chat/completions", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    model: "rag-proxy",
    messages: [{ role: "user", content: "Что такое RAG?" }],
  }),
});

const data = await response.json();
console.log(data.choices[0].message.content);
```

---

## Шаг 5 — Изучение API

### Список доступных моделей

```bash
curl http://localhost:8080/v1/models
```

### Метрики Prometheus

```bash
curl http://localhost:8080/metrics
```

### Виджет чата

Откройте в браузере:

```
http://localhost:8080/v1/widget
```

### Зонды здоровья для K8s

```bash
# Liveness
curl http://localhost:8080/v1/health/live

# Readiness
curl http://localhost:8080/v1/health/ready
```

---

## Типичные проблемы и решения

### 1. «Connection refused» при запуске

**Симптом:** `curl: (7) Failed to connect to localhost port 8080`

**Причина:** Контейнер прокси ещё запускается или упал.

**Решение:**

```bash
# Проверить состояние контейнера
docker compose ps

# Проверить логи прокси на ошибки
docker compose logs rag-proxy --tail=50

# Если контейнер завершился, перезапустить
docker compose restart rag-proxy
```

### 2. Ошибки подключения к Qdrant

**Симптом:** Health check показывает `"qdrant": "disconnected"`

**Причина:** Контейнер Qdrant не готов или указан неверный хост.

**Решение:**

```bash
# Убедиться, что Qdrant запущен
docker compose ps qdrant

# Проверить логи Qdrant
docker compose logs qdrant --tail=20

# Убедиться, что QDRANT_HOST совпадает с именем сервиса Docker
grep QDRANT_HOST proxy/.env
# Должно быть: QDRANT_HOST=qdrant (не localhost)
```

### 3. LLM-бэкенд недоступен

**Симптом:** Health check показывает `"llm": "disconnected"`

**Причина:** Неверно настроен LLM-эндпоинт или бэкенд не запущен.

**Решение:**

```bash
# Проверить LLM-эндпоинт напрямую
curl http://your-llm-endpoint:8000/v1/models

# Проверить логи прокси на детали подключения
docker compose logs rag-proxy | grep -i "llm"

# Обновить LLM_ENDPOINT в proxy/.env
```

### 4. Нехватка памяти (OOM)

**Симптом:** Контейнер неожиданно завершается, `dmesg` показывает OOM killer.

**Причина:** Недостаточно RAM для модели и сервисов.

**Решение:**

```bash
# Проверить использование памяти
docker stats --no-stream

# Уменьшить потребление: отключить необязательные функции
# В proxy/.env:
GRAPH_ENABLED=false    # Отключить Neo4j
USE_REDIS=false        # Использовать кэш в памяти
```

### 5. Порт уже занят

**Симптом:** `Bind for 0.0.0.0:8080 failed: port is already allocated`

**Решение:**

```bash
# Найти, что использует порт
lsof -i :8080

# Изменить порт в docker-compose.yml
# Или остановить конфликтующий сервис
```

### 6. Отказ в доступе к томам

**Симптом:** `PermissionError` в логах контейнера.

**Решение:**

```bash
# Исправить права на директорию данных
sudo chown -R 1000:1000 proxy/data/
```

---

## Следующие шаги

Теперь, когда система запущена:

| Цель | Руководство |
|------|-------------|
| **Загрузить данные** | [Руководство ETL](etl-guide.md) — Подключение Confluence, Jira, GitLab |
| **Развёртывание в продакшен** | [Руководство по развёртыванию](deployment-guide.md) — K8s, HA, GPU |
| **Изучить API** | [Примеры API](api-examples.md) — curl, Python, JavaScript |
| **Полная справка API** | [Справочник API](../../api_reference.md) — Все эндпоинты, схемы, параметры |
| **Настроить аутентификацию** | [Управление доступом](access-control-rbac.md) — JWT, Keycloak, LDAP |
| **Добавить инструменты** | [SDK агентных инструментов](agentic-tools-sdk.md) — Декоратор `@tool` |
| **Настроить производительность** | [Производительность и качество](performance-quality.md) — HNSW, кэширование |
| **Мониторинг** | [Руководство по эксплуатации](operations-guide.md) — Prometheus, Grafana |

---

## Остановка сервисов

```bash
cd proxy

# Остановить все сервисы (данные сохраняются)
docker compose down

# Остановить и удалить томы (чистый старт)
docker compose down -v

# Остановить и удалить образы
docker compose down -v --rmi all
```

---

## Быстрая справка

| Команда | Описание |
|---------|----------|
| `docker compose up -d` | Запустить все сервисы |
| `docker compose down` | Остановить все сервисы |
| `docker compose logs -f` | Следить за всеми логами |
| `docker compose logs rag-proxy` | Только логи прокси |
| `docker compose ps` | Список запущенных контейнеров |
| `docker compose restart` | Перезапустить все сервисы |
| `curl localhost:8080/v1/health` | Проверка здоровья |
| `curl localhost:8080/v1/models` | Список моделей |
| `curl localhost:8080/metrics` | Метрики Prometheus |
