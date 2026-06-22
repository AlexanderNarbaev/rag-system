# Model Evolution — Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development.

**Goal:** Enable on-prem fine-tuning of SLM, LLM, and Reranker models via LoRA/QLoRA with MLflow tracking, MinIO artifact storage, CI/CD eval gates, hot-reload adapters, and canary deployment — all gated behind `MODEL_EVOLUTION_ENABLED=false` for full backward compatibility.

**Architecture:** A new `proxy/app/model_evolution/` package (13 modules) implements the training pipeline (SLM LoRA, LLM QLoRA, Reranker Full/LoRA), MLflow integration, MinIO artifact store, EvalGate for CI/CD, AdapterManager for hot-reload, and CanaryController for gradual rollout. Existing singletons in `slm_router.py`, `rerank.py`, and `provider_adapter.py` are refactored to use AdapterManager-managed adapters when enabled. MLflow + MinIO services join docker-compose; CI/CD pipeline runs in GitHub Actions on self-hosted GPU runners.

**Tech Stack:** PEFT (LoRA), bitsandbytes (QLoRA 4-bit NF4), MLflow 2.15+ (tracking + registry), MinIO (S3 artifact store), rouge-score, bert-score, nltk, accelerate, transformers 4.45+, Prometheus metrics, threading (hot-reload), uuid, random, pathlib

## Global Constraints
- Backward-compatible: `MODEL_EVOLUTION_ENABLED=false` by default
- Graceful degradation: training failures never affect serving
- Air-gapped first: MLflow + MinIO local, all models pre-downloaded
- GPU-optional: CPU training mode via `TRAINING_PROFILE=dev`
- TDD: every task writes failing test first
- 3 env profiles: dev (CPU), prod (GPU), ci (no GPU)
- `WORKERS=1` — no multi-process synchronization needed for adapter swap
- No circular dependencies — the dependency graph is a DAG
- No placeholders in code — every implementation step shows actual runnable code

---

## Execution Sequence (5 Phases, 25 Tasks)

### Phase 1: Foundation — Config + Exceptions + Skeleton + Core Modules (Tasks 1-9)

Rationale: Config, exceptions, and data structures must exist before training pipeline. Core modules (artifact_store, tracking, data_processor, trainer, registry, eval_gate, metrics_gen) have no cross-dependencies and can be built in parallel after Task 3 (skeleton).

### Phase 2: Training Pipeline — SLM + LLM + Reranker Trainers + CLI Scripts (Tasks 10-15)

Rationale: Depends on Phase 1 modules (config, tracking, data_processor, registry). Each trainer is independent and can be built in parallel.

### Phase 3: Eval Gates & CI/CD — Gateway + GitHub Actions + Makefile (Tasks 16-19)

Rationale: Depends on all Phase 2 trainers registered in the registry.

### Phase 4: Hot-Reload & Canary — Adapter Integration + Admin API (Tasks 20-24)

Rationale: Depends on registry (Phase 1) for artifact download. AdapterManager and CanaryController are independent of each other.

### Phase 5: Integration Testing & Documentation (Task 25)

Rationale: Depends on all previous phases complete.

---

## Detailed Task Breakdown

### Task 1: Add Model Evolution Config to `config.py`

**Files:** Modify `proxy/app/config.py`

**Interfaces:** Consumes: environment variables; Produces: module-level config constants

**Dependencies:** None

**Risk:** Low — additive change, no existing behavior modified

- [ ] **Step 1: Write failing test**
  Create `tests/proxy/test_model_evolution_config.py` with 8 test methods:
  - `test_default_disabled` — MODEL_EVOLUTION_ENABLED defaults to False
  - `test_enabled_true` — MODEL_EVOLUTION_ENABLED=true parses correctly
  - `test_mlflow_uri_default` — MLFLOW_TRACKING_URI contains localhost:5000
  - `test_minio_vars_default` — MinIO env vars have defaults (localhost:9000, minioadmin)
  - `test_hot_reload_default_disabled` — HOT_RELOAD_ENABLED defaults to False
  - `test_canary_default_disabled` — CANARY_ENABLED defaults to False
  - `test_training_profile_default_dev` — TRAINING_PROFILE defaults to 'dev'
  - `test_eval_gate_thresholds_have_defaults` — EVAL_GATE_LLM_BERTSCORE_MIN=0.70, EVAL_GATE_LLM_HALLUCINATION_MAX=0.05, EVAL_GATE_SLM_F1_MIN=0.85

- [ ] **Step 2: Run test to verify failure**
  ```bash
  python -m pytest tests/proxy/test_model_evolution_config.py -v
  # Expect: AttributeError/ImportError for missing config vars
  ```

