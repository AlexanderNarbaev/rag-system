# Гайд по ротации секретов

Этот гайд охватывает автоматизированную систему ротации секретов для RAG-прокси — JWT-ключи подписи, API-ключи и учётные данные БД. Включает расписания ротации, аварийные процедуры, интеграцию с Vault и операционные runbook'и.

## Содержание

1. [Обзор](#обзор)
2. [Архитектура](#архитектура)
3. [Расписание ротации](#расписание-ротации)
4. [Автоматическая ротация](#автоматическая-ротация)
5. [Ручная ротация](#ручная-ротация)
6. [Аварийная ротация](#аварийная-ротация)
7. [Мониторинг здоровья](#мониторинг-здоровья)
8. [Интеграция с Vault / K8s](#интеграция-с-vault--k8s)
9. [Процедуры отката](#процедуры-отката)
10. [Решение проблем](#решение-проблем)

---

## Обзор

### Зачем ротировать секреты?

| Угроза                              | Митигация                              |
|-------------------------------------|-----------------------------------------|
| Утечка учётных данных               | Короткоживущие ключи ограничивают окно  |
| Инсайдерские угрозы                 | Регулярная ротация ограничивает доступ  |
| Compliance (SOC2, ISO 27001)        | Демонстрируемая политика ротации        |
| Обнаружение компрометации ключа     | Аварийная ротация                       |
| Устаревшие credentials в бэкапах    | Grace period для старых ключей          |

### Принципы дизайна

- **Zero-downtime**: старые ключи остаются валидными grace period после ротации.
- **Обратная совместимость**: in-flight токены проверяются по обоим ключам.
- **Аудит-трейл**: каждая ротация логируется с timestamp, fingerprints, инициатором.
- **Air-gapped совместимость**: нет внешних API-вызовов — вся генерация ключей локальная.
- **Graceful degradation**: сбои ротации не крашат прокси.

---

## Архитектура

### Компоненты

| Компонент                       | Файл                                        | Назначение                         |
|---------------------------------|---------------------------------------------|-------------------------------------|
| **SecretRotationManager**       | `proxy/app/auth/secret_rotation.py`         | Основная логика ротации, генерация ключей |
| **rotate-secrets.sh**           | `scripts/ops/rotate-secrets.sh`             | Shell-based ротация (cron, ручная)  |
| **Health endpoint**             | `proxy/app/api/health.py`                   | Статус ротации в `/v1/health`       |
| **Аудит-логгер**                | `proxy/app/shared/audit.py`                 | Аудит-трейл событий ротации         |
| **Состояние ротации**           | `data/rotation/rotation_state.json`         | Персистентные метаданные ротации    |

### Поток ротации

```
┌─────────────────────────────────────────────────────────────────┐
│                    Secrets Rotation Flow                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. Бэкап текущего .env                                         │
│     └── proxy/.env.backups/.env.20260716_030000                 │
│                                                                 │
│  2. Генерация новых ключей                                      │
│     ├── JWT: RSA-2048 / EC P-256 / HS256                       │
│     └── API: sk-{random} на пользователя                       │
│                                                                 │
│  3. Обновление .env файла                                       │
│     ├── JWT_SECRET=<new_private_key>                            │
│     ├── JWT_PUBLIC_KEY=<new_public_key>                         │
│     └── JWT_ALGORITHM=RS256                                     │
│                                                                 │
│  4. Сигнал на перезагрузку сервиса                              │
│     ├── /tmp/rag-secrets-rotated (file signal)                  │
│     └── SIGHUP в Docker-контейнер                              │
│                                                                 │
│  5. Начинается grace period                                     │
│     └── Старые токены валидны в течение JWT_GRACE_PERIOD_SECONDS│
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Расписание ротации

### Рекомендуемые интервалы

| Тип секрета            | Продакшен          | Разработка         | После инцидента |
|------------------------|--------------------|--------------------|-----------------|
| **JWT-ключи подписи**  | 90 дней            | 180 дней           | Немедленно      |
| **API-ключи**          | 180 дней           | 365 дней           | Немедленно      |
| **Пароли БД**          | 90 дней            | 365 дней           | Немедленно      |
| **Embedder API-ключи** | По политике вендора| По политике вендора| Немедленно      |
| **LLM API-ключи**      | По политике вендора| По политике вендора| Немедленно      |

### Конфигурация cron

```bash
# Ежемесячная JWT-ротация (1-го числа в 03:00 UTC)
0 3 1 * * FORCE=true SKIP_API_KEYS=true /scripts/ops/rotate-secrets.sh

# Ежеквартальная полная ротация (1-го янв/апр/июл/окт в 03:00 UTC)
0 3 1 1,4,7,10 * FORCE=true /scripts/ops/rotate-secrets.sh

# Еженедельная проверка здоровья (понедельник в 09:00 UTC)
0 9 * * 1 curl -sf http://localhost:8080/v1/health | jq '.components.secret_rotation'
```

### Планирование в Kubernetes

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: secrets-rotation
spec:
  schedule: "0 3 1 * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
            - name: rotate
              image: rag-system:latest
              command: ["/scripts/ops/rotate-secrets.sh", "--force"]
              volumeMounts:
                - name: env-file
                  mountPath: /app/proxy/.env
                  subPath: .env
                - name: rotation-data
                  mountPath: /app/data/rotation
          volumes:
            - name: env-file
              secret:
                secretName: rag-proxy-env
            - name: rotation-data
              persistentVolumeClaim:
                claimName: rotation-data
          restartPolicy: OnFailure
```

---

## Автоматическая ротация

### Через shell-скрипт

```bash
# Полная интерактивная ротация
./scripts/ops/rotate-secrets.sh

# Dry-run (предпросмотр изменений)
DRY_RUN=true ./scripts/ops/rotate-secrets.sh

# Только JWT (автоматизированная)
FORCE=true SKIP_API_KEYS=true ./scripts/ops/rotate-secrets.sh

# Ротация EC-ключей
JWT_KEY_TYPE=ec ./scripts/ops/rotate-secrets.sh

# С кастомным путём .env
ROTATE_ENV_FILE=/etc/rag/proxy.env ./scripts/ops/rotate-secrets.sh
```

### Через Python API

```python
from proxy.app.auth.secret_rotation import get_rotation_manager

manager = get_rotation_manager()

# Ротация JWT-ключей (RSA-2048, 1-часовой grace)
record = await manager.rotate_jwt_keys(
    algorithm="RS256",
    initiated_by="admin",
    grace_seconds=3600
)
print(f"Rotation {record.rotation_id}: {record.status}")

# Ротация API-ключей для конкретных пользователей
record = await manager.rotate_api_keys(
    user_ids=["user-1", "user-2"],
    initiated_by="cron",
    overlap_seconds=86400
)

# Проверка статуса ротации
status = manager.get_rotation_status()
print(f"Last rotation: {status['last_rotation']}")
print(f"JWT key age: {status['jwt_key_age_seconds']}s")
```

### Типы ключей

| Алгоритм | Тип ключа    | Размер     | Применение                    |
|----------|--------------|------------|-------------------------------|
| RS256    | RSA-2048     | 2048-bit   | Продакшен (по умолчанию)      |
| ES256    | EC P-256     | 256-bit    | Высокопроизводительный прод    |
| HS256    | Симметричный | 512-bit    | Разработка, air-gapped         |

---

## Ручная ротация

### Пошаговая процедура

1. **Проверить текущее здоровье**
   ```bash
   curl -s http://localhost:8080/v1/health | jq '.components.secret_rotation'
   ```

2. **Создать бэкап**
   ```bash
   cp proxy/.env proxy/.env.manual-backup-$(date +%Y%m%d)
   ```

3. **Запустить ротацию**
   ```bash
   ./scripts/ops/rotate-secrets.sh --jwt-only
   ```

4. **Проверить новое здоровье**
   ```bash
   curl -s http://localhost:8080/v1/health | jq '.components'
   ```

5. **Протестировать аутентификацию**
   ```bash
   # Сгенерировать тестовый токен
   curl -X POST http://localhost:8080/v1/auth/login \
     -H 'Content-Type: application/json' \
     -d '{"username": "admin", "password": "your-password"}'

   # Проверить работу токена
   curl -H 'Authorization: Bearer <token>' http://localhost:8080/v1/models
   ```

6. **Мониторить 15 минут**
   ```bash
   tail -f /var/log/rag-system/rotation_*.log
   ```

---

## Аварийная ротация

### Когда ротировать немедленно

- JWT-секрет утёк или залогирован
- API-ключи обнаружены в публичных репозиториях
- Подозрение на несанкционированный доступ
- Находка аудита безопасности
- Увольнение сотрудника (скомпрометированные аккаунты)

### Аварийная процедура

```bash
# 1. Ротировать немедленно (без подтверждения, grace=0)
FORCE=true ./scripts/ops/rotate-secrets.sh

# 2. Проверить здоровье
curl -s http://localhost:8080/v1/health | jq .

# 3. Проверить аудит-лог на несанкционированный доступ
tail -100 /var/log/rag-system/audit.jsonl | jq 'select(.event_type == "login")'

# 4. Принудительно завершить все сессии (отозвать все refresh-токены)
python3 -c "
import asyncio
from proxy.app.auth.user_db import get_user_db
db = get_user_db()
# Требуется реализация admin-эндпоинта
"
```

### Чек-лист реагирования на инцидент

- [ ] Ротировать все затронутые секреты немедленно
- [ ] Просмотреть аудит-логи на несанкционированный доступ
- [ ] Отозвать все активные сессии затронутых пользователей
- [ ] Уведомить команду безопасности
- [ ] Задокументировать таймлайн инцидента
- [ ] Обновить расписание ротации при необходимости
- [ ] Убедиться, что секреты не остались в version control

---

## Мониторинг здоровья

### Ответ health-эндпоинта

```json
{
  "status": "ok",
  "timestamp": "2026-07-16T10:30:00Z",
  "components": {
    "qdrant": "ok",
    "llm": "ok",
    "kb_manager": "ok",
    "secret_rotation": "ok",
    "secret_rotation_info": {
      "last_rotation": "2026-07-01T03:00:00Z",
      "total_rotations": 12,
      "failed_rotations": 0,
      "active_rotations": 0,
      "jwt_key_age_seconds": 1296000,
      "last_error": null,
      "grace_period_seconds": 3600
    }
  }
}
```

### Значения статусов

| Статус      | Значение                            | Требуемое действие           |
|-------------|-------------------------------------|------------------------------|
| `ok`        | Ротация здорова, ключ свежий        | Нет                          |
| `degraded`  | Последняя ротация с ошибками        | Проверить `last_error`       |
| `stale_key` | JWT-ключ старше 30 дней             | Запланировать ротацию        |
| `rotating`  | Ротация в процессе                  | Дождаться завершения         |
| `error`     | Сбой модуля ротации                 | Проверить логи, рестарт      |

### Prometheus-метрики

```yaml
# Добавить в config/monitoring/prometheus.yml
- alert: StaleJWTKey
  expr: rag_secret_rotation_jwt_key_age_seconds > 2592000  # 30 дней
  for: 1h
  labels:
    severity: warning
  annotations:
    summary: "JWT signing key старше 30 дней"

- alert: RotationFailed
  expr: rag_secret_rotation_failed_rotations > 0
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "Сбой ротации секретов"
```

---

## Интеграция с Vault / K8s

### HashiCorp Vault

```bash
# Сохранить секреты в Vault
vault kv put secret/rag-proxy/jwt \
  secret="$(cat data/rotation/jwt_private_key.pem)" \
  public_key="$(cat data/rotation/jwt_public_key.pem)" \
  algorithm="RS256"

# Получить в приложении
export JWT_SECRET=$(vault kv get -field=secret secret/rag-proxy/jwt)
export JWT_PUBLIC_KEY=$(vault kv get -field=public_key secret/rag-proxy/jwt)
```

### Vault Agent Auto-Rotation

```hcl
# vault-agent-config.hcl
template {
  source      = "/etc/vault-agent/jwt-secret.tpl"
  destination = "/etc/rag-proxy/jwt-secret"
  perms       = "0600"
}

template {
  source      = "/etc/vault-agent/env.tpl"
  destination = "/etc/rag-proxy/.env"
  perms       = "0644"

  command = "docker kill -s HUP rag-proxy"
}
```

### Kubernetes Secrets

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: rag-proxy-secrets
  namespace: rag-system
type: Opaque
data:
  JWT_SECRET: <base64-encoded>
  JWT_PUBLIC_KEY: <base64-encoded>
  API_KEY_EMBEDDER: <base64-encoded>
  API_KEY_RERANKER: <base64-encoded>
  API_KEY_LLM: <base64-encoded>
```

### External Secrets Operator

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: rag-proxy-secrets
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-backend
    kind: SecretStore
  target:
    name: rag-proxy-secrets
    creationPolicy: Owner
  data:
    - secretKey: JWT_SECRET
      remoteRef:
        key: secret/rag-proxy/jwt
        property: secret
```

### Sealed Secrets (Bitnami)

```bash
# Создать sealed secret для air-gapped окружений
kubeseal --format yaml < rag-proxy-secrets.yaml > rag-proxy-sealed.yaml
```

---

## Процедуры отката

### Автоматический откат

Скрипт ротации автоматически создаёт бэкапы перед изменениями:

```bash
# Список доступных бэкапов
ls -la proxy/.env.backups/

# Откат к последнему бэкапу
./scripts/ops/rotate-secrets.sh --rollback

# Откат к конкретному бэкапу
cp proxy/.env.backups/.env.20260716_030000 proxy/.env
docker restart rag-proxy
```

### Ручной откат

```bash
# 1. Остановить прокси
docker-compose -f proxy/docker-compose.yml stop proxy

# 2. Восстановить .env
cp proxy/.env.backups/.env.20260701_030000 proxy/.env

# 3. Рестарт
docker-compose -f proxy/docker-compose.yml start proxy

# 4. Верификация
curl -s http://localhost:8080/v1/health | jq .
```

### Валидация отката

```bash
# После отката проверить:
# 1. Health endpoint возвращает 200
curl -sf http://localhost:8080/v1/health

# 2. Аутентификация работает
curl -X POST http://localhost:8080/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username": "admin", "password": "your-password"}'

# 3. Нет ошибок в логах
docker logs rag-proxy --tail 50 | grep -i error
```

---

## Решение проблем

### Распространённые проблемы

#### Скрипт ротации падает

```bash
# Проверить предварительные требования
openssl version
python3 --version
jq --version

# Проверить права
ls -la proxy/.env
ls -la scripts/ops/rotate-secrets.sh
```

#### Grace period истёк, но сервис не перезагружен

```bash
# Проверить, существует ли файл-сигнал
ls -la /tmp/rag-secrets-rotated

# Отправить SIGHUP вручную
docker kill -s HUP rag-proxy

# Или через PID
kill -HUP $(pgrep -f "uvicorn proxy.app.main")
```

#### Старые токены не работают после ротации

```bash
# Проверить grace period в health endpoint
curl -s http://localhost:8080/v1/health | jq '.components.secret_rotation_info'

# Проверить, что .env обновлён
grep JWT_SECRET proxy/.env | head -c 50

# Проверить, что сервис перезагружен
docker logs rag-proxy --tail 10 | grep -i "rotation\|secret\|reload"
```

#### API-ключи не ротируются

```bash
# Проверить, что пользователи существуют
curl -s http://localhost:8080/v1/auth/me -H 'Authorization: Bearer <admin-token>'

# Проверить, что user_db доступна
python3 -c "from proxy.app.auth.user_db import get_user_db; db = get_user_db(); print(db.list_users())"
```

---

## Связанные документы

- [Security Guide](security-guide.md) — Общие практики безопасности
- [Operations Guide](operations-guide.md) — Операционные процедуры
- [Configuration Reference](configuration-reference.md) — Все опции конфигурации
