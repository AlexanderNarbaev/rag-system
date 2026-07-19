# Контроль доступа и дизайн RBAC

Этот документ определяет модель контроля доступа для RAG-прокси — от классификации данных через фильтрацию на уровне
Qdrant до ролевого сокращения контекста.

---

## 1. Уровни классификации данных

Каждый документ и чанк наследует метку классификации:

| Уровень          | Описание                                        | Примеры источников                         |
|------------------|-------------------------------------------------|--------------------------------------------|
| **Public**       | Доступен всем аутентифицированным пользователям | Общие документы, публичные README          |
| **Internal**     | Все сотрудники                                  | Вики команд, задачи Jira                   |
| **Confidential** | Ограниченные команды/группы                     | Архитектурная документация, HR-тикеты      |
| **Restricted**   | Только указанные лица                           | Инциденты безопасности, отчёты руководства |

Классификация назначается во время извлечения из прав доступа источника:

- **Confluence** — права на уровне пространства, сопоставляемые с `access_level`
- **Jira** — роли проекта (Administrators, Developers, Viewers)
- **GitLab** — членство в группе/проекте → массив `allowed_groups`

Метка хранится в payload Qdrant как:

```json
{
  "access_level": "confidential",
  "allowed_groups": ["engineering", "security"],
  "allowed_users": ["alice", "bob"]
}
```

---

## 2. Идентификация пользователя и аутентификация

Прокси интегрируется с корпоративным SSO через **Keycloak** (автономный, Docker). Пользователи аутентифицируются через
OIDC и получают **JWT**, содержащий:

```json
{
  "sub": "user-uuid",
  "preferred_username": "alice",
  "groups": ["engineering", "platform"],
  "realm_access": {"roles": ["developer"]},
  "access_level": "confidential"
}
```

### auth.py — модуль валидации JWT

```python
# proxy/app/auth.py
import jwt
from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional, List

security = HTTPBearer(auto_error=False)

class AuthContext:
    def __init__(self, payload: dict):
        self.user_id: str = payload["sub"]
        self.username: str = payload.get("preferred_username", "")
        self.groups: List[str] = payload.get("groups", [])
        self.roles: List[str] = payload.get("realm_access", {}).get("roles", [])
        self.access_level: str = payload.get("access_level", "internal")

    @property
    def is_admin(self) -> bool:
        return "admin" in self.roles

    @property
    def is_expert(self) -> bool:
        return "expert" in self.roles or self.is_admin


async def get_auth_context(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> AuthContext:
    """Извлечь AuthContext из JWT или вернуть анонимный контекст в режиме без аутентификации."""
    AUTH_ENABLED = request.app.state.config.get("auth_enabled", False)

    if not AUTH_ENABLED:
        return AuthContext({
            "sub": "anonymous",
            "groups": ["everyone"],
            "realm_access": {"roles": ["developer"]},
            "access_level": "public"
        })

    if not credentials:
        raise HTTPException(status_code=401, detail="Отсутствует токен авторизации")

    try:
        payload = jwt.decode(
            credentials.credentials,
            key=request.app.state.config["jwt_public_key"],
            algorithms=["RS256"],
            options={"verify_exp": True}
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Срок действия токена истёк")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Недействительный токен")

    return AuthContext(payload)
```

---

## 3. Безопасность на уровне строк в Qdrant

Контроль доступа применяется на уровне векторной БД через фильтры payload, передаваемые в Qdrant во время запроса. Это
позволяет избежать утечки ограниченных документов из базы данных.

### access_control.py — фильтрация при поиске