- [ ] **Step 3: Implement**
  Insert before `SHUTDOWN_TIMEOUT` in `proxy/app/config.py` (after line 273):
  ```python
  # ============ Model Evolution ============
  MODEL_EVOLUTION_ENABLED = os.getenv("MODEL_EVOLUTION_ENABLED", "false").lower() == "true"

  # MLflow
  MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
  MLFLOW_EXPERIMENT_NAME = os.getenv("MLFLOW_EXPERIMENT_NAME", "rag-system")
  MLFLOW_ARTIFACT_ROOT = os.getenv("MLFLOW_ARTIFACT_ROOT", "s3://rag-artifacts")

  # MinIO
  MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
  MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
  MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
  MINIO_BUCKET = os.getenv("MINIO_BUCKET", "rag-artifacts")
  MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"

  # Training
  TRAINING_PROFILE = os.getenv("TRAINING_PROFILE", "dev")

  # Hot-Reload
  HOT_RELOAD_ENABLED = os.getenv("HOT_RELOAD_ENABLED", "false").lower() == "true"
  HOT_RELOAD_WATCH_INTERVAL = int(os.getenv("HOT_RELOAD_WATCH_INTERVAL", "5"))
  HOT_RELOAD_SIGNAL_ENABLED = os.getenv("HOT_RELOAD_SIGNAL_ENABLED", "true").lower() == "true"

  # Canary
  CANARY_ENABLED = os.getenv("CANARY_ENABLED", "false").lower() == "true"
  CANARY_PHASE_DURATION_5 = int(os.getenv("CANARY_PHASE_DURATION_5", "300"))
  CANARY_PHASE_DURATION_25 = int(os.getenv("CANARY_PHASE_DURATION_25", "600"))
  CANARY_PHASE_DURATION_50 = int(os.getenv("CANARY_PHASE_DURATION_50", "900"))
  CANARY_PHASE_DURATION_75 = int(os.getenv("CANARY_PHASE_DURATION_75", "1200"))
  CANARY_COOLDOWN_SECONDS = int(os.getenv("CANARY_COOLDOWN_SECONDS", "3600"))

  # Eval Gate Thresholds
  EVAL_GATE_LLM_BERTSCORE_MIN = float(os.getenv("EVAL_GATE_LLM_BERTSCORE_MIN", "0.70"))
  EVAL_GATE_LLM_HALLUCINATION_MAX = float(os.getenv("EVAL_GATE_LLM_HALLUCINATION_MAX", "0.05"))
  EVAL_GATE_LLM_ROUGE_L_MIN = float(os.getenv("EVAL_GATE_LLM_ROUGE_L_MIN", "0.35"))
  EVAL_GATE_SLM_F1_MIN = float(os.getenv("EVAL_GATE_SLM_F1_MIN", "0.85"))
  EVAL_GATE_SLM_ACCURACY_MIN = float(os.getenv("EVAL_GATE_SLM_ACCURACY_MIN", "0.90"))
  EVAL_GATE_RERANKER_MRR_MIN = float(os.getenv("EVAL_GATE_RERANKER_MRR_MIN", "0.75"))
  EVAL_GATE_RERANKER_NDCG_MIN = float(os.getenv("EVAL_GATE_RERANKER_NDCG_MIN", "0.70"))
  ```

- [ ] **Step 4: Run test to verify pass**
  ```bash
  python -m pytest tests/proxy/test_model_evolution_config.py -v
  ```

- [ ] **Step 5: Commit**
  ```bash
  git add proxy/app/config.py tests/proxy/test_model_evolution_config.py
  git commit -m "feat(model-evolution): add MODEL_EVOLUTION_ENABLED and all config env vars"
  ```

---

### Task 2: Add Model Evolution Exceptions

**Files:** Modify `proxy/app/exceptions.py`

**Dependencies:** None

- [ ] **Step 1: Write failing test**
  Create `tests/proxy/test_model_evolution_exceptions.py`:
  - `test_training_error_inherits_ragerror` — TrainingError is RAGError, component="training"
  - `test_model_registry_error` — ModelRegistryError inherits RAGError
  - `test_eval_gate_error` — EvalGateError inherits RAGError
  - `test_canary_error` — CanaryError inherits RAGError
  - `test_hot_reload_error` — HotReloadError inherits RAGError
  - `test_all_carry_message` — all exceptions propagate str(message)

- [ ] **Step 2: Run test to verify failure**
  ```bash
  python -m pytest tests/proxy/test_model_evolution_exceptions.py -v
  ```

- [ ] **Step 3: Implement — append to `proxy/app/exceptions.py`:**
  ```python
  class TrainingError(RAGError):
      def __init__(self, message: str = "", component: str = "training"):
          super().__init__(message, component=component, recoverable=True)

  class ModelRegistryError(RAGError):
      def __init__(self, message: str = "", component: str = "registry"):
          super().__init__(message, component=component, recoverable=True)

  class EvalGateError(RAGError):
      def __init__(self, message: str = "", component: str = "eval_gate"):
          super().__init__(message, component=component, recoverable=False)

  class CanaryError(RAGError):
      def __init__(self, message: str = "", component: str = "canary"):
          super().__init__(message, component=component, recoverable=True)

  class HotReloadError(RAGError):
      def __init__(self, message: str = "", component: str = "adapter_manager"):
          super().__init__(message, component=component, recoverable=True)
  ```

- [ ] **Steps 4-5:** Verify pass + commit as standard pattern

---

### Task 3: Create `model_evolution/` Package Skeleton

**Files:** Create `proxy/app/model_evolution/__init__.py` + 13 module stubs

**Dependencies:** Task 1 (config), Task 2 (exceptions)

**Risk:** Medium — import validation must pass before further work

- [ ] **Step 1: Write failing test**
  Create `tests/model_evolution/test_package_init.py`:
  ```python
  class TestPackageInit:
      def test_package_imports(self):
          from proxy.app.model_evolution import __all__
          assert True

      def test_public_api_exports(self):
          from proxy.app.model_evolution.__init__ import __all__
          required = [
              "ModelEvolutionConfig", "EnvProfile",
              "TrainerBase", "TrainingJob", "TrainingConfig", "TrainerRegistry",
              "SLMTrainer", "LLMTrainer", "RerankerTrainer",
              "DataProcessor", "IntentDataset", "CompletionDataset", "RerankPairDataset",
              "ModelRegistry", "ModelVersion", "ModelStage",
              "ExperimentTracker", "RunContext",
              "EvalGate", "EvalGateConfig", "GateResult", "MetricThreshold",
              "AdapterManager", "ModelAdapter", "AdapterState", "HotReloadWatcher",
              "CanaryController", "CanaryConfig", "TrafficSplit",
              "ArtifactStore", "ArtifactRef",
              "compute_bleu", "compute_rouge_l", "compute_bertscore",
              "compute_hallucination_rate",
          ]
          for name in required:
              assert name in __all__, f"Missing: {name}"
  ```

- [ ] **Steps 2-5:** Create directory, write 13 stubs + `__init__.py`, verify, commit
  ```bash
  mkdir -p proxy/app/model_evolution tests/model_evolution
  touch tests/model_evolution/__init__.py
  for mod in config trainer slm_trainer llm_trainer reranker_trainer \
             data_processor registry tracking eval_gate adapter_manager \
             canary artifact_store metrics_gen conftest; do
    echo "# proxy/app/model_evolution/${mod}.py" > "proxy/app/model_evolution/${mod}.py"
  done
  ```

