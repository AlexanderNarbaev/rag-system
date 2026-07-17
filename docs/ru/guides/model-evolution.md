# Руководство по эволюции моделей

**Версия функции:** v2.0 (июнь 2026)
**Статус реализации:** Реализовано. Все 13 модулей находятся в `proxy/app/model_evolution/` с полными эндпоинтами admin
API и 358 юнит-тестами.

---

## 1. Концепция

Эволюция моделей — это полноценный пайплайн дообучения, который непрерывно улучшает модели RAG-системы с использованием
реальных данных обратной связи. Вместо статических моделей вы обучаете домен-специфичные адаптеры, которые становятся
лучше со временем по мере накопления экспертной обратной связи.

### 1.1 Зачем дообучать?

| Драйвер                                  | Проблема                                                                                                           | Решение через дообучение                                                                |
|------------------------------------------|--------------------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------|
| **Доменный дрейф**                       | Универсальные модели неправильно понимают корпоративный жаргон                                                     | Адаптация к словарю, аббревиатурам и терминологии вашей организации                     |
| **Неправильная классификация намерений** | SLM-маршрутизатор ошибочно направляет `"Как развернуть в staging?"` как фактологический вопрос вместо процедурного | Обучение классификатора намерений на реальном распределении запросов                    |
| **Поверхностные ответы**                 | LLM генерирует расплывчатые ответы на домен-специфичные вопросы                                                    | Инструкционная тонировка на экспертных исправлениях для точных, контекстуальных ответов |
| **Плохой реранкинг**                     | Универсальный cross-encoder ранжирует нерелевантные чанки выше                                                     | Дообучение на суждениях о релевантности из вашего корпуса документов                    |
| **Галлюцинации**                         | LLM выдумывает информацию, отсутствующую в извлечённом контексте                                                   | Заземление ответов с помощью исправленных HITL-примеров                                 |
| **Обратная связь**                       | Экспертные исправления логируются, но никогда не используются повторно                                             | Возврат исправлений в обучение, замыкание цикла улучшения                               |

### 1.2 Что можно дообучить?

| Модель       | Тип                     | Тренер            | Техника         | Размер адаптера                | Случай использования                                  |
|--------------|-------------------------|-------------------|-----------------|--------------------------------|-------------------------------------------------------|
| **SLM**      | Классификатор намерений | `SLMTrainer`      | LoRA (PEFT)     | ~5 МБ                          | Маршрутизация запросов для определения типа намерения |
| **LLM**      | Генератор               | `LLMTrainer`      | QLoRA 4-bit NF4 | ~20-50 МБ                      | Домен-специфичная генерация ответов                   |
| **Reranker** | Cross-Encoder           | `RerankerTrainer` | LoRA или полный | ~5 МБ (LoRA) / ~90 МБ (полный) | Оценка релевантности извлечённых чанков               |

### 1.3 Когда использовать каждый вариант

- **Дообучение SLM** — когда маршрутизатор намерений часто ошибается. Быстрое обучение (минуты на GPU), небольшой
  адаптер.
- **Дообучение LLM** — когда ответы нуждаются в домен-специфичной точности. Требует значительного объёма HITL-данных (
  рекомендуется 100+ исправленных примеров). GPU с 16+ ГБ VRAM для QLoRA.
- **Дообучение реранкера** — когда извлечённые документы релевантны, но ранжируются неправильно. Используйте режим LoRA
  для быстрой адаптации, полное дообучение для серьёзных доменных сдвигов.

---

## 2. Архитектура

### 2.1 Обзор системы

```
┌──────────────────────────────────────────────────────────────────────┐
│                         MODEL EVOLUTION SYSTEM                        │
│                                                                      │
│  ┌──────────┐   ┌──────────────┐   ┌──────────┐   ┌──────────────┐  │
│  │  HITL    │──▶│ DataProcessor│──▶│ Trainer  │──▶│  Artifact    │  │
│  │ Feedback │   │  (JSONL→DS)  │   │ (LoRA/   │   │  Store       │  │
│  │  Logs    │   │  split/fmt   │   │  QLoRA)  │   │ (MinIO/S3)   │  │
│  └──────────┘   └──────────────┘   └────┬─────┘   └──────┬───────┘  │
│                                         │                 │          │
│                                    ┌────▼─────┐    ┌──────▼───────┐  │
│                                    │ MLflow   │    │   Model      │  │
│                                    │ Tracker  │    │  Registry    │  │
│                                    └────┬─────┘    └──────┬───────┘  │
│                                         │                 │          │
│                                    ┌────▼─────┐    ┌──────▼───────┐  │
│                                    │ EvalGate │◀───│  Baseline    │  │
│                                    │ (CI/CD)  │    │  Metrics     │  │
│                                    └────┬─────┘    └──────────────┘  │
│                                         │                            │
│                    ┌────────────────────▼──────────────────────┐     │
│                    │           Canary Controller                │     │
│                    │  Traffic Splitting → Auto-Rollback         │     │
│                    └────────────────────┬──────────────────────┘     │
│                                         │                            │
│                    ┌────────────────────▼──────────────────────┐     │
│                    │           Adapter Manager                  │     │
│                    │  Hot-Reload → SIGHUP → Drain & Retire      │     │
│                    └────────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────────────────────┘
```

### 2.2 Поток пайплайна обучения

1. **Сбор данных** — экспертная обратная связь HITL накапливается в `logs/hitl.jsonl` (запросы, ответы, исправления,
   оценки релевантности, метки намерений).
2. **Обработка данных** — `DataProcessor` читает HITL-лог и создаёт три набора данных:
    - `slm_intent.jsonl` — пары `{query, intent_label}` для классификации намерений SLM
    - `llm_instruction.jsonl` — тройки `{instruction, input, output}` для инструкционной тонировки LLM
    - `reranker_pairs.jsonl` — тройки `{query, chunk, relevance}` для обучения реранкера
3. **Разделение train/val/test** — стратифицированное разделение 80%/10%/10% с настраиваемым зерном.
4. **Обучение** — настраиваемый профиль окружения (DEV/CI/PROD) управляет размером батча, эпохами, рангом LoRA,
   квантизацией.
5. **Оценка** — вычисляемые метрики: accuracy, weighted F1 (SLM); BLEU, ROUGE-L, частота галлюцинаций (LLM); MRR,
   nDCG@10, P@5 (Reranker).
6. **Хранение артефактов** — веса адаптера + конфиг сохраняются в MinIO/S3 или локальную файловую систему.
7. **Реестр моделей** — создаётся версия со статусом `staging`, прикрепляются метрики.
8. **EvalGate** — проверка порогов по настроенным критериям. PASS → допуск к канарейке; FAIL → блокировка.
9. **Канареечное развёртывание** — постепенное распределение трафика (5%→25%→50%→75%→100%) с автоматическим откатом при
   деградации метрик.
10. **Горячая перезагрузка** — новый адаптер загружается без перезапуска сервиса. SIGHUP запускает повторное
    сканирование.

### 2.3 Интеграция с MLflow + MinIO

| Компонент           | Переменная окружения     | По умолчанию            |
|---------------------|--------------------------|-------------------------|
| MLflow Tracking URI | `MLFLOW_TRACKING_URI`    | `http://localhost:5000` |
| MLflow Experiment   | `MLFLOW_EXPERIMENT_NAME` | `rag-system`            |
| Artifact Root       | `MLFLOW_ARTIFACT_ROOT`   | `s3://rag-artifacts`    |
| MinIO Endpoint      | `MINIO_ENDPOINT`         | `localhost:9000`        |
| MinIO Access Key    | `MINIO_ACCESS_KEY`       | `minioadmin`            |
| MinIO Secret Key    | `MINIO_SECRET_KEY`       | `minioadmin`            |
| MinIO Bucket        | `MINIO_BUCKET`           | `rag-artifacts`         |

Оба компонента MLflow и MinIO необязательны. При их недоступности (воздушный зазор или локальная разработка) система
использует запасные варианты:

