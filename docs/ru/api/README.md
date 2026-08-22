# Документация API — RAG-система

Машиночитаемая и человекочитаемая документация API для RAG-прокси.

## Файлы

| Файл | Описание | Как сгенерировать |
|------|----------|------------------|
| [`openapi.json`](openapi.json) | Спецификация OpenAPI 3.1 (машиночитаемая) | `make export-openapi` |
| [`reference.md`](reference.md) | Человекочитаемый справочник API (Markdown) | Генерируется автоматически вместе со спецификацией |
| [`../../api_reference.md`](../api_reference.md) | Подробное руководство по API с примерами, написанное вручную | Вручную |

## Быстрый старт

### Генерация / обновление спецификации

```bash
# Из корня проекта
make export-openapi

# Или напрямую
python scripts/export_openapi.py
```

### Только валидация (для CI)

```bash
python scripts/export_openapi.py --validate-only
```

### Пользовательский каталог вывода

```bash
python scripts/export_openapi.py --output-dir ./api-docs
```

## Подробности о спецификации

Спецификация OpenAPI извлекается напрямую из исходного кода FastAPI-приложения
`proxy/app/main.py`. Она включает все зарегистрированные роутеры:

| Тег | Роутер | Префикс |
|-----|--------|---------|
| `chat` | `api/chat.py` | `/v1/chat` |
| `models` | `main.py` | `/v1/models` |
| `health` | `api/health.py` | `/v1/health` |
| `auth` | `api/auth_endpoints.py` | `/v1/auth` |
| `feedback` | `api/feedback.py` | `/v1/feedback` |
| `tools` | `api/tools.py` | `/v1/tools` |
| `admin` | `api/admin.py` | `/v1/admin` |
| `files` | `api/files.py` | `/v1/files` |
| `widget` | `api/widget.py` | `/v1/widget` |
| `metrics` | `api/metrics.py` | `/metrics` |

## Использование спецификации

### Swagger UI (живой)

Когда прокси запущен, интерактивная документация доступна по адресам:

```
http://localhost:8080/docs      # Swagger UI
http://localhost:8080/redoc     # ReDoc
http://localhost:8080/openapi.json  # Живая спецификация
```

### Генерация клиентского кода

Используйте спецификацию для автоматической генерации типизированных API-клиентов:

```bash
# Python-клиент (openapi-python-client)
openapi-python-client generate --path docs/en/api/openapi.json

# TypeScript-клиент (openapi-typescript)
npx openapi-typescript docs/en/api/openapi.json -o src/api.d.ts

# Go-клиент (oapi-codegen)
oapi-codegen -package ragclient docs/en/api/openapi.json > client.go
```

### Postman / Insomnia

Импортируйте `openapi.json` напрямую в Postman или Insomnia для изучения API.

## Интеграция с CI

CI-пайплайн включает необязательный шаг валидации OpenAPI, который:

1. Извлекает спецификацию из FastAPI-приложения
2. Проверяет структурную целостность (paths, operations, schemas)
3. Завершается с ошибкой при критических проблемах; выдаёт предупреждения при отсутствии summary/description
4. Загружает спецификацию как артефакт сборки

См. джобу `openapi` в `.github/workflows/ci.yml`.

## Поддержание документации в актуальном состоянии

Спецификация **генерируется автоматически из исходного кода** — она всегда синхронизирована с
реальным API, пока роутеры корректно зарегистрированы в `proxy/app/main.py`.

Для обновления после изменения API-маршрутов:

```bash
make export-openapi
git add docs/en/api/openapi.json docs/en/api/reference.md
git commit -m "docs: update OpenAPI spec"
```
