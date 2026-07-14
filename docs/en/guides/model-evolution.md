# Model Evolution Guide

**Feature Version:** v2.0 (June 2026)
**Implementation Status:** Implemented. All 13 modules are in `proxy/app/model_evolution/` with full admin API endpoints
and 358 unit tests.

---

## 1. Concept

Model Evolution is a complete fine-tuning pipeline that continuously improves the RAG system's models using real-world
feedback data. Instead of shipping static models, you train domain-specific adapters that get better over time as more
expert feedback accumulates.

### 1.1 Why Fine-Tune?

| Driver                       | Problem                                                                                       | Fine-Tuning Solution                                                          |
|------------------------------|-----------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------|
| **Domain drift**             | General-purpose models misunderstand corporate jargon                                         | Adapt to your organization's vocabulary, acronyms, and terminology            |
| **Intent misclassification** | SLM router misroutes `"How do I deploy to staging?"` as a fact question instead of procedural | Train intent classifier on your actual query distribution                     |
| **Shallow answers**          | LLM generates vague responses for domain-specific questions                                   | Instruction-tune on expert corrections to produce precise, contextual answers |
| **Poor reranking**           | Generic cross-encoder ranks irrelevant chunks higher                                          | Fine-tune on relevance judgments from your document corpus                    |
| **Hallucination**            | LLM fabricates information not in retrieved context                                           | Ground answers with HITL-corrected examples                                   |
| **Feedback loop**            | Expert corrections are logged but never re-used                                               | Feed corrections back into training, closing the improvement loop             |

### 1.2 What Can Be Fine-Tuned?

| Model        | Type              | Trainer           | Technique       | Adapter Size                 | Use Case                               |
|--------------|-------------------|-------------------|-----------------|------------------------------|----------------------------------------|
| **SLM**      | Intent Classifier | `SLMTrainer`      | LoRA (PEFT)     | ~5 MB                        | Query routing to determine intent type |
| **LLM**      | Generator         | `LLMTrainer`      | QLoRA 4-bit NF4 | ~20-50 MB                    | Domain-specific answer generation      |
| **Reranker** | Cross-Encoder     | `RerankerTrainer` | LoRA or Full    | ~5 MB (LoRA) / ~90 MB (full) | Relevance scoring for retrieved chunks |

### 1.3 When to Use Each

- **SLM fine-tuning** — when the intent router frequently misclassifies queries. Quick to train (minutes on GPU), small
  adapter.
- **LLM fine-tuning** — when answers need domain-specific precision. Requires substantial HITL feedback data (100+
  corrected examples recommended). GPU with 16+ GB VRAM for QLoRA.
- **Reranker fine-tuning** — when retrieved documents are relevant but ranked incorrectly. Use LoRA mode for quick
  adaptation, full fine-tune for major domain shifts.

---

## 2. Architecture

### 2.1 System Overview

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

### 2.2 Training Pipeline Flow

1. **Data Collection** — HITL expert feedback accumulates in `logs/hitl.jsonl` (queries, answers, corrections, relevance
   scores, intent labels).
2. **Data Processing** — `DataProcessor` reads the HITL log and produces three datasets:
    - `slm_intent.jsonl` — `{query, intent_label}` pairs for SLM intent classification
    - `llm_instruction.jsonl` — `{instruction, input, output}` triples for LLM instruction-tuning
    - `reranker_pairs.jsonl` — `{query, chunk, relevance}` triples for reranker training
3. **Train/Val/Test Split** — 80%/10%/10% stratified split with configurable seed.
4. **Training** — Configurable environment profile (DEV/CI/PROD) controls batch size, epochs, LoRA rank, quantization.
5. **Evaluation** — Metrics computed: accuracy, weighted F1 (SLM); BLEU, ROUGE-L, hallucination rate (LLM); MRR,
   nDCG@10, P@5 (Reranker).
6. **Artifact Storage** — Adapter weights + config saved to MinIO/S3 or local filesystem.
7. **Model Registry** — Version created with status `staging`, metrics attached.
8. **EvalGate** — Threshold check against configured criteria. PASS → eligible for canary; FAIL → blocked.
9. **Canary Deployment** — Gradual traffic split (5%→25%→50%→75%→100%) with auto-rollback on metric degradation.
10. **Hot-Reload** — New adapter loaded without service restart. SIGHUP triggers re-scan.

### 2.3 MLflow + MinIO Integration