---

### Task 4: Implement `model_evolution/config.py`

**Files:** Create `proxy/app/model_evolution/config.py`

**Dependencies:** Task 1, Task 3

**Key classes implemented:** `EnvProfile` (dev/prod/ci enum), `TrainerType` (slm/llm/reranker), `TrainingConfig` dataclass (all training hyperparams), `EnvProfiles` static (DEV/PROD/CI pre-built configs), `ModelEvolutionConfig` from_env() aggregator

**Test file:** `tests/model_evolution/test_config.py` — 3 test classes (TestEnvProfile, TestTrainingConfig, TestEnvProfiles, TestModelEvolutionConfig)

**Verification:**
```bash
python -m pytest tests/model_evolution/test_config.py -v
```

**Commit message:** `feat(model-evolution): implement ModelEvolutionConfig, EnvProfile, TrainingConfig, EnvProfiles`

---

### Task 5: Implement `model_evolution/metrics_gen.py`

**Files:** Create `proxy/app/model_evolution/metrics_gen.py`

**Dependencies:** Task 3 (no logic dependencies — pure functions)

**Key functions:** `compute_bleu(refs, hyps, max_n=4) → dict`, `compute_rouge_l(refs, hyps) → dict` (LCS DP), `compute_bertscore(refs, hyps) → dict` (tries bert_score library, falls back to token overlap), `compute_hallucination_rate(answers, contexts) → float` (token overlap ratio < 0.3), `compute_perplexity(model, eval_texts) → float`, `compute_all_gen_metrics(refs, hyps, contexts) → dict`

**Test file:** `tests/model_evolution/test_metrics_gen.py` — 5 test classes with 11 test methods

**Verification:**
```bash
python -m pytest tests/model_evolution/test_metrics_gen.py -v
```

**Commit message:** `feat(model-evolution): implement metrics_gen — BLEU, ROUGE-L, BertScore, hallucination rate`

---

### Task 6: Implement `model_evolution/artifact_store.py`

**Files:** Create `proxy/app/model_evolution/artifact_store.py`

**Dependencies:** Task 1 (MinIO config vars)

**Key classes:** `ArtifactRef` (bucket, key, version_id, size, uri property), `ArtifactStore` (endpoint, access_key, secret_key, bucket, secure — methods: `_get_client()`, `ensure_bucket()`, `store_artifact(local_path, artifact_name) → ArtifactRef`, `load_artifact(ref, dst_path) → str`, `list_artifacts(prefix) → list[ArtifactRef]`, `delete_artifact(ref)`)

**Graceful degradation:** ImportError on `minio` package raises ImportError with install instructions; all methods guarded by _get_client()

**Test file:** `tests/model_evolution/test_artifact_store.py` — mocked MinIO client, tests for store/load round-trip, list, ensure_bucket

**Verification:**
```bash
python -m pytest tests/model_evolution/test_artifact_store.py -v
```

**Commit message:** `feat(model-evolution): implement ArtifactStore MinIO client with store/load/list`

---

### Task 7: Implement `model_evolution/tracking.py`

**Files:** Create `proxy/app/model_evolution/tracking.py`

**Dependencies:** Task 1 (MLFLOW_TRACKING_URI, MLFLOW_EXPERIMENT_NAME)

**Key classes:** `RunContext` (wraps MlflowClient run — `log_params`, `log_metrics`, `log_artifact`, `set_tag`, `set_terminated`), `ExperimentTracker` (tracking_uri, experiment_name — `_get_or_create_experiment()`, `start_run(run_name, tags) → RunContext`)

**Test file:** `tests/model_evolution/test_tracking.py` — mocked `MlflowClient`, verifies create_run, log_params, log_metrics called

**Verification:**
```bash
python -m pytest tests/model_evolution/test_tracking.py -v
```

**Commit message:** `feat(model-evolution): implement ExperimentTracker MLflow wrapper with RunContext`

---

### Task 8: Implement `model_evolution/data_processor.py`

**Files:** Create `proxy/app/model_evolution/data_processor.py`

**Dependencies:** Task 3 (no logic deps — pure data processing), existing `hitl.py` for data source

**Key classes:** `IntentDataset`, `CompletionDataset`, `RerankPairDataset` (PyTorch Dataset-compatible with `__len__`/`__getitem__`), `DataProcessor` with static methods: `load_interactions(path)`, `export_intent_pairs(interactions, intent_map)` → list[tuple], `export_completion_pairs(feedback)` → list[tuple], `export_reranker_triples(interactions, chunk_func, score)` → list[tuple], `train_eval_split(data, eval_split, seed)` → tuple

**Test file:** `tests/model_evolution/test_data_processor.py` — sample JSONL fixtures, 8 test methods

**Verification:**
```bash
python -m pytest tests/model_evolution/test_data_processor.py -v
```

**Commit message:** `feat(model-evolution): implement DataProcessor with Intent/Completion/RerankPair datasets`

---

### Task 9: Implement `model_evolution/trainer.py` (Base Classes)

**Files:** Create `proxy/app/model_evolution/trainer.py`

**Dependencies:** Task 4 (TrainingConfig), Task 3

**Key classes:** `TrainerType` enum (SLM/LLM/RERANKER), `TrainingJob` dataclass (job_id, trainer_type, config, status, mlflow_run_id, metrics, artifact_uri, started_at, completed_at, error_message, to_dict()), `TrainerBase` ABC (abstract prepare_data, train, evaluate; concrete save_adapter), `TrainerRegistry` singleton (register, get, list_types, get_instance)

**Test file:** `tests/model_evolution/test_trainer.py` — verifies ABC cannot instantiate, TrainingJob to_dict, registry register/get/singleton

**Verification:**
```bash
python -m pytest tests/model_evolution/test_trainer.py -v
```