- **Трекинг экспериментов** → локальные JSON-файлы в `data/experiments/<name>/<run_id>.json`
- **Хранение артефактов** → локальная директория `data/artifacts/<bucket>/`

---

## 3. Быстрый старт

### 3.1 Включение эволюции моделей

```bash
export MODEL_EVOLUTION_ENABLED=true
```

### 3.2 Запуск вспомогательных сервисов

**Вариант A: Docker Compose (рекомендуется для разработки)**

```bash
# MLflow tracking server
docker run -d -p 5000:5000 --name mlflow \
  ghcr.io/mlflow/mlflow:v2.15.0 \
  mlflow server --host 0.0.0.0 --port 5000 \
  --backend-store-uri sqlite:///mlflow.db \
  --default-artifact-root s3://rag-artifacts

# MinIO (S3-compatible artifact store)
docker run -d -p 9000:9000 -p 9001:9001 --name minio \
  -e MINIO_ROOT_USER=minioadmin \
  -e MINIO_ROOT_PASSWORD=minioadmin \
  minio/minio server /data --console-address ":9001"
```

**Вариант B: Воздушный зазор / только локально**

Внешние сервисы не требуются. Система автоматически использует локальные запасные варианты.

### 3.3 Первая тренировочная задача

```bash
# Trigger SLM intent classifier training in DEV profile
curl -X POST http://localhost:8080/v1/admin/models/train \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -d '{
    "trainer_type": "slm",
    "base_model": "bert-base-uncased",
    "profile": "dev",
    "epochs": 1,
    "batch_size": 2,
    "use_lora": true
  }'
```

Ответ:

```json
{
  "job_id": "abc12345-6789-4abc-def0-1234567890ab",
  "trainer_type": "slm",
  "status": "running",
  "message": "Training job abc12345-6789-4abc-def0-1234567890ab started"
}
```

### 3.4 Проверка статуса задачи

```bash
curl -X GET http://localhost:8080/v1/admin/models/status/abc12345-6789-4abc-def0-1234567890ab \
  -H "Authorization: Bearer $JWT_TOKEN"
```

Ответ:

```json
{
  "job_id": "abc12345-6789-4abc-def0-1234567890ab",
  "trainer_type": "slm",
  "status": "completed",
  "metrics": {
    "accuracy": 0.92,
    "weighted_f1": 0.89,
    "loss": 0.23
  },
  "artifact_uri": "./models/training/abc12345-6789-4abc-def0-1234567890ab/adapter",
  "completed_at": "2026-07-06T12:00:00.000000+00:00"
}
```

### 3.5 Продвижение и развёртывание

```bash
# Evaluate against baseline
curl -X POST http://localhost:8080/v1/admin/models/evaluate \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -d '{
    "model_name": "slm",
    "version": "1",
    "metrics": {"accuracy": 0.92, "weighted_f1": 0.89}
  }'
```

Если оценка пройдена, продвигайте через жизненный цикл:

```bash
# staging → canary
curl -X POST http://localhost:8080/v1/admin/models/promote \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -d '{"model_name": "slm", "version": "1"}'

# Start canary at 5% traffic
curl -X POST http://localhost:8080/v1/admin/models/canary/split \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -d '{"model_name": "slm", "traffic_split": 0.05}'

# canary → production (after monitoring confirms quality)
curl -X POST http://localhost:8080/v1/admin/models/promote \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -d '{"model_name": "slm", "version": "1"}'
```

---

## 4. Профили обучения

Поведением обучения управляет `EnvProfile`, выбираемый через параметр `profile` в запросе на обучение или
`TrainingConfig.from_profile()`.

### 4.1 Предустановки профилей

| Параметр                 | DEV       | CI        | PROD       |
|--------------------------|-----------|-----------|------------|
| `epochs`                 | 1         | 1         | 5          |
| `batch_size`             | 2         | 1         | 16         |
| `use_lora`               | true      | true      | true       |
| `lora_r`                 | 4         | 2         | 16         |
| `lora_alpha`             | 8         | 4         | 32         |
| `use_qlora`              | false     | false     | true       |
| `load_in_4bit`           | false     | false     | true       |
| `bnb_4bit_compute_dtype` | `float16` | `float16` | `bfloat16` |
| `max_seq_length`         | 256       | 128       | 2048       |
| `eval_split`             | 0.2       | 0.5       | 0.2        |
| `logging_steps`          | 5         | 1         | 10         |
| `eval_steps`             | 50        | 10        | 500        |
| `warmup_steps`           | —         | —         | 100        |
| `save_steps`             | —         | —         | 500        |
| `gpu_enabled`            | false     | false     | true       |

### 4.2 Выбор профиля

| Профиль  | Когда использовать                                         | Оборудование      | Время обучения (SLM) |
|----------|------------------------------------------------------------|-------------------|----------------------|
| **DEV**  | Локальная разработка, дымовые тесты, быстрые эксперименты  | CPU               | ~1 минута            |
| **CI**   | Автоматизированные CI-пайплайны, валидация PR              | CPU (раннер)      | ~30 секунд           |
| **PROD** | Реальные тренировочные запуски для продакшен-развёртывания | GPU (16+ ГБ VRAM) | ~5-15 минут          |

### 4.3 Переопределение настроек профиля

Все предустановки профиля могут быть переопределены в запросе на обучение:

```bash
curl -X POST http://localhost:8080/v1/admin/models/train \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -d '{
    "trainer_type": "slm",
    "profile": "dev",
    "epochs": 10,
    "batch_size": 4,
    "learning_rate": 1e-4
  }'
```

Переопределения на уровне API имеют приоритет над предустановками профиля. Метод `TrainingConfig.from_profile()`
объединяет предустановки профиля с явными kwargs — явные ключи всегда побеждают.

---

## 5. Типы обучения

### 5.1 Обучение SLM — классификация намерений

**Тренер:** `SLMTrainer` в `slm_trainer.py`
**Техника:** LoRA-дообучение `AutoModelForSequenceClassification`
**Набор данных:** пары `{query, intent_label}`
**Метки намерений:** `greeting`, `simple_fact`, `factual`, `procedural`, `comparison`, `summarize`, `complex`

#### Конфигурация

```python
from proxy.app.model_evolution.trainer import TrainingConfig, TrainerType
from proxy.app.model_evolution.env_profile import EnvProfile

config = TrainingConfig(
    trainer_type=TrainerType.SLM,
    base_model="bert-base-uncased",  # or any AutoModelForSequenceClassification model
    env_profile=EnvProfile.PROD,
    epochs=5,
    batch_size=16,
    learning_rate=2e-4,
    use_lora=True,
    lora_r=16,        # LoRA rank — higher = more capacity, more memory
    lora_alpha=32,     # LoRA scaling factor
    lora_dropout=0.05,
    max_seq_length=512,
)
```

#### Целевые модули

Целевые модули LoRA автоматически определяются из архитектуры базовой модели:

| Базовая модель               | Целевые модули                         |
|------------------------------|----------------------------------------|
| BERT / RoBERTa               | `query`, `value`                       |
| GPT / Llama / Mistral / Qwen | `q_proj`, `v_proj`, `k_proj`, `o_proj` |
| Неизвестная                  | `q_proj`, `v_proj`                     |

#### Метрики

| Метрика       | Описание                                   |
|---------------|--------------------------------------------|
| `accuracy`    | Общая точность классификации               |
| `weighted_f1` | F1-оценка, взвешенная по частоте классов   |
| `loss`        | Кросс-энтропийная оценочная функция потерь |

#### Пример формата данных

```jsonl
{"query": "How do I deploy to staging?", "intent": "procedural"}
{"query": "What is the SLA for incident response?", "intent": "factual"}
{"query": "Compare Kubernetes and Nomad", "intent": "comparison"}
```

### 5.2 Обучение LLM — домен-специфичная генерация

**Тренер:** `LLMTrainer` в `llm_trainer.py`
**Техника:** QLoRA (4-bit NF4 квантизация + PEFT LoRA) для экономии памяти
**Набор данных:** инструкционные пары в формате `messages` (роли system/user/assistant)

