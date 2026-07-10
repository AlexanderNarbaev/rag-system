# Руководство по интеграции

**Статус реализации:** Реализовано. RAG-система предоставляет OpenAI-совместимый API, встраиваемый чат-виджет, Tools SDK и MCP-сервер для интеграции с IDE.

---

## 1. Обзор

RAG-система предоставляет несколько точек интеграции:

| Интеграция | Метод | Применение |
|------------|-------|------------|
| **OpenAI-совместимый API** | REST / SSE | Любой OpenAI-клиент, чат-приложения, пользовательский код |
| **Чат-виджет** | HTML/JS | Встраивание RAG-чата в веб-страницы, дашборды, вики |
| **Tools SDK** | Python декоратор | Определение пользовательских инструментов для агентской оркестрации |
| **Декларативные инструменты** | YAML/JSON | Определение инструментов без кода для HTTP и shell интеграций |
| **OpenAPI авто-обнаружение** | OpenAPI спецификация | Автоматическая генерация инструментов из спецификаций API |
| **MCP-сервер** | STDIO / HTTP | Интеграция с IDE (OpenCode, Claude Desktop) |

Все интеграции взаимодействуют через слой прокси по адресу `http://<host>:8080/v1`.

---

## 2. OpenAI-совместимый API

Прокси является заменой для любого OpenAI-совместимого клиента. Специальный клиентский код не требуется.

### 2.1 Эндпоинт

```
POST /v1/chat/completions
```

### 2.2 Базовый запрос

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "your-model-name",
    "messages": [
      {"role": "user", "content": "Как работает сервис аутентификации?"}
    ]
  }'
```

### 2.3 Стриминг

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "your-model-name",
    "messages": [{"role": "user", "content": "Объясните ETL-пайплайн"}],
    "stream": true
  }'
```

### 2.4 RAG-специфичные параметры

| Параметр | Тип | Описание |
|----------|-----|----------|
| `rag_version` | `string` | Запрос конкретной версии документа |
| `rag_force_refresh` | `bool` | Обход кэша ответов для получения свежих результатов |

### 2.5 Расширения ответа

Прокси добавляет RAG-метаданные к ответу:

```json
{
  "choices": [...],
  "rag_feedback_id": "fb-abc123",
  "rag_confidence": 0.87,
  "rag_sources": [
    {"title": "Auth Service ADR", "source": "confluence", "relevance": 0.92}
  ]
}
```

### 2.6 Другие эндпоинты

| Эндпоинт | Метод | Описание |
|----------|-------|----------|
| `/v1/models` | GET | Список доступных моделей |
| `/v1/health` | GET | Проверка здоровья (статус Qdrant + LLM) |
| `/v1/health/live` | GET | Проверка жизнеспособности (совместимо с K8s) |
| `/v1/health/ready` | GET | Проверка готовности |
| `/v1/feedback` | POST | Отправка экспертной обратной связи |
| `/v1/tools` | GET | Список доступных инструментов |
| `/metrics` | GET | Метрики Prometheus |

---

## 3. Интеграция с чат-системами

### 3.1 OpenWebUI

Укажите RAG-прокси как OpenAI-совместимый эндпоинт в OpenWebUI:

1. Откройте OpenWebUI Settings → Connections
2. Установите **API Base URL** на `http://<rag-proxy-host>:8080/v1`
3. Установите **API Key** на ваш RAG API ключ (или оставьте пустым, если `AUTH_ENABLED=false`)
4. Список моделей заполнится автоматически из `/v1/models`

### 3.2 Любой OpenAI-совместимый клиент

Любой клиент, поддерживающий формат OpenAI API, будет работать:

- **Python (библиотека openai)**

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8080/v1",
    api_key="your-api-key",
)

response = client.chat.completions.create(
    model="your-model-name",
    messages=[{"role": "user", "content": "Каков процесс деплоя?"}],
)
print(response.choices[0].message.content)
```

- **Node.js (пакет openai)**

```javascript
import OpenAI from "openai";

const client = new OpenAI({
  baseURL: "http://localhost:8080/v1",
  apiKey: "your-api-key",
});

const response = await client.chat.completions.create({
  model: "your-model-name",
  messages: [{ role: "user", content: "Каков процесс деплоя?" }],
});
console.log(response.choices[0].message.content);
```

- **curl**

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-api-key" \
  -d '{"model":"your-model-name","messages":[{"role":"user","content":"Привет"}]}'
```

---

## 4. Интеграция с IDE

### 4.1 OpenCode (через MCP-сервер)

Настройте OpenCode на использование RAG MCP-сервера в `opencode.json`:

```json
{
  "providers": {
    "rag-system": {
      "name": "RAG System",
      "base_url": "http://localhost:8080/v1",
      "api_key": "${RAG_API_KEY}",
      "models": ["your-model-name"]
    }
  },
  "mcp_servers": {
    "rag-system": {
      "type": "streamableHttp",
      "url": "http://localhost:8081/mcp",
      "description": "RAG System — поиск по корпоративной базе знаний"
    }
  },
  "model": "rag-system/your-model-name"
}
```

Подробная настройка описана в [Руководстве по MCP-серверу](mcp-server-guide.md).

### 4.2 Claude Desktop (через MCP-сервер)

Добавьте RAG MCP-сервер в конфигурацию Claude Desktop:

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "rag-system": {
      "command": "python",
      "args": ["-m", "mcp_server.server"],
      "env": {
        "RAG_PROXY_URL": "http://localhost:8080/v1"
      }
    }
  }
}
```

Для удалённого сервера (Streamable HTTP):

```json
{
  "mcpServers": {
    "rag-system": {
      "url": "http://rag-proxy.internal.company.com:8081/mcp"
    }
  }
}
```

---

## 5. Интеграция виджета

### 5.1 Встраивание виджета

RAG чат-виджет можно встроить в любую веб-страницу. Два метода:

**Метод 1: Автономный JavaScript (рекомендуется)**

```html
<script src="http://localhost:8080/v1/widget.js"></script>
<div id="rag-chat"></div>
<script>
  RAGChatWidget.init({
    container: 'rag-chat',
    endpoint: 'http://localhost:8080/v1/chat/completions',
    token: 'your-jwt-token',  // опционально
    model: 'your-model-name', // опционально
  });
</script>
```

**Метод 2: Полная HTML-страница (iframe)**

```html
<iframe
  src="http://localhost:8080/v1/widget"
  width="720"
  height="560"
  frameborder="0"
  title="RAG Chat"
></iframe>
```

### 5.2 Конфигурация виджета

| Опция | Тип | По умолчанию | Описание |
|-------|-----|-------------|----------|
| `container` | `string` | обязательно | CSS-селектор или ID элемента для корневого контейнера |
| `endpoint` | `string` | `/v1/chat/completions` | URL эндпоинта чат-завершений |
| `token` | `string` | `null` | JWT Bearer токен для аутентифицированных запросов |
| `model` | `string` | `null` | Переопределение имени модели |

### 5.3 Настройка внешнего вида

Виджет использует CSS-переменные. Переопределите их для соответствия вашему дизайну:

```css
:root {
  --rag-bg: #1a1a2e;          /* Фон виджета */
  --rag-surface: #16213e;      /* Область заголовка и ввода */
  --rag-border: #2a3a5c;       /* Цвет границ */
  --rag-text: #e0e0e0;         /* Цвет текста */
  --rag-accent: #4fc3f7;       /* Акцентный цвет (логотип, ссылки) */
  --rag-user-bg: #1b3a5c;      /* Пузырь сообщения пользователя */
  --rag-assistant-bg: #16213e;  /* Пузырь сообщения ассистента */
  --rag-error: #ef5350;         /* Цвет ошибки */
  --rag-radius: 8px;           /* Радиус скругления */
}
```

---

## 6. Интеграция инструментов

Система инструментов позволяет RAG-прокси вызывать внешние сервисы и выполнять действия во время агентской оркестрации.

### 6.1 Создание инструментов с декоратором `@tool`

```python
from proxy.app.tools.sdk import tool, ToolContext

@tool(
    name="search_confluence",
    description="Поиск страниц Confluence по CQL-запросу",
    category="live_source",
    tags=["confluence", "search"],
    timeout=15.0,
)
async def search_confluence(
    query: str,
    max_results: int = 5,
    ctx: ToolContext = None,
) -> str:
    """Поиск страниц Confluence по CQL-запросу."""
    # Реализация: вызов Confluence REST API
    return f"Найдено {max_results} результатов для '{query}'"
```

Типы данных автоматически конвертируются в JSON Schema. Имя функции становится именем инструмента, строка документации — описанием.

### 6.2 Декларативные инструменты (YAML/JSON)

Создайте YAML или JSON файлы в директории декларативных инструментов (`TOOLS_DECLARATIVE_DIR`):

**Пример HTTP-инструмента** (`tools/search_confluence.yaml`):

```yaml
tools:
  - name: search_confluence
    type: http
    description: Поиск страниц Confluence через REST API
    category: live_source
    tags: [confluence, search]
    version: "1.0.0"
    visibility: user
    parameters:
      query:
        type: string
        description: CQL поисковый запрос
        required: true
      max_results:
        type: integer
        description: Максимальное количество результатов
        default: 5
    http:
      method: GET
      url_template: "{{CONFLUENCE_API_URL}}/rest/api/content/search?cql={{query}}&limit={{max_results}}"
      headers:
        Authorization: "Bearer {{CONFLUENCE_API_TOKEN}}"
      response_path: results
      allowed_hosts:
        - confluence.internal.company.com
