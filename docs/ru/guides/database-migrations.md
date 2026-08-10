# Гайд по миграциям БД

Этот гайд охватывает фреймворк миграций БД для системы RAG, который управляет изменениями схемы для SQLite (БД пользователей) и Neo4j (граф знаний).

## Обзор

Фреймворк миграций предоставляет:

- **Версионирование** через таблицу `_migrations`
- **Up/down миграции** для применения и отката изменений
- **Режим dry-run** для безопасного предпросмотра
- **Аудит-трейл** всех операций миграции
- **Идемпотентные миграции** (безопасно перезапускать)
- **Поддержка нескольких бэкендов** (SQLite и Neo4j)

## Быстрый старт

### Проверка статуса миграций

```bash
python scripts/migrate.py status
```

Вывод:

```
================================================================
  Database Migration Status
================================================================
  Current Version:    2
  Latest Available:   3
  Applied:            2
  Pending:            1
  Up to Date:         ✗ No
================================================================
```

### Применение ожидающих миграций

```bash
# Применить все ожидающие миграции
python scripts/migrate.py upgrade

# Предпросмотр (dry run)
python scripts/migrate.py upgrade --dry-run

# До указанной версии
python scripts/migrate.py upgrade --target 2
```

### Откат миграций

```bash
# Откатить до версии 1
python scripts/migrate.py downgrade 1

# Предпросмотр отката (dry run)
python scripts/migrate.py downgrade 1 --dry-run
```

### История миграций

```bash
python scripts/migrate.py history
```

## Создание новых миграций

### Через CLI

```bash
python scripts/migrate.py create add_user_preferences
```

Это создаёт файл миграции со следующим номером версии.

### Структура файла миграции

```python
# proxy/app/db/migration_004_add_user_preferences.py
"""
Migration 004: Add User Preferences

Adds user preferences table for storing user settings.
"""

from proxy.app.db.migrations import MigrationInfo, register_migration

# ─── Up-миграция ─────────────────────────────────────────────────────────────

UP_SQL = """
CREATE TABLE IF NOT EXISTS user_preferences (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, key)
);
"""

# ─── Down-миграция ──────────────────────────────────────────────────────────

DOWN_SQL = """
DROP TABLE IF EXISTS user_preferences;
"""

# ─── Регистрация миграции ───────────────────────────────────────────────────

MIGRATION = MigrationInfo(
    version=4,
    name="add_user_preferences",
    description="Add user preferences table for storing user settings",
    up_sql=UP_SQL,
    down_sql=DOWN_SQL,
    backend="sqlite",
)

# Зарегистрировать при импорте модуля
register_migration(MIGRATION)
```

### Асинхронные миграции

Для сложной логики на Python:

```python
from proxy.app.db.migrations import MigrationInfo, register_migration


async def migrate_up(conn):
    """Пользовательская логика миграции."""
    cursor = await conn.execute("SELECT id, roles FROM users")
    rows = await cursor.fetchall()

    for row in rows:
        user_id, roles_json = row
        # ... логика трансформации ...
        await conn.execute(
            "UPDATE users SET roles = ? WHERE id = ?",
            (new_roles, user_id),
        )


async def migrate_down(conn):
    """Логика отката."""
    pass


MIGRATION = MigrationInfo(
    version=5,
    name="migrate_roles",
    description="Migrate roles to new format",
    up_async=migrate_up,
    down_async=migrate_down,
    backend="sqlite",
)

register_migration(MIGRATION)
```

## Neo4j миграции

Для изменений схемы Neo4j:

```python
from proxy.app.db.migrations import MigrationInfo, register_migration


async def setup_schema(session):
    """Применение Neo4j-ограничений и индексов."""
    await session.run(
        "CREATE CONSTRAINT entity_id IF NOT EXISTS "
        "FOR (e:Entity) REQUIRE e.id IS UNIQUE"
    )
    await session.run(
        "CREATE INDEX entity_name IF NOT EXISTS "
        "FOR (e:Entity) ON (e.name)"
    )


async def teardown_schema(session):
    """Удаление элементов схемы."""
    await session.run("DROP CONSTRAINT entity_id IF EXISTS")
    await session.run("DROP INDEX entity_name IF EXISTS")


MIGRATION = MigrationInfo(
    version=6,
    name="neo4j_entity_schema",
    description="Add Entity constraints and indexes",
    up_async=setup_schema,
    down_async=teardown_schema,
    backend="neo4j",
)

register_migration(MIGRATION)
```

