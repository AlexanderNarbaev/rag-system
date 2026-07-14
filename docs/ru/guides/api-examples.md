# Примеры API

**Версия:** v2.0.0 | **Обновлено:** 2026-07-10

Практические примеры для каждого эндпоинта API RAG-системы с использованием **curl**, **Python (httpx)** и *
*JavaScript (fetch)**. Все примеры предполагают, что прокси запущен по адресу `http://localhost:8080`.

---

## Базовый URL

```
http://localhost:8080/v1
```

При включённой аутентификации во все запросы добавляйте JWT-токен:

```
Authorization: Bearer <access_token>
```

---

## Завершение чата

### Простой чат

=== "curl"

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

=== "Python"

    ```python
    import httpx

    response = httpx.post(
        "http://localhost:8080/v1/chat/completions",
        json={
            "model": "rag-proxy",
            "messages": [
                {"role": "user", "content": "Что такое RAG?"}
            ],
        },
    )
    data = response.json()
    print(data["choices"][0]["message"]["content"])
    ```

=== "JavaScript"

    ```javascript
    const response = await fetch("http://localhost:8080/v1/chat/completions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: "rag-proxy",
        messages: [
          { role: "user", content: "Что такое RAG?" },
        ],
      }),
    });

    const data = await response.json();
    console.log(data.choices[0].message.content);
    ```

### Потоковый ответ

=== "curl"

    ```bash
    curl -X POST http://localhost:8080/v1/chat/completions \
      -H "Content-Type: application/json" \
      -d '{
        "model": "rag-proxy",
        "messages": [
          {"role": "user", "content": "Объясни гибридный поиск"}
        ],
        "stream": true
      }'
    ```

=== "Python"

    ```python
    import httpx

    with httpx.stream(
        "POST",
        "http://localhost:8080/v1/chat/completions",
        json={
            "model": "rag-proxy",
            "messages": [
                {"role": "user", "content": "Объясни гибридный поиск"}
            ],
            "stream": True,
        },
    ) as response:
        for line in response.iter_lines():
            if line.startswith("data: ") and line != "data: [DONE]":
                import json
                chunk = json.loads(line[6:])
                content = chunk["choices"][0]["delta"].get("content", "")
                if content:
                    print(content, end="", flush=True)
    ```

=== "JavaScript"

    ```javascript
    const response = await fetch("http://localhost:8080/v1/chat/completions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: "rag-proxy",
        messages: [{ role: "user", content: "Объясни гибридный поиск" }],
        stream: true,
      }),
    });

    const reader = response.body.getReader();
    const decoder = new TextDecoder();

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const text = decoder.decode(value);
      const lines = text.split("\n").filter((l) => l.startsWith("data: "));
      for (const line of lines) {
        if (line === "data: [DONE]") break;
        const chunk = JSON.parse(line.slice(6));
        const content = chunk.choices[0]?.delta?.content;
        if (content) process.stdout.write(content);
      }
    }
    ```

### RAG-специфичные параметры

| Параметр              | Тип      | По умолчанию | Описание                                            |
|-----------------------|----------|--------------|-----------------------------------------------------|
| `rag_version`         | `string` | `null`       | Запрос конкретной версии документа                  |
| `rag_force_refresh`   | `bool`   | `false`      | Обход кэша ответов для получения свежих результатов |
| `rag_top_k`           | `int`    | `null`       | Переопределение количества извлекаемых чанков       |
| `rag_skip_generation` | `bool`   | `false`      | Возврат извлечённых чанков без генерации LLM        |
| `rag_return_chunks`   | `bool`   | `false`      | Включение сырых чанков в ответ                      |

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "rag-proxy",
    "messages": [
      {"role": "user", "content": "Что изменилось в руководстве по развёртыванию?"}
    ],
    "rag_version": "2026-07-01",
    "rag_force_refresh": true,
    "rag_top_k": 5
  }'
