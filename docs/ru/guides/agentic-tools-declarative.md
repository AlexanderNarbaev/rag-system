# Агентные инструменты — справочник по декларативным инструментам (YAML/JSON)

**Статус реализации:** Реализовано в Beyond v2.0. Инструменты могут быть определены декларативно в файлах YAML или JSON, загружаемых при запуске из `TOOLS_DECLARATIVE_DIR`, с валидацией схемы, подстановкой переменных и встроенными обработчиками HTTP/shell.

---

## 1. Обзор

Декларативные инструменты позволяют определять инструменты без написания Python-кода. Определения инструментов хранятся в виде файлов YAML или JSON и автоматически загружаются при запуске прокси. Это идеально подходит для:

- Конфигурации инструментов не-разработчиками
- Автоматизации инфраструктуры (shell-команды)
- Интеграции с внешними API (HTTP-эндпоинты)
- Рабочих процессов «конфигурация как код»
- Пакетов инструментов, развёрнутых через RPM/Helm

---

## 2. Схема определения инструмента

### 2.1 Минимальный пример (YAML)

```yaml
# tools_declarative/check_service.yaml
name: check_service
description: Check health of a service by HTTP endpoint
category: monitoring
type: http
visibility: public

parameters:
  - name: service_name
    type: string
    description: Name of the service to check
    required: true

http:
  method: GET
  url_template: "https://{{service_name}}.internal/health"
  allowed_hosts:
    - "*.internal"

timeout: 10
```

### 2.2 Пример shell-инструмента

```yaml
# tools_declarative/disk_usage.yaml
name: disk_usage
description: Check disk usage on the server
category: monitoring
type: shell
visibility: admin

parameters:
  - name: path
    type: string
    description: Filesystem path to check
    required: true
    default: "/var/log"

shell:
  command: "df -h {{path}}"
  allowed_commands: ["df", "du"]
  allowed_paths: ["/var/log", "/data"]
  timeout: 15
```

---

## 3. Полная справочная схема

### 3.1 Поля верхнего уровня

| Поле | Тип | Обязательно | Описание |
|------|-----|-------------|----------|
| `name` | `string` | Да | Уникальный идентификатор инструмента |
| `description` | `string` | Да | Описание инструмента для маршрутизации LLM |
| `category` | `string` | Нет | Категория группировки (по умолчанию: `"general"`) |
| `type` | `string` | Да | Тип обработчика: `"http"`, `"shell"` |
| `parameters` | `array` | Нет | Список определений параметров |
| `tags` | `array<string>` | Нет | Теги для поиска |
| `version` | `string` | Нет | Семантическая версия (по умолчанию: `"1.0.0"`) |
| `timeout` | `number` | Нет | Тайм-аут выполнения в секундах (по умолчанию: `30`) |
| `visibility` | `string` | Нет | Уровень RBAC: `"public"`, `"user"`, `"internal"`, `"admin"` |
| `depends_on` | `array<string>` | Нет | Зависимости инструмента |
| `retry` | `object` | Нет | Конфигурация политики повторных попыток |
| `http` | `object` | Обязательно для `type: http` | Конфигурация HTTP-обработчика |
| `shell` | `object` | Обязательно для `type: shell` | Конфигурация shell-обработчика |

### 3.2 Определение параметра

| Поле | Тип | Обязательно | Описание |
|------|-----|-------------|----------|
| `name` | `string` | Да | Имя параметра |
| `type` | `string` | Да | Тип JSON Schema: `"string"`, `"integer"`, `"number"`, `"boolean"`, `"array"`, `"object"` |
| `description` | `string` | Нет | Описание параметра |
| `required` | `boolean` | Нет | Обязательность параметра (по умолчанию: `false`, если задан `default`) |
| `default` | `any` | Нет | Значение по умолчанию |
| `enum` | `array<string>` | Нет | Допустимые значения |
| `items_type` | `string` | Нет | Для типа `array`: тип внутреннего элемента |

### 3.3 Политика повторных попыток

```yaml
retry:
  max_retries: 3
  backoff_s: 2.0
  retry_on: ["timeout", "http_5xx"]
```

| Поле | Тип | По умолчанию | Описание |
|------|-----|--------------|----------|
| `max_retries` | `number` | `1` | Максимальное количество повторных попыток |
| `backoff_s` | `number` | `1.0` | Множитель задержки в секундах |
| `retry_on` | `array<string>` | `["timeout"]` | Типы ошибок: `"timeout"`, `"http_5xx"`, `"all"` |

---

## 4. Конфигурация HTTP-инструмента

```yaml
http:
  method: POST
  url_template: "https://api.internal/{{CONTEXT.namespace}}/search"
  headers:
    Authorization: "Bearer {{api_token}}"
    Content-Type: "application/json"
  body_template: '{"query": "{{query}}", "limit": {{limit}}}'
  allowed_hosts:
    - "api.internal"
    - "*.corp.example.com"
  follow_redirects: false
  verify_ssl: true
```

