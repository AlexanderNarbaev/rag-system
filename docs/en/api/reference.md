# RAG Proxy for Gemma

**Version:** 2.0.0  
**Generated:** 2026-07-16 05:08 UTC  
**OpenAPI:** 3.1.0  

OpenAI-compatible proxy with hybrid search, reranking, and Gemma LLM.

---

## Table of Contents

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

List all registered models with versions and stages (admin only).

#### Responses

**`200`** — Successful Response

_operationId: `admin_models_list_v1_admin_models_get`_

---

### `POST /v1/admin/models/canary/split`
**Admin Models Canary Split**

Set canary traffic split for a model (admin only).

#### Request Body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `model_name` | `string` | ✓ |  |
| `traffic_split` | `number` | ✓ | Fraction of traffic to canary (0.0-1.0) |

#### Responses

**`200`** — Successful Response

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `model_name` | `string` | ✓ |  |
| `traffic_split` | `number` | ✓ |  |
| `status` | `string` | ✓ |  |

**`422`** — Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `admin_models_canary_split_v1_admin_models_canary_split_post`_

---

### `GET /v1/admin/models/canary/status`
**Admin Models Canary Status**

Get current canary deployment status and metrics (admin only).

#### Responses

**`200`** — Successful Response

_operationId: `admin_models_canary_status_v1_admin_models_canary_status_get`_

---

### `POST /v1/admin/models/evaluate`
**Admin Models Evaluate**

Run eval gate on model metrics (admin only).

#### Request Body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `model_name` | `string` | ✓ |  |
| `version` | `string` |  |  |
| `metrics` | `object` | ✓ |  |

#### Responses

**`200`** — Successful Response

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `model_name` | `string` | ✓ |  |
| `version` | `string` | ✓ |  |
| `status` | `string` | ✓ |  |
| `failures` | `array[string]` | ✓ |  |
| `warnings` | `array[string]` | ✓ |  |
| `metrics` | `object` | ✓ |  |

**`422`** — Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `admin_models_evaluate_v1_admin_models_evaluate_post`_

---

### `POST /v1/admin/models/promote`
**Admin Models Promote**

Promote a model version through staging -> canary -> production (admin only).

#### Request Body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `model_name` | `string` | ✓ |  |
| `version` | `string` | ✓ |  |

#### Responses

**`200`** — Successful Response

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `model_name` | `string` | ✓ |  |
| `version` | `string` | ✓ |  |
| `previous_status` | `string` | ✓ |  |
| `new_status` | `string` | ✓ |  |

**`422`** — Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `admin_models_promote_v1_admin_models_promote_post`_

---

### `POST /v1/admin/models/rollback`
**Admin Models Rollback**

Rollback to previous production version (admin only).

#### Request Body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `model_name` | `string` | ✓ |  |

#### Responses

**`200`** — Successful Response

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `model_name` | `string` | ✓ |  |
| `version` | `string` | ✓ |  |
| `previous_version` | `string` | ✓ |  |
| `status` | `string` | ✓ |  |

**`422`** — Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `admin_models_rollback_v1_admin_models_rollback_post`_

---

### `GET /v1/admin/models/status/{job_id}`
**Admin Models Status**

Check training job status (admin only).

#### Parameters

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| `job_id` | path | `string` | ✓ |  |

#### Responses

**`200`** — Successful Response

**`422`** — Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `admin_models_status_v1_admin_models_status__job_id__get`_

---

### `POST /v1/admin/models/train`
**Admin Models Train**

Trigger a model training job (admin only).

#### Request Body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `trainer_type` | `string` | ✓ |  |
| `base_model` | `string` |  |  |
| `profile` | `string` |  |  |
| `data_dir` | `string` |  |  |
| `epochs` | `integer` |  |  |
| `batch_size` | `integer` |  |  |
| `learning_rate` | `number` |  |  |
| `use_lora` | `boolean` |  |  |

#### Responses

**`200`** — Successful Response

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `job_id` | `string` | ✓ |  |
| `trainer_type` | `string` | ✓ |  |
| `status` | `string` | ✓ |  |
| `message` | `string` | ✓ |  |

**`422`** — Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `admin_models_train_v1_admin_models_train_post`_

---

### `POST /v1/admin/warmup`
**Admin Warmup**

