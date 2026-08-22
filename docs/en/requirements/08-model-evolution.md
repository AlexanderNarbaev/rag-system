# Block H. Model Evolution (FR-95 — FR-102)

---

## FR-95. SLM LoRA fine-tuning

**Description:**
The system supports fine-tuning the SLM (Llama-3B, Gemma-2B, Qwen-2.5-3B) with LoRA:
rank=8, alpha=16, target_modules=[q_proj, v_proj]. Training data comes from HITL feedback.

**Acceptance criteria:**

1. POST `/v1/admin/models/train` with `model_type=slm` — starts a training job
2. The training job completes successfully
3. The adapter is saved to MinIO
4. Metrics are logged to MLflow

**Status:** ✅ Confirmed (extracted into `model_evolution_service/trainers/slm_trainer.py`)
**Priority:** HIGH
**Reference:** ADR-010

---

## FR-96. LLM QLoRA fine-tuning

**Description:**
The system supports fine-tuning the LLM with QLoRA: 4-bit NF4 quantization, rank=16,
alpha=32. For large models (7B+) this saves GPU memory.

**Acceptance criteria:**

1. POST `/v1/admin/models/train` with `model_type=llm` — starts a training job
2. The training job completes successfully
3. The adapter is saved to MinIO

**Status:** ✅ Confirmed (extracted into `model_evolution_service/trainers/llm_trainer.py`)
**Priority:** HIGH
**Reference:** ADR-010

---

## FR-97. Reranker fine-tuning

**Description:**
The system supports fine-tuning the reranker in two ways:

- Full fine-tuning via CrossEncoder.fit()
- LoRA fine-tuning (rank=4)

Training data — positive/negative pairs from HITL feedback.

**Acceptance criteria:**

1. The training job completes successfully
2. The fine-tuned reranker shows MRR ≥ baseline + 0.02
3. The adapter/model is saved to MinIO

**Status:** ✅ Confirmed (extracted into `model_evolution_service/trainers/reranker_trainer.py`)
**Priority:** HIGH
**Reference:** ADR-010

---

## FR-98. MLflow experiment tracking

**Description:**
All training jobs are logged to MLflow:

- Parameters (model, rank, alpha, learning_rate, epochs)
- Metrics (loss, accuracy, F1, BertScore)
- Artifacts (adapter weights, training data)

**Acceptance criteria:**

1. The MLflow UI shows runs with parameters and metrics
2. Artifacts are uploaded to MLflow
3. The S3 storage (MinIO) contains the artifacts

**Status:** ✅ Confirmed (extracted into `model_evolution_service/experiment_tracker.py`)
**Priority:** HIGH
**Reference:** ADR-ME-001

---

## FR-99. MLflow Model Registry

**Description:**
The MLflow Model Registry tracks model versions with stage transitions:
None → Staging → Production → Archived.

**Acceptance criteria:**

1. A new model — stage=None
2. Promotion — stage=Production
3. Rollback — stage=Archived, previous → Production

**Status:** ✅ Confirmed (extracted into `model_evolution_service/model_registry.py`)
**Priority:** HIGH
**Reference:** ADR-ME-001

---

## FR-100. EvalGate CI/CD quality gating

**Description:**
Before promotion, a model passes a quality gate:

- SLM: F1 ≥ 0.85
- LLM: BertScore ≥ 0.70, hallucination ≤ 0.05
- Reranker: MRR ≥ baseline + 0.02, Rouge-L ≥ 0.35

A model that fails the gate is blocked from promotion.

**Acceptance criteria:**

1. A model with F1=0.90 — passes the gate, can be promoted
2. A model with F1=0.70 — is blocked, cannot be promoted
3. The gate logs the reason for blocking

**Status:** ✅ Confirmed (extracted into `model_evolution_service/eval_gate.py`)
**Priority:** HIGH
**Reference:** ADR-010 3.4

---

## FR-101. CanaryController — phased traffic splitting

**Description:**
When deploying a new model, traffic is split in phases:

- Phase 1: 5% to the new model
- Phase 2: 25%
- Phase 3: 50%
- Phase 4: 75%
- Phase 5: 100%

Each phase lasts a configurable time. On metric degradation — automatic rollback.

**Acceptance criteria:**

1. Phase 1 — 5% of requests go to the new model
2. Metrics OK — move to the next phase
3. Metrics degraded — rollback to the previous model
4. Prometheus metrics track the canary status

**Status:** ✅ Confirmed (extracted into `model_evolution_service/canary_controller.py`)
**Priority:** HIGH
**Reference:** ADR-ME-004

---

## FR-102. AdapterManager — hot-reload without restart

**Description:**
The AdapterManager loads new LoRA adapters without restarting the proxy:

- Lifecycle: UNLOADED → LOADING → ACTIVE → DRAINING → RETIRING
- In-flight requests finish on the old adapter
- New requests — on the new one
- A file watcher detects a new adapter in the directory

**Acceptance criteria:**

1. A new adapter in the directory — detected by the file watcher
2. Hot-reload — the proxy does not restart
3. In-flight requests — complete successfully
4. New requests — use the new adapter

**Status:** ✅ Confirmed (extracted into `model_evolution_service/adapter_manager.py`)
**Priority:** HIGH
**Reference:** ADR-ME-003