```python
# proxy/app/access_control.py
from typing import List, Dict, Any, Optional
from qdrant_client.models import Filter, FieldCondition, MatchAny, MatchValue, Range
from proxy.app.auth import AuthContext

def build_access_filter(auth: AuthContext) -> Optional[Filter]:
    """Построить фильтр payload Qdrant для текущего пользователя."""
    conditions = []

    # Администраторы и эксперты видят всё
    if auth.is_admin or auth.is_expert:
        return None

    # Построить разрешённые access_levels: public + internal всегда видны
    allowed_levels = ["public", "internal"]

    # Добавить confidential, если пользователь в какой-либо группе
    if auth.groups:
        allowed_levels.append("confidential")

    conditions.append(FieldCondition(
        key="access_level",
        match=MatchAny(any=allowed_levels)
    ))

    # Для restricted-контента проверить allowed_users
    if auth.username:
        conditions.append(FieldCondition(
            key="allowed_users",
            match=MatchValue(value=auth.username)
        ))

    # Фильтрация на основе групп
    if auth.groups:
        conditions.append(FieldCondition(
            key="allowed_groups",
            match=MatchAny(any=auth.groups)
        ))

    return Filter(
        should=[
            Filter(
                must=[
                    FieldCondition(key="access_level", match=MatchAny(any=["public", "internal"])),
                ]
            ),
            Filter(
                must=[
                    FieldCondition(key="access_level", match=MatchValue(value="confidential")),
                    FieldCondition(key="allowed_groups", match=MatchAny(any=auth.groups)),
                ]
            ),
            Filter(
                must=[
                    FieldCondition(key="access_level", match=MatchValue(value="restricted")),
                    FieldCondition(key="allowed_users", match=MatchValue(value=auth.username)),
                ]
            ),
        ]
    )


def trim_restricted_context(
    chunks: List[Dict[str, Any]],
    auth: AuthContext
) -> List[Dict[str, Any]]:
    """Сокращение контекста после поиска: удалить чанки, которые пользователь не должен видеть."""
    access_filter = build_access_filter(auth)
    if access_filter is None:
        return chunks

    filtered = []
    for chunk in chunks:
        level = chunk.get("payload", {}).get("access_level", "public")
        if level in ("public", "internal"):
            filtered.append(chunk)
        elif level == "confidential" and _user_in_allowed_groups(chunk, auth):
            filtered.append(chunk)
        elif level == "restricted" and _user_is_allowed(chunk, auth):
            filtered.append(chunk)
    return filtered
```

---

## 4. Модель RBAC

| Роль          | Public | Internal | Confidential | Restricted | Панель эксперта | Админ-панель |
|---------------|--------|----------|--------------|------------|-----------------|--------------|
| **Admin**     | Полный | Полный   | Полный       | Полный     | Да              | Да           |
| **Expert**    | Полный | Полный   | По группе    | Нет        | Да              | Нет          |
| **Developer** | Полный | Полный   | По группе    | Нет        | Только чтение   | Нет          |
| **Viewer**    | Полный | Полный   | Нет          | Нет        | Нет             | Нет          |
| **External**  | Полный | Нет      | Нет          | Нет        | Нет             | Нет          |

Ролевое сокращение контекста удаляет ограниченные фрагменты из контекста LLM перед генерацией:

```python
# В orchestrator.py, перед сборкой промпта:
visible_chunks = trim_restricted_context(retrieved_chunks, auth)
context = build_context(visible_chunks)
```

---

## 5. Необходимые изменения реализации

| Модуль                            | Изменение                                                     |
|-----------------------------------|---------------------------------------------------------------|
| `proxy/app/auth.py`               | Новый — валидация JWT, извлечение AuthContext                 |
| `proxy/app/access_control.py`     | Новый — build_access_filter(), trim_restricted_context()      |
| `etl/extractors/*.py`             | Добавить метаданные доступа к каждому документу               |
| `etl/chunker/semantic_chunker.py` | Передавать теги доступа чанкам                                |
| `etl/indexer/qdrant_hybrid.py`    | Хранить access_level, allowed_groups, allowed_users в payload |
| `proxy/app/config.py`             | Добавить `auth_enabled`, `jwt_public_key`, `oidc_issuer`      |
| `proxy/app/orchestrator.py`       | Интегрировать access_filter в конвейер поиска                 |
| `scripts/`                        | Добавить `init_keycloak.sh` для начальной настройки           |

---

## 6. Особенности автономной среды

- **Keycloak** работает как Docker-сервис в `docker-compose.yml`; нет зависимости от внешнего IdP.
- **Публичные ключи JWT** загружаются из примонтированного тома (`/secrets/jwt_public.pem`).
- **Валидация токенов** использует офлайн-верификацию RS256 — без вызовов к IdP во время запроса.
- **Синхронизация пользователей/групп** происходит через запланированный внутренний скрипт, который запрашивает
  корпоративный LDAP и отправляет обновления в API администратора Keycloak, офлайн между запусками синхронизации.

---

## 7. Стратегия поэтапного внедрения

| Фаза | Область                     | Режим аутентификации | Уровень фильтрации              |
|------|-----------------------------|----------------------|---------------------------------|
| 1    | Текущее состояние           | Нет                  | Без фильтрации                  |
| 2    | Уровень источников          | JWT + Keycloak       | Блокировка целых источников     |
| 3    | Уровень документов          | JWT + Keycloak       | Фильтр payload на документ      |
| 4    | Уровень чанков + сокращение | JWT + Keycloak       | Фильтр Qdrant + пост-сокращение |

Каждая фаза управляется флагами конфигурации `auth_enabled` и `filtering_level`, позволяя командам внедрять контроль
доступа инкрементально, не нарушая существующие рабочие процессы.