Trigger model warm-up (admin only).

#### Responses

**`200`** — Successful Response

_operationId: `admin_warmup_v1_admin_warmup_post`_

---

## Admin-Kb
### `GET /v1/admin/kb/`
**List Knowledge Bases**

List all knowledge bases.

#### Parameters

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| `include_deleted` | query | `boolean` |  |  |

#### Responses

**`200`** — Successful Response

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `knowledge_bases` | `array[KBResponse]` | ✓ |  |
| `total` | `integer` | ✓ |  |

**`422`** — Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `list_knowledge_bases_v1_admin_kb__get`_

---

### `POST /v1/admin/kb/`
**Create Knowledge Base**

Create a new knowledge base with its own Qdrant collection.

#### Request Body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | `string` | ✓ | Knowledge base name |
| `description` | `string` |  | KB description |
| `embedding_model` | `string` |  | Embedding model name |
| `dense_vector_size` | `integer` |  | Dense vector dimension |
| `parser_config` | `any` |  | Parser configuration |

#### Responses

**`201`** — Successful Response

| Field | Type | Required | Description |
|-------|------|----------|-------------|
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

**`422`** — Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `create_knowledge_base_v1_admin_kb__post`_

---

### `PUT /v1/admin/kb/{kb_id}`
**Update Knowledge Base**

Update a knowledge base.

#### Parameters

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| `kb_id` | path | `string` | ✓ |  |

#### Request Body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | `any` |  |  |
| `description` | `any` |  |  |
| `embedding_model` | `any` |  |  |
| `parser_config` | `any` |  |  |

#### Responses

**`200`** — Successful Response

| Field | Type | Required | Description |
|-------|------|----------|-------------|
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

**`422`** — Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `update_knowledge_base_v1_admin_kb__kb_id__put`_

---

### `DELETE /v1/admin/kb/{kb_id}`
**Delete Knowledge Base**

Delete a knowledge base (soft delete by default).

#### Parameters

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| `kb_id` | path | `string` | ✓ |  |
| `hard` | query | `boolean` |  |  |

#### Responses

**`200`** — Successful Response

_No properties defined._

**`422`** — Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `delete_knowledge_base_v1_admin_kb__kb_id__delete`_

---

### `GET /v1/admin/kb/{kb_id}`
**Get Knowledge Base**

Get a knowledge base by ID.

#### Parameters

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| `kb_id` | path | `string` | ✓ |  |

#### Responses

**`200`** — Successful Response

| Field | Type | Required | Description |
|-------|------|----------|-------------|
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

**`422`** — Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `get_knowledge_base_v1_admin_kb__kb_id__get`_

---

### `GET /v1/admin/kb/{kb_id}/tasks`
**List Etl Tasks**

List ETL tasks for a knowledge base.

#### Parameters

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| `kb_id` | path | `string` | ✓ |  |
| `status` | query | `any` |  |  |

#### Responses

**`200`** — Successful Response

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `tasks` | `array[TaskResponse]` | ✓ |  |
| `total` | `integer` | ✓ |  |

**`422`** — Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `list_etl_tasks_v1_admin_kb__kb_id__tasks_get`_

---

### `POST /v1/admin/kb/{kb_id}/tasks`
**Create Etl Task**

Create an ETL task for a knowledge base.

#### Parameters

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| `kb_id` | path | `string` | ✓ |  |

#### Request Body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `source_type` | `string` | ✓ | Source type: confluence, jira, gitlab, file |
| `source_id` | `string` | ✓ | Source identifier (page ID, issue key, etc.) |

#### Responses

**`201`** — Successful Response

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | `string` | ✓ |  |
| `kb_id` | `string` | ✓ |  |
| `source_type` | `string` | ✓ |  |
| `source_id` | `string` | ✓ |  |
| `status` | `string` | ✓ |  |
| `progress` | `number` | ✓ |  |
| `error_message` | `string` | ✓ |  |
| `created_at` | `number` | ✓ |  |
| `updated_at` | `number` | ✓ |  |

**`422`** — Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `create_etl_task_v1_admin_kb__kb_id__tasks_post`_

---

### `GET /v1/admin/kb/{kb_id}/tasks/{task_id}`
**Get Etl Task**

Get an ETL task by ID.