```

**Возврат чанков без генерации** (полезно для отладки поиска):

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "rag-proxy",
    "messages": [
      {"role": "user", "content": "руководство по развёртыванию"}
    ],
    "rag_skip_generation": true,
    "rag_return_chunks": true
  }'
```

### Инструменты / Вызов функций

Передайте `tools` в запросе для включения агентского вызова инструментов. Прокси выбирает и вызывает инструменты
автоматически через оркестратор.

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "rag-proxy",
    "messages": [
      {"role": "user", "content": "Найди документы по развёртыванию в Confluence"}
    ],
    "tools": [
      {
        "type": "function",
        "function": {
          "name": "search_confluence",
          "description": "Поиск страниц Confluence по запросу",
          "parameters": {
            "type": "object",
            "properties": {
              "query": {
                "type": "string",
                "description": "Поисковый запрос"
              },
              "max_results": {
                "type": "integer",
                "description": "Максимум результатов",
                "default": 5
              }
            },
            "required": ["query"]
          }
        }
      }
    ]
  }'
```

=== "Python"

    ```python
    import httpx

    response = httpx.post(
        "http://localhost:8080/v1/chat/completions",
        json={
            "model": "rag-proxy",
            "messages": [
                {"role": "user", "content": "Найди документы по развёртыванию"}
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "search_confluence",
                        "description": "Поиск страниц Confluence",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string"},
                            },
                            "required": ["query"],
                        },
                    },
                }
            ],
        },
    )
    data = response.json()
    print(data["choices"][0]["message"]["content"])
    ```

=== "JavaScript"

    ```javascript
    const response = await fetch("http://localhost:8080/v1/chat/completions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: "rag-proxy",
        messages: [{ role: "user", content: "Найди документы по развёртыванию" }],
        tools: [
          {
            type: "function",
            function: {
              name: "search_confluence",
              description: "Поиск страниц Confluence",
              parameters: {
                type: "object",
                properties: { query: { type: "string" } },
                required: ["query"],
              },
            },
          },
        ],
      }),
    });
    const data = await response.json();
    console.log(data.choices[0].message.content);
    ```

### Многораундовый диалог

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "rag-proxy",
    "messages": [
      {"role": "system", "content": "Ты полезный ассистент для внутренней документации."},
      {"role": "user", "content": "Как развернуть прокси?"},
      {"role": "assistant", "content": "Используйте docker compose up -d в директории proxy..."},
      {"role": "user", "content": "А что насчёт Kubernetes?"}
    ]
  }'
```

---

## Модели

### Список моделей

=== "curl"

    ```bash
    curl http://localhost:8080/v1/models
    ```

=== "Python"

    ```python
    import httpx

    response = httpx.get("http://localhost:8080/v1/models")
    for model in response.json()["data"]:
        print(f"  {model['id']}")
    ```

=== "JavaScript"

    ```javascript
    const response = await fetch("http://localhost:8080/v1/models");
    const data = await response.json();
    data.data.forEach((m) => console.log(m.id));
    ```

---

## Проверка состояния

### Здоровье сервиса

=== "curl"

    ```bash
    curl http://localhost:8080/v1/health
    ```

=== "Python"

    ```python
    import httpx

    r = httpx.get("http://localhost:8080/v1/health")
    health = r.json()
    print(f"Статус: {health['status']}")
    print(f"Qdrant: {health.get('qdrant', 'N/A')}")
    print(f"LLM: {health.get('llm', 'N/A')}")
    ```

### Liveness-зонд (K8s)

```bash
curl http://localhost:8080/v1/health/live
```

### Readiness-зонд (K8s)

```bash
curl http://localhost:8080/v1/health/ready
```

---

## Аутентификация

### Регистрация

=== "curl"

    ```bash
    curl -X POST http://localhost:8080/v1/auth/register \
      -H "Content-Type: application/json" \
      -d '{
        "username": "analyst",
        "password": "secure-password-123",
        "email": "analyst@company.com"
      }'
    ```

