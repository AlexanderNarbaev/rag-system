# Примеры API RAG-системы

Краткий справочник по наиболее распространённым вызовам API. Все примеры предполагают,
что прокси запущен по адресу `http://localhost:8080`. Полный справочник см. в
[`reference.md`](reference.md) и схеме OpenAPI в [`openapi.json`](openapi.json).

## Быстрый старт

### Проверка состояния

```bash
curl -X GET http://localhost:8080/v1/health/live
# {"status":"alive","timestamp":"..."}

curl -X GET http://localhost:8080/v1/health/ready
# {"status":"ready","components":{"qdrant":"ok","llm":"ok"}}
```

### Список моделей

```bash
curl -X GET http://localhost:8080/v1/models
# Returns list of models with +RAG suffix variants
```

### Чат с RAG (без стриминга)

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-635b+RAG",
    "messages": [{"role": "user", "content": "What is RAG?"}]
  }'
```

### Чат с RAG (стриминг)

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-635b+RAG",
    "stream": true,
    "messages": [{"role": "user", "content": "Explain RAG"}]
  }'
```

### Прямой вызов LLM (passthrough)

```bash
# Without +RAG suffix — direct LLM call, no retrieval
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-635b",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

## Примеры на Python

### Использование OpenAI SDK

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8080/v1",
    api_key="not-needed",
)

# RAG chat
response = client.chat.completions.create(
    model="qwen3-635b+RAG",
    messages=[{"role": "user", "content": "What is RAG?"}],
)
print(response.choices[0].message.content)

# Streaming
stream = client.chat.completions.create(
    model="qwen3-635b+RAG",
    messages=[{"role": "user", "content": "Explain"}],
    stream=True,
)
for chunk in stream:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")
```

## Параметры RAG

| Параметр | Тип | Описание |
|----------|-----|----------|
| rag_version | string | Запросить конкретную версию документа (например, "v1") |
| rag_force_refresh | bool | Обойти кэш ответов |
| rag_skip_generation | bool | Режим только поиска (вернуть чанки без вызова LLM) |
| rag_return_chunks | bool | Включить чанки в ответ |
| rag_top_k | int | Переопределить количество чанков после реранкинга |

## Поля ответа

| Поле | Тип | Описание |
|------|-----|----------|
| rag_feedback_id | string | ID для отправки экспертной обратной связи |
| rag_confidence | float (0-1) | Уверенность системы в ответе |
| rag_sources | array | Список использованных чанков-источников |
| rag_knowledge_status | string | "found", "absent", "partial" |
