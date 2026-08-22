# RAG-прокси для Gemma

**Версия:** 2.0.0  
**Сгенерировано:** 2026-07-16 05:08 UTC  
**OpenAPI:** 3.1.0  

OpenAI-совместимый прокси с гибридным поиском, реранкингом и LLM Gemma.

---

## Содержание

- [admin](#admin)
- [admin-kb](#admin-kb)
- [auth](#auth)
- [chat](#chat)
- [feedback](#feedback)
- [files](#files)
- [health](#health)
- [metrics](#metrics)
- [tools](#tools)
- [untagged](#untagged)
- [widget](#widget)

---

## Admin
### `GET /v1/admin/models`
**Admin Models List**

Список всех зарегистрированных моделей с версиями и стадиями (только для администраторов).

#### Ответы

**`200`** — Успешный ответ

_operationId: `admin_models_list_v1_admin_models_get`_

---

### `POST /v1/admin/models/canary/split`
**Admin Models Canary Split**

Установить долю canary-трафика для модели (только для администраторов).

#### Тело запроса

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `model_name` | `string` | ✓ |  |
| `traffic_split` | `number` | ✓ | Доля трафика, направляемая на canary (0.0-1.0) |

#### Ответы

**`200`** — Успешный ответ

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `model_name` | `string` | ✓ |  |
| `traffic_split` | `number` | ✓ |  |
| `status` | `string` | ✓ |  |

**`422`** — Ошибка валидации

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `admin_models_canary_split_v1_admin_models_canary_split_post`_

---

### `GET /v1/admin/models/canary/status`
**Admin Models Canary Status**

Получить текущий статус canary-развёртывания и метрики (только для администраторов).

#### Ответы

**`200`** — Успешный ответ

_operationId: `admin_models_canary_status_v1_admin_models_canary_status_get`_

---

### `POST /v1/admin/models/evaluate`
**Admin Models Evaluate**

Запустить eval gate по метрикам модели (только для администраторов).

#### Тело запроса

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `model_name` | `string` | ✓ |  |
| `version` | `string` |  |  |
| `metrics` | `object` | ✓ |  |

#### Ответы

**`200`** — Успешный ответ

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `model_name` | `string` | ✓ |  |
| `version` | `string` | ✓ |  |
| `status` | `string` | ✓ |  |
| `failures` | `array[string]` | ✓ |  |
| `warnings` | `array[string]` | ✓ |  |
| `metrics` | `object` | ✓ |  |

**`422`** — Ошибка валидации

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `admin_models_evaluate_v1_admin_models_evaluate_post`_

---

### `POST /v1/admin/models/promote`
**Admin Models Promote**

Продвинуть версию модели по цепочке staging -> canary -> production (только для администраторов).

#### Тело запроса

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `model_name` | `string` | ✓ |  |
| `version` | `string` | ✓ |  |

#### Ответы

**`200`** — Успешный ответ

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `model_name` | `string` | ✓ |  |
| `version` | `string` | ✓ |  |
| `previous_status` | `string` | ✓ |  |
| `new_status` | `string` | ✓ |  |

**`422`** — Ошибка валидации

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `admin_models_promote_v1_admin_models_promote_post`_

---

### `POST /v1/admin/models/rollback`
**Admin Models Rollback**

Откатиться к предыдущей production-версии (только для администраторов).

#### Тело запроса

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `model_name` | `string` | ✓ |  |

#### Ответы

**`200`** — Успешный ответ

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `model_name` | `string` | ✓ |  |
| `version` | `string` | ✓ |  |
| `previous_version` | `string` | ✓ |  |
| `status` | `string` | ✓ |  |

**`422`** — Ошибка валидации

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `admin_models_rollback_v1_admin_models_rollback_post`_

---

### `GET /v1/admin/models/status/{job_id}`
**Admin Models Status**

Проверить статус задачи обучения (только для администраторов).

#### Параметры

| Имя | Расположение | Тип | Обязательное | Описание |
|-----|--------------|-----|--------------|----------|
| `job_id` | path | `string` | ✓ |  |

#### Ответы

**`200`** — Успешный ответ

**`422`** — Ошибка валидации

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `admin_models_status_v1_admin_models_status__job_id__get`_

---

### `POST /v1/admin/models/train`
**Admin Models Train**

Запустить задачу обучения модели (только для администраторов).

#### Тело запроса

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `trainer_type` | `string` | ✓ |  |
| `base_model` | `string` |  |  |
| `profile` | `string` |  |  |
| `data_dir` | `string` |  |  |
| `epochs` | `integer` |  |  |
| `batch_size` | `integer` |  |  |
| `learning_rate` | `number` |  |  |
| `use_lora` | `boolean` |  |  |

#### Ответы

**`200`** — Успешный ответ

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `job_id` | `string` | ✓ |  |
| `trainer_type` | `string` | ✓ |  |
| `status` | `string` | ✓ |  |
| `message` | `string` | ✓ |  |

**`422`** — Ошибка валидации

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `admin_models_train_v1_admin_models_train_post`_

---

### `POST /v1/admin/warmup`
**Admin Warmup**

Запустить прогрев модели (только для администраторов).

#### Ответы

**`200`** — Успешный ответ

_operationId: `admin_warmup_v1_admin_warmup_post`_

---

## Admin-Kb
### `GET /v1/admin/kb/`
**List Knowledge Bases**

Список всех баз знаний.

#### Параметры

| Имя | Расположение | Тип | Обязательное | Описание |
|-----|--------------|-----|--------------|----------|
| `include_deleted` | query | `boolean` |  |  |

#### Ответы

**`200`** — Успешный ответ

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `knowledge_bases` | `array[KBResponse]` | ✓ |  |
| `total` | `integer` | ✓ |  |

**`422`** — Ошибка валидации

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `list_knowledge_bases_v1_admin_kb__get`_

---

### `POST /v1/admin/kb/`
**Create Knowledge Base**

Создать новую базу знаний с собственной коллекцией Qdrant.

#### Тело запроса

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `name` | `string` | ✓ | Название базы знаний |
| `description` | `string` |  | Описание базы знаний |
| `embedding_model` | `string` |  | Название модели эмбеддингов |
| `dense_vector_size` | `integer` |  | Размерность плотного вектора |
| `parser_config` | `any` |  | Конфигурация парсера |

#### Ответы

**`201`** — Успешный ответ

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `id` | `string` | ✓ |  |
| `name` | `string` | ✓ |  |
| `description` | `string` | ✓ |  |
| `collection_name` | `string` | ✓ |  |
| `embedding_model` | `string` | ✓ |  |
| `dense_vector_size` | `integer` | ✓ |  |
| `parser_config` | `object` | ✓ |  |
| `doc_count` | `integer` | ✓ |  |
| `chunk_count` | `integer` | ✓ |  |
| `token_count` | `integer` | ✓ |  |
| `status` | `string` | ✓ |  |
| `created_at` | `number` | ✓ |  |
| `updated_at` | `number` | ✓ |  |

**`422`** — Ошибка валидации

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `create_knowledge_base_v1_admin_kb__post`_

---

### `PUT /v1/admin/kb/{kb_id}`
**Update Knowledge Base**

Обновить базу знаний.

#### Параметры

| Имя | Расположение | Тип | Обязательное | Описание |
|-----|--------------|-----|--------------|----------|
| `kb_id` | path | `string` | ✓ |  |

#### Тело запроса

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `name` | `any` |  |  |
| `description` | `any` |  |  |
| `embedding_model` | `any` |  |  |
| `parser_config` | `any` |  |  |

#### Ответы

**`200`** — Успешный ответ

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `id` | `string` | ✓ |  |
| `name` | `string` | ✓ |  |
| `description` | `string` | ✓ |  |
| `collection_name` | `string` | ✓ |  |
| `embedding_model` | `string` | ✓ |  |
| `dense_vector_size` | `integer` | ✓ |  |
| `parser_config` | `object` | ✓ |  |
| `doc_count` | `integer` | ✓ |  |
| `chunk_count` | `integer` | ✓ |  |
| `token_count` | `integer` | ✓ |  |
| `status` | `string` | ✓ |  |
| `created_at` | `number` | ✓ |  |
| `updated_at` | `number` | ✓ |  |

**`422`** — Ошибка валидации

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `update_knowledge_base_v1_admin_kb__kb_id__put`_

---

### `DELETE /v1/admin/kb/{kb_id}`
**Delete Knowledge Base**

Удалить базу знаний (по умолчанию — мягкое удаление).

#### Параметры

| Имя | Расположение | Тип | Обязательное | Описание |
|-----|--------------|-----|--------------|----------|
| `kb_id` | path | `string` | ✓ |  |
| `hard` | query | `boolean` |  |  |

#### Ответы

**`200`** — Успешный ответ

_Свойства не определены._

**`422`** — Ошибка валидации

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `delete_knowledge_base_v1_admin_kb__kb_id__delete`_

---

### `GET /v1/admin/kb/{kb_id}`
**Get Knowledge Base**

Получить базу знаний по ID.

#### Параметры

| Имя | Расположение | Тип | Обязательное | Описание |
|-----|--------------|-----|--------------|----------|
| `kb_id` | path | `string` | ✓ |  |

#### Ответы

**`200`** — Успешный ответ

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `id` | `string` | ✓ |  |
| `name` | `string` | ✓ |  |
| `description` | `string` | ✓ |  |
| `collection_name` | `string` | ✓ |  |
| `embedding_model` | `string` | ✓ |  |
| `dense_vector_size` | `integer` | ✓ |  |
| `parser_config` | `object` | ✓ |  |
| `doc_count` | `integer` | ✓ |  |
| `chunk_count` | `integer` | ✓ |  |
| `token_count` | `integer` | ✓ |  |
| `status` | `string` | ✓ |  |
| `created_at` | `number` | ✓ |  |
| `updated_at` | `number` | ✓ |  |

**`422`** — Ошибка валидации

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `get_knowledge_base_v1_admin_kb__kb_id__get`_

---

### `GET /v1/admin/kb/{kb_id}/tasks`
**List Etl Tasks**

Список ETL-задач базы знаний.

#### Параметры

| Имя | Расположение | Тип | Обязательное | Описание |
|-----|--------------|-----|--------------|----------|
| `kb_id` | path | `string` | ✓ |  |
| `status` | query | `any` |  |  |

#### Ответы

**`200`** — Успешный ответ

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `tasks` | `array[TaskResponse]` | ✓ |  |
| `total` | `integer` | ✓ |  |

**`422`** — Ошибка валидации

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `list_etl_tasks_v1_admin_kb__kb_id__tasks_get`_

---

### `POST /v1/admin/kb/{kb_id}/tasks`
**Create Etl Task**

Создать ETL-задачу для базы знаний.

#### Параметры

| Имя | Расположение | Тип | Обязательное | Описание |
|-----|--------------|-----|--------------|----------|
| `kb_id` | path | `string` | ✓ |  |

#### Тело запроса

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `source_type` | `string` | ✓ | Тип источника: confluence, jira, gitlab, file |
| `source_id` | `string` | ✓ | Идентификатор источника (ID страницы, ключ задачи и т.п.) |

#### Ответы

**`201`** — Успешный ответ

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `id` | `string` | ✓ |  |
| `kb_id` | `string` | ✓ |  |
| `source_type` | `string` | ✓ |  |
| `source_id` | `string` | ✓ |  |
| `status` | `string` | ✓ |  |
| `progress` | `number` | ✓ |  |
| `error_message` | `string` | ✓ |  |
| `created_at` | `number` | ✓ |  |
| `updated_at` | `number` | ✓ |  |

**`422`** — Ошибка валидации

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `create_etl_task_v1_admin_kb__kb_id__tasks_post`_

---

### `GET /v1/admin/kb/{kb_id}/tasks/{task_id}`
**Get Etl Task**

Получить ETL-задачу по ID.

#### Параметры

| Имя | Расположение | Тип | Обязательное | Описание |
|-----|--------------|-----|--------------|----------|
| `kb_id` | path | `string` | ✓ |  |
| `task_id` | path | `string` | ✓ |  |

#### Ответы

**`200`** — Успешный ответ

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `id` | `string` | ✓ |  |
| `kb_id` | `string` | ✓ |  |
| `source_type` | `string` | ✓ |  |
| `source_id` | `string` | ✓ |  |
| `status` | `string` | ✓ |  |
| `progress` | `number` | ✓ |  |
| `error_message` | `string` | ✓ |  |
| `created_at` | `number` | ✓ |  |
| `updated_at` | `number` | ✓ |  |

**`422`** — Ошибка валидации

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `get_etl_task_v1_admin_kb__kb_id__tasks__task_id__get`_

---

## Auth
### `POST /v1/auth/login`
**Auth Login**

Аутентифицировать пользователя и вернуть пару токенов (access + refresh).

#### Тело запроса

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `username` | `string` | ✓ |  |
| `password` | `string` | ✓ |  |
| `expires_in_hours` | `any` |  |  |

#### Ответы

**`200`** — Успешный ответ

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `access_token` | `string` | ✓ |  |
| `refresh_token` | `any` |  |  |
| `token_type` | `string` |  |  |
| `expires_in` | `integer` | ✓ |  |
| `user_id` | `string` | ✓ |  |
| `username` | `string` | ✓ |  |
| `roles` | `array[string]` | ✓ |  |
| `groups` | `array[string]` | ✓ |  |

**`422`** — Ошибка валидации

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `auth_login_v1_auth_login_post`_

---

### `POST /v1/auth/logout`
**Auth Logout**

Выход из системы: отозвать refresh-токены и, опционально, добавить текущий access-токен в чёрный список.

#### Тело запроса

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `refresh_token` | `any` |  |  |
| `all_sessions` | `boolean` |  |  |

#### Ответы

**`200`** — Успешный ответ

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `status` | `string` | ✓ |  |
| `message` | `string` | ✓ |  |

**`422`** — Ошибка валидации

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `auth_logout_v1_auth_logout_post`_

---

### `GET /v1/auth/me`
**Auth Me**

Вернуть контекст текущего аутентифицированного пользователя.

#### Ответы

**`200`** — Успешный ответ

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `user_id` | `string` | ✓ |  |
| `username` | `string` | ✓ |  |
| `roles` | `array[string]` | ✓ |  |
| `groups` | `array[string]` | ✓ |  |
| `access_level` | `string` | ✓ |  |
| `is_admin` | `boolean` | ✓ |  |
| `is_authenticated` | `boolean` | ✓ |  |

_operationId: `auth_me_v1_auth_me_get`_

---

### `POST /v1/auth/refresh`
**Auth Refresh**

Обменять refresh-токен (или валидный access-токен) на новую пару токенов.

#### Тело запроса

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `token` | `string` | ✓ |  |

#### Ответы

**`200`** — Успешный ответ

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `access_token` | `string` | ✓ |  |
| `refresh_token` | `any` |  |  |
| `token_type` | `string` |  |  |
| `expires_in` | `integer` | ✓ |  |

**`422`** — Ошибка валидации

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `auth_refresh_v1_auth_refresh_post`_

---

### `POST /v1/auth/register`
**Auth Register**

Зарегистрировать новую учётную запись пользователя.

#### Тело запроса

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `username` | `string` | ✓ |  |
| `password` | `string` | ✓ |  |
| `email` | `any` |  |  |

#### Ответы

**`201`** — Успешный ответ

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `user_id` | `string` | ✓ |  |
| `username` | `string` | ✓ |  |
| `created_at` | `string` | ✓ |  |

**`422`** — Ошибка валидации

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `auth_register_v1_auth_register_post`_

---

## Chat
### `POST /v1/chat/completions`
**Chat Completions**

Основной эндпоинт чата (совместим с OpenAI).

#### Тело запроса

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `model` | `string` | ✓ |  |
| `messages` | `array[ChatMessage]` | ✓ |  |
| `temperature` | `any` |  |  |
| `top_p` | `any` |  |  |
| `max_tokens` | `any` |  |  |
| `stream` | `any` |  |  |
| `rag_version` | `any` |  |  |
| `rag_force_refresh` | `any` |  |  |
| `rag_skip_generation` | `any` |  |  |
| `rag_return_chunks` | `any` |  |  |
| `rag_top_k` | `any` |  |  |

#### Ответы

**`200`** — Успешный ответ

**`422`** — Ошибка валидации

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `chat_completions_v1_chat_completions_post`_

---

## Feedback
### `POST /v1/feedback`
**Submit Feedback**

Отправить обратную связь по ответу RAG.

#### Тело запроса

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `feedback_id` | `string` | ✓ | rag_feedback_id из ответа |
| `rating` | `string` | ✓ |  |
| `correction` | `any` |  | Исправленный текст ответа |
| `comment` | `any` |  | Комментарий эксперта |
| `question` | `any` |  | Исходный вопрос пользователя |
| `answer` | `any` |  | Ответ системы, который был оценён |
| `contexts` | `any` |  | Полученные при поиске чанки контекста |

#### Ответы

**`200`** — Успешный ответ

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `status` | `string` | ✓ |  |
| `message` | `string` | ✓ |  |

**`422`** — Ошибка валидации

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `submit_feedback_v1_feedback_post`_

---

## Files
### `GET /v1/files`
**List Files**

Список загруженных файлов.

#### Параметры

| Имя | Расположение | Тип | Обязательное | Описание |
|-----|--------------|-----|--------------|----------|
| `prefix` | query | `string` |  |  |

#### Ответы

**`200`** — Успешный ответ

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `files` | `array[FileMetadata]` | ✓ |  |
| `total` | `integer` | ✓ |  |

**`422`** — Ошибка валидации

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `list_files_v1_files_get`_

---

### `POST /v1/files`
**Upload File**

Загрузить файл в хранилище MinIO.

#### Тело запроса

#### Ответы

**`200`** — Успешный ответ

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `id` | `string` | ✓ | Уникальный идентификатор файла (object key) |
| `filename` | `string` | ✓ | Исходное имя файла |
| `size` | `integer` | ✓ | Размер файла в байтах |
| `content_type` | `string` | ✓ | MIME-тип |
| `bucket` | `string` | ✓ | Имя бакета MinIO |
| `uploaded_at` | `string` | ✓ | Метка времени загрузки (ISO 8601) |

**`422`** — Ошибка валидации

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `upload_file_v1_files_post`_

---

### `DELETE /v1/files/{file_id}`
**Delete File**

Удалить файл из хранилища.

#### Параметры

| Имя | Расположение | Тип | Обязательное | Описание |
|-----|--------------|-----|--------------|----------|
| `file_id` | path | `string` | ✓ |  |

#### Ответы

**`200`** — Успешный ответ

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `status` | `string` | ✓ |  |
| `message` | `string` | ✓ |  |
| `id` | `string` | ✓ |  |

**`422`** — Ошибка валидации

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `delete_file_v1_files__file_id__delete`_

---

### `GET /v1/files/{file_id}`
**Get File Metadata**

Получить метаданные конкретного файла.

#### Параметры

| Имя | Расположение | Тип | Обязательное | Описание |
|-----|--------------|-----|--------------|----------|
| `file_id` | path | `string` | ✓ |  |

#### Ответы

**`200`** — Успешный ответ

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `id` | `string` | ✓ | Идентификатор файла (object key) |
| `size` | `integer` | ✓ | Размер файла в байтах |
| `last_modified` | `string` | ✓ | Метка времени последнего изменения |
| `content_type` | `string` | ✓ | MIME-тип |
| `metadata` | `object` |  | Пользовательские метаданные |

**`422`** — Ошибка валидации

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `get_file_metadata_v1_files__file_id__get`_

---

### `GET /v1/files/{file_id}/download`
**Download File**

Скачать файл из хранилища.

#### Параметры

| Имя | Расположение | Тип | Обязательное | Описание |
|-----|--------------|-----|--------------|----------|
| `file_id` | path | `string` | ✓ |  |

#### Ответы

**`200`** — Успешный ответ

**`422`** — Ошибка валидации

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `download_file_v1_files__file_id__download_get`_

---

### `GET /v1/files/{file_id}/presigned`
**Get Presigned Url**

Сгенерировать presigned-URL для скачивания файла.

#### Параметры

| Имя | Расположение | Тип | Обязательное | Описание |
|-----|--------------|-----|--------------|----------|
| `file_id` | path | `string` | ✓ |  |
| `expiration` | query | `integer` |  |  |

#### Ответы

**`200`** — Успешный ответ

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `url` | `string` | ✓ |  |
| `expires_in` | `integer` | ✓ |  |

**`422`** — Ошибка валидации

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `get_presigned_url_v1_files__file_id__presigned_get`_

---

## Health
### `GET /v1/health`
**Health**

Проверить состояние прокси и его зависимостей.

#### Ответы

**`200`** — Успешный ответ

_operationId: `health_v1_health_get`_

---

### `GET /v1/health/live`
**Health Live**

Проверка живости (liveness probe) — возвращает 200, если процесс работает.

#### Ответы

**`200`** — Успешный ответ

_operationId: `health_live_v1_health_live_get`_

---

### `GET /v1/health/ready`
**Health Ready**

Проверка готовности (readiness probe) — проверяет доступность Qdrant и LLM.

#### Ответы

**`200`** — Успешный ответ

_operationId: `health_ready_v1_health_ready_get`_

---

### `GET /v1/health/tls`
**Health Tls**

Проверка TLS — верифицирует конфигурацию TLS и статус сертификата.

#### Ответы

**`200`** — Успешный ответ

_operationId: `health_tls_v1_health_tls_get`_

---

## Metrics
### `GET /metrics`
**Metrics**

Предоставляет метрики Prometheus в текстовом формате OpenMetrics.

#### Ответы

**`200`** — Успешный ответ

_operationId: `metrics_metrics_get`_

---

## Tools
### `GET /v1/tools`
**List Tools**

Список доступных инструментов с опциональными фильтрами. RBAC: видимость фильтруется по роли пользователя.

#### Параметры

| Имя | Расположение | Тип | Обязательное | Описание |
|-----|--------------|-----|--------------|----------|
| `category` | query | `any` |  |  |
| `tag` | query | `any` |  |  |
| `provider` | query | `any` |  |  |

#### Ответы

**`200`** — Успешный ответ

_Свойства не определены._

**`422`** — Ошибка валидации

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `list_tools_v1_tools_get`_

---

### `GET /v1/tools/{name}`
**Get Tool**

Получить детали одного инструмента по имени. Никогда не раскрывает код обработчика.

#### Параметры

| Имя | Расположение | Тип | Обязательное | Описание |
|-----|--------------|-----|--------------|----------|
| `name` | path | `string` | ✓ |  |

#### Ответы

**`200`** — Успешный ответ

_Свойства не определены._

**`422`** — Ошибка валидации

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `get_tool_v1_tools__name__get`_

---

## Untagged
### `GET /v1/models`
**List Models**

Вернуть список доступных моделей.

#### Ответы

**`200`** — Успешный ответ

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `object` | `string` |  |  |
| `data` | `array[ModelInfo]` | ✓ |  |

_operationId: `list_models_v1_models_get`_

---

## Widget
### `GET /v1/widget`
**Serve Widget**

Отдать HTML-страницу встраиваемого чат-виджета RAG.

#### Ответы

**`200`** — Успешный ответ

_operationId: `serve_widget_v1_widget_get`_

---

### `GET /v1/widget.js`
**Serve Widget Js**

Отдать автономный JavaScript чат-виджета RAG.

#### Ответы

**`200`** — Успешный ответ

_operationId: `serve_widget_js_v1_widget_js_get`_

---

## Schemas

### `Body_upload_file_v1_files_post`
| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `file` | `string` | ✓ |  |

### `CanarySplitRequest`
| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `model_name` | `string` | ✓ |  |
| `traffic_split` | `number` | ✓ | Доля трафика, направляемая на canary (0.0-1.0) |

### `CanarySplitResponse`
| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `model_name` | `string` | ✓ |  |
| `traffic_split` | `number` | ✓ |  |
| `status` | `string` | ✓ |  |

### `ChatCompletionRequest`
OpenAI-совместимый запрос chat completion с расширениями RAG.

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `model` | `string` | ✓ |  |
| `messages` | `array[ChatMessage]` | ✓ |  |
| `temperature` | `any` |  |  |
| `top_p` | `any` |  |  |
| `max_tokens` | `any` |  |  |
| `stream` | `any` |  |  |
| `rag_version` | `any` |  |  |
| `rag_force_refresh` | `any` |  |  |
| `rag_skip_generation` | `any` |  |  |
| `rag_return_chunks` | `any` |  |  |
| `rag_top_k` | `any` |  |  |

### `ChatMessage`
Одно сообщение в чат-диалоге.

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `role` | `string` | ✓ |  |
| `content` | `string` | ✓ |  |

### `EvaluateRequest`
| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `model_name` | `string` | ✓ |  |
| `version` | `string` |  |  |
| `metrics` | `object` | ✓ |  |

### `EvaluateResponse`
| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `model_name` | `string` | ✓ |  |
| `version` | `string` | ✓ |  |
| `status` | `string` | ✓ |  |
| `failures` | `array[string]` | ✓ |  |
| `warnings` | `array[string]` | ✓ |  |
| `metrics` | `object` | ✓ |  |

### `FeedbackRequest`
| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `feedback_id` | `string` | ✓ | rag_feedback_id из ответа |
| `rating` | `string` | ✓ |  |
| `correction` | `any` |  | Исправленный текст ответа |
| `comment` | `any` |  | Комментарий эксперта |
| `question` | `any` |  | Исходный вопрос пользователя |
| `answer` | `any` |  | Ответ системы, который был оценён |
| `contexts` | `any` |  | Полученные при поиске чанки контекста |

### `FeedbackResponse`
| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `status` | `string` | ✓ |  |
| `message` | `string` | ✓ |  |

### `FileDeleteResponse`
| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `status` | `string` | ✓ |  |
| `message` | `string` | ✓ |  |
| `id` | `string` | ✓ |  |

### `FileListResponse`
| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `files` | `array[FileMetadata]` | ✓ |  |
| `total` | `integer` | ✓ |  |

### `FileMetadata`
| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `id` | `string` | ✓ | Идентификатор файла (object key) |
| `size` | `integer` | ✓ | Размер файла в байтах |
| `last_modified` | `string` | ✓ | Метка времени последнего изменения |
| `content_type` | `string` | ✓ | MIME-тип |
| `metadata` | `object` |  | Пользовательские метаданные |

### `FileUploadResponse`
| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `id` | `string` | ✓ | Уникальный идентификатор файла (object key) |
| `filename` | `string` | ✓ | Исходное имя файла |
| `size` | `integer` | ✓ | Размер файла в байтах |
| `content_type` | `string` | ✓ | MIME-тип |
| `bucket` | `string` | ✓ | Имя бакета MinIO |
| `uploaded_at` | `string` | ✓ | Метка времени загрузки (ISO 8601) |

### `HTTPValidationError`
| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `detail` | `array[ValidationError]` |  |  |

### `KBCreateRequest`
Запрос на создание базы знаний.

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `name` | `string` | ✓ | Название базы знаний |
| `description` | `string` |  | Описание базы знаний |
| `embedding_model` | `string` |  | Название модели эмбеддингов |
| `dense_vector_size` | `integer` |  | Размерность плотного вектора |
| `parser_config` | `any` |  | Конфигурация парсера |

### `KBListResponse`
Список баз знаний.

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `knowledge_bases` | `array[KBResponse]` | ✓ |  |
| `total` | `integer` | ✓ |  |

### `KBResponse`
Ответ с данными базы знаний.

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `id` | `string` | ✓ |  |
| `name` | `string` | ✓ |  |
| `description` | `string` | ✓ |  |
| `collection_name` | `string` | ✓ |  |
| `embedding_model` | `string` | ✓ |  |
| `dense_vector_size` | `integer` | ✓ |  |
| `parser_config` | `object` | ✓ |  |
| `doc_count` | `integer` | ✓ |  |
| `chunk_count` | `integer` | ✓ |  |
| `token_count` | `integer` | ✓ |  |
| `status` | `string` | ✓ |  |
| `created_at` | `number` | ✓ |  |
| `updated_at` | `number` | ✓ |  |

### `KBUpdateRequest`
Запрос на обновление базы знаний.

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `name` | `any` |  |  |
| `description` | `any` |  |  |
| `embedding_model` | `any` |  |  |
| `parser_config` | `any` |  |  |

### `LoginRequest`
| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `username` | `string` | ✓ |  |
| `password` | `string` | ✓ |  |
| `expires_in_hours` | `any` |  |  |

### `LoginResponse`
| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `access_token` | `string` | ✓ |  |
| `refresh_token` | `any` |  |  |
| `token_type` | `string` |  |  |
| `expires_in` | `integer` | ✓ |  |
| `user_id` | `string` | ✓ |  |
| `username` | `string` | ✓ |  |
| `roles` | `array[string]` | ✓ |  |
| `groups` | `array[string]` | ✓ |  |

### `LogoutRequest`
| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `refresh_token` | `any` |  |  |
| `all_sessions` | `boolean` |  |  |

### `LogoutResponse`
| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `status` | `string` | ✓ |  |
| `message` | `string` | ✓ |  |

### `ModelInfo`
Метаданные модели, возвращаемые эндпоинтом /v1/models.

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `id` | `string` | ✓ |  |
| `object` | `string` |  |  |
| `created` | `integer` | ✓ |  |
| `owned_by` | `string` |  |  |

### `ModelsResponse`
Обёртка ответа эндпоинта /v1/models.

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `object` | `string` |  |  |
| `data` | `array[ModelInfo]` | ✓ |  |

### `PresignedUrlResponse`
| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `url` | `string` | ✓ |  |
| `expires_in` | `integer` | ✓ |  |

### `PromoteRequest`
| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `model_name` | `string` | ✓ |  |
| `version` | `string` | ✓ |  |

### `PromoteResponse`
| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `model_name` | `string` | ✓ |  |
| `version` | `string` | ✓ |  |
| `previous_status` | `string` | ✓ |  |
| `new_status` | `string` | ✓ |  |

### `RefreshRequest`
| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `token` | `string` | ✓ |  |

### `RefreshResponse`
| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `access_token` | `string` | ✓ |  |
| `refresh_token` | `any` |  |  |
| `token_type` | `string` |  |  |
| `expires_in` | `integer` | ✓ |  |

### `RegisterRequest`
| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `username` | `string` | ✓ |  |
| `password` | `string` | ✓ |  |
| `email` | `any` |  |  |

### `RegisterResponse`
| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `user_id` | `string` | ✓ |  |
| `username` | `string` | ✓ |  |
| `created_at` | `string` | ✓ |  |

### `RollbackRequest`
| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `model_name` | `string` | ✓ |  |

### `RollbackResponse`
| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `model_name` | `string` | ✓ |  |
| `version` | `string` | ✓ |  |
| `previous_version` | `string` | ✓ |  |
| `status` | `string` | ✓ |  |

### `TaskCreateRequest`
Запрос на создание ETL-задачи.

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `source_type` | `string` | ✓ | Тип источника: confluence, jira, gitlab, file |
| `source_id` | `string` | ✓ | Идентификатор источника (ID страницы, ключ задачи и т.п.) |

### `TaskListResponse`
Список ETL-задач.

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `tasks` | `array[TaskResponse]` | ✓ |  |
| `total` | `integer` | ✓ |  |

### `TaskResponse`
Ответ с данными ETL-задачи.

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `id` | `string` | ✓ |  |
| `kb_id` | `string` | ✓ |  |
| `source_type` | `string` | ✓ |  |
| `source_id` | `string` | ✓ |  |
| `status` | `string` | ✓ |  |
| `progress` | `number` | ✓ |  |
| `error_message` | `string` | ✓ |  |
| `created_at` | `number` | ✓ |  |
| `updated_at` | `number` | ✓ |  |

### `TrainRequest`
| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `trainer_type` | `string` | ✓ |  |
| `base_model` | `string` |  |  |
| `profile` | `string` |  |  |
| `data_dir` | `string` |  |  |
| `epochs` | `integer` |  |  |
| `batch_size` | `integer` |  |  |
| `learning_rate` | `number` |  |  |
| `use_lora` | `boolean` |  |  |

### `TrainResponse`
| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `job_id` | `string` | ✓ |  |
| `trainer_type` | `string` | ✓ |  |
| `status` | `string` | ✓ |  |
| `message` | `string` | ✓ |  |

### `TrainerType`
Enum: `slm`, `llm`, `reranker`

### `UserInfoResponse`
| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `user_id` | `string` | ✓ |  |
| `username` | `string` | ✓ |  |
| `roles` | `array[string]` | ✓ |  |
| `groups` | `array[string]` | ✓ |  |
| `access_level` | `string` | ✓ |  |
| `is_admin` | `boolean` | ✓ |  |
| `is_authenticated` | `boolean` | ✓ |  |

### `ValidationError`
| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `loc` | `array[any]` | ✓ |  |
| `msg` | `string` | ✓ |  |
| `type` | `string` | ✓ |  |
| `input` | `any` |  |  |
| `ctx` | `object` |  |  |