#### Конфигурация

```python
config = TrainingConfig(
    trainer_type=TrainerType.LLM,
    base_model="meta-llama/Llama-3-8B",  # or Mistral, Gemma, Qwen, etc.
    env_profile=EnvProfile.PROD,
    epochs=3,
    batch_size=4,
    learning_rate=2e-4,
    use_qlora=True,
    load_in_4bit=True,          # bitsandbytes 4-bit NF4 quantization
    bnb_4bit_compute_dtype="bfloat16",
    lora_r=16,
    lora_alpha=32,
    lora_dropout=0.05,
    max_seq_length=2048,
    gradient_accumulation_steps=4,  # effective batch = batch_size × this
)
```

#### Детали QLoRA

QLoRA позволяет дообучать большие модели (7B-70B параметров) на одном GPU благодаря:

1. **4-bit NormalFloat квантизация** — сжатие весов базовой модели до 4 бит
2. **Двойная квантизация** — квантизация констант квантизации (экономия ~0.5 ГБ)
3. **Страничные оптимизаторы** — выгрузка состояний оптимизатора в CPU при нехватке GPU-памяти
4. **LoRA-адаптеры** — обучение только ~1% параметров в виде малых матриц низкого ранга

С QLoRA модель 7B помещается в ~6 ГБ VRAM (против ~28 ГБ для полного дообучения).

#### Поведение GPU vs CPU

| Окружение                                    | Поведение                                                                            |
|----------------------------------------------|--------------------------------------------------------------------------------------|
| Профиль PROD + CUDA доступен                 | Полноценное GPU-обучение QLoRA с bitsandbytes                                        |
| Профиль DEV/CI или нет CUDA                  | **Mock-обучение** — создаёт заглушки метрик и конфигурацию адаптера для тестирования |
| Профиль GPU, но библиотеки QLoRA отсутствуют | Возвращается к mock с предупреждением                                                |

Mock-обучение — полностью валидный путь для разработки и CI. Оно генерирует реальные файлы адаптера и метрики, поэтому
весь пайплайн (реестр, EvalGate, канарейка) может быть протестирован без GPU.

#### Формат данных

```json
{
  "messages": [
    {"role": "user", "content": "How do I set up SSO for Jira?"},
    {"role": "assistant", "content": "Navigate to Administration → SSO 2.0. Select your IdP..."}
  ]
}
```

### 5.3 Обучение реранкера — оценка релевантности

**Тренер:** `RerankerTrainer` в `reranker_trainer.py`
**Техника:** LoRA (GPU) или полное дообучение через `CrossEncoder.fit()` (CPU)
**Набор данных:** тройки `(query, chunk_text, relevance_score)`

#### Конфигурация

```python
config = TrainingConfig(
    trainer_type=TrainerType.RERANKER,
    base_model="cross-encoder/ms-marco-MiniLM-L-6-v2",
    env_profile=EnvProfile.PROD,
    epochs=3,
    batch_size=16,
    learning_rate=2e-4,
    use_lora=True,          # True → PEFT LoRA (~5 MB adapter)
    lora_r=4,               # False → CrossEncoder.fit() (full model)
    lora_alpha=8,
    max_seq_length=512,
)
```

#### LoRA vs полное дообучение

| Режим      | Активация        | Техника                                           | Размер адаптера | Когда использовать                              |
|------------|------------------|---------------------------------------------------|-----------------|-------------------------------------------------|
| **LoRA**   | `use_lora=True`  | PEFT LoRA на `AutoModelForSequenceClassification` | ~5 МБ           | Быстрая адаптация, частые обновления            |
| **Полный** | `use_lora=False` | `CrossEncoder.fit()`                              | ~90 МБ          | Серьёзный доменный сдвиг, максимальное качество |

Тренер автоматически выбирает режим: если `use_lora=True` и PEFT + transformers установлены, используется LoRA; иначе
возвращается к полному дообучению через `sentence-transformers`.

#### Метрики

| Метрика          | Описание                                                       |
|------------------|----------------------------------------------------------------|
| `mrr`            | Средний взаимный ранг — позиция первого релевантного документа |
| `ndcg_at_10`     | Нормализованный дисконтированный кумулятивный выигрыш на 10    |
| `precision_at_5` | Точность топ-5 результатов                                     |

#### Формат данных

```jsonl
["How to configure SSO", "Navigate to Admin → Authentication → SSO...", 1.0]
["How to configure SSO", "Today's lunch menu: pizza", 0.0]
["What is the SLA", "Our SLA guarantees 99.9% uptime...", 0.85]
```

---

## 6. Пайплайн данных

### 6.1 HITL-обратная связь → тренировочный набор данных

`DataProcessor` читает логи HITL-обратной связи и создаёт тренировочные наборы данных для всех трёх типов моделей за
один проход.

```python
from proxy.app.model_evolution.data_processor import DataProcessor

processor = DataProcessor(hitl_log_path="logs/hitl.jsonl")
dataset = processor.export_training_dataset(output_dir="data/training")

# dataset.slm_data       → [{query, intent}, ...]
# dataset.llm_data       → [{instruction, input, output}, ...]
# dataset.reranker_data  → [{query, chunk, relevance}, ...]
```

### 6.2 Разделение train/val/test

```python
train, val, test = processor.split_train_val_test(
    data=dataset.slm_data,
    train_ratio=0.8,
    val_ratio=0.1,
    test_ratio=0.1,
    seed=42,
)
```

### 6.3 Форматированный вывод для конкретных тренеров

Процессор предоставляет вспомогательные функции форматирования для каждого тренера:

```python
# SLM: flat text+label format
slm_formatted = processor.format_for_slm(train)

# LLM: OpenAI-compatible messages format
llm_formatted = processor.format_for_llm(train)

# Reranker: already in tuple format from export
```

### 6.4 Формат HITL-лога

Каждая строка в `logs/hitl.jsonl` — это JSON-объект со следующими ключами:

| Ключ                          | Тип     | Обязателен для     | Описание                                                    |
|-------------------------------|---------|--------------------|-------------------------------------------------------------|
| `query`                       | `str`   | SLM, LLM, Reranker | Оригинальный запрос пользователя                            |
| `answer` / `response`         | `str`   | LLM                | Оригинальный сгенерированный ответ                          |
| `correction`                  | `str`   | LLM                | Экспертно-исправленный ответ (цель для обучения)            |
| `intent` / `predicted_intent` | `str`   | SLM                | Исправленная метка намерения                                |
| `relevance` / `score`         | `float` | Reranker           | Оценка релевантности (0.0-1.0)                              |
| `chunks` / `sources`          | `list`  | Reranker           | Извлечённые чанки с `{text, ...}` или строковыми значениями |

### 6.5 Выходные файлы

После выполнения `export_training_dataset()`:

```
data/training/
├── slm_intent.jsonl        # SLM training pairs
├── llm_instruction.jsonl   # LLM instruction-tuning pairs
└── reranker_pairs.jsonl    # Reranker (query, chunk, score) triples
```

---

## 7. Трекинг экспериментов

### 7.1 ExperimentTracker

Обёртка над MLflow с прозрачным локальным запасным вариантом:

```python
from proxy.app.model_evolution.experiment_tracker import ExperimentTracker

# With MLflow available
tracker = ExperimentTracker(
    tracking_uri="http://localhost:5000",
    experiment_name="intent-classifier-v2",
)

# Without MLflow → local JSON files
tracker = ExperimentTracker(experiment_name="intent-classifier-v2")
```

### 7.2 Жизненный цикл запуска

```python
run = tracker.start_run(run_name="slm-prod-run-1")
tracker.log_params({"lora_r": 16, "epochs": 5, "batch_size": 16})
tracker.log_metrics({"accuracy": 0.92, "weighted_f1": 0.89}, step=1)
tracker.log_artifact("./models/adapter/config.json")
tracker.end_run()
```

При недоступности MLflow запуски сохраняются как JSON-файлы:

```
data/experiments/
└── intent-classifier-v2/
    └── a1b2c3d4.json
```