| Component           | Environment Variable     | Default                 |
|---------------------|--------------------------|-------------------------|
| MLflow Tracking URI | `MLFLOW_TRACKING_URI`    | `http://localhost:5000` |
| MLflow Experiment   | `MLFLOW_EXPERIMENT_NAME` | `rag-system`            |
| Artifact Root       | `MLFLOW_ARTIFACT_ROOT`   | `s3://rag-artifacts`    |
| MinIO Endpoint      | `MINIO_ENDPOINT`         | `localhost:9000`        |
| MinIO Access Key    | `MINIO_ACCESS_KEY`       | `minioadmin`            |
| MinIO Secret Key    | `MINIO_SECRET_KEY`       | `minioadmin`            |
| MinIO Bucket        | `MINIO_BUCKET`           | `rag-artifacts`         |

Both MLflow and MinIO are optional. When unavailable (air-gapped or local dev), the system falls back to:

- **Experiment tracking** → local JSON files in `data/experiments/<name>/<run_id>.json`
- **Artifact storage** → local directory at `data/artifacts/<bucket>/`

---

## 3. Quick Start

### 3.1 Enable Model Evolution

```bash
export MODEL_EVOLUTION_ENABLED=true
```

### 3.2 Start Supporting Services

**Option A: Docker Compose (recommended for dev)**

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

**Option B: Air-gapped / local only**

No external services needed. The system uses local filesystem fallbacks automatically.

### 3.3 Your First Training Job

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

Response:

```json
{
  "job_id": "abc12345-6789-4abc-def0-1234567890ab",
  "trainer_type": "slm",
  "status": "running",
  "message": "Training job abc12345-6789-4abc-def0-1234567890ab started"
}
```

### 3.4 Check Job Status

```bash
curl -X GET http://localhost:8080/v1/admin/models/status/abc12345-6789-4abc-def0-1234567890ab \
  -H "Authorization: Bearer $JWT_TOKEN"
```

Response:

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

### 3.5 Promote and Deploy

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

If the evaluation passes, promote through the lifecycle:

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

## 4. Training Profiles

Training behavior is controlled by `EnvProfile`, selected via the `profile` parameter in the train request or
`TrainingConfig.from_profile()`.

### 4.1 Profile Presets

| Parameter                | DEV       | CI        | PROD       |
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

### 4.2 Profile Selection

| Profile  | When to Use                                       | Hardware          | Training Time (SLM) |
|----------|---------------------------------------------------|-------------------|---------------------|
| **DEV**  | Local development, smoke tests, quick experiments | CPU               | ~1 minute           |
| **CI**   | Automated CI pipelines, PR validation             | CPU (runner)      | ~30 seconds         |
| **PROD** | Real training runs for production deployment      | GPU (16+ GB VRAM) | ~5-15 minutes       |

### 4.3 Overriding Profile Settings

All profile presets can be overridden in the train request:

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

Overrides at the API level take precedence over profile defaults. The `TrainingConfig.from_profile()` method merges
profile presets with explicit kwargs — explicit keys always win.

---

## 5. Training Types

### 5.1 SLM Training — Intent Classification

**Trainer:** `SLMTrainer` in `slm_trainer.py`
**Technique:** LoRA fine-tuning on `AutoModelForSequenceClassification`
**Dataset:** `{query, intent_label}` pairs
**Intent Labels:** `greeting`, `simple_fact`, `factual`, `procedural`, `comparison`, `summarize`, `complex`

#### Configuration

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

#### Target Modules

LoRA target modules are auto-detected from the base model architecture:

| Base Model                   | Target Modules                         |
|------------------------------|----------------------------------------|
| BERT / RoBERTa               | `query`, `value`                       |
| GPT / Llama / Mistral / Qwen | `q_proj`, `v_proj`, `k_proj`, `o_proj` |
| Unknown                      | `q_proj`, `v_proj`                     |

#### Metrics

| Metric        | Description                          |
|---------------|--------------------------------------|
| `accuracy`    | Overall classification accuracy      |
| `weighted_f1` | F1 score weighted by class frequency |
| `loss`        | Cross-entropy eval loss              |

#### Example Data Format

```jsonl
{"query": "How do I deploy to staging?", "intent": "procedural"}
{"query": "What is the SLA for incident response?", "intent": "factual"}
{"query": "Compare Kubernetes and Nomad", "intent": "comparison"}
```

### 5.2 LLM Training — Domain-Specific Generation

**Trainer:** `LLMTrainer` in `llm_trainer.py`
**Technique:** QLoRA (4-bit NF4 quantization + PEFT LoRA) for memory efficiency
**Dataset:** Instruction-tuning pairs with `messages` format (system/user/assistant roles)

#### Configuration

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