#### Parameters

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| `kb_id` | path | `string` | ✓ |  |
| `task_id` | path | `string` | ✓ |  |

#### Responses

**`200`** — Successful Response

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | `string` | ✓ |  |
| `kb_id` | `string` | ✓ |  |
| `source_type` | `string` | ✓ |  |
| `source_id` | `string` | ✓ |  |
| `status` | `string` | ✓ |  |
| `progress` | `number` | ✓ |  |
| `error_message` | `string` | ✓ |  |
| `created_at` | `number` | ✓ |  |
| `updated_at` | `number` | ✓ |  |

**`422`** — Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `get_etl_task_v1_admin_kb__kb_id__tasks__task_id__get`_

---

## Auth
### `POST /v1/auth/login`
**Auth Login**

Authenticate user and return a token pair (access + refresh).

#### Request Body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `username` | `string` | ✓ |  |
| `password` | `string` | ✓ |  |
| `expires_in_hours` | `any` |  |  |

#### Responses

**`200`** — Successful Response

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `access_token` | `string` | ✓ |  |
| `refresh_token` | `any` |  |  |
| `token_type` | `string` |  |  |
| `expires_in` | `integer` | ✓ |  |
| `user_id` | `string` | ✓ |  |
| `username` | `string` | ✓ |  |
| `roles` | `array[string]` | ✓ |  |
| `groups` | `array[string]` | ✓ |  |

**`422`** — Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `auth_login_v1_auth_login_post`_

---

### `POST /v1/auth/logout`
**Auth Logout**

Logout: revoke refresh tokens and optionally blacklist the current access token.

#### Request Body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `refresh_token` | `any` |  |  |
| `all_sessions` | `boolean` |  |  |

#### Responses

**`200`** — Successful Response

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `status` | `string` | ✓ |  |
| `message` | `string` | ✓ |  |

**`422`** — Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `auth_logout_v1_auth_logout_post`_

---

### `GET /v1/auth/me`
**Auth Me**

Return the current authenticated user's context.

#### Responses

**`200`** — Successful Response

| Field | Type | Required | Description |
|-------|------|----------|-------------|
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

Exchange a refresh token (or valid access token) for a new token pair.

#### Request Body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `token` | `string` | ✓ |  |

#### Responses

**`200`** — Successful Response

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `access_token` | `string` | ✓ |  |
| `refresh_token` | `any` |  |  |
| `token_type` | `string` |  |  |
| `expires_in` | `integer` | ✓ |  |

**`422`** — Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `auth_refresh_v1_auth_refresh_post`_

---

### `POST /v1/auth/register`
**Auth Register**

Register a new user account.

#### Request Body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `username` | `string` | ✓ |  |
| `password` | `string` | ✓ |  |
| `email` | `any` |  |  |

#### Responses

**`201`** — Successful Response

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `user_id` | `string` | ✓ |  |
| `username` | `string` | ✓ |  |
| `created_at` | `string` | ✓ |  |

**`422`** — Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `auth_register_v1_auth_register_post`_

---

## Chat
### `POST /v1/chat/completions`
**Chat Completions**

Main chat endpoint (OpenAI compatible).

#### Request Body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
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

#### Responses

**`200`** — Successful Response

**`422`** — Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `chat_completions_v1_chat_completions_post`_

---

## Feedback
### `POST /v1/feedback`
**Submit Feedback**

Submit feedback on a RAG response.

#### Request Body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `feedback_id` | `string` | ✓ | rag_feedback_id from the response |
| `rating` | `string` | ✓ |  |
| `correction` | `any` |  | Corrected answer text |
| `comment` | `any` |  | Expert comment |
| `question` | `any` |  | Original user question |
| `answer` | `any` |  | System answer that was rated |
| `contexts` | `any` |  | Retrieved context chunks |

#### Responses

**`200`** — Successful Response

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `status` | `string` | ✓ |  |
| `message` | `string` | ✓ |  |

**`422`** — Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `submit_feedback_v1_feedback_post`_

---

## Files
### `GET /v1/files`
**List Files**

List uploaded files.

#### Parameters

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| `prefix` | query | `string` |  |  |

#### Responses

**`200`** — Successful Response

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `files` | `array[FileMetadata]` | ✓ |  |
| `total` | `integer` | ✓ |  |