### 7.3 Метрики Prometheus

Эволюция моделей экспортирует следующие метрики Prometheus для мониторинга:

```
# Training
rag_training_jobs_total{type="slm|llm|reranker", status="completed|failed"}
rag_training_duration_seconds{type="slm|llm|reranker"}

# Canary Deployment
rag_canary_traffic_total{model="slm|llm|reranker", target="stable|canary"}
rag_canary_result_total{model, target, outcome="success|error"}
rag_canary_latency_seconds{model, target}
rag_canary_phase{model}               # 0=idle ... 5=full, 6=rollback
rag_canary_split_ratio{model}         # Current canary traffic fraction
rag_canary_rollback_total{model}      # Total rollback events

# Adapter State
rag_adapter_state{name, state}        # unloaded/loading/active/draining/retiring/error
rag_adapter_request_count{name}       # In-flight requests
rag_adapter_error_count{name}         # Cumulative errors
```

---

## 8. Хранение артефактов

### 8.1 ArtifactStore

Управляет артефактами моделей в MinIO/S3 или локальной файловой системе:

```python
from proxy.app.model_evolution.artifact_store import ArtifactStore

# With MinIO/S3
store = ArtifactStore(
    endpoint="localhost:9000",
    access_key="minioadmin",
    secret_key="minioadmin",
    bucket="rag-artifacts",
)

# Local fallback (reads from data/artifacts/rag-artifacts/)
store = ArtifactStore(bucket="rag-artifacts")
```

### 8.2 Операции

```python
# Upload trained adapter
ref = store.upload_model(
    model_name="slm_intent",
    version="v3",
    local_path="./models/training/abc123/adapter",
)
# ref.bucket, ref.key, ref.uri

# Download for deployment
dest = store.download_model(
    model_name="slm_intent",
    version="v3",
    local_dir="/opt/models/loaded",
)
# Returns: "/opt/models/loaded/slm_intent/v3"

# List available versions
versions = store.list_versions("slm_intent")
# Returns: ["v1", "v2", "v3"]

# Remove old version
store.delete_version("slm_intent", "v1")
```

### 8.3 Структура хранилища

**S3/MinIO:**

```
s3://rag-artifacts/
└── models/
    └── slm_intent/
        ├── v1/
        │   ├── adapter_config.json
        │   └── adapter_model.safetensors
        └── v2/
            └── ...
```

**Локальная файловая система (запасной вариант):**

```
data/artifacts/rag-artifacts/
└── models/
    └── slm_intent/
        └── ...
```

---

## 9. EvalGate

### 9.1 Концепция

EvalGate — это CI/CD-шлюз качества, который решает, может ли вновь обученная модель быть продвинута. Он оценивает
метрики по настраиваемым порогам, обнаруживает регрессию относительно базового уровня и выдаёт решение **PASS / WARN /
FAIL**.

### 9.2 Конфигурация порогов

```python
from proxy.app.model_evolution.eval_gate import EvalGate, EvalGateConfig, MetricThreshold

config = EvalGateConfig(
    model_name="slm",
    thresholds=[
        MetricThreshold("accuracy", 0.90, "gte"),               # accuracy >= 0.90 → FAIL if not
        MetricThreshold("weighted_f1", 0.85, "gte"),            # weighted_f1 >= 0.85 → FAIL if not
        MetricThreshold("eval_loss", 1.0, "lte", severity="warn"),  # loss <= 1.0 → WARN if not
    ],
    require_baseline_comparison=True,
    baseline_regression_tolerance=0.02,   # 2% regression triggers WARN
    min_eval_samples=50,
)
```

### 9.3 Операторы сравнения

| Оператор | Значение         | Пример                      |
|----------|------------------|-----------------------------|
| `gte`    | больше или равно | `accuracy >= 0.90`          |
| `gt`     | больше           | `bleu_4 > 0.15`             |
| `lte`    | меньше или равно | `eval_loss <= 1.0`          |
| `lt`     | меньше           | `hallucination_rate < 0.05` |

### 9.4 Уровни серьёзности

| Серьёзность | При сбое                        | Блокирует продвижение?                                 |
|-------------|---------------------------------|--------------------------------------------------------|
| `fail`      | Добавляется в список `failures` | **Да** — шлюз возвращает FAIL                          |
| `warn`      | Добавляется в список `warnings` | **Нет** — шлюз возвращает WARN, но остаётся проходимым |

### 9.5 Сравнение с базовым уровнем

Когда `require_baseline_comparison=True` и предоставлены базовые метрики:

1. Вычисляются дельта-метрики: `delta = current - baseline`
2. Для каждой FAIL-пороговой метрики отрицательная дельта, превышающая `baseline_regression_tolerance`, вызывает WARN
3. Если базовый уровень не предоставлен, добавляется предупреждение: `"No baseline metrics provided for comparison"`

### 9.6 Интеграция с NLI

EvalGate может включать метрики заземления ответов на основе NLI:

```python
result = EvalGate.evaluate_with_nli(
    metrics={"accuracy": 0.92},
    config=config,
    answer_context_pairs=[
        ("SSO requires configuring the IdP...", "Navigate to Admin → SSO..."),
        ("The SLA is 99.9%...", "Service Level Agreement: 99.9% uptime..."),
    ],
    baseline_metrics=baseline,
    use_real_nli=True,  # Uses DeBERTa-v3; False → lightweight proxy
)
```