```

**Пример shell-инструмента** (`tools/get_git_status.yaml`):

```yaml
tools:
  - name: get_git_status
    type: shell
    description: Получить статус git текущего репозитория
    category: devops
    tags: [git, status]
    shell:
      command: "git status --short"
      allowed_commands: [git]
      allowed_paths: [/opt/repos]
      working_dir: /opt/repos/main
```

### 6.3 OpenAPI авто-обнаружение

Настройте OpenAPI спецификации в переменных окружения:

```bash
# В .env:
TOOLS_OPENAPI_SPECS='[{"name":"petstore","url":"https://petstore3.swagger.io/api/v3/openapi.json","mode":"auto"}]'
```

Система автоматически:
1. Загружает и парсит OpenAPI спецификацию
2. Конвертирует GET-эндпоинты в инструменты поиска
3. Конвертирует POST/PUT/DELETE-эндпоинты в инструменты действий
4. Генерирует обработчики, выполняющие фактические HTTP-запросы
5. Разрешает `$ref` указатели и извлекает параметры из схем

### 6.4 API обнаружения инструментов

Список всех доступных инструментов:

```bash
curl http://localhost:8080/v1/tools
```

Детали конкретного инструмента:

```bash
curl http://localhost:8080/v1/tools/search_confluence
```

Фильтрация по категории или тегу:

```bash
curl "http://localhost:8080/v1/tools?category=live_source&tag=search"
```

---

## 7. Аутентификация

### 7.1 JWT аутентификация

Когда `AUTH_ENABLED=true`, все эндпоинты требуют Bearer токен:

```bash
# Вход для получения токена
curl -X POST http://localhost:8080/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "user", "password": "pass"}'

# Использование токена
curl http://localhost:8080/v1/chat/completions \
  -H "Authorization: Bearer <access_token>"
```

### 7.2 Аутентификация по API ключу

При использовании с OpenAI-совместимыми клиентами передайте API ключ как Bearer токен:

```python
client = OpenAI(
    base_url="http://localhost:8080/v1",
    api_key="your-api-key",  # пересылается на LLM бэкенд
)
```

### 7.3 Контроль доступа на основе ролей (RBAC)

| Роль | Видимые инструменты | Уровень доступа |
|------|---------------------|----------------|
| `admin` | Все инструменты (public, user, expert, admin) | Полный доступ |
| `expert` | public, user, expert | Инструменты экспертного уровня |
| `user` | public, user | Стандартные пользовательские инструменты |
| `read_only` | только public | Только чтение |

---

## 8. Примеры

### 8.1 Python — Полный RAG-запрос с обратной связью

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8080/v1", api_key="key")

# Запрос с RAG-обогащением
response = client.chat.completions.create(
    model="your-model-name",
    messages=[{"role": "user", "content": "Как развернуть сервис?"}],
)

answer = response.choices[0].message.content
print(answer)

# Отправка обратной связи
import requests
requests.post("http://localhost:8080/v1/feedback", json={
    "rag_feedback_id": response.rag_feedback_id,
    "rating": "positive",
})
```

### 8.2 JavaScript — Стриминг с виджетом

```javascript
// На веб-странице
<script src="http://localhost:8080/v1/widget.js"></script>
<div id="rag-chat"></div>
<script>
  RAGChatWidget.init({
    container: 'rag-chat',
    endpoint: 'http://localhost:8080/v1/chat/completions',
    token: localStorage.getItem('rag_token'),
  });
</script>
```

### 8.3 Docker Compose — Полный стек

```yaml
services:
  rag-proxy:
    build: ./proxy
    ports:
      - "8080:8080"
    env_file: ./proxy/.env
    depends_on:
      - qdrant
      - redis

  qdrant:
    image: qdrant/qdrant:latest
    ports:
      - "6333:6333"
    volumes:
      - qdrant_data:/qdrant/storage

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

volumes:
  qdrant_data:
```

---

## Смотрите также

- [Руководство по MCP-серверу](mcp-server-guide.md) — Интеграция с IDE через MCP
- [Руководство по Tools SDK](agentic-tools-sdk.md) — Справочник по Python декоратору `@tool`
- [Декларативные инструменты](agentic-tools-declarative.md) — YAML/JSON определения инструментов
- [OpenAPI авто-обнаружение](agentic-tools-openapi.md) — Автоматическая генерация инструментов
- [Руководство по деплою](deployment-guide.md) — Промышленный деплой
- [Аутентификация и RBAC](access-control-rbac.md) — Настройка контроля доступа