## Автоматические миграции при старте

Приложение автоматически применяет ожидающие миграции при запуске:

```python
# In proxy/app/main.py lifespan()
from proxy.app.db.migrations import get_migration_manager

migration_manager = get_migration_manager(
    db_path=USER_DB_PATH,
    neo4j_uri=NEO4J_URI if GRAPH_ENABLED else None,
    neo4j_user=NEO4J_USER if GRAPH_ENABLED else None,
    neo4j_password=NEO4J_PASSWORD if GRAPH_ENABLED else None,
)
await migration_manager.initialize()
await migration_manager.upgrade()
```

Чтобы отключить авто-миграции, задайте переменную окружения:

```bash
AUTO_MIGRATE=false
```

## Бэкапы БД

**Всегда делайте бэкап перед миграцией на проде:**

```bash
# Бэкап SQLite
cp ./data/users.db ./data/users.db.backup.$(date +%Y%m%d%H%M%S)

# Бэкап Neo4j (через скрипты)
./scripts/ops/backup_neo4j.sh
```

## Лучшие практики миграций

1. **Держите миграции небольшими** — одно логическое изменение на миграцию
2. **Всегда предоставляйте rollback** — добавьте `down_sql` или `down_async`
3. **Тестируйте миграции** — используйте `--dry-run` перед применением
4. **Сначала бэкап** — всегда бэкапьте продовые БД
5. **Идемпотентные операции** — используйте `IF NOT EXISTS` / `IF EXISTS`
6. **Избегайте потери данных** — не дропайте колонки без периода миграции
7. **Документируйте изменения** — понятное описание в метаданных

## Решение проблем

### Миграция завершилась ошибкой

1. Прочитайте сообщение об ошибке
2. Просмотрите лог аудита: `python scripts/migrate.py history`
3. Исправьте и повторите, либо откатитесь:

```bash
# Откат к предыдущей версии
python scripts/migrate.py downgrade <previous_version>
```

### Застрявшая миграция

Если БД в несогласованном состоянии:

1. Проверьте таблицу `_migrations` напрямую
2. Проверьте `_migration_log` для деталей ошибки
3. Исправьте вручную (с осторожностью)

### Дрейф схемы

Если схема не соответствует миграциям:

1. Сравните реальную схему с SQL миграций
2. Создайте корректирующую миграцию
3. Или сбросьте (только dev):

```bash
# Только для разработки — удаляет все данные
rm ./data/users.db
python scripts/migrate.py upgrade
```

## API Reference

### MigrationManager

```python
from proxy.app.db.migrations import MigrationManager

manager = MigrationManager(
    db_path="./data/users.db",
    neo4j_uri="bolt://localhost:7687",
    neo4j_user="neo4j",
    neo4j_password="password",
)

await manager.initialize()
await manager.upgrade(dry_run=False, target_version=None)
await manager.downgrade(target_version=1, dry_run=False)
status = await manager.get_status()
log = await manager.get_audit_log(limit=100)
await manager.close()
```

### MigrationInfo

```python
from proxy.app.db.migrations import MigrationInfo

migration = MigrationInfo(
    version=1,                  # Уникальный номер версии
    name="initial_schema",      # Имя миграции
    description="Description",  # Человеко-читаемое описание
    up_sql="SQL...",            # SQL upgrade
    down_sql="SQL...",          # SQL rollback
    up_async=None,              # Async-вызов upgrade
    down_async=None,            # Async-вызов rollback
    backend="sqlite",           # "sqlite" или "neo4j"
)
```

## Переменные окружения

| Variable          | Default                 | Описание                       |
|-------------------|-------------------------|--------------------------------|
| `USER_DB_PATH`    | `./data/users.db`       | Путь к SQLite                  |
| `NEO4J_URI`       | `bolt://localhost:7687` | URI подключения к Neo4j        |
| `NEO4J_USER`      | `neo4j`                 | Имя пользователя Neo4j         |
| `NEO4J_PASSWORD`  | `neo4j`                 | Пароль Neo4j                   |
| `GRAPH_ENABLED`   | `false`                 | Включить Neo4j-миграции        |

## Связанные документы

- [Security Guide](security-guide.md) — лучшие практики безопасности БД
- [Operations Guide](operations-guide.md) — процедуры бэкапа и восстановления
- [Configuration Reference](configuration-reference.md) — все опции конфигурации
