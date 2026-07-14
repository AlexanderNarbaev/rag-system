# Руководство разработчика

**Версия:** v2.0.0 | **Обновлено:** 2026-07-10

Это руководство охватывает настройку среды разработки, запуск тестов, соглашения по стилю кода и внесение вклада в RAG
System.

---

## 1. Структура проекта

```
rag-system/
├── proxy/                         # RAG-прокси (FastAPI + LangGraph)
│   ├── app/
│   │   ├── main.py                # Точка входа FastAPI (25+ эндпоинтов)
│   │   ├── core/                  # Основная логика RAG
│   │   │   ├── retrieval.py       # Гибридный поиск Qdrant
│   │   │   ├── rerank.py          # Cross-encoder реранкер
│   │   │   ├── context.py         # Сборка контекста
│   │   │   ├── confidence.py      # Оценка уверенности
│   │   │   ├── token_optimizer.py # Бюджетирование токенов
│   │   │   ├── orchestrator.py    # Агентный пайплайн LangGraph
│   │   │   ├── enricher.py        # Самообогащение из обратной связи
│   │   │   └── hitl.py            # Логирование взаимодействий
│   │   ├── auth/                  # Аутентификация и авторизация
│   │   │   ├── jwt.py             # Управление JWT-токенами
│   │   │   ├── rbac.py            # Контроль доступа на основе ролей
│   │   │   ├── user_db.py         # SQLite база пользователей
│   │   │   └── ldap.py            # Интеграция LDAP/AD
│   │   ├── llm/                   # Адаптеры LLM-провайдеров
│   │   │   └── provider.py        # Мульти-провайдерная генерация
│   │   ├── tools/                 # Система агентных инструментов
│   │   │   ├── registry.py        # Реестр инструментов
│   │   │   ├── declarative.py     # YAML/JSON определения инструментов
│   │   │   └── openapi_discovery.py # Автообнаружение OpenAPI
│   │   ├── model_evolution/       # Пайплайн дообучения (13 модулей)
│   │   │   ├── trainer.py         # Базовый тренер + TrainingJob
│   │   │   ├── slm_trainer.py     # LoRA дообучение SLM
│   │   │   ├── llm_trainer.py     # QLoRA дообучение LLM
│   │   │   ├── reranker_trainer.py # Обучение реранкера
│   │   │   ├── adapter_manager.py # Горячая перезагрузка адаптеров
│   │   │   ├── canary_controller.py # Канареечное развёртывание
│   │   │   ├── model_registry.py  # Реестр артефактов моделей
│   │   │   ├── eval_gate.py       # Контроль качества CI/CD
│   │   │   └── env_profile.py     # Профили Dev/Prod/CI
│   │   ├── shared/                # Общие утилиты
│   │   │   ├── config.py          # Конфигурация на основе переменных окружения
│   │   │   ├── cache.py           # Redis + in-memory кэш
│   │   │   ├── metrics.py         # Prometheus метрики
│   │   │   ├── middleware.py       # Middleware запросов
│   │   │   ├── rate_limiter.py    # Token bucket ограничитель
│   │   │   ├── security.py        # Санитизация ввода
│   │   │   └── logging.py         # Структурированное логирование
│   │   └── static/                # Виджет HTML/JS
│   ├── Dockerfile.proxy
│   └── docker-compose.yml
├── etl/                           # ETL-пайплайн (автономный)
│   ├── extractors/                # Экстракторы источников данных
│   ├── chunker/                   # Нарезка документов
│   ├── graph_builder/             # Построение графа Neo4j
│   ├── indexer/                   # Векторная индексация
│   ├── scheduler/                 # Оркестрация пайплайна
│   ├── config/
│   │   └── etl_config.yaml
│   ├── Dockerfile.etl
│   └── requirements_etl.txt
├── mcp_server/                    # MCP сервер для интеграции с IDE
├── hitl_dashboard/                # Streamlit дашборд экспертов
├── scripts/                       # Утилитарные скрипты
├── tests/                         # Тестовый набор
├── docs/                          # Документация (EN + RU)
├── k8s/helm/rag-system/           # Kubernetes Helm-чарт
├── Makefile                       # Основная точка входа разработки
├── pyproject.toml                 # Конфигурация Python-проекта
├── setup.sh                       # Скрипт установки
└── README.md
```

---

## 2. Настройка среды разработки

### Предварительные требования

- Python 3.11+
- Docker 24+ и Docker Compose v2.20+
- Git
- Минимум 16 ГБ RAM (для тестирования с локальными моделями)
- uv (рекомендуется) или pip

### Быстрая настройка

```bash
# Клонирование репозитория
git clone https://github.com/AlexanderNarbaev/rag-system.git
cd rag-system

# Полная настройка (создаёт venv, устанавливает зависимости)
make install-dev

# Или вручную:
bash setup.sh --dev
```

### Ручная настройка