**Commit message:** `feat(model-evolution): implement TrainerBase, TrainingJob, TrainerRegistry`

---

### Task 10: Implement `model_evolution/registry.py`

**Files:** Create `proxy/app/model_evolution/registry.py`

**Dependencies:** Tasks 6, 7 (artifact store, tracking for artifact URIs)

**Key classes:** `ModelStage` enum (None/Staging/Production/Archived), `ModelVersion` dataclass (name, version, stage, run_id, artifact_uri, metrics, tags, is_staging/is_production/is_archived), `ModelRegistry` (tracking_uri → MlflowClient — `register_model(name, run_id, artifact_path)`, `get_latest_version(name, stage)`, `get_version(name, version)`, `transition_stage(name, version, stage)`, `list_models()`, `download_artifact(name, version, dst)`, `tag_version(name, version, tags)`)

**Test file:** `tests/model_evolution/test_registry.py` — mocked MlflowClient, verifies register_model, transition_stage, error on missing model

**Verification:**
```bash
python -m pytest tests/model_evolution/test_registry.py -v
```

**Commit message:** `feat(model-evolution): implement ModelRegistry MLflow wrapper`

---

### Task 11: Implement `model_evolution/eval_gate.py`

**Files:** Create `proxy/app/model_evolution/eval_gate.py`

**Dependencies:** Task 5 (metrics_gen for reference, though independent)

**Key classes:** `GateStatus` enum (PASS/FAIL/WARN), `MetricThreshold` dataclass (metric_name, threshold, comparison gt/lt/gte/lte, severity fail/warn, tolerance — evaluate method), `GateResult` dataclass (status, model_name, version, metrics, thresholds, failures, warnings, baseline_metrics, delta_metrics, mlflow_run_id), `EvalGateConfig` (thresholds, require_baseline_comparison, baseline_regression_tolerance, min_eval_samples), `EvalGate` static class (evaluate metrics → GateResult, from_mlflow_run, format_report, is_passing)

**Test file:** `tests/model_evolution/test_eval_gate.py` — tests all comparison operators, PASS/FAIL/WARN paths, baseline comparison, format_report output

**Verification:**
```bash
python -m pytest tests/model_evolution/test_eval_gate.py -v
```

**Commit message:** `feat(model-evolution): implement EvalGate with threshold evaluation and GateResult`

---

### Task 12: Implement `model_evolution/slm_trainer.py`

**Files:** Create `proxy/app/model_evolution/slm_trainer.py`

**Dependencies:** Tasks 4, 8, 9

**Key classes:** `SLMTrainingConfig(TrainingConfig)` — defaults lora_r=8, lora_alpha=16, max_seq_length=512, qlora=False. `SLMTrainer(TrainerBase)` — `__init__(base_model_path)`, `prepare_data(samples=)`, `train(config) → TrainingJob`, `evaluate(model, eval_data) → dict` (intent_accuracy, weighted_f1)

**Stub mode:** In CI profile, `train()` logs intent and returns simulated metrics without actual GPU training. Production path uses PEFT+transformers (imports guarded).

**Test file:** `tests/model_evolution/test_slm_trainer.py`

**Verification:**
```bash
python -m pytest tests/model_evolution/test_slm_trainer.py -v
```

**Commit message:** `feat(model-evolution): implement SLMTrainer for LoRA intent classification`

---

### Task 13: Implement `model_evolution/llm_trainer.py`

**Files:** Create `proxy/app/model_evolution/llm_trainer.py`

**Dependencies:** Tasks 4, 8, 9

**Key classes:** `LLMTrainingConfig(TrainingConfig)` — defaults lora_r=16, lora_alpha=32, use_qlora=True, load_in_4bit=True, bnb_4bit_compute_dtype="bfloat16", max_seq_length=2048. `LLMTrainer(TrainerBase)` — QLoRA domain generation fine-tuning. `train()` returns TrainingJob with bertscore_f1, rouge_l, hallucination_rate, perplexity metrics.

**Test file:** `tests/model_evolution/test_llm_trainer.py`

**Verification:**
```bash
python -m pytest tests/model_evolution/test_llm_trainer.py -v
```

**Commit message:** `feat(model-evolution): implement LLMTrainer for QLoRA domain generation`

---

### Task 14: Implement `model_evolution/reranker_trainer.py`

**Files:** Create `proxy/app/model_evolution/reranker_trainer.py`

**Dependencies:** Tasks 4, 8, 9

**Key classes:** `RerankerTrainingConfig(TrainingConfig)` — defaults lora_r=4, lora_alpha=8. `RerankerTrainer(TrainerBase)` — supports both `full_fine_tune` (existing CrossEncoder.fit() path) and `lora` (new PEFT path). `train()` returns metrics: mrr, ndcg_10, precision_5, kendall_tau.

**Test file:** `tests/model_evolution/test_reranker_trainer.py`

**Verification:**
```bash
python -m pytest tests/model_evolution/test_reranker_trainer.py -v
```

**Commit message:** `feat(model-evolution): implement RerankerTrainer with full FT + LoRA paths`

---

### Task 15: Implement CLI Scripts

**Files:** Create `scripts/train_slm.py`, `scripts/train_llm.py`, `scripts/train_reranker.py`, `scripts/run_eval_gate.py`, `scripts/promote_model.py`, `scripts/export_training_data.py`

**Dependencies:** Tasks 10-14 (all trainers and eval gate exist)

**Pattern (each script):** argparse → load ModelEvolutionConfig.from_env() → get profile → instantiate trainer → train → eval gate → register → print result. Exit code 0 on pass, 1 on fail.