**`422`** — Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `list_files_v1_files_get`_

---

### `POST /v1/files`
**Upload File**

Upload a file to MinIO storage.

#### Request Body

#### Responses

**`200`** — Successful Response

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | `string` | ✓ | Unique file identifier (object key) |
| `filename` | `string` | ✓ | Original filename |
| `size` | `integer` | ✓ | File size in bytes |
| `content_type` | `string` | ✓ | MIME type |
| `bucket` | `string` | ✓ | MinIO bucket name |
| `uploaded_at` | `string` | ✓ | Upload timestamp (ISO 8601) |

**`422`** — Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `upload_file_v1_files_post`_

---

### `DELETE /v1/files/{file_id}`
**Delete File**

Delete a file from storage.

#### Parameters

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| `file_id` | path | `string` | ✓ |  |

#### Responses

**`200`** — Successful Response

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `status` | `string` | ✓ |  |
| `message` | `string` | ✓ |  |
| `id` | `string` | ✓ |  |

**`422`** — Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `delete_file_v1_files__file_id__delete`_

---

### `GET /v1/files/{file_id}`
**Get File Metadata**

Get metadata for a specific file.

#### Parameters

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| `file_id` | path | `string` | ✓ |  |

#### Responses

**`200`** — Successful Response

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | `string` | ✓ | File identifier (object key) |
| `size` | `integer` | ✓ | File size in bytes |
| `last_modified` | `string` | ✓ | Last modified timestamp |
| `content_type` | `string` | ✓ | MIME type |
| `metadata` | `object` |  | User metadata |

**`422`** — Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `get_file_metadata_v1_files__file_id__get`_

---

### `GET /v1/files/{file_id}/download`
**Download File**

Download a file from storage.

#### Parameters

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| `file_id` | path | `string` | ✓ |  |

#### Responses

**`200`** — Successful Response

**`422`** — Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `download_file_v1_files__file_id__download_get`_

---

### `GET /v1/files/{file_id}/presigned`
**Get Presigned Url**

Generate a presigned download URL for a file.

#### Parameters

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| `file_id` | path | `string` | ✓ |  |
| `expiration` | query | `integer` |  |  |

#### Responses

**`200`** — Successful Response

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `url` | `string` | ✓ |  |
| `expires_in` | `integer` | ✓ |  |

**`422`** — Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `get_presigned_url_v1_files__file_id__presigned_get`_

---

## Health
### `GET /v1/health`
**Health**

Check proxy and dependency health.

#### Responses

**`200`** — Successful Response

_operationId: `health_v1_health_get`_

---

### `GET /v1/health/live`
**Health Live**

Liveness probe — returns 200 if the process is alive.

#### Responses

**`200`** — Successful Response

_operationId: `health_live_v1_health_live_get`_

---

### `GET /v1/health/ready`
**Health Ready**

Readiness probe — checks Qdrant and LLM connectivity.

#### Responses

**`200`** — Successful Response

_operationId: `health_ready_v1_health_ready_get`_

---

### `GET /v1/health/tls`
**Health Tls**

TLS health check — verifies TLS configuration and certificate status.

#### Responses

**`200`** — Successful Response

_operationId: `health_tls_v1_health_tls_get`_

---

## Metrics
### `GET /metrics`
**Metrics**

Expose Prometheus metrics in OpenMetrics text format.

#### Responses

**`200`** — Successful Response

_operationId: `metrics_metrics_get`_

---

## Tools
### `GET /v1/tools`
**List Tools**

List available tools with optional filters. RBAC: visibility-filtered by user role.

#### Parameters

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| `category` | query | `any` |  |  |
| `tag` | query | `any` |  |  |
| `provider` | query | `any` |  |  |

#### Responses

**`200`** — Successful Response

_No properties defined._

**`422`** — Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `list_tools_v1_tools_get`_

---

### `GET /v1/tools/{name}`
**Get Tool**

Get a single tool's details by name. Never exposes handler code.

#### Parameters

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| `name` | path | `string` | ✓ |  |

#### Responses

**`200`** — Successful Response

_No properties defined._