Это добавляет `nli_entailment_rate`, `nli_contradiction_rate`, `nli_neutral_rate` и `nli_overall_score` в словарь метрик
перед оценкой. См. [§15 — NLI-оценщик](#15-nli-оценщик) для подробностей.

### 9.7 Формат отчёта

Вызовите `EvalGate.format_report(result)` для человекочитаемого отчёта:

```
============================================================
Eval Gate Report
============================================================
Model:    slm
Version:  3
Status:   PASS
Run ID:   a1b2c3d4

------------------------------------------------------------
Metrics
------------------------------------------------------------
  accuracy: 0.9200  (Δ+0.0100)
  eval_loss: 0.2300  (Δ-0.0500)
  weighted_f1: 0.8900  (Δ+0.0200)

------------------------------------------------------------
Thresholds
------------------------------------------------------------
  accuracy gte 0.9 [PASS] (fail)
  weighted_f1 gte 0.85 [PASS] (fail)
  eval_loss lte 1.0 [PASS] (warn)

------------------------------------------------------------
Delta from Baseline
------------------------------------------------------------
  accuracy: +0.0100
  eval_loss: -0.0500
  weighted_f1: +0.0200

============================================================
```

---

## 10. Реестр моделей

### 10.1 Концепция

`ModelRegistry` управляет версиями моделей с жизненным циклом продвижения. Состояние сохраняется как JSON-файл, что
обеспечивает полную совместимость с воздушным зазором.

### 10.2 Жизненный цикл версий

```
register() → staging
    │
    ▼
promote() → canary
    │
    ▼
promote() → production   (previous production → archived)
    │
    ▼
rollback() → previous production restored
```

### 10.3 Состояния

| Статус         | Значение                                   | Может обрабатывать трафик? |
|----------------|--------------------------------------------|----------------------------|
| **staging**    | Новый, ещё не оценённый                    | Нет                        |
| **canary**     | Прошёл EvalGate, получает частичный трафик | Да (настраиваемый %)       |
| **production** | Полный трафик, текущий базовый уровень     | Да (100%)                  |
| **archived**   | Заменён более новой версией                | Нет                        |

### 10.4 API реестра

```python
from proxy.app.model_evolution.model_registry import ModelRegistry

registry = ModelRegistry(store_path="./data/model_registry.json")

# Register
mv = registry.register(
    name="slm",
    artifact_path="./models/slm_v3/adapter",
    metrics={"accuracy": 0.92, "weighted_f1": 0.89},
    version="3",
)

# Query
mv = registry.get("slm", "3")
latest = registry.get_latest("slm")
production = registry.get_latest_production("slm")

# Promote
mv = registry.promote("slm", "3")
# staging → canary (first promote)
# canary → production (second promote, archives previous production)

# Rollback
reverted = registry.rollback("slm")
# Archives current production, restores most recent archived version

# List
registry.list_models()                            # ["slm", "llm", "reranker"]
registry.list_versions("slm")                     # [ModelVersion, ...]
registry.list_by_status("slm", "production")      # [ModelVersion, ...]

# Update metrics after evaluation
registry.update_metrics("slm", "3", {"accuracy": 0.93})
```

### 10.5 JSON-персистентность

Файл реестра (`data/model_registry.json`) атомарен — сначала запись идёт во временный файл `.tmp`, затем атомарно
заменяется через `os.replace()`:

```json
{
  "models": {
    "slm": {
      "1": {
        "name": "slm",
        "version": "1",
        "artifact_path": "./models/slm_v1",
        "metrics": {"accuracy": 0.88},
        "status": "archived",
        "created_at": "2026-07-01T10:00:00+00:00"
      },
      "2": {
        "name": "slm",
        "version": "2",
        "artifact_path": "./models/slm_v2",
        "metrics": {"accuracy": 0.91},
        "status": "production",
        "created_at": "2026-07-03T10:00:00+00:00"
      }
    }
  }
}
```

---

## 11. Канареечное развёртывание

### 11.1 Концепция

`CanaryController` маршрутизирует настраиваемый процент трафика на новую версию модели, пока основная часть продолжает
работать на стабильном базовом уровне. Если метрики деградируют, автоматически происходит откат на 100% базового уровня.

### 11.2 Фазы развёртывания

| Фаза       | % трафика | Описание                                 |
|------------|-----------|------------------------------------------|
| `IDLE`     | 0%        | Канарейка не активна                     |
| `RAMP_5`   | <5%       | Начальный дымовой тест                   |
| `RAMP_25`  | 5-24%     | Ранняя валидация                         |
| `RAMP_50`  | 25-49%    | Средний масштаб                          |
| `RAMP_75`  | 50-74%    | Предпродакшен                            |
| `FULL`     | 75-100%   | Канарейка становится стабильной          |
| `ROLLBACK` | 0%        | Автоматически запускается при деградации |

### 11.3 Конфигурация

```python
from proxy.app.model_evolution.canary_controller import CanaryController

controller = CanaryController()

controller.configure(
    model_name="slm",
    stable_version="v2",
    canary_version="v3",
    canary_percent=0.05,               # Start at 5%
    min_samples=100,                    # Minimum requests before evaluating
    rollback_thresholds={
        "error_rate": (0.05, "gt"),     # Rollback if error_rate > 5%
        "p95_latency_ms": (10000, "gt"),  # Rollback if p95 > 10s
    },
    cooldown_seconds=3600,             # 1-hour cooldown after rollback
)
```

### 11.4 Маршрутизация запросов

```python
# Each request: decide which model variant to use
target = controller.route("slm")  # Returns "stable" or "canary"

# After the request: record the outcome
controller.record_result(
    model_name="slm",
    target=target,
    success=True,
    latency_ms=450.0,
)
```

### 11.5 Автоматический откат

Контроллер оценивает метрики при каждом запросе:

1. Проверяет, достигнуто ли минимальное количество выборок (`min_samples`)
2. Вычисляет текущую частоту ошибок из записанных результатов
3. Сравнивает с каждым порогом в `rollback_thresholds`
4. Если какой-либо порог нарушен → `rollback()` → трафик канарейки устанавливается на 0%, начинается кулдаун
5. Возвращает `True` из `should_rollback()`, пока деградация сохраняется

```python
if controller.should_rollback("slm"):
    controller.rollback("slm")
    # Canary traffic drops to 0%; cooldown period begins
```

### 11.6 Проверка статуса

```python
status = controller.status("slm")
# {
#     "phase": "ramp_5",
#     "split": {"stable": 0.95, "canary": 0.05},
#     "stable_version": "v2",
#     "canary_version": "v3",
#     "cooldown_remaining_seconds": 0,
#     "metrics": {
#         "total_stable": 1050,
#         "total_canary": 55,
#         "canary_error_rate": 0.018,
#         "stable_error_rate": 0.015,
#     },
# }
```

---

## 12. Горячая перезагрузка

### 12.1 Концепция

`AdapterManager` обеспечивает загрузку и выгрузку адаптеров моделей без перезапуска прокси. Новые версии адаптеров
обнаруживаются через опрос файловой системы или изменения в реестре MLflow и горячо заменяются с нулевым временем
простоя для обрабатываемых запросов.

### 12.2 Состояния жизненного цикла адаптера

```
UNLOADED ──→ LOADING ──→ ACTIVE ──→ DRAINING ──→ RETIRING ──→ UNLOADED
    ↑                       │            │             │            │
    └───────────────────────┴────────────┴─────────────┴────────────┘
                            ERROR ←──────┘
```

Допустимые переходы:

| Из       | Допустимые целевые состояния     |
|----------|----------------------------------|
| UNLOADED | LOADING, ERROR                   |
| LOADING  | ACTIVE, ERROR                    |
| ACTIVE   | DRAINING, ERROR                  |
| DRAINING | RETIRING, ACTIVE, LOADING, ERROR |
| RETIRING | UNLOADED, ERROR                  |
| ERROR    | UNLOADED, LOADING, ACTIVE        |

### 12.3 Регистрация и загрузка

```python
from proxy.app.model_evolution.adapter_manager import (
    AdapterManager, ModelAdapter, get_adapter_manager,
)

manager = get_adapter_manager()

# Register adapter metadata
manager.register_adapter(ModelAdapter(
    name="slm_intent",
    adapter_type="lora",
    base_model="bert-base-uncased",
))

# Register callbacks for actual model loading/unloading
manager.register_load_callback("slm_intent", my_load_function)
manager.register_unload_callback("slm_intent", my_unload_function)

# Load adapter weights
manager.load_adapter(
    name="slm_intent",
    model_path="./models/slm_v3/adapter",
    version="v3",
)

# Track in-flight requests
manager.begin_request("slm_intent")
# ... process request ...
manager.end_request("slm_intent")
```

### 12.4 Рабочий процесс горячей перезагрузки

```python
# Detect new version and hot-swap atomically
manager.hot_reload(
    name="slm_intent",
    new_path="./models/slm_v4/adapter",
    new_version="v4",
)
```

Что происходит внутри:

1. Старый адаптер переходит в состояние DRAINING
2. Новый адаптер загружается с диска → переходит в ACTIVE
3. Если новый адаптер не удалось загрузить, старый возвращается в ACTIVE (нет простоя)
4. Старый адаптер ожидает завершения обрабатываемых запросов (опрос каждые 0.5 секунды, тайм-аут 30 секунд)
5. После завершения всех запросов старый адаптер переходит: RETIRING → UNLOADED

### 12.5 Наблюдение за файловой системой

Включение автоматического обнаружения новых версий адаптеров:

```python
manager.enable_watcher(
    name="slm_intent",
    path="/opt/models/adapters/slm_intent/",
    poll_interval=5.0,  # Check every 5 seconds
)

# Watcher detects new subdirectories or adapter files:
#   adapter_config.json, *.safetensors, *.bin, *.pt, *.ckpt,
#   lora_weights.*, pytorch_model.*
```

При появлении новой версии наблюдатель автоматически запускает `hot_reload()`.

### 12.6 Обработка SIGHUP

```python
from proxy.app.model_evolution.adapter_manager import setup_signal_handlers

setup_signal_handlers()  # Registers SIGHUP → manager.reload_all()
```

Отправка SIGHUP процессу прокси запускает полное повторное сканирование всех зарегистрированных адаптеров:

```bash
kill -HUP $(pgrep -f "granian")
```

### 12.7 Освобождение и вывод из эксплуатации

Метод `_drain_and_retire()` обеспечивает замену с нулевым временем простоя:

1. Опрашивает `adapter.request_count` каждые 0.5 секунды
2. Когда счётчик достигает 0 → немедленный вывод из эксплуатации
3. Через 30 секунд (60 попыток) → принудительный вывод из эксплуатации с предупреждением

---

## 13. Справочник по Admin API

Все эндпоинты требуют **роль администратора** (`Role.ADMIN`) через JWT-аутентификацию.

### 13.1 Запуск обучения

**`POST /v1/admin/models/train`**

| Параметр        | Тип     | По умолчанию         | Описание                                                                                     |
|-----------------|---------|----------------------|----------------------------------------------------------------------------------------------|
| `trainer_type`  | `str`   | (обязательно)        | Один из: `"slm"`, `"llm"`, `"reranker"`                                                      |
| `base_model`    | `str`   | `""`                 | Имя или путь модели HuggingFace (например, `"bert-base-uncased"`, `"meta-llama/Llama-3-8B"`) |
| `profile`       | `str`   | `"dev"`              | Профиль окружения: `"dev"`, `"prod"`, `"ci"`                                                 |
| `data_dir`      | `str`   | `"./data/training/"` | Директория с файлами тренировочных данных                                                    |
| `epochs`        | `int`   | `3`                  | Количество эпох обучения                                                                     |
| `batch_size`    | `int`   | `8`                  | Размер батча на устройство                                                                   |
| `learning_rate` | `float` | `2e-4`               | Скорость обучения                                                                            |
| `use_lora`      | `bool`  | `true`               | Включить обучение LoRA-адаптера                                                              |

**Запрос:**

```json
{
  "trainer_type": "slm",
  "base_model": "bert-base-uncased",
  "profile": "prod",
  "epochs": 5,
  "batch_size": 16,
  "learning_rate": 2e-4,
  "use_lora": true
}
```

**Ответ (202 accepted):**

```json
{
  "job_id": "abc12345-6789-4abc-def0-1234567890ab",
  "trainer_type": "slm",
  "status": "running",
  "message": "Training job abc12345-6789-4abc-def0-1234567890ab started"
}
```

Обучение выполняется асинхронно. По завершении модель автоматически регистрируется в реестре моделей со статусом
`staging`.

---

### 13.2 Проверка статуса задачи

**`GET /v1/admin/models/status/{job_id}`**

**Ответ:**

```json
{
  "job_id": "abc12345-6789-4abc-def0-1234567890ab",
  "trainer_type": "slm",
  "config": { "epochs": 5, "batch_size": 16, "..." : "..." },
  "status": "completed",
  "metrics": { "accuracy": 0.92, "weighted_f1": 0.89, "loss": 0.23 },
  "artifact_uri": "./models/training/abc123/adapter",
  "started_at": "2026-07-06T12:00:00Z",
  "completed_at": "2026-07-06T12:05:00Z"
}
```

Возможные значения статуса: `queued`, `running`, `completed`, `failed`.

---

### 13.3 Список моделей

**`GET /v1/admin/models`**

**Ответ:**

```json
{
  "models": {
    "slm": {
      "versions": [
        {
          "version": "1",
          "status": "archived",
          "artifact_path": "./models/slm_v1",
          "metrics": { "accuracy": 0.88 },
          "created_at": "2026-06-01T10:00:00Z"
        },
        {
          "version": "2",
          "status": "production",
          "artifact_path": "./models/slm_v2",
          "metrics": { "accuracy": 0.91 },
          "created_at": "2026-07-01T10:00:00Z"
        }
      ],
      "production_version": "2"
    }
  }
}
```

---

### 13.4 Продвижение модели

**`POST /v1/admin/models/promote`**

| Параметр     | Тип   | Описание                                 |
|--------------|-------|------------------------------------------|
| `model_name` | `str` | Идентификатор модели (например, `"slm"`) |
| `version`    | `str` | Версия для продвижения                   |

**Запрос:**

```json
{
  "model_name": "slm",
  "version": "3"
}
```

**Ответ:**

```json
{
  "model_name": "slm",
  "version": "3",
  "previous_status": "staging",
  "new_status": "canary"
}
```

Переходы статусов:

- `staging` → `canary` (первое продвижение)
- `canary` → `production` (второе продвижение, архивирует предыдущий production)
- `production` → `production` (без изменений)
- `archived` → `archived` (без изменений)

---

### 13.5 Откат модели

**`POST /v1/admin/models/rollback`**

| Параметр     | Тип   | Описание             |
|--------------|-------|----------------------|
| `model_name` | `str` | Идентификатор модели |

**Запрос:**

```json
{
  "model_name": "slm"
}
```

**Ответ:**

```json
{
  "model_name": "slm",
  "version": "2",
  "previous_version": "3",
  "status": "production"
}
```

Находит текущую production-версию, архивирует её и восстанавливает последнюю архивированную версию в production.

---

### 13.6 Оценка модели

**`POST /v1/admin/models/evaluate`**

| Параметр     | Тип    | По умолчанию  | Описание                       |
|--------------|--------|---------------|--------------------------------|
| `model_name` | `str`  | (обязательно) | Идентификатор модели           |
| `version`    | `str`  | `"unknown"`   | Версия для оценки              |
| `metrics`    | `dict` | (обязательно) | Маппинг имя метрики → значение |

Применяемые пороги по умолчанию:

| Метрика        | Порог | Сравнение | Серьёзность |
|----------------|-------|-----------|-------------|
| `accuracy`     | 0.90  | `gte`     | `fail`      |
| `weighted_f1`  | 0.85  | `gte`     | `fail`      |
| `mrr`          | 0.70  | `gte`     | `fail`      |
| `recall_at_10` | 0.65  | `gte`     | `fail`      |
| `rouge_l_f1`   | 0.35  | `gte`     | `fail`      |
| `eval_loss`    | 1.0   | `lte`     | `warn`      |

**Запрос:**

```json
{
  "model_name": "slm",
  "version": "3",
  "metrics": {
    "accuracy": 0.92,
    "weighted_f1": 0.89,
    "mrr": 0.78
  }
}
```

**Ответ:**

```json
{
  "model_name": "slm",
  "version": "3",
  "status": "PASS",
  "failures": [],
  "warnings": [],
  "metrics": {
    "accuracy": 0.92,
    "weighted_f1": 0.89,
    "mrr": 0.78
  }
}
```

Если для модели существует production-версия, её метрики используются как базовый уровень для обнаружения регрессии.
Метрики также сохраняются в реестр через `update_metrics()`.

---

### 13.7 Канареечное распределение трафика

**`POST /v1/admin/models/canary/split`**

| Параметр        | Тип     | Описание                                  |
|-----------------|---------|-------------------------------------------|
| `model_name`    | `str`   | Идентификатор модели                      |
| `traffic_split` | `float` | Доля трафика на канарейку (от 0.0 до 1.0) |

**Запрос:**

```json
{
  "model_name": "slm",
  "traffic_split": 0.25
}
```

**Ответ:**

```json
{
  "model_name": "slm",
  "traffic_split": 0.25,
  "status": "ramp"
}
```

---

### 13.8 Статус канарейки

**`GET /v1/admin/models/canary/status`**

**Ответ:**

```json
{
  "slm": {
    "traffic_split": 0.25,
    "stable_traffic": 0.75,
    "phase": "ramp",
    "stable_version": null,
    "canary_version": null
  }
}
```

---

## 14. Интеграция с CI/CD

### 14.1 GitHub Actions Workflow

Пример `.github/workflows/model-evolution.yml`:

```yaml
name: Model Evolution Pipeline

on:
  schedule:
    - cron: '0 2 * * 1'      # Weekly at 2 AM Monday
  workflow_dispatch:
    inputs:
      trainer_type:
        description: 'Model type to train'
        required: true
        type: choice
        options: [slm, llm, reranker]
      profile:
        description: 'Training profile'
        default: 'prod'
        type: choice
        options: [dev, prod]

env:
  PROXY_URL: ${{ secrets.PROXY_URL }}
  JWT_TOKEN: ${{ secrets.ADMIN_JWT_TOKEN }}

jobs:
  train-and-evaluate:
    runs-on: [self-hosted, gpu]  # GPU runner for prod
    steps:
      - name: Trigger training
        id: train
        run: |
          RESPONSE=$(curl -s -X POST "$PROXY_URL/v1/admin/models/train" \
            -H "Authorization: Bearer $JWT_TOKEN" \
            -H "Content-Type: application/json" \
            -d "{
              \"trainer_type\": \"${{ inputs.trainer_type || 'slm' }}\",
              \"profile\": \"${{ inputs.profile || 'prod' }}\"
            }")
          JOB_ID=$(echo "$RESPONSE" | jq -r '.job_id')
          echo "job_id=$JOB_ID" >> $GITHUB_OUTPUT

      - name: Wait for training
        run: |
          for i in $(seq 1 120); do
            STATUS=$(curl -s "$PROXY_URL/v1/admin/models/status/${{ steps.train.outputs.job_id }}" \
              -H "Authorization: Bearer $JWT_TOKEN" | jq -r '.status')
            if [ "$STATUS" = "completed" ]; then
              echo "Training completed"
              exit 0
            elif [ "$STATUS" = "failed" ]; then
              echo "Training failed"
              exit 1
            fi
            sleep 30
          done
          echo "Timeout waiting for training"
          exit 1

      - name: Fetch metrics
        id: metrics
        run: |
          METRICS=$(curl -s "$PROXY_URL/v1/admin/models/status/${{ steps.train.outputs.job_id }}" \
            -H "Authorization: Bearer $JWT_TOKEN" | jq -c '.metrics')
          echo "metrics=$METRICS" >> $GITHUB_OUTPUT

      - name: Evaluate against EvalGate
        id: eval
        run: |
          RESULT=$(curl -s -X POST "$PROXY_URL/v1/admin/models/evaluate" \
            -H "Authorization: Bearer $JWT_TOKEN" \
            -H "Content-Type: application/json" \
            -d "{
              \"model_name\": \"${{ inputs.trainer_type || 'slm' }}\",
              \"version\": \"ci-$(date +%Y%m%d)\",
              \"metrics\": ${{ steps.metrics.outputs.metrics }}
            }")
          echo "$RESULT" | jq .
          STATUS=$(echo "$RESULT" | jq -r '.status')
          echo "status=$STATUS" >> $GITHUB_OUTPUT
          if [ "$STATUS" = "FAIL" ]; then
            echo "EvalGate failed — model blocked"
            exit 1
          fi

      - name: Promote to canary (if PASS)
        if: steps.eval.outputs.status != 'FAIL'
        run: |
          curl -s -X POST "$PROXY_URL/v1/admin/models/promote" \
            -H "Authorization: Bearer $JWT_TOKEN" \
            -H "Content-Type: application/json" \
            -d "{\"model_name\": \"${{ inputs.trainer_type || 'slm' }}\", \"version\": \"ci-$(date +%Y%m%d)\"}"
```

### 14.2 Матрица решений по продвижению

| Результат EvalGate | Действие                                           | Требуется ручной шаг?    |
|--------------------|----------------------------------------------------|--------------------------|
| **PASS**           | Автопродвижение на канарейку на 5%                 | Нет                      |
| **WARN**           | Автопродвижение на канарейку на 5% (с оповещением) | Нет                      |
| **FAIL**           | Блокировка продвижения                             | Да — исследование метрик |

---

## 15. NLI-оценщик

### 15.1 Концепция

NLI-оценщик (Natural Language Inference) проверяет, заземлены ли сгенерированные ответы в исходном контексте, разбивая
ответы на утверждения и оценивая каждое утверждение на entailment (следование), contradiction (противоречие) или
neutrality (нейтральность) относительно контекста.

### 15.2 Модель

**Основная:** `MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli` — модель DeBERTa-v3, дообученная на наборах данных MNLI,
FEVER и ANLI. Классифицирует каждую пару (контекст, утверждение) в:

- **Entailment** — утверждение логически следует из контекста
- **Contradiction** — утверждение противоречит контексту
- **Neutral** — утверждение ни не следует, ни не противоречит

### 15.3 NLI-метрики

| Метрика                  | Формула                                                    | Диапазон            |
|--------------------------|------------------------------------------------------------|---------------------|
| `nli_entailment_rate`    | entailed_claims / total_claims                             | [0, 1] — выше лучше |
| `nli_contradiction_rate` | contradicted_claims / total_claims                         | [0, 1] — ниже лучше |
| `nli_neutral_rate`       | neutral_claims / total_claims                              | [0, 1]              |
| `nli_overall_score`      | max(0, min(1, entailment_rate − 0.5 × contradiction_rate)) | [0, 1] — выше лучше |

### 15.4 Использование

```python
from proxy.app.model_evolution.nli_evaluator import evaluate_nli, evaluate_nli_batch

# Single answer evaluation
result = evaluate_nli(
    answer="SSO requires configuring the Identity Provider in Administration → SSO.",
    context="Navigate to Administration → SSO. Select your IdP and configure the SAML endpoint.",
    use_real_nli=True,
)
# result.entailment_rate = 0.75
# result.overall_score = 0.625

# Batch evaluation (for EvalGate integration)
metrics = evaluate_nli_batch(
    answer_context_pairs=[
        ("Answer 1...", "Context 1..."),
        ("Answer 2...", "Context 2..."),
    ],
    use_real_nli=True,
)
# Returns dict with nli_entailment_rate, nli_contradiction_rate, etc.
```

### 15.5 Лёгкий запасной вариант

Когда модель DeBERTa-v3 недоступна (воздушный зазор или не установлена), оценщик возвращается к **прокси на основе
пересечения токенов**:

1. Токенизирует утверждение и контекст в множества слов
2. Вычисляет косинусное сходство по пересечению токенов
3. Вычисляет покрытие утверждения (доля токенов утверждения, встречающихся в контексте)
4. Объединяет сходство и покрытие → классифицирует как entailment / contradiction / neutral

**Включение лёгкого режима:**

```python
evaluate_nli(answer, context, use_real_nli=False)
```

### 15.6 Декомпозиция утверждений

Ответы разбиваются на отдельные утверждения по границам предложений (`.`, `!`, `?`, `\n`, `;`). Утверждения короче 10
символов фильтруются. Маркеры списков (`-`, `*`, `•`) удаляются.

---

## 16. Справочник по профилям окружения

### 16.1 Профиль DEV

```yaml
# Designed for local development on CPU
gpu_enabled: false
epochs: 1
batch_size: 2
use_lora: true
lora_r: 4
lora_alpha: 8
use_qlora: false
load_in_4bit: false
max_seq_length: 256
eval_split: 0.2
logging_steps: 5
eval_steps: 50
```

### 16.2 Профиль CI

```yaml
# Designed for automated CI pipelines — fast, minimal resource usage
gpu_enabled: false
epochs: 1
batch_size: 1
use_lora: true
lora_r: 2
lora_alpha: 4
use_qlora: false
load_in_4bit: false
max_seq_length: 128
eval_split: 0.5          # More data for validation in CI smoke test
logging_steps: 1
eval_steps: 10
```

### 16.3 Профиль PROD

```yaml
# Designed for production training on GPU
gpu_enabled: true
epochs: 5
batch_size: 16
use_lora: true
lora_r: 16
lora_alpha: 32
use_qlora: true           # Enable 4-bit quantization for LLM
load_in_4bit: true
bnb_4bit_compute_dtype: bfloat16  # Use bfloat16 on supported GPUs (Ampere+)
max_seq_length: 2048
eval_split: 0.2
warmup_steps: 100
logging_steps: 10
eval_steps: 500
save_steps: 500
```

---

## 17. Устранение неполадок

### 17.1 Обучение завершается ошибкой "transformers and peft are required"

**Симптом:** Обучение SLM или реранкера возвращает ошибку об отсутствующих `transformers` или `peft`.

**Решение:**

```bash
pip install transformers peft accelerate
```

### 17.2 LLM возвращается к mock-обучению

**Симптом:** В логах `"Running LLM mock training (CPU profile)"`, даже когда GPU доступен.

**Причины и решения:**

1. **Неправильный профиль:** Убедитесь, что в запросе на обучение указано `"profile": "prod"`. Профили DEV и CI всегда
   используют CPU/mock.
2. **Отсутствующие GPU-библиотеки:**
   ```bash
   pip install bitsandbytes peft torch transformers accelerate
   ```
3. **CUDA недоступна:** Проверьте `python -c "import torch; print(torch.cuda.is_available())"`

### 17.3 OOM при обучении LLM QLoRA

**Симптом:** `torch.cuda.OutOfMemoryError` при обучении LLM.

**Решения:**

- Уменьшите `batch_size` до 1 или 2
- Увеличьте `gradient_accumulation_steps` (например, до 8) для сохранения эффективного размера батча
- Уменьшите `max_seq_length` до 1024 или 512
- Используйте более мелкую базовую модель (7B вместо 13B)
- Включите CPU-оффлоудинг: установите `device_map="auto"` (уже по умолчанию)

### 17.4 Реестр возвращает "Model not found"

**Симптом:** `KeyError: "Model 'slm' not found in registry"`

**Решение:** Модель должна быть зарегистрирована. После успешной тренировочной задачи модели регистрируются
автоматически. Для ручной регистрации:

```python
from proxy.app.model_evolution.model_registry import ModelRegistry
registry = ModelRegistry()
registry.register("slm", "./path/to/adapter", {"accuracy": 0.92})
```

### 17.5 EvalGate всегда возвращает WARN — "No baseline metrics"

**Симптом:** Каждая оценка показывает предупреждение `"No baseline metrics provided for comparison"`.

**Решение:** Это ожидаемо для первой версии модели или при отсутствии production-версии. Это не ошибка — шлюз
по-прежнему оценивает пороги. Для подавления:

- Сначала продвиньте модель в production
- Или установите `require_baseline_comparison=False` в `EvalGateConfig`

### 17.6 Канареечный откат срабатывает немедленно

**Симптом:** Канарейка откатывается сразу после маршрутизации трафика, даже без реальных ошибок.

**Причины:**

- `min_samples` установлен слишком высоко → недостаточно данных, но `error_rate` кажется завышенной на ранних этапах
- `rollback_thresholds` слишком строгие (например, `error_rate > 0.01`)

**Решение:** Начните с щедрых порогов и постепенно ужесточайте:

```python
rollback_thresholds={
    "error_rate": (0.10, "gt"),      # Start at 10%
}
```

### 17.7 Наблюдатель горячей перезагрузки не обнаруживает новые файлы

**Симптом:** Новые файлы адаптеров, размещённые в директории наблюдения, не обнаруживаются.

**Проверки:**

1. Включён ли наблюдатель? `manager.enable_watcher("name", "/path/to/adapters")`
2. Соответствуют ли файлы паттернам обнаружения? По умолчанию: `adapter_config.json`, `*.safetensors`, `*.bin`, `*.pt`,
   `*.ckpt`, `lora_weights.*`, `pytorch_model.*`
3. Вызвали ли вы `watch_directory()` для наблюдения на уровне файлов (а не поддиректорий)?
4. Вызовите `watcher.force_rescan()` для очистки кэша и немедленного повторного сканирования.

### 17.8 Адаптер застрял в состоянии LOADING или ERROR

**Симптом:** `adapter.state` — `LOADING` или `ERROR` и не переходит в `ACTIVE`.

**Решение:**

- Для LOADING: проверьте, что callback загрузки возвращает `True` и не выбрасывает исключений
- Для ERROR: сначала выгрузите адаптер (`manager.unload_adapter("name")`), что переводит ERROR → UNLOADED, затем
  попробуйте загрузить снова
- Проверьте Prometheus: `rag_adapter_error_count{name="..."}` для истории ошибок

### 17.9 Файл реестра моделей повреждён

**Симптом:** `json.JSONDecodeError` при загрузке реестра.

**Решение:** Реестр использует атомарные записи (сначала запись в `.tmp`, затем `os.replace`). Если основной файл
повреждён, проверьте наличие файла `.tmp`:

```bash
ls -la data/model_registry.json*
```

Если оба повреждены, удалите их и перерегистрируйте модели из хранилища артефактов.

### 17.10 NLI-оценщик использует лёгкий запасной вариант

**Симптом:** В логах `"NLI model loading skipped: transformers not installed"` или `"NLI model load failed"`.

**Решения:**

1. Установите зависимости: `pip install transformers torch`
2. Скачайте NLI-модель для использования в воздушном зазоре: сохраните `MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli`
   локально и установите `local_files_only=True` (уже по умолчанию)
3. Если лёгкий прокси приемлем (нет GPU, воздушный зазор), никаких действий не требуется — это осознанный запасной
   вариант

### 17.11 Обучение проходит успешно, но адаптер не меняет поведение модели

**Возможные причины:**

- Адаптер загружен в неправильную базовую модель — проверьте поле `base_model` в `trainer_config.json`
- Канареечное распределение на 0% — весь трафик по-прежнему идёт на стабильную версию
- Адаптер не продвинут через жизненный цикл — застрял в статусе `staging`
- Неправильные целевые модули для LoRA — проверьте, что `_resolve_target_modules()` соответствует архитектуре вашей
  модели

**Проверка:**

```bash
# Check registry
curl http://localhost:8080/v1/admin/models -H "Authorization: Bearer $JWT_TOKEN"

# Check canary status
curl http://localhost:8080/v1/admin/models/canary/status -H "Authorization: Bearer $JWT_TOKEN"
```

---

## Справочник по конфигурации

Вся конфигурация эволюции моделей через переменные окружения:

| Переменная                | По умолчанию                 | Описание                              |
|---------------------------|------------------------------|---------------------------------------|
| `MODEL_EVOLUTION_ENABLED` | `false`                      | Главный переключатель всей подсистемы |
| `MLFLOW_TRACKING_URI`     | `http://localhost:5000`      | URL сервера MLflow tracking           |
| `MLFLOW_EXPERIMENT_NAME`  | `rag-system`                 | Имя эксперимента MLflow               |
| `MLFLOW_ARTIFACT_ROOT`    | `s3://rag-artifacts`         | Корень хранилища артефактов           |
| `MINIO_ENDPOINT`          | `localhost:9000`             | Эндпоинт MinIO/S3                     |
| `MINIO_ACCESS_KEY`        | `minioadmin`                 | Ключ доступа MinIO                    |
| `MINIO_SECRET_KEY`        | `minioadmin`                 | Секретный ключ MinIO                  |
| `MINIO_BUCKET`            | `rag-artifacts`              | Имя бакета MinIO                      |
| `MINIO_SECURE`            | `false`                      | Использовать HTTPS для MinIO          |
| `MODEL_REGISTRY_PATH`     | `./data/model_registry.json` | Путь к JSON-файлу реестра             |

---

## Иерархия исключений

```
ModelEvolutionError (base)
├── TrainingError       — data prep, GPU OOM, checkpoint failures
├── EvalGateError       — threshold not met, baseline regression
├── AdapterError        — load failure, version mismatch, memory error
└── CanaryError         — rollback failure, metric unavailability
```

---

## Зависимости

Требуются для полной функциональности:

```bash
# Core training
pip install transformers peft accelerate

# LLM QLoRA
pip install bitsandbytes

# Reranker full fine-tune (optional, for use_lora=false mode)
pip install sentence-transformers

# Metrics (optional, for BERTScore)
pip install bert-score

# Experiment tracking (optional)
pip install mlflow

# Artifact storage (optional, for S3/MinIO)
pip install boto3

# Safe tensor format (recommended)
pip install safetensors
```

---

**Связанные руководства:**

- [Оценка зрелости RAG](rag-maturity-assessment.md) — место эволюции моделей в модели зрелости RAG
- [Чек-лист лучших практик](best-practices-checklist.md) — измерения готовности к продакшену
- [Контроль доступа и RBAC](access-control-rbac.md) — роль администратора required для всех эндпоинтов эволюции моделей
- [Устранение неполадок](troubleshooting.md) — общее устранение неполадок системы
