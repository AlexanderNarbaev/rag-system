# ADR-008: Java/Quarkus Proxy Migration — Rejected

**Status:** Rejected
**Date:** 2026-07-16
**Sprint:** S4-2026 Wave 3/4, Tasks P2-4 / P3-3

## Context

The RAG System proxy layer is implemented in Python with FastAPI (30+ endpoints), LangGraph orchestrator (10-node
state graph), hybrid Qdrant retrieval, cross-encoder reranker, multi-provider LLM routing, JWT auth with RBAC, Redis
caching, Prometheus metrics, and SSE streaming. The full stack is described in ADR-004 (OpenAI-compatible proxy pattern)
and ADR-006 (Agentic RAG with LangGraph).

A migration to Java 25 + Quarkus was previously proposed (ADR-008 original, 2026-07-03) with a hybrid architecture:
Quarkus proxy for infrastructure logic + Python ML sidecar for model inference, connected via gRPC. The proposal was
deferred on 2026-07-13 pending stabilization of the Python proxy, team capacity confirmation, and gRPC latency
validation.

This ADR supersedes the original proposal and formally rejects the Java/Quarkus migration path.

## Decision

**Keep Python/FastAPI as the proxy technology stack. No Java/Quarkus migration.**

Focus engineering effort on Python-native optimization, type safety, and operational maturity rather than a full
language migration.

## Rationale

### 1. Python ecosystem dominance for ML inference

The proxy is not purely infrastructure code — it is deeply coupled to the Python ML ecosystem. The following components
have no viable Java equivalents at equivalent quality:

- **Embeddings:** `sentence-transformers` with BAAI/bge-m3 (dense + sparse + ColBERT) — the `encode_sparse()` method
  and tokenizer behavior are Python-specific (`proxy/app/core/retrieval.py`).
- **Reranker:** `cross-encoder/ms-marco-MiniLM-L-6-v2` via `sentence-transformers` (`proxy/app/core/rerank.py`).
- **NLI hallucination detection:** entailment/contradiction/neutral scoring via HuggingFace transformers
  (`proxy/app/core/hallucination.py`).
- **HyDE generation:** hypothetical document embedding via LLM + embedder pipeline (`proxy/app/core/hyde.py`).
- **Token optimization:** BPE-aware counting and LLMLingua compression (`proxy/app/core/token_optimizer.py`).
- **Query enhancement:** rewriting, expansion, decomposition (`proxy/app/core/query_enhancer.py`).

The original proposal estimated the proxy at ~50% infrastructure / ~50% ML-invocation code. In practice, the boundary
is not clean — retrieval, reranking, context assembly, and generation are interleaved in the orchestrator graph. A
gRPC sidecar split introduces latency (10–30 ms per query path) and operational complexity (two deployment artifacts,
cross-language debugging, version coupling) for marginal infrastructure benefits.

### 2. Air-gapped model support

The system operates in an air-gapped environment where all models are pre-downloaded. The Python ML ecosystem
(HuggingFace `transformers`, `sentence-transformers`, PyTorch) provides first-class offline model loading with local
weight paths. Java alternatives (DJL/Deep Java Library, ONNX Runtime) require model conversion steps that:

- Risk quality regression for bge-m3 sparse embeddings and ColBERT multi-vectors.
- Add a conversion pipeline that must be maintained for every model update.
- Lack parity for tokenizer edge cases critical to retrieval accuracy.

Staying Python eliminates the conversion risk entirely.

### 3. Team expertise and velocity

The development team's primary competency for this project is Python. The proxy, ETL pipeline, MCP server, and ML
components are all Python. A Java migration would:

- Split team focus across two language ecosystems (JVM + Python).
- Require maintaining a gRPC protocol layer between them.
- Slow feature velocity during the 7–8 month migration period.
- Introduce JVM operational knowledge requirements (GraalVM native compilation, GC tuning, thread analysis).

The original proposal cited "JVM-first team" expertise — but the project's actual codebase and contribution history are
Python-first. Aligning the technology stack with the team's demonstrated project expertise is lower risk than aligning
with hypothetical team preferences.

### 4. Python optimization path addresses the original concerns

The original proposal identified four structural limitations. Each has a Python-native mitigation:

| Original Concern            | Python-Native Mitigation                                                        | Effort   |
|-----------------------------|---------------------------------------------------------------------------------|----------|
| GIL constraints             | `granian` (Rust-based ASGI server) with subprocess workers; `uvloop` event loop | Low      |
| Memory footprint            | Model quantization (GPTQ/AWQ), lazy loading, model unloading for idle routes   | Medium   |
| Startup time                | `granian` provides ~5x faster startup than uvicorn; model pre-warming on health | Low      |
| Observability gap           | OpenTelemetry Python SDK + structured JSON logging + Prometheus                 | Medium   |

These mitigations deliver 80% of the benefit at 10% of the migration cost.

### 5. gRPC sidecar adds unacceptable latency

The hybrid architecture requires 4–6 gRPC calls per query path (embed, rerank, NLI check, HyDE, compress). At 2–5 ms
per call, this adds 10–30 ms baseline — before model inference. In air-gapped environments with co-located services,
this overhead is pure waste compared to in-process Python calls that take <0.1 ms.

## Consequences

### Positive

1. **Zero migration risk** — no dual-runtime deployment, no gRPC protocol versioning, no cross-language debugging
   complexity. The system continues to operate as a single Python process.

2. **Faster feature delivery** — engineering effort that would have been spent on Java migration (7–8 months) is
   redirected to Python optimization, new features, and quality improvements.

3. **Unified stack** — proxy, ETL, MCP server, and ML components all remain Python. Single language for the entire
   project reduces onboarding time and context-switching overhead.

4. **ML ecosystem access** — direct access to HuggingFace model hub, PyTorch CUDA acceleration, `sentence-transformers`
   updates, and emerging Python ML tools without conversion layers.

5. **Incremental optimization** — Python-native improvements (granian, type checking, model quantization) can be
   adopted incrementally without a big-bang migration.

### Negative

1. **GIL persists** — true CPU parallelism remains unavailable. Mitigated by `granian` subprocess workers and the
   fact that the proxy is I/O-bound (network calls to Qdrant, LLM, Redis), not CPU-bound.

2. **No GraalVM native compilation** — startup time remains in the 2–3 second range (vs. ~50 ms native Java).
   Mitigated by `granian` (~5x improvement) and model pre-warming. Acceptable for the deployment model (long-running
   containers, not serverless scale-to-zero).

3. **Python type safety is weaker** — runtime duck-typing vs. Java compile-time checking. Mitigated by adopting
   `mypy` strict mode, Pydantic v2 validation, and expanding the test suite. See the optimization roadmap below.

### Risks

| Risk                                                        | Probability | Impact | Mitigation                                                       |
|-------------------------------------------------------------|-------------|--------|------------------------------------------------------------------|
| Python performance ceiling reached under production load     | Low         | Medium | Profile early; `granian` + model quantization; horizontal scaling |
| Team member requests JVM work; morale impact of rejection    | Low         | Low    | Clear ADR rationale; Python optimization work is substantive     |
| Future ML models require Java-only inference                 | Low         | High   | Revisit ADR if a concrete model with no Python support emerges   |

## Optimization Roadmap

Since the migration is rejected, the following Python-native improvements are prioritized:

| Phase | Improvement                                       | Target Sprint  |
|-------|---------------------------------------------------|----------------|
| Q3    | Migrate from uvicorn to `granian` ASGI server     | S4-2026 Wave 4 |
| Q3    | Enable `mypy --strict` on `proxy/app/`            | S4-2026 Wave 4 |
| Q3    | Structured JSON logging with OpenTelemetry        | S4-2026 Wave 4 |
| Q4    | Model quantization (GPTQ/AWQ) for embedder/reranker | S1-2027       |
| Q4    | Lazy model loading + idle route unloading          | S1-2027        |
| Q4    | Async profiler integration for Python              | S1-2027        |

## Status History

- **2026-07-03** — Proposed as hybrid Java/Quarkus migration.
- **2026-07-13** — Deferred. Pending Python proxy stabilization, team capacity, gRPC benchmarks.
- **2026-07-16** — **Rejected.** Formal decision to keep Python/FastAPI. Rationale: Python ecosystem dominance for ML
  inference, air-gapped model support, team expertise alignment, and Python-native optimization path addresses original
  concerns. Sprint S4-2026 Wave 3/4, Tasks P2-4 / P3-3.