**`422`** — Validation Error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` |  |  |

_operationId: `get_tool_v1_tools__name__get`_

---

## Untagged
### `GET /v1/models`
**List Models**

Return list of available models.

#### Responses

**`200`** — Successful Response

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `object` | `string` |  |  |
| `data` | `array[ModelInfo]` | ✓ |  |

_operationId: `list_models_v1_models_get`_

---

## Widget
### `GET /v1/widget`
**Serve Widget**

Serve the embeddable RAG chat widget HTML page.

#### Responses

**`200`** — Successful Response

_operationId: `serve_widget_v1_widget_get`_

---

### `GET /v1/widget.js`
**Serve Widget Js**

Serve the standalone RAG chat widget JavaScript.

#### Responses

**`200`** — Successful Response

_operationId: `serve_widget_js_v1_widget_js_get`_

---

## Schemas

### `Body_upload_file_v1_files_post`
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file` | `string` | ✓ |  |

### `CanarySplitRequest`
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `model_name` | `string` | ✓ |  |
| `traffic_split` | `number` | ✓ | Fraction of traffic to canary (0.0-1.0) |

### `CanarySplitResponse`
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `model_name` | `string` | ✓ |  |
| `traffic_split` | `number` | ✓ |  |
| `status` | `string` | ✓ |  |

### `ChatCompletionRequest`
OpenAI-compatible chat completion request with RAG extensions.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
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
Single message in a chat conversation.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `role` | `string` | ✓ |  |
| `content` | `string` | ✓ |  |

### `EvaluateRequest`
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `model_name` | `string` | ✓ |  |
| `version` | `string` |  |  |
| `metrics` | `object` | ✓ |  |

### `EvaluateResponse`
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `model_name` | `string` | ✓ |  |
| `version` | `string` | ✓ |  |
| `status` | `string` | ✓ |  |
| `failures` | `array[string]` | ✓ |  |
| `warnings` | `array[string]` | ✓ |  |
| `metrics` | `object` | ✓ |  |

### `FeedbackRequest`
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `feedback_id` | `string` | ✓ | rag_feedback_id from the response |
| `rating` | `string` | ✓ |  |
| `correction` | `any` |  | Corrected answer text |
| `comment` | `any` |  | Expert comment |
| `question` | `any` |  | Original user question |
| `answer` | `any` |  | System answer that was rated |
| `contexts` | `any` |  | Retrieved context chunks |

### `FeedbackResponse`
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `status` | `string` | ✓ |  |
| `message` | `string` | ✓ |  |

### `FileDeleteResponse`
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `status` | `string` | ✓ |  |
| `message` | `string` | ✓ |  |
| `id` | `string` | ✓ |  |

### `FileListResponse`
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `files` | `array[FileMetadata]` | ✓ |  |
| `total` | `integer` | ✓ |  |

### `FileMetadata`
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | `string` | ✓ | File identifier (object key) |
| `size` | `integer` | ✓ | File size in bytes |
| `last_modified` | `string` | ✓ | Last modified timestamp |
| `content_type` | `string` | ✓ | MIME type |
| `metadata` | `object` |  | User metadata |

### `FileUploadResponse`
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | `string` | ✓ | Unique file identifier (object key) |
| `filename` | `string` | ✓ | Original filename |
| `size` | `integer` | ✓ | File size in bytes |
| `content_type` | `string` | ✓ | MIME type |
| `bucket` | `string` | ✓ | MinIO bucket name |
| `uploaded_at` | `string` | ✓ | Upload timestamp (ISO 8601) |