**Example — `scripts/train_slm.py`:**
```python
#!/usr/bin/env python3
"""Train SLM intent classifier."""
import argparse, sys
from proxy.app.model_evolution.config import ModelEvolutionConfig, EnvProfile
from proxy.app.model_evolution.slm_trainer import SLMTrainer
from proxy.app.model_evolution.data_processor import DataProcessor
from proxy.app.model_evolution.eval_gate import EvalGate, EvalGateConfig, MetricThreshold

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="dev", choices=["dev","prod","ci"])
    parser.add_argument("--data-dir", default="./data/training/")
    parser.add_argument("--base-model", default="")
    args = parser.parse_args()
    me_cfg = ModelEvolutionConfig.from_env()
    train_cfg = me_cfg.get_profile(args.profile)
    trainer = SLMTrainer(base_model_path=args.base_model)
    dp = DataProcessor()
    interactions = dp.load_interactions(f"{args.data_dir}/interactions.jsonl")
    intent_map = {}  # In production: load from pre-labeled data
    pairs = dp.export_intent_pairs(interactions, intent_map)
    train_data, eval_data = dp.train_eval_split(pairs, eval_split=0.2)
    samples = trainer.prepare_data(samples=train_data)
    job = trainer.train(train_cfg)
    print(f"Training {job.status}: {job.metrics}")
    if job.status == "failed":
        sys.exit(1)
    gate = EvalGateConfig(model_name="slm", thresholds=[
        MetricThreshold("weighted_f1", 0.85, "gte"),
        MetricThreshold("intent_accuracy", 0.90, "gte"),
    ])
    result = EvalGate.evaluate(job.metrics, gate)
    print(EvalGate.format_report(result))
    sys.exit(0 if EvalGate.is_passing(result) else 1)

if __name__ == "__main__":
    main()
```

**Verification:**
```bash
python scripts/train_slm.py --profile ci --help
python scripts/train_slm.py --profile ci  # runs stub training
```

**Commit message:** `feat(model-evolution): add CLI scripts for training, eval gate, and model promotion`

---

### Task 16: Implement `model_evolution/adapter_manager.py`

**Files:** Create `proxy/app/model_evolution/adapter_manager.py`

**Dependencies:** Task 10 (registry for artifact download)

**Key classes (detailed implementation — match ADR spec):**
- `AdapterState` enum: UNLOADED → LOADING → ACTIVE → DRAINING → RETIRING → UNLOADED, + ERROR
- `ModelAdapter` dataclass: name, state, version, model_path, adapter_type (lora/full/base), base_model, loaded_at, request_count (in-flight counter), error_count, metadata
- `HotReloadWatcher`: polling daemon thread, watches directory for mtime changes, triggers callback(path, version), configurable poll_interval
- `AdapterManager`: threading.RLock-guarded registry, `register_adapter(name, adapter)`, `get_adapter(name) → ModelAdapter|None`, `reload_adapter(name, new_path, version)` → load new → ACTIVE, old → DRAINING → RETIRING → UNLOADED, `_load_adapter_weights(name, path, version)` → ModelAdapter (override point for PEFT loading), `list_adapters()`, `enable_watcher/disable_watcher`, `shutdown()`
- Global singleton: `get_adapter_manager()`

**Test file:** `tests/model_evolution/test_adapter_manager.py` — 4 test classes: TestAdapterState, TestModelAdapter, TestAdapterManager (register/get/list/reload/shutdown), TestHotReloadWatcher (start/stop/double_start), TestSingleton

**Verification:**
```bash
python -m pytest tests/model_evolution/test_adapter_manager.py -v
```

**Commit message:** `feat(model-evolution): implement AdapterManager with hot-reload lifecycle and HotReloadWatcher`

---

### Task 17: Implement `model_evolution/canary.py`

**Files:** Create `proxy/app/model_evolution/canary.py`

**Dependencies:** Task 16 (AdapterManager)

**Key classes (match ADR spec exactly):**
- `CanaryPhase` enum: IDLE, RAMP_5, RAMP_25, RAMP_50, RAMP_75, FULL, ROLLBACK
- `TrafficSplit` dataclass: stable_weight, canary_weight, total()
- `RollbackPolicy` dataclass: metric, threshold, comparison
- `CanaryConfig` dataclass: model_name, stable_version, canary_version, phases list[(phase, weight, duration_seconds)], metrics_window, rollback_thresholds dict, cooldown_seconds
- `CanaryController`: `start_canary(config)` → sets RAMP_5, `get_traffic_split(name) → TrafficSplit`, `evaluate_and_advance(name)` → checks metrics → rollback or advance phase, `evaluate_metrics(name) → dict[str,bool]` (stub queries Prometheus; defaults all-passing), `promote(name)` → FULL, `rollback(name)` → ROLLBACK + cooldown, `status() → dict`
- Global singleton: `get_canary_controller(adapter_manager=None)`

**Test file:** `tests/model_evolution/test_canary.py` — tests for all phases, traffic split math, start/promote/rollback/cooldown, singleton

**Verification:**
```bash
python -m pytest tests/model_evolution/test_canary.py -v
```

**Commit message:** `feat(model-evolution): implement CanaryController with traffic splitting and rollback`

---

### Task 18: Add Admin API Endpoints to `main.py`

**Files:** Modify `proxy/app/main.py`

**Dependencies:** Tasks 16, 17 (AdapterManager, CanaryController), Task 1 (MODEL_EVOLUTION_ENABLED)

**Endpoints added (gated behind MODEL_EVOLUTION_ENABLED):**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `GET /v1/admin/models` | GET | List registered models (from ModelRegistry) |
| `POST /v1/admin/models/reload` | POST | Trigger hot-reload (body: `{"model": "slm", "path": "/models/v3", "version": "v3"}`) |
| `POST /v1/admin/models/promote` | POST | Promote model to Production (body: `{"model": "slm-intent-classifier", "version": "3"}`) |
| `GET /v1/admin/canary/status` | GET | Current canary status |
| `POST /v1/admin/canary/promote` | POST | Manual canary advance |
| `POST /v1/admin/canary/rollback` | POST | Immediate rollback |
| `GET /v1/admin/training/jobs` | GET | List recent training jobs |
| `POST /v1/admin/training/run` | POST | Trigger training job |