#### QLoRA Details

QLoRA enables fine-tuning large models (7B-70B parameters) on a single GPU by:

1. **4-bit NormalFloat quantization** — compresses base model weights to 4 bits
2. **Double quantization** — quantizes the quantization constants (saves ~0.5 GB)
3. **Paged optimizers** — offloads optimizer states to CPU when GPU OOM
4. **LoRA adapters** — trains only ~1% of parameters as small rank-decomposition matrices

With QLoRA, a 7B model fits in ~6 GB VRAM (vs. ~28 GB for full fine-tuning).

#### GPU vs CPU Behavior

| Environment                        | Behavior                                                                        |
|------------------------------------|---------------------------------------------------------------------------------|
| PROD profile + CUDA available      | Full QLoRA GPU training with bitsandbytes                                       |
| DEV/CI profile or no CUDA          | **Mock training** — produces placeholder metrics and adapter config for testing |
| GPU profile but QLoRA libs missing | Falls back to mock with warning                                                 |

Mock training is a fully valid path for development and CI. It generates real adapter files and metrics, so the full
pipeline (registry, EvalGate, canary) can be tested without a GPU.

#### Data Format

```json
{
  "messages": [
    {"role": "user", "content": "How do I set up SSO for Jira?"},
    {"role": "assistant", "content": "Navigate to Administration → SSO 2.0. Select your IdP..."}
  ]
}
```

### 5.3 Reranker Training — Relevance Scoring

**Trainer:** `RerankerTrainer` in `reranker_trainer.py`
**Technique:** LoRA (GPU) or full fine-tune via `CrossEncoder.fit()` (CPU)
**Dataset:** `(query, chunk_text, relevance_score)` triples

#### Configuration

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

#### LoRA vs Full Fine-Tune

| Mode     | Activation       | Technique                                         | Adapter Size | When to Use                         |
|----------|------------------|---------------------------------------------------|--------------|-------------------------------------|
| **LoRA** | `use_lora=True`  | PEFT LoRA on `AutoModelForSequenceClassification` | ~5 MB        | Quick adaptation, frequent updates  |
| **Full** | `use_lora=False` | `CrossEncoder.fit()`                              | ~90 MB       | Major domain shift, maximum quality |

The trainer auto-selects the mode: if `use_lora=True` and PEFT + transformers are installed, it uses LoRA; otherwise it
falls back to full fine-tune via `sentence-transformers`.

#### Metrics

| Metric           | Description                                                |
|------------------|------------------------------------------------------------|
| `mrr`            | Mean Reciprocal Rank — position of first relevant document |
| `ndcg_at_10`     | Normalized Discounted Cumulative Gain at 10                |
| `precision_at_5` | Precision of top 5 results                                 |

#### Data Format

```jsonl
["How to configure SSO", "Navigate to Admin → Authentication → SSO...", 1.0]
["How to configure SSO", "Today's lunch menu: pizza", 0.0]
["What is the SLA", "Our SLA guarantees 99.9% uptime...", 0.85]
```

---

## 6. Data Pipeline

### 6.1 HITL Feedback → Training Dataset

The `DataProcessor` reads HITL feedback logs and produces training datasets for all three model types in a single pass.

```python
from proxy.app.model_evolution.data_processor import DataProcessor

processor = DataProcessor(hitl_log_path="logs/hitl.jsonl")
dataset = processor.export_training_dataset(output_dir="data/training")

# dataset.slm_data       → [{query, intent}, ...]
# dataset.llm_data       → [{instruction, input, output}, ...]
# dataset.reranker_data  → [{query, chunk, relevance}, ...]
```

### 6.2 Train/Val/Test Split

```python
train, val, test = processor.split_train_val_test(
    data=dataset.slm_data,
    train_ratio=0.8,
    val_ratio=0.1,
    test_ratio=0.1,
    seed=42,
)
```

### 6.3 Format-Specific Output

The processor provides format helpers for each trainer:

```python
# SLM: flat text+label format
slm_formatted = processor.format_for_slm(train)

# LLM: OpenAI-compatible messages format
llm_formatted = processor.format_for_llm(train)

# Reranker: already in tuple format from export
```

### 6.4 HITL Log Format

Each line in `logs/hitl.jsonl` is a JSON object with these keys:

| Key                           | Type    | Required For       | Description                                          |
|-------------------------------|---------|--------------------|------------------------------------------------------|
| `query`                       | `str`   | SLM, LLM, Reranker | User's original query                                |
| `answer` / `response`         | `str`   | LLM                | Original generated answer                            |
| `correction`                  | `str`   | LLM                | Expert-corrected answer (target for training)        |
| `intent` / `predicted_intent` | `str`   | SLM                | Corrected intent label                               |
| `relevance` / `score`         | `float` | Reranker           | Relevance score (0.0-1.0)                            |
| `chunks` / `sources`          | `list`  | Reranker           | Retrieved chunks with `{text, ...}` or string values |

### 6.5 Output Files

After `export_training_dataset()` runs:

```
data/training/
├── slm_intent.jsonl        # SLM training pairs
├── llm_instruction.jsonl   # LLM instruction-tuning pairs
└── reranker_pairs.jsonl    # Reranker (query, chunk, score) triples
```

---

## 7. Experiment Tracking

### 7.1 ExperimentTracker

Wraps MLflow with transparent local fallback:

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

### 7.2 Run Lifecycle

```python
run = tracker.start_run(run_name="slm-prod-run-1")
tracker.log_params({"lora_r": 16, "epochs": 5, "batch_size": 16})
tracker.log_metrics({"accuracy": 0.92, "weighted_f1": 0.89}, step=1)
tracker.log_artifact("./models/adapter/config.json")
tracker.end_run()
```

When MLflow is unavailable, runs are persisted as JSON files:

```
data/experiments/
└── intent-classifier-v2/
    └── a1b2c3d4.json
```

### 7.3 Prometheus Metrics

Model evolution exposes these Prometheus metrics for monitoring:

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

## 8. Artifact Storage

### 8.1 ArtifactStore

Manages model artifacts in MinIO/S3 or local filesystem:

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

### 8.2 Operations

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

### 8.3 Storage Layout

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

**Local filesystem (fallback):**

```
data/artifacts/rag-artifacts/
└── models/
    └── slm_intent/
        └── ...
```

---

## 9. EvalGate

### 9.1 Concept

EvalGate is a CI/CD quality gate that decides whether a newly trained model can be promoted. It evaluates metrics
against configurable thresholds, detects baseline regression, and produces a **PASS / WARN / FAIL** decision.

### 9.2 Threshold Configuration

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

### 9.3 Comparisons

| Operator | Meaning               | Example                     |
|----------|-----------------------|-----------------------------|
| `gte`    | greater than or equal | `accuracy >= 0.90`          |
| `gt`     | greater than          | `bleu_4 > 0.15`             |
| `lte`    | less than or equal    | `eval_loss <= 1.0`          |
| `lt`     | less than             | `hallucination_rate < 0.05` |

### 9.4 Severity Levels

| Severity | On Failure              | Blocks Promotion?                             |
|----------|-------------------------|-----------------------------------------------|
| `fail`   | Adds to `failures` list | **Yes** — gate returns FAIL                   |
| `warn`   | Adds to `warnings` list | **No** — gate returns WARN but still passable |

### 9.5 Baseline Comparison

When `require_baseline_comparison=True` and baseline metrics are provided:

1. Delta metrics are computed: `delta = current - baseline`
2. For each FAIL-threshold metric, a negative delta exceeding `baseline_regression_tolerance` triggers a WARN
3. If no baseline is provided, a warning is added: `"No baseline metrics provided for comparison"`

### 9.6 NLI Integration

EvalGate can incorporate NLI-based answer grounding metrics:

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

