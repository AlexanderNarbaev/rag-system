# Блок H. Model Evolution (FR-95 — FR-102)

---

## FR-95. SLM LoRA fine-tuning

**Описание:**
Система поддерживает fine-tuning SLM (Llama-3B, Gemma-2B, Qwen-2.5-3B) с LoRA:
rank=8, alpha=16, target_modules=[q_proj, v_proj]. Training data — из HITL feedback.

**Критерий приёмки:**
1. POST `/v1/admin/models/train` с `model_type=slm` — запускает training job
2. Training job завершается успешно
3. Adapter сохраняется в MinIO
4. Metrics логируются в MLflow

**Статус:** ⚠️ Код есть (`proxy/app/model_evolution/slm_trainer.py`), нужен интеграционный тест
**Приоритет:** HIGH
**Связь:** ADR-010

---

## FR-96. LLM QLoRA fine-tuning

**Описание:**
Система поддерживает fine-tuning LLM с QLoRA: 4-bit NF4 квантизация, rank=16,
alpha=32. Для больших моделей (7B+) экономит память GPU.

**Критерий приёмки:**
1. POST `/v1/admin/models/train` с `model_type=llm` — запускает training job
2. Training job завершается успешно
3. Adapter сохраняется в MinIO

**Статус:** ⚠️ Код есть (`proxy/app/model_evolution/llm_trainer.py`), нужен интеграционный тест
**Приоритет:** HIGH
**Связь:** ADR-010

---

## FR-97. Reranker fine-tuning

**Описание:**
Система поддерживает fine-tuning reranker двумя способами:
- Full fine-tuning через CrossEncoder.fit()
- LoRA fine-tuning (rank=4)

Training data — positive/negative pairs из HITL feedback.

**Критерий приёмки:**
1. Training job завершается успешно
2. Fine-tuned reranker показывает MRR ≥ baseline + 0.02
3. Adapter/model сохраняется в MinIO

**Статус:** ⚠️ Код есть (`proxy/app/model_evolution/reranker_trainer.py`), нужен интеграционный тест
**Приоритет:** HIGH
**Связь:** ADR-010

---

## FR-98. MLflow experiment tracking

**Описание:**
Все training jobs логируются в MLflow:
- Parameters (model, rank, alpha, learning_rate, epochs)
- Metrics (loss, accuracy, F1, BertScore)
- Artifacts (adapter weights, training data)

**Критерий приёмки:**
1. MLflow UI показывает runs с parameters и metrics
2. Artifacts загружаются в MLflow
3. S3-хранилище (MinIO) содержит artifacts

**Статус:** ⚠️ Код есть (`proxy/app/model_evolution/experiment_tracker.py`), нужен интеграционный тест
**Приоритет:** HIGH
**Связь:** ADR-ME-001

---

## FR-99. MLflow Model Registry

**Описание:**
MLflow Model Registry отслеживает версии моделей со stage transitions:
None → Staging → Production → Archived.

**Критерий приёмки:**
1. Новая модель — stage=None
2. Promotion — stage=Production
3. Rollback — stage=Archived, предыдущая → Production

**Статус:** ⚠️ Код есть (`proxy/app/model_evolution/model_registry.py`), нужен интеграционный тест
**Приоритет:** HIGH
**Связь:** ADR-ME-001

---

## FR-100. EvalGate CI/CD quality gating

**Описание:**
Перед promotion модель проходит quality gate:
- SLM: F1 ≥ 0.85
- LLM: BertScore ≥ 0.70, hallucination ≤ 0.05
- Reranker: MRR ≥ baseline + 0.02, Rouge-L ≥ 0.35

Модель, не прошедшая gate, блокируется от promotion.

**Критерий приёмки:**
1. Модель с F1=0.90 — проходит gate, можно promote
2. Модель с F1=0.70 — блокируется, нельзя promote
3. Gate логирует reason для блокировки

**Статус:** ⚠️ Код есть (`proxy/app/model_evolution/eval_gate.py`), нужен интеграционный тест
**Приоритет:** HIGH
**Связь:** ADR-010 3.4

---

## FR-101. CanaryController — phased traffic splitting

**Описание:**
При deployment новой модели трафик распределяется по фазам:
- Phase 1: 5% на новую модель
- Phase 2: 25%
- Phase 3: 50%
- Phase 4: 75%
- Phase 5: 100%

Каждая фаза длится configurable время. При деградации метрик — автоматический rollback.

**Критерий приёмки:**
1. Phase 1 — 5% запросов идут на новую модель
2. Метрики OK — переход к следующей фазе
3. Метрики деградировали — rollback к предыдущей модели
4. Prometheus-метрики отслеживают canary status

**Статус:** ⚠️ Код есть (`proxy/app/model_evolution/canary_controller.py`), нужен интеграционный тест
**Приоритет:** HIGH
**Связь:** ADR-ME-004

---

## FR-102. AdapterManager — hot-reload без restart

**Описание:**
AdapterManager загружает новые LoRA-адаптеры без перезапуска прокси:
- Lifecycle: UNLOADED → LOADING → ACTIVE → DRAINING → RETIRING
- In-flight запросы завершаются на старом адаптере
- Новые запросы — на новом
- File watcher обнаруживает новый адаптер в директории

**Критерий приёмки:**
1. Новый адаптер в директории — обнаруживается file watcher
2. Hot-reload — прокси не перезапускается
3. In-flight запросы — завершаются успешно
4. Новые запросы — используют новый адаптер

**Статус:** ⚠️ Код есть (`proxy/app/model_evolution/adapter_manager.py`), нужен интеграционный тест
**Приоритет:** HIGH
**Связь:** ADR-ME-003