=== "Python"

    ```python
    import httpx

    r = httpx.post(
        "http://localhost:8080/v1/auth/register",
        json={
            "username": "analyst",
            "password": "secure-password-123",
            "email": "analyst@company.com",
        },
    )
    print(r.json())
    ```

=== "JavaScript"

    ```javascript
    const response = await fetch("http://localhost:8080/v1/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: "analyst",
        password: "secure-password-123",
        email: "analyst@company.com",
      }),
    });
    console.log(await response.json());
    ```

### Вход

=== "curl"

    ```bash
    curl -X POST http://localhost:8080/v1/auth/login \
      -H "Content-Type: application/json" \
      -d '{
        "username": "analyst",
        "password": "secure-password-123"
      }'
    ```

=== "Python"

    ```python
    import httpx

    r = httpx.post(
        "http://localhost:8080/v1/auth/login",
        json={"username": "analyst", "password": "secure-password-123"},
    )
    tokens = r.json()
    access_token = tokens["access_token"]
    refresh_token = tokens["refresh_token"]
    print(f"Access: {access_token[:20]}...")
    ```

=== "JavaScript"

    ```javascript
    const response = await fetch("http://localhost:8080/v1/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: "analyst", password: "secure-password-123" }),
    });
    const { access_token, refresh_token } = await response.json();
    ```

### Обновление токена

```bash
curl -X POST http://localhost:8080/v1/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "<your-refresh-token>"}'
```

### Текущий пользователь

```bash
curl http://localhost:8080/v1/auth/me \
  -H "Authorization: Bearer <access_token>"
```

### Выход

```bash
curl -X POST http://localhost:8080/v1/auth/logout \
  -H "Authorization: Bearer <access_token>"
```

---

## Обратная связь

### Положительная обратная связь

=== "curl"

    ```bash
    curl -X POST http://localhost:8080/v1/feedback \
      -H "Content-Type: application/json" \
      -H "Authorization: Bearer <access_token>" \
      -d '{
        "feedback_id": "fb-abc123",
        "rating": "positive",
        "comment": "Ответ был точным и хорошо подтверждён источниками"
      }'
    ```

=== "Python"

    ```python
    import httpx

    r = httpx.post(
        "http://localhost:8080/v1/feedback",
        headers={"Authorization": f"Bearer {access_token}"},
        json={
            "feedback_id": "fb-abc123",
            "rating": "positive",
            "comment": "Ответ был точным и хорошо подтверждён источниками",
        },
    )
    print(r.json())  # {"status": "ok", "message": "Feedback recorded"}
    ```

=== "JavaScript"

    ```javascript
    const response = await fetch("http://localhost:8080/v1/feedback", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${accessToken}`,
      },
      body: JSON.stringify({
        feedback_id: "fb-abc123",
        rating: "positive",
        comment: "Ответ был точным и хорошо подтверждён источниками",
      }),
    });
    console.log(await response.json());
    ```

### Отрицательная обратная связь с исправлением

```bash
curl -X POST http://localhost:8080/v1/feedback \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <access_token>" \
  -d '{
    "feedback_id": "fb-def456",
    "rating": "negative",
    "comment": "Ответ не учёл последнее обновление политики",
    "correction": "Правильная процедура — подача через новый портал"
  }'
