# Блок G. HITL, Auth и RBAC (FR-73 — FR-94)

---

## FR-73. Expert feedback submission

**Описание:**
Эксперты могут отправлять feedback на ответы системы:
- `positive` — ответ корректен
- `negative` — ответ некорректен (с обязательным полем `correction`)
- Feedback привязывается к `rag_feedback_id` из ответа

**Критерий приёмки:**
1. POST `/v1/feedback` с `feedback_type=positive` — 200 OK
2. POST `/v1/feedback` с `feedback_type=negative, correction="..."` — 200 OK
3. Feedback без `correction` при `negative` — 400 Bad Request

**Статус:** ⚠️ Код есть (`proxy/app/api/feedback.py`), нужен интеграционный тест
**Приоритет:** HIGH
**Связь:** ADR-007

---

## FR-74. Feedback storage (SQLite)

**Описание:**
Feedback хранится в SQLite с метаданными: user_id, feedback_id, query, answer,
feedback_type, correction, timestamp. Поддерживает экспорт в JSONL для fine-tuning.

**Критерий приёмки:**
1. Feedback сохраняется в SQLite
2. Экспорт в JSONL — валидный формат для fine-tuning
3. Запрос feedback по feedback_id — возвращает запись

**Статус:** ⚠️ Код есть (`proxy/app/core/feedback_store.py`), нужен интеграционный тест
**Приоритет:** HIGH
**Связь:** ADR-007

---

## FR-75. Feedback analytics

**Описание:**
Админ-панель показывает статистику feedback:
- Количество positive/negative за период
- Топ-10 запросов с negative feedback
- Средний confidence score по feedback
- Тренды по дням/неделям

**Критерий приёмки:**
1. GET `/v1/admin/feedback/stats` — возвращает статистику
2. Статистика включает count_positive, count_negative, avg_confidence
3. Фильтрация по дате работает

**Статус:** ⚠️ Код есть (`proxy/app/api/admin_analytics.py`), нужен интеграционный тест
**Приоритет:** HIGH
**Связь:** ADR-007

---

## FR-76. Feedback → training dataset export

**Описание:**
Система экспортирует feedback в формате для fine-tuning:
- Positive feedback → positive pairs (query, good_answer)
- Negative feedback → negative pairs (query, bad_answer, correction)
- Формат: JSONL с полями query, response, correction, label

**Критерий приёмки:**
1. Экспорт в JSONL — валидный формат
2. Positive feedback → positive pair в экспорте
3. Negative feedback → negative pair с correction в экспорте

**Статус:** ⚠️ Код есть (`proxy/app/core/feedback_store.py`), нужен интеграционный тест
**Приоритет:** HIGH
**Связь:** ADR-007, ADR-010

---

## FR-77. Rate limiting для feedback

**Описание:**
Один пользователь может отправить не более 100 feedback-записей в час.

**Критерий приёмки:**
1. 100 feedback/час — все обрабатываются
2. 101-й feedback — 429 Too Many Requests

**Статус:** ⚠️ Код есть (`proxy/app/api/feedback.py`), нужен интеграционный тест
**Приоритет:** MEDIUM
**Связь:** NFR-S12

---

## FR-78. Feedback metadata preservation

**Описание:**
При переиндексации документа feedback сохраняется и привязывается к новой версии
чанка (если содержимое не изменилось кардинально).

**Критерий приёмки:**
1. Переиндексация документа — feedback сохраняется
2. Feedback привязывается к новому chunk_id (если контент тот же)
3. Полностью изменённый контент — feedback отвязывается

**Статус:** ⚠️ Код есть, нужен интеграционный тест
**Приоритет:** MEDIUM
**Связь:** NFR-M05

---

## FR-84. JWT authentication (access + refresh)

**Описание:**
Система генерирует JWT-токены:
- **Access token** —短期 (15 мин), содержит user_id, roles, permissions
- **Refresh token** —长期 (7 дней), хранится в SQLite, можно отозвать

При login — выдаётся пара токенов. При refresh — старый refresh инвалидируется,
выдаётся новая пара.

**Критерий приёмки:**
1. POST `/v1/auth/login` — возвращает `{access_token, refresh_token, token_type, expires_in}`
2. GET `/v1/auth/me` с access_token — возвращает user context
3. POST `/v1/auth/refresh` с refresh_token — возвращает новую пару
4. Истёкший access_token — 401 Unauthorized
5. Отозванный refresh_token — 401 Unauthorized

**Статус:** ✅ Подтверждено (`proxy/app/auth/jwt.py`)
**Приоритет:** CRITICAL
**Связь:** ADR-004

---

## FR-85. Keycloak OIDC integration

**Описание:**
Система интегрируется с Keycloak для корпоративного SSO. Пользователь
аутентифицируется через Keycloak, прокси получает access token и маппит
roles из Keycloak в локальные роли.

**Критерий приёмки:**
1. Keycloak access token — прокси аутентифицирует пользователя
2. Roles из Keycloak маппятся в локальные (admin/expert/user/read_only)
3. Невалидный Keycloak token — 401

**Статус:** ⚠️ Код есть (`proxy/app/auth/ldap.py`), нужен интеграционный тест
**Приоритет:** HIGH
**Связь:** access-control-rbac

---

## FR-86. LDAP/AD authentication

**Описание:**
Система подключается к LDAP/AD для аутентифициации корпоративных пользователей.
Параметры: LDAP URL, base DN, bind DN, bind password.

**Критерий приёмки:**
1. Валидные LDAP credentials — аутентификация успешна
2. Невалидные credentials — 401
3. LDAP недоступен — fallback к локальной БД