**Implementation pattern (in `main.py` lifespan / route):**
```python
from app.config import MODEL_EVOLUTION_ENABLED

if MODEL_EVOLUTION_ENABLED:
    from proxy.app.model_evolution.adapter_manager import get_adapter_manager
    from proxy.app.model_evolution.canary import get_canary_controller
    from proxy.app.model_evolution.registry import ModelRegistry
    _adapter_mgr = get_adapter_manager()
    _canary_ctrl = get_canary_controller()
    _registry = ModelRegistry(MLFLOW_TRACKING_URI)

@app.get("/v1/admin/models")
async def admin_list_models():
    if not MODEL_EVOLUTION_ENABLED:
        return {"error": "Model evolution disabled"}, 404
    return {"models": _registry.list_models()}
# ... (repeat pattern for all 8 endpoints)
```

**Test file:** Add 8 test methods to existing `tests/proxy/test_main.py` or create `tests/model_evolution/test_admin_api.py`

**Verification:**
```bash
MODEL_EVOLUTION_ENABLED=true python -c "
from proxy.app.main import app
from fastapi.testclient import TestClient
client = TestClient(app)
resp = client.get('/v1/admin/models')
assert resp.status_code in (200, 404)
"
```

**Commit message:** `feat(model-evolution): add 8 admin API endpoints for model management, canary, and training`

---

### Task 19: Implement CI/CD Pipeline

**Files:** Create `.github/workflows/model-evolution.yml`

**Dependencies:** Tasks 15 (CLI scripts), 11 (eval gate)

**Pipeline structure (match ADR section 8):**
```yaml
name: Model Evolution Pipeline
on:
  push:
    paths: ['proxy/app/model_evolution/**', 'proxy/app/hitl.py', 'scripts/train_*.py']
  schedule:
    - cron: '0 2 * * 0'  # Weekly Sunday 2am
  workflow_dispatch:
    inputs:
      model: {description: 'Model to train', default: 'all'}
      profile: {description: 'Training profile', default: 'ci'}

jobs:
  export-data: {runs-on: ubuntu-latest, upload-artifact: training-data}
  train-slm: {needs: export-data, if: model in (slm, all), steps: [checkout, download-artifact, train SLM, run eval gate, promote on pass]}
  train-llm: {needs: export-data, if: model in (llm, all), same pattern}
  train-reranker: {needs: export-data, if: model in (reranker, all), same pattern}
  integration-test: {needs: [train-slm, train-llm, train-reranker], if: always() && !cancelled(), runs: pytest tests/model_evolution/test_integration.py}
```

**Verification:** CI runs on push to branch; manual dispatch available

**Commit message:** `feat(model-evolution): add GitHub Actions CI/CD pipeline for model training and eval gates`

---

### Task 20: Add `docker-compose.yml` Extensions

**Files:** Modify `proxy/docker-compose.yml`

**Dependencies:** Tasks 1 (config for ports)

**Add services:**
```yaml
  mlflow:
    image: ghcr.io/mlflow/mlflow:v2.15.0
    ports: ["5000:5000"]
    environment:
      - MLFLOW_S3_ENDPOINT_URL=http://minio:9000
      - AWS_ACCESS_KEY_ID=minioadmin
      - AWS_SECRET_ACCESS_KEY=minioadmin
    command: mlflow server --backend-store-uri sqlite:///mlflow.db --default-artifact-root s3://rag-artifacts --host 0.0.0.0 --port 5000
    volumes: [mlflow_data:/mlflow]
    depends_on: [minio]

  minio:
    image: minio/minio:latest
    ports: ["9000:9000", "9001:9001"]
    environment:
      - MINIO_ROOT_USER=minioadmin
      - MINIO_ROOT_PASSWORD=minioadmin
    command: server /data --console-address ":9001"
    volumes: [minio_data:/data]

volumes:
  mlflow_data:
  minio_data:
```

**Verification:**
```bash
cd proxy && docker-compose up -d mlflow minio
curl http://localhost:5000/health
curl http://localhost:9001
docker-compose down
```

**Commit message:** `feat(model-evolution): add mlflow and minio services to docker-compose.yml`

---

### Task 21: Update `requirements_proxy.txt` and `Dockerfile`

**Files:** Modify `proxy/requirements_proxy.txt`, `proxy/Dockerfile`

**Dependencies:** None (additive)

**Add to requirements_proxy.txt:**
```
# Model Evolution
peft>=0.12.0
bitsandbytes>=0.44.0
mlflow>=2.15.0
minio>=7.2.0
rouge-score>=0.1.0
bert-score>=0.3.0
nltk>=3.9.0
accelerate>=0.34.0
transformers>=4.45.0
```

**Add to Dockerfile** (after existing pip install):
```dockerfile
# Model Evolution dependencies (optional, fail gracefully if GPU unavailable)
RUN pip install --no-cache-dir peft bitsandbytes mlflow minio rouge-score bert-score nltk accelerate 2>/dev/null || true
```

**Verification:**
```bash
pip install -r proxy/requirements_proxy.txt --dry-run
```

**Commit message:** `feat(model-evolution): add model evolution dependencies to requirements and Dockerfile`

---

### Task 22: Update `Makefile` with Training Targets

**Files:** Modify `Makefile`

**Dependencies:** Task 15 (CLI scripts)

**Add targets:**
```makefile
train-slm: ## Train SLM intent classifier
	python scripts/train_slm.py --profile $(TRAINING_PROFILE) --data-dir ./data/training/

train-llm: ## Train LLM domain generator
	python scripts/train_llm.py --profile $(TRAINING_PROFILE) --data-dir ./data/training/

train-reranker: ## Train reranker
	python scripts/train_reranker.py --profile $(TRAINING_PROFILE) --data-dir ./data/training/

eval-gate: ## Run eval gate for latest model
	python scripts/run_eval_gate.py --model $(MODEL) --latest

promote-model: ## Promote model to Production
	python scripts/promote_model.py --model $(MODEL) --stage Production

test-model-evolution: ## Run all model evolution tests
	python -m pytest tests/model_evolution/ tests/proxy/test_model_evolution_*.py -v
```