```

!!! note
Поле `feedback_id` берётся из поля `rag_feedback_id` в ответе на запрос чата. Поле `correction` (единственное число)
содержит исправленный текст ответа. Поле `comment` — необязательная заметка эксперта. Требуется роль `expert` или
`admin`.

---

## Файлы

API файлов предоставляет операции загрузки, скачивания, списка и удаления на базе MinIO. Требуется роль `user` или выше.

!!! info
API файлов требует настройки MinIO/S3. Установите `boto3` (`pip install boto3`) и задайте переменные окружения `MINIO_*`
в `proxy/.env`.

### Загрузка файла

=== "curl"

    ```bash
    curl -X POST http://localhost:8080/v1/files \
      -H "Authorization: Bearer <access_token>" \
      -F "file=@/path/to/document.pdf"
    ```

=== "Python"

    ```python
    import httpx

    with open("/path/to/document.pdf", "rb") as f:
        r = httpx.post(
            "http://localhost:8080/v1/files",
            headers={"Authorization": f"Bearer {access_token}"},
            files={"file": ("document.pdf", f, "application/pdf")},
        )
    print(r.json())
    # {"id": "abc123", "filename": "document.pdf", "size": 102400, ...}
    ```

=== "JavaScript"

    ```javascript
    const formData = new FormData();
    formData.append("file", fileInput.files[0]);

    const response = await fetch("http://localhost:8080/v1/files", {
      method: "POST",
      headers: { Authorization: `Bearer ${accessToken}` },
      body: formData,
    });
    console.log(await response.json());
    ```

**Допустимые типы файлов:** PDF, текст, Markdown, CSV, JSON, JSONL, XLSX, DOCX (макс. 100 МБ).

### Список файлов

=== "curl"

    ```bash
    curl http://localhost:8080/v1/files \
      -H "Authorization: Bearer <access_token>"

    # С фильтром по префиксу
    curl "http://localhost:8080/v1/files?prefix=documents/" \
      -H "Authorization: Bearer <access_token>"
    ```

=== "Python"

    ```python
    import httpx

    r = httpx.get(
        "http://localhost:8080/v1/files",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    for f in r.json()["files"]:
        print(f"{f['filename']} ({f['size']} bytes)")
    ```

=== "JavaScript"

    ```javascript
    const response = await fetch("http://localhost:8080/v1/files", {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    const data = await response.json();
    data.files.forEach((f) => console.log(`${f.filename} (${f.size} bytes)`));
    ```

### Скачивание файла

=== "curl"

    ```bash
    curl -o output.pdf http://localhost:8080/v1/files/<file_id> \
      -H "Authorization: Bearer <access_token>"
    ```

=== "Python"

    ```python
    import httpx

    r = httpx.get(
        f"http://localhost:8080/v1/files/{file_id}",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    with open("output.pdf", "wb") as f:
        f.write(r.content)
    ```

=== "JavaScript"

    ```javascript
    const response = await fetch(`http://localhost:8080/v1/files/${fileId}`, {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    const blob = await response.blob();
    ```

### Метаданные файла

```bash
curl http://localhost:8080/v1/files/<file_id>/metadata \
  -H "Authorization: Bearer <access_token>"
```

### Подписанная ссылка

```bash
curl "http://localhost:8080/v1/files/<file_id>/presign?expiration=3600" \
  -H "Authorization: Bearer <access_token>"
```

### Удаление файла

```bash
curl -X DELETE http://localhost:8080/v1/files/<file_id> \
  -H "Authorization: Bearer <access_token>"
```

!!! warning
Удаление файлов требует роли `expert` или `admin`.

---

## Инструменты

### Список всех инструментов

```bash
curl http://localhost:8080/v1/tools
```

### Фильтрация по категории

```bash
curl "http://localhost:8080/v1/tools?category=search"
```

### Детали инструмента

```bash
curl http://localhost:8080/v1/tools/confluence_search
```

---

## Эволюция моделей (Admin)

### Список зарегистрированных моделей

```bash
curl http://localhost:8080/v1/admin/models \
  -H "Authorization: Bearer <admin_token>"
```

### Запуск обучения

```bash
curl -X POST http://localhost:8080/v1/admin/models/train \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <admin_token>" \
  -d '{
    "model_type": "slm",
    "base_model": "Qwen/Qwen2.5-3B",
    "dataset_path": "/data/training/feedback.jsonl",
    "epochs": 3,
    "learning_rate": 2e-4
  }'
```

### Статус обучения

```bash
curl http://localhost:8080/v1/admin/models/status/<job_id> \
  -H "Authorization: Bearer <admin_token>"
```

### Продвижение версии модели

```bash
curl -X POST http://localhost:8080/v1/admin/models/promote \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <admin_token>" \
  -d '{
    "model_name": "slm-router",
    "version": "v3",
    "stage": "production"
  }'
```

### Откат модели

```bash
curl -X POST http://localhost:8080/v1/admin/models/rollback \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <admin_token>" \
  -d '{
    "model_name": "slm-router",
    "target_version": "v2"
  }'
```

### Настройка канареечного трафика

```bash
curl -X POST http://localhost:8080/v1/admin/models/canary/split \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <admin_token>" \
  -d '{
    "model_name": "slm-router",
    "canary_version": "v3",
    "traffic_percent": 10
  }'
```

### Статус канареечного развёртывания

```bash
curl http://localhost:8080/v1/admin/models/canary/status \
  -H "Authorization: Bearer <admin_token>"
```

### Оценка качества модели

```bash
curl -X POST http://localhost:8080/v1/admin/models/evaluate \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <admin_token>" \
  -d '{
    "model_name": "slm-router",
    "version": "v3",
    "eval_dataset": "/data/eval/test_set.jsonl"
  }'
```

---

## Метрики

### Метрики Prometheus

```bash
curl http://localhost:8080/metrics
```

### Ключевые метрики для мониторинга

```bash
# Количество запросов по эндпоинтам
curl http://localhost:8080/metrics | grep rag_requests_total

# Гистограмма задержки
curl http://localhost:8080/metrics | grep rag_request_duration_seconds

# Активные соединения
curl http://localhost:8080/metrics | grep rag_active_connections

# Коэффициент попаданий в кэш
curl http://localhost:8080/metrics | grep rag_cache_hits_total
```

---

## Виджет

### Встраиваемый виджет чата (HTML)

```bash
curl http://localhost:8080/v1/widget
```

### JavaScript виджета

```bash
curl http://localhost:8080/v1/widget.js
```

### Встраивание в HTML

```html
<!DOCTYPE html>
<html>
<head>
  <title>RAG Чат</title>
</head>
<body>
  <div id="rag-widget"></div>
  <script src="http://localhost:8080/v1/widget.js"></script>
  <script>
    RAGWidget.init({
      container: "#rag-widget",
      apiUrl: "http://localhost:8080",
      model: "rag-proxy",
      theme: "light",
    });
  </script>
</body>
</html>
```

---

## Обработка ошибок

### Коды состояния HTTP

| Код   | Значение                  | Типичная причина                                |
|-------|---------------------------|-------------------------------------------------|
| `200` | Успех                     | Запрос выполнен                                 |
| `400` | Неверный запрос           | Неверный JSON или отсутствуют обязательные поля |
| `401` | Не авторизован            | Отсутствует или истёк JWT-токен                 |
| `403` | Запрещено                 | Недостаточная роль RBAC                         |
| `404` | Не найдено                | Эндпоинт или ресурс не существует               |
| `422` | Ошибка валидации          | Тело запроса не проходит схему                  |
| `429` | Слишком много запросов    | Превышен лимит частоты                          |
| `500` | Внутренняя ошибка сервера | Непредвиденная ошибка                           |
| `502` | Плохой шлюз               | LLM-бэкенд недоступен                           |
| `503` | Сервис недоступен         | Прокси не готов или перегружен                  |

### Формат ответа с ошибкой

```json
{
  "error": {
    "message": "Invalid request: missing required field 'messages'",
    "type": "invalid_request_error",
    "code": "missing_field"
  }
}
```

### Обработка ошибок в Python

```python
import httpx

try:
    response = httpx.post(
        "http://localhost:8080/v1/chat/completions",
        json={"model": "rag-proxy", "messages": []},
        timeout=30.0,
    )
    response.raise_for_status()
    data = response.json()
except httpx.HTTPStatusError as e:
    error = e.response.json().get("error", {})
    print(f"Ошибка API {e.response.status_code}: {error.get('message')}")
except httpx.ConnectError:
    print("Не удалось подключиться к RAG-прокси. Он запущен?")
except httpx.TimeoutException:
    print("Таймаут запроса. LLM-бэкенд может работать медленно.")
```

### Обработка ошибок в JavaScript

```javascript
async function chatCompletion(messages) {
  try {
    const response = await fetch("http://localhost:8080/v1/chat/completions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: "rag-proxy", messages }),
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(`Ошибка API ${response.status}: ${error.error?.message}`);
    }

    return await response.json();
  } catch (err) {
    if (err.name === "TypeError") {
      console.error("Не удалось подключиться к RAG-прокси. Он запущен?");
    } else {
      console.error(err.message);
    }
  }
}
```

### Повтор с экспоненциальной задержкой (Python)

```python
import httpx
import time

def chat_with_retry(messages, max_retries=3):
    for attempt in range(max_retries):
        try:
            response = httpx.post(
                "http://localhost:8080/v1/chat/completions",
                json={"model": "rag-proxy", "messages": messages},
                timeout=60.0,
            )
            if response.status_code == 429:
                wait = 2 ** attempt
                print(f"Превышен лимит. Повтор через {wait}с...")
                time.sleep(wait)
                continue
            response.raise_for_status()
            return response.json()
        except httpx.TimeoutException:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
    raise Exception("Превышено максимальное количество попыток")
```

---

## Полный рабочий пример

### Аутентифицированный чат с обратной связью

=== "Python"

    ```python
    import httpx

    BASE = "http://localhost:8080/v1"

    # 1. Регистрация
    r = httpx.post(f"{BASE}/auth/register", json={
        "username": "demo", "password": "demo123", "email": "demo@co.com"
    })
    print("Зарегистрирован:", r.json())

    # 2. Вход
    r = httpx.post(f"{BASE}/auth/login", json={
        "username": "demo", "password": "demo123"
    })
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 3. Чат
    r = httpx.post(f"{BASE}/chat/completions", headers=headers, json={
        "model": "rag-proxy",
        "messages": [{"role": "user", "content": "Как настроить RBAC?"}],
    })
    answer = r.json()
    feedback_id = answer.get("rag_feedback_id")
    print("Ответ:", answer["choices"][0]["message"]["content"][:200])

    # 4. Обратная связь
    if feedback_id:
        r = httpx.post(f"{BASE}/feedback", headers=headers, json={
            "feedback_id": feedback_id,
            "rating": "positive",
            "comment": "Полезный ответ",
        })
        print("Обратная связь отправлена:", r.status_code)
    ```

=== "JavaScript"

    ```javascript
    const BASE = "http://localhost:8080/v1";

    // 1. Регистрация
    await fetch(`${BASE}/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: "demo", password: "demo123", email: "demo@co.com",
      }),
    });

    // 2. Вход
    const loginRes = await fetch(`${BASE}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: "demo", password: "demo123" }),
    });
    const { access_token } = await loginRes.json();
    const headers = {
      "Content-Type": "application/json",
      Authorization: `Bearer ${access_token}`,
    };

    // 3. Чат
    const chatRes = await fetch(`${BASE}/chat/completions`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        model: "rag-proxy",
        messages: [{ role: "user", content: "Как настроить RBAC?" }],
      }),
    });
    const answer = await chatRes.json();
    const feedbackId = answer.rag_feedback_id;
    console.log("Ответ:", answer.choices[0].message.content.slice(0, 200));

    // 4. Обратная связь
    if (feedbackId) {
      await fetch(`${BASE}/feedback`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          feedback_id: feedbackId,
          rating: "positive",
          comment: "Полезный ответ",
        }),
      });
    }
    ```