```bash
# Создание виртуального окружения
python -m venv .venv
source .venv/bin/activate

# Установка зависимостей прокси
pip install -r requirements-proxy.txt

# Установка зависимостей ETL
pip install -r requirements-etl.txt

# Установка dev-зависимостей
pip install -r requirements-dev.txt

# Создание .env из шаблона
cp .env.example proxy/.env
# Отредактируйте proxy/.env
```

### Конфигурация

Вся конфигурация через переменные окружения или `proxy/.env`. Ключевые настройки для разработки:

```bash
# Минимальная локальная настройка
QDRANT_HOST=localhost
LLM_ENDPOINT=http://localhost:8000/v1
LLM_MODEL_NAME=your-model-name

# Включение функций для тестирования
USE_LANGGRAPH=false        # Начните просто, включите позже
USE_REDIS=false            # Использовать in-memory кэш
GRAPH_ENABLED=false        # Пропустить Neo4j для быстрого старта
AUTH_ENABLED=false         # Пропустить auth для локальной разработки
METRICS_ENABLED=true
```

### Запуск сервисов локально

```bash
# Вариант 1: Docker Compose (все сервисы)
cd proxy && docker compose up -d

# Вариант 2: Только инфраструктура
docker run -d -p 6333:6333 qdrant/qdrant:v1.12.1
docker run -d -p 6379:6379 redis:7-alpine

# Затем запустите прокси локально
make run
# Или: uvicorn proxy.app.main:app --host 0.0.0.0 --port 8080 --workers 1
```

---

## 3. Запуск тестов

### Команды тестирования

```bash
# Запуск всех тестов
make test

# Запуск конкретных наборов
make test-proxy           # Только тесты прокси
make test-etl             # Только тесты ETL
make test-integration     # Интеграционные тесты (требуются сервисы)

# С подробным выводом
python -m pytest tests/ -v

# Конкретный файл тестов
python -m pytest tests/proxy/test_retrieval.py -v

# Конкретный тест
python -m pytest tests/proxy/test_retrieval.py::TestHybridSearch::test_rrf_fusion -v

# С покрытием
python -m pytest tests/ --cov=proxy --cov=etl --cov-report=html

# Только быстрые тесты (исключая slow/e2e/benchmark)
python -m pytest tests/ -m "not slow and not e2e and not benchmark"
```

### Маркеры тестов

| Маркер        | Описание                            | Требуется            |
|---------------|-------------------------------------|----------------------|
| `e2e`         | End-to-end тесты                    | Запущенные сервисы   |
| `benchmark`   | Тесты производительности и нагрузки | Запущенные сервисы   |
| `chaos`       | Тесты устойчивости                  | Запущенные сервисы   |
| `asyncio`     | Тесты с asyncio                     | Ничего额外             |
| `slow`        | Тесты дольше 5 секунд               | Ничего额外             |
| `integration` | Тесты с внешними сервисами          | Qdrant, Neo4j, Redis |

### Написание тестов

```python
# tests/proxy/test_example.py
import pytest
from unittest.mock import AsyncMock, patch


class TestExample:
    """Пример тестового класса по соглашениям проекта."""

    def test_basic_retrieval(self):
        """Тест: гибридный поиск возвращает результаты."""
        # Arrange
        query = "тестовый запрос"
        # Act
        # ...
        # Assert
        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_async_endpoint(self):
        """Тест: асинхронный эндпоинт."""
        # Используйте AsyncMock для асинхронных зависимостей
        with patch("proxy.app.core.retrieval.hybrid_search") as mock:
            mock.return_value = []
            # ...

    @pytest.mark.slow
    def test_expensive_operation(self):
        """Помечайте медленные тесты для исключения из быстрых запусков."""
        # ...
```

---

## 4. Стиль кода

### Ruff (Линтинг + Форматирование)