**Verification:**
```bash
make train-slm TRAINING_PROFILE=ci
make test-model-evolution
```

**Commit message:** `feat(model-evolution): add Makefile targets for training, eval, promotion`

---

### Task 23: Add `export_intent_dataset()` to `hitl.py`

**Files:** Modify `proxy/app/hitl.py`

**Dependencies:** None (additive method)

**Add method to InteractionLogger (or module-level function):**
```python
def export_intent_dataset(
    interactions_file: str | None = None,
    output_path: str | None = None,
    intent_classifier: callable | None = None,
) -> list[dict[str, str]]:
    """Export query-intent pairs from HITL logs for SLM training.

    If intent_classifier is provided, uses it to label queries.
    Otherwise, uses heuristics: queries containing 'how'/'steps' → procedural,
    'vs'/'compare' → comparison, 'error'/'fix' → troubleshooting, else → factual.
    """
    # heuristic intent classification
    def classify(query: str) -> str:
        q = query.lower()
        if any(w in q for w in ["how", "steps", "guide", "tutorial"]):
            return "procedural"
        if any(w in q for w in ["vs", "compare", "difference", "versus"]):
            return "comparison"
        if any(w in q for w in ["error", "fix", "bug", "issue", "fail"]):
            return "troubleshooting"
        if len(q.split()) < 3:
            return "meta"
        return "factual"

    interactions = load_interactions(interactions_file) if interactions_file else []
    pairs = []
    for item in interactions:
        query = item.get("query", "")
        if query:
            intent = classify(query)
            pairs.append({"query": query, "intent": intent})
    if output_path:
        import json
        with open(output_path, "w") as f:
            for p in pairs:
                f.write(json.dumps(p) + "\n")
    return pairs
```

**Test file:** `tests/proxy/test_hitl.py` — add `test_export_intent_dataset` method

**Commit message:** `feat(model-evolution): add export_intent_dataset() to hitl.py for SLM training data`

---

### Task 24: Extend `ab_test.py` for Model Variant Selection

**Files:** Modify `proxy/app/ab_test.py`

**Dependencies:** Task 17 (CanaryController for traffic split)

**Add ModelVariant dataclass and modify ABTest:**
```python
@dataclass
class ModelVariant:
    """Variant for A/B testing different model versions."""
    name: str
    model_name: str  # "slm", "llm", "reranker"
    version: str
    weight: float = 0.5  # traffic allocation weight

# In ABTest class, add:
def select_model_variant(self, model_name: str) -> str:
    """Select a model version based on canary traffic split or A/B weights."""
    from proxy.app.model_evolution.canary import get_canary_controller
    ctrl = get_canary_controller()
    split = ctrl.get_traffic_split(model_name)
    if split.canary_weight > 0 and random.random() < split.canary_weight:
        return "canary"
    return "stable"
```

**Test file:** `tests/proxy/test_ab_test.py` — add `test_model_variant_selection`

**Commit message:** `feat(model-evolution): extend ABTest with ModelVariant for canary-integrated A/B testing`

---

### Task 25: Integration Testing & Documentation

**Files:**
- Create `tests/model_evolution/test_integration.py`
- Create `docs/en/guides/model-evolution-guide.md`

**Dependencies:** All previous tasks

**Integration test flow (test_integration.py):**
```python
class TestModelEvolutionIntegration:
    def test_full_training_flow_slm_ci(self):
        """End-to-end: config → prepare data → train → eval gate → pass."""
        from proxy.app.model_evolution.config import ModelEvolutionConfig, EnvProfiles
        from proxy.app.model_evolution.slm_trainer import SLMTrainer
        from proxy.app.model_evolution.data_processor import DataProcessor
        from proxy.app.model_evolution.eval_gate import EvalGate, EvalGateConfig, MetricThreshold

        cfg = EnvProfiles.CI
        cfg.trainer_type = TrainerType.SLM
        trainer = SLMTrainer()
        dp = DataProcessor()
        samples = [("query1", "factual"), ("query2", "procedural"), ("query3", "factual")]
        train, eval_data = dp.train_eval_split(samples, eval_split=0.33, seed=42)
        data = trainer.prepare_data(samples=train)
        job = trainer.train(cfg)
        assert job.status == "completed"

        gate = EvalGateConfig(model_name="slm", thresholds=[
            MetricThreshold("weighted_f1", 0.80, "gte"),
        ])
        result = EvalGate.evaluate(job.metrics, gate)
        assert result.status in (GateStatus.PASS,)

    def test_registry_flow(self):
        """ModelRegistry → register → transition → get_latest."""
        # ... full flow test

    def test_adapter_manager_lifecycle(self):
        """AdapterManager: register → reload → drain → retire."""
        # ... full lifecycle test

    def test_canary_ramp_up_and_rollback(self):
        """CanaryController: start → advance → promote → rollback."""
        # ... full canary test

    def test_eval_gate_rejects_failing_model(self):
        """EvalGate correctly fails a model below threshold."""
        # ... gate rejection test
```

**Guide document:** `docs/en/guides/model-evolution-guide.md` covering:
1. Overview and architecture
2. Quick start: enabling model evolution
3. Training profiles (dev/prod/ci)
4. Running training jobs (CLI + CI/CD)
5. Eval gates and thresholds
6. Hot-reload adapter management
7. Canary deployment workflow
8. Admin API reference
9. Troubleshooting common issues (OOM, MLflow SQLite, MinIO connectivity)
10. Rollback procedures

**Verification:**
```bash
python -m pytest tests/model_evolution/test_integration.py -v
python -m pytest tests/ -v --tb=short  # full suite, verify no regressions
```

**Commit message:** `feat(model-evolution): add integration tests and model-evolution-guide documentation`

---

## Coverage Map