**Статус:** ⚠️ Код есть (`proxy/app/auth/ldap.py`), нужен интеграционный тест
**Приоритет:** HIGH
**Связь:** access-control-rbac

---

## FR-87. API key authentication

**Описание:**
Система поддерживает API-ключи как альтернативный метод аутентификации.
Ключи хранятся в SQLite, привязаны к пользователю, могут быть отозваны.

**Критерий приёмки:**
1. `Authorization: Bearer sk-xxx` — аутентификация успешна
2. Невалидный ключ — 401
3. Отозванный ключ — 401

**Статус:** ⚠️ Код есть (`proxy/app/auth/api_keys.py`), нужен интеграционный тест
**Приоритет:** HIGH
**Связь:** access-control-rbac

---

## FR-88. RBAC — 4 роли

**Описание:**
Система реализует Role-Based Access Control с 4 ролями:
- **admin** — полный доступ ко всем эндпоинтам и админ-панели
- **expert** — доступ к chat, feedback, knowledge base management
- **user** — доступ к chat только
- **read_only** — доступ к chat в режиме «только чтение» (без feedback)

**Критерий приёмки:**
1. Admin — доступ ко всем `/v1/admin/*` эндпоинтам
2. Expert — доступ к `/v1/feedback`, 403 на `/v1/admin/*`
3. User — доступ к `/v1/chat/completions`, 403 на `/v1/feedback`
4. Read_only — доступ к `/v1/chat/completions`, 403 на `/v1/feedback`

**Статус:** ⚠️ Код есть (`proxy/app/auth/rbac.py`), нужен интеграционный тест
**Приоритет:** CRITICAL
**Связь:** access-control-rbac

---

## FR-89. ACL в Qdrant-запросах

**Описание:**
Каждый поисковый запрос к Qdrant включает фильтр по ACL. Пользователь видит
только те чанки, к которым у него есть доступ. ACL хранится в payload каждого чанка.

**Критерий приёмки:**
1. User с role=user — видит только чанки с access_level=public или access_level=user
2. User с role=admin — видит все чанки
3. Запрос без аутентификации — видит только public чанки

**Статус:** ⚠️ Код есть (`proxy/app/shared/access_control.py`), нужен интеграционный тест
**Приоритет:** CRITICAL
**Связь:** NFR-S03

---

## FR-90. Secret rotation

**Описание:**
Система поддерживает ротацию секретов (JWT secret, API keys) без простоя.
Старый секрет остаётся валидным в течение grace period (по умолчанию 24 часа).

**Критерий приёмки:**
1. Ротация JWT secret — старые токены валидны в течение grace period
2. После grace period — старые токены невалидны
3. Ротация API key — старый ключ валиден в течение grace period

**Статус:** ⚠️ Код есть (`proxy/app/auth/secret_rotation.py`), нужен интеграционный тест
**Приоритет:** HIGH
**Связь:** secrets-rotation.md

---

## FR-91. Rate limiting ✅

**Описание:**
Система ограничивает количество запросов с одного IP: token bucket algorithm
с burst. Параметры: `RATE_LIMIT_PER_MINUTE=60`, `RATE_LIMIT_BURST=10`.

**Критерий приёмки:**
1. 60 запросов/минуту — все обрабатываются
2. 61-й запрос — 429 Too Many Requests
3. Burst до 10 запросов — обрабатываются немедленно
4. После burst — rate limit восстанавливается по token bucket

**Статус:** ✅ Подтверждено (`proxy/app/shared/rate_limiter.py`)
**Приоритет:** HIGH
**Связь:** best-practices-checklist 3.2

---

## FR-92. Input validation ✅

**Описание:**
Система валидирует все входные данные:
- Query ≤ 10,000 символов
- Messages ≤ 100 сообщений
- Content не пустой
- JSON валидный
- Temperature 0-2
- Max_tokens > 0

**Критерий приёмки:**
1. Query > 10K символов — 400 Bad Request
2. Пустой content — 400
3. Невалидный JSON — 400
4. Temperature > 2 — 400

**Статус:** ✅ Подтверждено (`proxy/app/shared/security.py`)
**Приоритет:** CRITICAL
**Связь:** best-practices-checklist 3.5

---

## FR-93. Audit logging

**Описание:**
Все события безопасности логируются в JSONL-файл:
- Login/logout (user_id, timestamp, IP, success/failure)
- Admin actions (who, what, when)
- Config changes (who, old_value, new_value)
- Feedback submissions (user_id, feedback_id, timestamp)

**Критерий приёмки:**
1. Login — запись в audit log с user_id, timestamp, IP
2. Admin action — запись в audit log
3. Audit log — валидный JSONL
4. Секреты замаскированы (не в открытом виде)

**Статус:** ⚠️ Код есть (`proxy/app/shared/audit.py`), нужен интеграционный тест
**Приоритет:** CRITICAL
**Связь:** best-practices-checklist 3.10

---

## FR-94. CORS configuration

**Описание:**
CORS-заголовки настраиваются через `CORS_ORIGINS` (список разрешённых origins).
По умолчанию — `*` (все origins). В production — конкретные домены.

**Критерий приёмки:**
1. `CORS_ORIGINS=*` — заголовок `Access-Control-Allow-Origin: *`
2. `CORS_ORIGINS=https://example.com` — заголовок `Access-Control-Allow-Origin: https://example.com`
3. Preflight OPTIONS — возвращает 200 с CORS-заголовками

**Статус:** ⚠️ Код есть (`proxy/app/shared/middleware.py`), нужен интеграционный тест
**Приоритет:** HIGH
**Связь:** middleware.py