### `HTTPValidationError`
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array[ValidationError]` |  |  |

### `KBCreateRequest`
Request to create a knowledge base.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | `string` | ✓ | Knowledge base name |
| `description` | `string` |  | KB description |
| `embedding_model` | `string` |  | Embedding model name |
| `dense_vector_size` | `integer` |  | Dense vector dimension |
| `parser_config` | `any` |  | Parser configuration |

### `KBListResponse`
List of knowledge bases.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `knowledge_bases` | `array[KBResponse]` | ✓ |  |
| `total` | `integer` | ✓ |  |

### `KBResponse`
Knowledge base response.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
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
Request to update a knowledge base.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | `any` |  |  |
| `description` | `any` |  |  |
| `embedding_model` | `any` |  |  |
| `parser_config` | `any` |  |  |

### `LoginRequest`
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `username` | `string` | ✓ |  |
| `password` | `string` | ✓ |  |
| `expires_in_hours` | `any` |  |  |

### `LoginResponse`
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `access_token` | `string` | ✓ |  |
| `refresh_token` | `any` |  |  |
| `token_type` | `string` |  |  |
| `expires_in` | `integer` | ✓ |  |
| `user_id` | `string` | ✓ |  |
| `username` | `string` | ✓ |  |
| `roles` | `array[string]` | ✓ |  |
| `groups` | `array[string]` | ✓ |  |

### `LogoutRequest`
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `refresh_token` | `any` |  |  |
| `all_sessions` | `boolean` |  |  |

### `LogoutResponse`
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `status` | `string` | ✓ |  |
| `message` | `string` | ✓ |  |

### `ModelInfo`
Model metadata returned by the /v1/models endpoint.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | `string` | ✓ |  |
| `object` | `string` |  |  |
| `created` | `integer` | ✓ |  |
| `owned_by` | `string` |  |  |

### `ModelsResponse`
Response wrapper for the /v1/models endpoint.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `object` | `string` |  |  |
| `data` | `array[ModelInfo]` | ✓ |  |

### `PresignedUrlResponse`
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `url` | `string` | ✓ |  |
| `expires_in` | `integer` | ✓ |  |

### `PromoteRequest`
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `model_name` | `string` | ✓ |  |
| `version` | `string` | ✓ |  |

### `PromoteResponse`
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `model_name` | `string` | ✓ |  |
| `version` | `string` | ✓ |  |
| `previous_status` | `string` | ✓ |  |
| `new_status` | `string` | ✓ |  |

### `RefreshRequest`
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `token` | `string` | ✓ |  |

### `RefreshResponse`
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `access_token` | `string` | ✓ |  |
| `refresh_token` | `any` |  |  |
| `token_type` | `string` |  |  |
| `expires_in` | `integer` | ✓ |  |

### `RegisterRequest`
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `username` | `string` | ✓ |  |
| `password` | `string` | ✓ |  |
| `email` | `any` |  |  |

### `RegisterResponse`
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `user_id` | `string` | ✓ |  |
| `username` | `string` | ✓ |  |
| `created_at` | `string` | ✓ |  |

### `RollbackRequest`
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `model_name` | `string` | ✓ |  |

### `RollbackResponse`
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `model_name` | `string` | ✓ |  |
| `version` | `string` | ✓ |  |
| `previous_version` | `string` | ✓ |  |
| `status` | `string` | ✓ |  |

### `TaskCreateRequest`
Request to create an ETL task.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `source_type` | `string` | ✓ | Source type: confluence, jira, gitlab, file |
| `source_id` | `string` | ✓ | Source identifier (page ID, issue key, etc.) |

### `TaskListResponse`
List of ETL tasks.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `tasks` | `array[TaskResponse]` | ✓ |  |
| `total` | `integer` | ✓ |  |

### `TaskResponse`
ETL task response.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
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
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `trainer_type` | `string` | ✓ |  |
| `base_model` | `string` |  |  |
| `profile` | `string` |  |  |
| `data_dir` | `string` |  |  |
| `epochs` | `integer` |  |  |
| `batch_size` | `integer` |  |  |
| `learning_rate` | `number` |  |  |
| `use_lora` | `boolean` |  |  |

### `TrainResponse`
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `job_id` | `string` | ✓ |  |
| `trainer_type` | `string` | ✓ |  |
| `status` | `string` | ✓ |  |
| `message` | `string` | ✓ |  |

### `TrainerType`
Enum: `slm`, `llm`, `reranker`

### `UserInfoResponse`
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `user_id` | `string` | ✓ |  |
| `username` | `string` | ✓ |  |
| `roles` | `array[string]` | ✓ |  |
| `groups` | `array[string]` | ✓ |  |
| `access_level` | `string` | ✓ |  |
| `is_admin` | `boolean` | ✓ |  |
| `is_authenticated` | `boolean` | ✓ |  |

### `ValidationError`
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `loc` | `array[any]` | ✓ |  |
| `msg` | `string` | ✓ |  |
| `type` | `string` | ✓ |  |
| `input` | `any` |  |  |
| `ctx` | `object` |  |  |