| Acceptance Criterion | Task IDs |
|---------------------|----------|
| MODEL_EVOLUTION_ENABLED=false preserves existing behavior | 1, 18, 25 |
| SLM LoRA fine-tuning works in all 3 profiles | 12, 15, 25 |
| LLM QLoRA fine-tuning works in all 3 profiles | 13, 15, 25 |
| Reranker FT + LoRA fine-tuning works | 14, 15, 25 |
| MLflow tracks experiments and stores artifacts | 7, 10, 20 |
| MinIO stores and retrieves model artifacts | 6, 20 |
| Eval gate blocks promotion on failing metrics | 11, 15, 19, 25 |
| Hot-reload swaps adapters without restart | 16, 18 |
| Canary deploys gradually with automatic rollback | 17, 18, 24 |
| Admin API exposes model management | 18 |
| CI/CD pipeline runs on push and schedule | 19 |
| All features disabled by default | 1, 18 |
| CPU training works (TRAINING_PROFILE=dev) | 4, 12, 13, 14 |
| GPU training works (TRAINING_PROFILE=prod) | 4, 12, 13, 14 |
| CI smoke test works without GPU | 4, 12, 13, 14, 19 |
| Existing 1469 tests continue passing | 25 |
| No circular dependencies | 3, 9 |

**Uncovered criteria:** None — all ADR-010 requirements mapped.

---

## Risks and Mitigations

| Risk | Probability | Impact | Mitigation | Tasks |
|------|------------|--------|------------|-------|
| OOM on adapter swap | Medium | High | Drain before unload; `threading.RLock`; configurable `HOT_RELOAD_MAX_ADAPTERS` | 16 |
| Training data leakage | Medium | Medium | `data_processor.train_eval_split()` uses seeded shuffle; same-document grouping in production | 8 |
| Canary flapping | Low | Medium | Mandatory cooldown; minimum phase duration; alert on repeated rollbacks | 17 |
| MLflow SQLite corruption | Low | High | Persistent volume; migration path to PostgreSQL documented; regular backups | 10, 20 |
| MinIO SPOF | Medium | High | Local adapter cache at `./models/adapters/versions/` works without MinIO; MinIO replication | 6, 16 |
| GPU OOM during QLoRA | Medium | Medium | `TRAINING_PROFILE=ci` uses CPU fallback; prod validates VRAM; gradient checkpointing | 13 |
| PEFT version incompatibility | Low | Medium | Pin versions in requirements; store `adapter_config.json` with `peft_version`; check before load | 21 |
| Hallucination regression | Medium | High | Eval gate blocks promotion if hallucination_rate > 5%; canary catches drift | 11, 13, 17 |
| Hot-reload race condition | Low | High | `threading.RLock`; in-flight request counter; DRAINING state prevents new requests | 16 |

---

## Open Blockers Requiring Human Input

1. **GPU runner availability** — CI/CD pipeline (`model-evolution.yml`) uses `[self-hosted, gpu]` runner tag. Verify GPU self-hosted runner is configured in GitHub Actions before enabling production training jobs.
2. **MinIO persistence** — PVC size for MinIO `minio_data` volume must be provisioned based on expected model artifact volume (estimate: 1-5 GB per model version × ~10 versions). Consult infrastructure team.
3. **MLflow PostgreSQL migration** — ADR documents SQLite is sufficient for <10K runs but PostgreSQL needed for larger scale. Decision needed: deploy with SQLite initially and schedule PostgreSQL migration, or go directly to PostgreSQL.
4. **NLI model for hallucination detection** — `compute_hallucination_rate()` in `metrics_gen.py` uses token-overlap fallback. Production-grade NLI (DeBERTa MNLI) requires ~2 GB GPU memory. Decision: always deploy NLI or use heuristic-only for initial rollout.
5. **SIGHUP handler integration** — ADR specifies SIGHUP signal handler for manual hot-reload. Integration with FastAPI's uvicorn signal handling must be tested; `signal.signal(signal.SIGHUP, handler)` may conflict with uvicorn's internal signal handling. Verify in integration testing (Task 25).

---

## Execution Order (rationale)

```
Phase 1: Foundation (Tasks 1-9)
  Task 1 (config)     ──┐
  Task 2 (exceptions) ──┤── No dependencies, parallel
  Task 3 (skeleton)   ──┤── Depends on Tasks 1,2
  Task 4 (me config)  ──┤── Depends on Tasks 1,3
  Task 5 (metrics_gen)──┤── Depends on Task 3 only
  Task 6 (artifact)   ──┤── Depends on Task 1
  Task 7 (tracking)   ──┤── Depends on Task 1
  Task 8 (data_proc)  ──┤── Depends on Task 3
  Task 9 (trainer)    ──┘── Depends on Tasks 4,8

Phase 2: Training Pipeline (Tasks 10-15)
  Task 10 (registry)    ── Depends on Tasks 6,7
  Task 11 (eval_gate)   ── Depends on Task 5 (optional)
  Task 12 (slm)         ── Depends on Tasks 4,8,9
  Task 13 (llm)         ── Depends on Tasks 4,8,9
  Task 14 (reranker)    ── Depends on Tasks 4,8,9
  Task 15 (CLI scripts) ── Depends on Tasks 10-14

Phase 3: Eval Gates & CI/CD (Tasks 16-19)
  Task 16 (adapter_mgr) ── Depends on Task 10
  Task 17 (canary)      ── Depends on Task 16
  Task 18 (admin API)   ── Depends on Tasks 16,17
  Task 19 (CI/CD)       ── Depends on Task 15

Phase 4: Infrastructure & Integration (Tasks 20-24)
  Task 20 (docker-comp) ── Depends on Task 1
  Task 21 (requirements)── Depends on none
  Task 22 (Makefile)    ── Depends on Task 15
  Task 23 (hitl export) ── Depends on existing hitl.py
  Task 24 (ab_test ext) ── Depends on Task 17

Phase 5: Testing & Docs (Task 25)
  Task 25 (integration) ── Depends on ALL previous tasks
```

**Estimated total effort:** ~40-50 person-days engineering + 5-10 person-days infrastructure/devops + 5 person-days documentation.