This appends `nli_entailment_rate`, `nli_contradiction_rate`, `nli_neutral_rate`, and `nli_overall_score` to the metrics
dict before evaluation. See [§15 — NLI Evaluator](#15-nli-evaluator) for details.

### 9.7 Report Format

Call `EvalGate.format_report(result)` for a human-readable report:

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

## 10. Model Registry

### 10.1 Concept

The `ModelRegistry` manages model versions with a promotion lifecycle. State is persisted as a JSON file, making it
fully air-gapped compatible.

### 10.2 Version Lifecycle

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

### 10.3 States

| Status         | Meaning                                    | Can Serve Traffic?   |
|----------------|--------------------------------------------|----------------------|
| **staging**    | Newly trained, not yet evaluated           | No                   |
| **canary**     | Passed EvalGate, receiving partial traffic | Yes (configurable %) |
| **production** | Full traffic, current baseline             | Yes (100%)           |
| **archived**   | Replaced by newer version                  | No                   |

### 10.4 Registry API

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

### 10.5 JSON Persistence

The registry file (`data/model_registry.json`) is atomic — writes go to a `.tmp` file first, then atomically replaced
with `os.replace()`:

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

## 11. Canary Deployment

### 11.1 Concept

The `CanaryController` routes a configurable percentage of traffic to a new model version while the majority continues
to the stable baseline. If metrics degrade, it automatically rolls back to 100% baseline.

### 11.2 Rollout Phases

| Phase      | Traffic % | Description                   |
|------------|-----------|-------------------------------|
| `IDLE`     | 0%        | Canary not active             |
| `RAMP_5`   | <5%       | Initial smoke test            |
| `RAMP_25`  | 5-24%     | Early validation              |
| `RAMP_50`  | 25-49%    | Mid-scale                     |
| `RAMP_75`  | 50-74%    | Pre-production                |
| `FULL`     | 75-100%   | Canary becomes stable         |
| `ROLLBACK` | 0%        | Auto-triggered on degradation |

### 11.3 Configuration

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

### 11.4 Request Routing

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

### 11.5 Automatic Rollback

The controller evaluates metrics on each request:

1. Checks if minimum samples (`min_samples`) reached
2. Computes current error rate from recorded results
3. Compares against each threshold in `rollback_thresholds`
4. If any threshold is breached → `rollback()` → sets traffic to 0% canary, starts cooldown
5. Returns True from `should_rollback()` while degradation persists

```python
if controller.should_rollback("slm"):
    controller.rollback("slm")
    # Canary traffic drops to 0%; cooldown period begins
```

### 11.6 Status Check

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

## 12. Hot-Reload

### 12.1 Concept

The `AdapterManager` enables loading and unloading model adapters without restarting the proxy. New adapter versions are
detected via filesystem polling or MLflow registry changes, and hot-swapped with zero-downtime draining of in-flight
requests.

### 12.2 Adapter Lifecycle States

```
UNLOADED ──→ LOADING ──→ ACTIVE ──→ DRAINING ──→ RETIRING ──→ UNLOADED
    ↑                       │            │             │            │
    └───────────────────────┴────────────┴─────────────┴────────────┘
                            ERROR ←──────┘
```

Valid transitions:

| From     | Valid Target States              |
|----------|----------------------------------|
| UNLOADED | LOADING, ERROR                   |
| LOADING  | ACTIVE, ERROR                    |
| ACTIVE   | DRAINING, ERROR                  |
| DRAINING | RETIRING, ACTIVE, LOADING, ERROR |
| RETIRING | UNLOADED, ERROR                  |
| ERROR    | UNLOADED, LOADING, ACTIVE        |

### 12.3 Registration and Loading

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

### 12.4 Hot-Reload Workflow

```python
# Detect new version and hot-swap atomically
manager.hot_reload(
    name="slm_intent",
    new_path="./models/slm_v4/adapter",
    new_version="v4",
)
```

What happens internally:

1. Old adapter transitions to DRAINING
2. New adapter loads from disk → transitions to ACTIVE
3. If new adapter fails to load, old adapter transitions back to ACTIVE (no downtime)
4. Old adapter waits for in-flight requests to drain (polling at 0.5s intervals, 30s timeout)
5. After all requests complete, old adapter transitions: RETIRING → UNLOADED

### 12.5 Filesystem Watching

Enable automatic detection of new adapter versions:

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

When a new version appears, the watcher triggers `hot_reload()` automatically.

### 12.6 SIGHUP Handling

```python
from proxy.app.model_evolution.adapter_manager import setup_signal_handlers

setup_signal_handlers()  # Registers SIGHUP → manager.reload_all()
```

Sending SIGHUP to the proxy process triggers a full re-scan of all registered adapters:

```bash
kill -HUP $(pgrep -f "uvicorn main:app")
```

### 12.7 Drain-and-Retire

The `_drain_and_retire()` method ensures zero-downtime swaps:

1. Polls `adapter.request_count` every 0.5 seconds
2. When count reaches 0 → retire immediately
3. After 30 seconds (60 attempts) → force retirement with warning

---

## 13. Admin API Reference

All endpoints require **admin role** (`Role.ADMIN`) via JWT authentication.

### 13.1 Trigger Training

**`POST /v1/admin/models/train`**

| Parameter       | Type    | Default              | Description                                                                             |
|-----------------|---------|----------------------|-----------------------------------------------------------------------------------------|
| `trainer_type`  | `str`   | (required)           | One of: `"slm"`, `"llm"`, `"reranker"`                                                  |
| `base_model`    | `str`   | `""`                 | HuggingFace model name or path (e.g., `"bert-base-uncased"`, `"meta-llama/Llama-3-8B"`) |
| `profile`       | `str`   | `"dev"`              | Environment profile: `"dev"`, `"prod"`, `"ci"`                                          |
| `data_dir`      | `str`   | `"./data/training/"` | Directory containing training data files                                                |
| `epochs`        | `int`   | `3`                  | Number of training epochs                                                               |
| `batch_size`    | `int`   | `8`                  | Per-device batch size                                                                   |
| `learning_rate` | `float` | `2e-4`               | Learning rate                                                                           |
| `use_lora`      | `bool`  | `true`               | Enable LoRA adapter training                                                            |

**Request:**

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

**Response (202 accepted):**

```json
{
  "job_id": "abc12345-6789-4abc-def0-1234567890ab",
  "trainer_type": "slm",
  "status": "running",
  "message": "Training job abc12345-6789-4abc-def0-1234567890ab started"
}
```

Training runs asynchronously. On completion, the model is auto-registered in the model registry with status `staging`.

---

### 13.2 Check Job Status

**`GET /v1/admin/models/status/{job_id}`**

**Response:**

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

Possible status values: `queued`, `running`, `completed`, `failed`.

---

### 13.3 List Models

**`GET /v1/admin/models`**

**Response:**

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

### 13.4 Promote Model

**`POST /v1/admin/models/promote`**

| Parameter    | Type  | Description                      |
|--------------|-------|----------------------------------|
| `model_name` | `str` | Model identifier (e.g., `"slm"`) |
| `version`    | `str` | Version to promote               |

**Request:**

```json
{
  "model_name": "slm",
  "version": "3"
}
```

**Response:**

```json
{
  "model_name": "slm",
  "version": "3",
  "previous_status": "staging",
  "new_status": "canary"
}
```

Status transitions:

- `staging` → `canary` (first promote)
- `canary` → `production` (second promote, archives previous production)
- `production` → `production` (no-op)
- `archived` → `archived` (no-op)

---

### 13.5 Rollback Model

**`POST /v1/admin/models/rollback`**

| Parameter    | Type  | Description      |
|--------------|-------|------------------|
| `model_name` | `str` | Model identifier |

**Request:**

```json
{
  "model_name": "slm"
}
```

**Response:**

```json
{
  "model_name": "slm",
  "version": "2",
  "previous_version": "3",
  "status": "production"
}
```

Finds the current production version, archives it, and restores the most recent archived version to production.

---

### 13.6 Evaluate Model

**`POST /v1/admin/models/evaluate`**

| Parameter    | Type   | Default     | Description                 |
|--------------|--------|-------------|-----------------------------|
| `model_name` | `str`  | (required)  | Model identifier            |
| `version`    | `str`  | `"unknown"` | Version to evaluate         |
| `metrics`    | `dict` | (required)  | Metric name → value mapping |

Default thresholds applied:

| Metric         | Threshold | Comparison | Severity |
|----------------|-----------|------------|----------|
| `accuracy`     | 0.90      | `gte`      | `fail`   |
| `weighted_f1`  | 0.85      | `gte`      | `fail`   |
| `mrr`          | 0.70      | `gte`      | `fail`   |
| `recall_at_10` | 0.65      | `gte`      | `fail`   |
| `rouge_l_f1`   | 0.35      | `gte`      | `fail`   |
| `eval_loss`    | 1.0       | `lte`      | `warn`   |

**Request:**

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

**Response:**

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

If a production version exists for the model, its metrics are used as baseline for regression detection. Metrics are
also saved to the registry via `update_metrics()`.

---

### 13.7 Canary Split

**`POST /v1/admin/models/canary/split`**

| Parameter       | Type    | Description                                |
|-----------------|---------|--------------------------------------------|
| `model_name`    | `str`   | Model identifier                           |
| `traffic_split` | `float` | Fraction of traffic to canary (0.0 to 1.0) |

**Request:**

```json
{
  "model_name": "slm",
  "traffic_split": 0.25
}
```

**Response:**

```json
{
  "model_name": "slm",
  "traffic_split": 0.25,
  "status": "ramp"
}
```

---

### 13.8 Canary Status

**`GET /v1/admin/models/canary/status`**

**Response:**

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

## 14. CI/CD Integration

### 14.1 GitHub Actions Workflow

Example `.github/workflows/model-evolution.yml`:

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

### 14.2 Promotion Decision Matrix

| EvalGate Result | Action                                    | Manual Step Required?     |
|-----------------|-------------------------------------------|---------------------------|
| **PASS**        | Auto-promote to canary at 5%              | No                        |
| **WARN**        | Auto-promote to canary at 5% (with alert) | No                        |
| **FAIL**        | Block promotion                           | Yes — investigate metrics |

---

## 15. NLI Evaluator

### 15.1 Concept

The NLI (Natural Language Inference) evaluator checks whether generated answers are grounded in their source context by
decomposing answers into claims and evaluating each claim for entailment, contradiction, or neutrality against the
context.

### 15.2 Model

**Primary:** `MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli` — a DeBERTa-v3 model fine-tuned on MNLI, FEVER, and ANLI
datasets. Classifies each (context, claim) pair into:

- **Entailment** — the claim logically follows from the context
- **Contradiction** — the claim contradicts the context
- **Neutral** — the claim is neither entailed nor contradicted

### 15.3 NLI Metrics

| Metric                   | Formula                                                    | Range                     |
|--------------------------|------------------------------------------------------------|---------------------------|
| `nli_entailment_rate`    | entailed_claims / total_claims                             | [0, 1] — higher is better |
| `nli_contradiction_rate` | contradicted_claims / total_claims                         | [0, 1] — lower is better  |
| `nli_neutral_rate`       | neutral_claims / total_claims                              | [0, 1]                    |
| `nli_overall_score`      | max(0, min(1, entailment_rate − 0.5 × contradiction_rate)) | [0, 1] — higher is better |

### 15.4 Usage

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

### 15.5 Lightweight Fallback

When the DeBERTa-v3 model is unavailable (air-gapped or not installed), the evaluator falls back to a **token-overlap
proxy**:

1. Tokenizes claim and context into word sets
2. Computes cosine similarity from token overlap
3. Computes claim coverage (fraction of claim tokens appearing in context)
4. Combines similarity and coverage → classifies as entailment / contradiction / neutral

**Enable lightweight mode:**

```python
evaluate_nli(answer, context, use_real_nli=False)
```

### 15.6 Claim Decomposition

Answers are split into individual claims using sentence boundaries (`.`, `!`, `?`, `\n`, `;`). Claims shorter than 10
characters are filtered out. Bullet-point markers (`-`, `*`, `•`) are stripped.

---

## 16. Environment Profiles Reference

### 16.1 DEV Profile

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

### 16.2 CI Profile

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

### 16.3 PROD Profile

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

## 17. Troubleshooting

### 17.1 Training fails with "transformers and peft are required"

**Symptom:** SLM or Reranker training returns error about missing `transformers` or `peft`.

**Solution:**

```bash
pip install transformers peft accelerate
```

### 17.2 LLM falls back to mock training

**Symptom:** Log says `"Running LLM mock training (CPU profile)"` even when GPU is available.

**Causes & Solutions:**

1. **Wrong profile:** Ensure `"profile": "prod"` in the train request. DEV and CI profiles always use CPU/mock.
2. **Missing GPU libraries:**
   ```bash
   pip install bitsandbytes peft torch transformers accelerate
   ```
3. **CUDA not available:** Check `python -c "import torch; print(torch.cuda.is_available())"`

### 17.3 OOM during LLM QLoRA training

**Symptom:** `torch.cuda.OutOfMemoryError` during LLM training.

**Solutions:**

- Reduce `batch_size` to 1 or 2
- Set `gradient_accumulation_steps` higher (e.g., 8) to maintain effective batch size
- Reduce `max_seq_length` to 1024 or 512
- Use a smaller base model (7B instead of 13B)
- Enable CPU offloading: set `device_map="auto"` (already default)

### 17.4 Registry returns "Model not found"

**Symptom:** `KeyError: "Model 'slm' not found in registry"`

**Solution:** The model must be registered first. After a successful training job, models are auto-registered. For
manual registration:

```python
from proxy.app.model_evolution.model_registry import ModelRegistry
registry = ModelRegistry()
registry.register("slm", "./path/to/adapter", {"accuracy": 0.92})
```

### 17.5 EvalGate always returns WARN — "No baseline metrics"

**Symptom:** Every evaluation shows warning `"No baseline metrics provided for comparison"`.

**Solution:** This is expected for the first model version or when no production version exists. It is not an error —
the gate still evaluates thresholds. To suppress:

- Promote a model to production first
- Or set `require_baseline_comparison=False` in `EvalGateConfig`

### 17.6 Canary rollback triggers immediately

**Symptom:** Canary rolls back as soon as traffic is routed, even without real errors.

**Causes:**

- `min_samples` set too high → not enough data, but `error_rate` appears inflated early
- `rollback_thresholds` too strict (e.g., `error_rate > 0.01`)

**Solution:** Start with generous thresholds and tighten gradually:

```python
rollback_thresholds={
    "error_rate": (0.10, "gt"),      # Start at 10%
}
```

### 17.7 Hot-reload watcher not detecting new files

**Symptom:** New adapter files placed in the watch directory are not picked up.

**Checks:**

1. Is the watcher enabled? `manager.enable_watcher("name", "/path/to/adapters")`
2. Do files match the detection patterns? Default: `adapter_config.json`, `*.safetensors`, `*.bin`, `*.pt`, `*.ckpt`,
   `lora_weights.*`, `pytorch_model.*`
3. Did you call `watch_directory()` for file-level watching (vs. subdirectory-level)?
4. Call `watcher.force_rescan()` to clear the cache and re-scan immediately.

### 17.8 Adapter stuck in LOADING or ERROR state

**Symptom:** `adapter.state` is `LOADING` or `ERROR` and won't transition to `ACTIVE`.

**Solution:**

- For LOADING: check load callback returns `True` and doesn't throw exceptions
- For ERROR: unload the adapter first (`manager.unload_adapter("name")`) which transitions ERROR → UNLOADED, then try
  loading again
- Check Prometheus: `rag_adapter_error_count{name="..."}` for error history

### 17.9 Model registry file corrupted

**Symptom:** `json.JSONDecodeError` when loading registry.

**Solution:** The registry uses atomic writes (write to `.tmp`, then `os.replace`). If the main file is corrupted, check
for a `.tmp` file:

```bash
ls -la data/model_registry.json*
```

If both are corrupted, delete them and re-register models from artifact store.

### 17.10 NLI evaluator uses lightweight fallback

**Symptom:** Log says `"NLI model loading skipped: transformers not installed"` or `"NLI model load failed"`.

**Solutions:**

1. Install dependencies: `pip install transformers torch`
2. Download the NLI model for air-gapped use: store `MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli` locally and set
   `local_files_only=True` (already default)
3. If lightweight proxy is acceptable (no GPU, air-gapped), no action needed — it's a conscious fallback

### 17.11 Training succeeds but adapter doesn't change model behavior

**Possible causes:**

- Adapter loaded into wrong base model — check `trainer_config.json` for `base_model` field
- Canary split at 0% — all traffic still goes to stable
- Adapter not promoted through lifecycle — stuck in `staging` status
- Wrong target modules for LoRA — check `_resolve_target_modules()` matches your model architecture

**Verification:**

```bash
# Check registry
curl http://localhost:8080/v1/admin/models -H "Authorization: Bearer $JWT_TOKEN"

# Check canary status
curl http://localhost:8080/v1/admin/models/canary/status -H "Authorization: Bearer $JWT_TOKEN"
```

---

## Configuration Reference

All model evolution configuration via environment variables:

| Variable                  | Default                      | Description                            |
|---------------------------|------------------------------|----------------------------------------|
| `MODEL_EVOLUTION_ENABLED` | `false`                      | Master switch for the entire subsystem |
| `MLFLOW_TRACKING_URI`     | `http://localhost:5000`      | MLflow tracking server URL             |
| `MLFLOW_EXPERIMENT_NAME`  | `rag-system`                 | MLflow experiment name                 |
| `MLFLOW_ARTIFACT_ROOT`    | `s3://rag-artifacts`         | Artifact storage root                  |
| `MINIO_ENDPOINT`          | `localhost:9000`             | MinIO/S3 endpoint                      |
| `MINIO_ACCESS_KEY`        | `minioadmin`                 | MinIO access key                       |
| `MINIO_SECRET_KEY`        | `minioadmin`                 | MinIO secret key                       |
| `MINIO_BUCKET`            | `rag-artifacts`              | MinIO bucket name                      |
| `MINIO_SECURE`            | `false`                      | Use HTTPS for MinIO                    |
| `MODEL_REGISTRY_PATH`     | `./data/model_registry.json` | Registry JSON file path                |

---

## Exception Hierarchy

```
ModelEvolutionError (base)
├── TrainingError       — data prep, GPU OOM, checkpoint failures
├── EvalGateError       — threshold not met, baseline regression
├── AdapterError        — load failure, version mismatch, memory error
└── CanaryError         — rollback failure, metric unavailability
```

---

## Dependencies

Required for full functionality:

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

**Related Guides:**

- [RAG Maturity Assessment](rag-maturity-assessment.md) — where Model Evolution fits in the RAG capability model
- [Best Practices Checklist](best-practices-checklist.md) — production readiness dimensions
- [Access Control & RBAC](access-control-rbac.md) — admin role required for all model evolution endpoints
- [Troubleshooting](troubleshooting.md) — general system troubleshooting