| Поле | Тип | Обязательно | Описание |
|------|-----|-------------|----------|
| `method` | `string` | Да | HTTP-метод: `GET`, `POST`, `PUT`, `DELETE`, `PATCH` |
| `url_template` | `string` | Да | URL с плейсхолдерами `{{variable}}` |
| `headers` | `object` | Нет | HTTP-заголовки для отправки |
| `body_template` | `string` | Нет | Шаблон тела запроса (для POST/PUT/PATCH) |
| `allowed_hosts` | `array<string>` | Да | Белый список хостов (поддерживаются glob-паттерны) |
| `follow_redirects` | `boolean` | Нет | Следовать HTTP-редиректам (по умолчанию: `false`) |
| `verify_ssl` | `boolean` | Нет | Проверять SSL-сертификаты (по умолчанию: `true`) |

---

## 5. Конфигурация shell-инструмента

```yaml
shell:
  command: "grep {{pattern}} {{path}} | tail -{{lines}}"
  working_dir: "/var/log"
  allowed_commands:
    - "grep"
    - "cat"
    - "tail"
    - "head"
  allowed_paths:
    - "/var/log"
    - "/tmp"
  timeout: 10
  env:
    PATH: "/usr/bin:/bin"
```

| Поле | Тип | Обязательно | Описание |
|------|-----|-------------|----------|
| `command` | `string` | Да | Shell-команда с плейсхолдерами `{{variable}}` |
| `working_dir` | `string` | Нет | Рабочая директория для команды |
| `allowed_commands` | `array<string>` | Да | Белый список команд (только первое слово) |
| `allowed_paths` | `array<string>` | Нет | Белый список путей для аргументов |
| `timeout` | `number` | Нет | Переопределение тайм-аута для конкретной команды |
| `env` | `object` | Нет | Переменные окружения |

### Примечания по безопасности

- Shell-команды проверяются на наличие метасимволов (`;`, `&&`, `|`, `$()`, обратные кавычки) в значениях параметров
- Проходят валидацию только команды и пути из белого списка
- Используйте `allowed_commands` для ограничения доступных исполняемых файлов
- Используйте `allowed_paths` для ограничения доступа к файловой системе

---

## 6. Подстановка переменных

Все строковые поля поддерживают плейсхолдеры `{{VARIABLE}}`, которые разрешаются во время выполнения:

```yaml
http:
  url_template: "https://{{CONTEXT.namespace}}.internal/api/v1/{{resource}}"
  headers:
    X-User: "{{CONTEXT.user_id}}"
    X-Request-Id: "{{request_id}}"
```

Порядок разрешения:
1. **Параметры инструмента** — значения, переданные при вызове
2. **CONTEXT.*** — общий контекст выполнения (`user_id`, `namespace`, `request_id` и т.д.)
3. **Переменные окружения** — `os.environ`
4. Неразрешённые плейсхолдеры остаются как есть (например, `{{unknown}}` остаётся `"{{unknown}}"`)

---

## 7. Валидация схемы

Каждый файл валидируется при загрузке:

- Обязательные поля верхнего уровня (`name`, `description`, `type`)
- Наличие конфигурационных секций, специфичных для типа (`http` или `shell`)
- Типы параметров являются допустимыми типами JSON Schema
- Формат файла — валидный YAML или JSON

Невалидные файлы логируются как предупреждения и пропускаются — остальные инструменты продолжают загружаться.

---

## 8. Обнаружение файлов

Инструменты загружаются из `TOOLS_DECLARATIVE_DIR` (по умолчанию: `./tools_declarative/`):

```bash
TOOLS_DECLARATIVE_DIR=/etc/rag/tools python -m proxy.app.main
```

Загружаются файлы с расширениями `.yaml`, `.yml` или `.json`. Поддиректории обрабатываются рекурсивно.

### Структура директорий в продакшене

```
tools_declarative/
├── monitoring/
│   ├── check_service.yaml
│   ├── disk_usage.yaml
│   └── tail_logs.yaml
├── external_apis/
│   ├── slack_notify.json
│   └── pagerduty_incident.yaml
└── db_queries/
    └── psql_query.yaml
```

---

## 9. Формат JSON

Все приведённые выше примеры также работают в формате JSON:

```json
{
  "name": "check_service",
  "description": "Check service health",
  "category": "monitoring",
  "type": "http",
  "parameters": [
    {
      "name": "service_name",
      "type": "string",
      "description": "Service to check",
      "required": true
    }
  ],
  "http": {
    "method": "GET",
    "url_template": "https://{{service_name}}.internal/health",
    "allowed_hosts": ["*.internal"]
  }
}
```

---

## 10. Связанные документы

- [Руководство по Python SDK](agentic-tools-sdk.md) — декоратор `@tool` и `ToolBuilder`
- [Руководство по обнаружению через OpenAPI](agentic-tools-openapi.md) — автоматическое обнаружение инструментов из спецификаций OpenAPI
- [ADR-009: Архитектура расширения агентных инструментов](../adr/ADR-009-agentic-tools-expansion.md)