Проект использует [Ruff](https://docs.astral.sh/ruff/) для линтинга и форматирования.

```bash
# Линтинг
make lint                 # Проверка проблем
ruff check .              # То же самое

# Форматирование
make format               # Автоформатирование
ruff format .             # То же самое

# Проверка форматирования без изменений
make format-check
ruff format --check .
```

**Конфигурация** (из `pyproject.toml`):

```toml
[tool.ruff]
line-length = 120
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP", "B", "C4", "SIM"]

[tool.ruff.format]
quote-style = "double"
```

### Mypy (Проверка типов)

```bash
make typecheck            # Запуск mypy
mypy proxy/ etl/ --exclude '.venv|__pycache__'
```

**Конфигурация** (из `pyproject.toml`):

```toml
[tool.mypy]
python_version = "3.11"
ignore_missing_imports = true
```

### Pre-commit хуки

```bash
# Установка pre-commit хуков
pre-commit install

# Ручной запуск
pre-commit run --all-files
```

### Соглашения по коду

1. **Аннотации типов**: Используйте современный синтаксис Python 3.11+ (`list[str]` вместо `List[str]`, `X | None`
   вместо `Optional[X]`).
2. **Докстроки**: Google-style для публичных функций.
3. **Импорты**: Сортируются Ruff (stdlib → third-party → local).
4. **Длина строки**: Максимум 120 символов.
5. **Именование**: `snake_case` для функций/переменных, `PascalCase` для классов, `UPPER_SNAKE` для констант.
6. **Обработка ошибок**: Graceful degradation — логируйте и продолжайте, никогда не роняйте прокси.

---

## 5. Добавление нового функционала

### Добавление нового ETL-экстрактора

1. Создайте `etl/extractors/my_source.py`:

```python
# etl/extractors/my_source.py
from etl.extractors.base_extractor import BaseExtractor


class MySourceExtractor(BaseExtractor):
    """Извлечение данных из MySource."""

    def extract(self, config: dict) -> list[dict]:
        """Извлечение документов из MySource."""
        documents = []
        # ... логика извлечения ...
        return documents
```

2. Зарегистрируйте в `etl/scheduler/run_etl.py`.
3. Добавьте конфигурацию в `etl/config/etl_config.yaml`.
4. Напишите тесты в `tests/etl/test_my_source.py`.

### Добавление нового API-эндпоинта

1. Добавьте эндпоинт в `proxy/app/main.py`:

```python
@app.get("/v1/my-endpoint")
async def my_endpoint(
    user: UserContext = Depends(get_optional_auth_context),
):
    """Мой новый эндпоинт."""
    return {"status": "ok"}
```

2. Добавьте Pydantic-модели для запроса/ответа при необходимости.
3. Напишите тесты в `tests/proxy/test_my_endpoint.py`.
4. Обновите документацию API.

### Добавление нового инструмента

Смотрите [Agentic Tools SDK](agentic-tools-sdk.md) для декоратора `@tool`:

```python
from proxy.app.tools.registry import tool


@tool(
    name="my_tool",
    description="Делает что-то полезное",
    category="custom",
)
async def my_tool(query: str) -> str:
    """Выполнить мой инструмент."""
    return f"Результат для: {query}"
```

### Добавление нового LLM-провайдера

1. Добавьте адаптер в `proxy/app/llm/provider.py`:

```python
async def my_provider_completion(
    messages: list[dict],
    temperature: float = 0.2,
    max_tokens: int = 4096,
) -> str:
    """Генерация через API MyProvider."""
    # ... реализация ...
```

2. Добавьте тип провайдера в конфигурацию (`LLM_PROVIDER_TYPE`).
3. Напишите тесты.

---

## 6. Git-воркфлоу

### Ветки

| Ветка       | Назначение            |
|-------------|-----------------------|
| `main`      | Продакшен-готовый код |
| `develop`   | Интеграционная ветка  |
| `feature/*` | Разработка функций    |
| `fix/*`     | Исправление ошибок    |
| `release/*` | Подготовка релиза     |

### Сообщения коммитов

Следуйте conventional commits:

```
<тип>(<область>): <описание>

[опциональное тело]

[опциональный футер]
```

Типы: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`

Примеры:

```
feat(proxy): добавить эндпоинт федеративного поиска
fix(etl): корректная обработка пустых страниц Confluence
docs(api): обновить документацию chat completions
test(retrieval): добавить тесты граничных случаев RRF fusion
```

### Pull Requests

1. Создайте feature-ветку от `develop`
2. Внесите изменения с правильными коммитами
3. Запустите полный CI: `make all` (install → lint → test)
4. Создайте PR с описанием изменений
5. Запросите ревью
6. Squash-merge в `develop`

### CI-пайплайн

```bash
make all    # Запуск: install → lint → test
```

Отдельные шаги:

```bash
make install    # Установка зависимостей
make lint       # Ruff линтинг
make format     # Ruff форматирование
make typecheck  # Mypy проверка типов
make test       # Все тесты
```

---

## 7. Полезные команды

```bash
# ── Настройка ──────────────────────────────
make install          # Полная настройка (proxy + ETL)
make install-dev      # Настройка с dev-зависимостями
make setup            # Создать .env из .env.example

# ── Запуск ─────────────────────────────────
make run              # Запуск прокси локально

# ── Тестирование ───────────────────────────
make test             # Все тесты
make test-proxy       # Тесты прокси
make test-etl         # Тесты ETL
make test-integration # Интеграционные тесты

# ── Качество кода ──────────────────────────
make lint             # Ruff линтинг
make format           # Ruff форматирование
make format-check     # Проверка форматирования
make typecheck        # Mypy проверка типов

# ── Docker ─────────────────────────────────
make docker-build     # Сборка Docker-образов
make docker-up        # Запуск docker-compose
make docker-down      # Остановка docker-compose
make docker-logs      # Просмотр логов

# ── Очистка ────────────────────────────────
make clean            # Удаление артефактов сборки и кэшей

# ── CI ─────────────────────────────────────
make all              # Install → lint → test
```
