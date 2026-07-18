# System Architecture Overview

This document provides a high-level architectural overview of the RAG System — a production-grade, air-gapped,
OpenAI-compatible RAG proxy that ingests corporate knowledge into a hybrid search engine and serves context-aware
answers via configurable LLM backends.

---

## Six-Layer Architecture

The system is organized into six layers, each with a well-defined responsibility:

### 1. ETL Layer (Data Ingestion)

**Purpose:** Extract, transform, and load corporate data sources into the vector and graph databases.

| Component         | Responsibility                                               |
|:------------------|:-------------------------------------------------------------|
| Extractors        | Fetch data from Confluence, Jira, GitLab, file systems, books, and chat logs |
| Semantic Chunker  | Split documents into coherent chunks using semantic boundaries; convert HTML to Markdown |
| Hash Versioner    | SHA-256 content-addressable chunk identification for incremental updates |
| Entity Extractor  | NLP-based entity recognition (organizations, people, technologies, concepts) |
| Neo4j Loader      | Write extracted entities and relationships into the graph database |
| Qdrant Indexer    | Embed chunks with BGE-M3 (dense, sparse, ColBERT) and index into Qdrant |
| WAL Manager       | Write-ahead log checkpointing for resume-capable, incremental ETL runs |
| Scheduler         | Orchestrate the full pipeline with configurable intervals and dependency ordering |

**Key characteristics:**
- **Incremental by default** — WAL-based checkpointing ensures only changed documents are reindexed.
- **HTML→Markdown** — preserves structural semantics (headings, lists, tables, code blocks) during chunking.
- **Streaming ETL** — processes large datasets in bounded batches, avoiding memory exhaustion.

### 2. Proxy Layer (RAG Serving)

**Purpose:** OpenAI-compatible API server that orchestrates retrieval, reranking, context assembly, and LLM generation.

| Component           | Responsibility                                                |
|:--------------------|:--------------------------------------------------------------|
| API Layer (FastAPI) | 30+ REST endpoints: chat, models, health, auth, feedback, admin, tools, files |
| Orchestrator        | LangGraph state graph (10 nodes) for agentic multi-step reasoning |
| Retrieval           | Hybrid search (dense + sparse RRF fusion) against Qdrant + optional Neo4j graph expansion |
| Reranker            | Cross-encoder (MiniLM-L-6-v2) re-ranks retrieved chunks for precision |
| Context Builder     | Token-budgeted assembly with deduplication, version tracking, and compression |
| LLM Router          | Multi-provider abstraction — routes to vLLM, llama.cpp, or any OpenAI-compatible backend |
| SLM Router          | Lightweight model for fast-path tasks: intent classification, query decomposition, entity extraction, chunk enrichment |
| Token Optimizer     | BPE-aware token counting, 4 compression strategies, smart budget allocation |
| Hallucination Check | NLI-based grounding: verifies generated claims against retrieved context |
| Confidence Scoring  | Heuristics + SLM verification pipeline |
| Feedback Enricher   | Self-enrichment loop: positive/corrected Q&A pairs feed back into Qdrant |

**Key characteristics:**
- **Progressive retrieval** — Iterative refinement with HyDE query expansion, CRAG evaluation, and reflection loops.
- **SLM enrichment** — Lightweight model adds summaries, extracted entities, and quality tags to chunks at indexing time.
- **Reranker quality control** — Chunk-level feedback scoring enables negative pair mining for reranker fine-tuning.
- **Graceful degradation** — Neo4j unavailable? Skip graph expansion. Reranker OOM? Use raw hybrid scores. Redis down? Fall back to in-memory cache.

### 3. HITL Layer (Quality Control)

**Purpose:** Expert dashboard for human-in-the-loop feedback, correction, and quality monitoring.

- **Streamlit dashboard** — Review answers, correct responses, rate chunks, flag stale documents.
- **Feedback pipeline** — Structured feedback (positive/negative, corrections, per-chunk relevance) flows back to the enricher and feedback store.
- **Admin analytics** — Query volume, latency percentiles, token consumption, top knowledge bases, user activity trends.

### 4. MCP Server Layer (IDE Integration)

**Purpose:** Expose RAG tools, resources, and prompts to MCP-compatible clients (OpenCode, Claude Desktop).

- **STDIO transport** — Direct IDE integration via standard input/output.
- **Streamable HTTP transport** — Remote clients connect over HTTP with streaming support.
- **Tools** — RAG search, document listing, KB management.
- **Resources** — Knowledge base documents as MCP resources.
- **Prompts** — Pre-configured prompt templates for common query patterns.

### 5. Model Evolution Layer (Fine-Tuning)

**Purpose:** Continuous model improvement through fine-tuning, evaluation, and safe deployment.

| Component            | Responsibility                                              |
|:---------------------|:------------------------------------------------------------|
| SLM Trainer          | LoRA fine-tuning of lightweight models for classification and extraction |
| LLM Trainer          | QLoRA fine-tuning of generation models                     |
| Reranker Trainer     | Full/LoRA fine-tuning of cross-encoder models              |
| MLflow Tracker       | Experiment tracking, metric logging, artifact versioning   |
| EvalGate             | CI/CD quality gate — blocks promotion on quality regression |
| Canary Controller    | Gradual rollout with traffic splitting (5% → 25% → 50% → 100%) |
| Adapter Manager      | Hot-reload trained LoRA/QLoRA adapters without service restart |

### 6. Agentic Tools Layer (Extensibility)

**Purpose:** Custom tool SDK for extending the system with user-defined capabilities.

| Component           | Responsibility                                               |
|:--------------------|:-------------------------------------------------------------|
| Tool SDK            | `@tool` decorator with automatic JSON Schema from type hints |
| Declarative Tools   | YAML/JSON definitions for HTTP and shell-based tools         |
| OpenAPI Discovery   | Auto-convert REST APIs to tool definitions from OpenAPI specs |
| Tool Orchestrator   | Parallel execution with DAG-based dependency resolution      |
| Security Validator  | Input validation, sandboxing, rate limiting per-tool         |

---

## Data Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        INGESTION PATH (ETL)                             │
│                                                                         │
│  Confluence ─┐                                                          │
│  Jira ───────┼──► Extractors ──► Semantic Chunker ──► BGE-M3 Embedder  │
│  GitLab ─────┤        │              │                    │             │
│  Files ──────┘        │         HTML→Markdown           │             │
│                        ▼              │                    ▼             │
│                   Entity Extractor    │              Qdrant (vectors)    │
│                        │              │                    │             │
│                        ▼              │                    │             │
│                   Neo4j (graph)       │              Dense + Sparse      │
│                                       │              + ColBERT          │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│                        QUERY PATH (Proxy)                               │
│                                                                         │
│  Client ──► FastAPI ──► Auth/JWT ──► SLM Classifier                    │
│    │                                      │                             │
│    │                           ┌──────────┼──────────┐                  │
│    │                           ▼          ▼          ▼                  │
│    │                      Intent    Query Decomp   Entity               │
│    │                      Class      (Subquestions) Extract             │
│    │                           │          │          │                  │
│    │                           └──────────┼──────────┘                  │
│    │                                      ▼                             │
│    │                            HyDE Query Expansion                    │
│    │                                      │                             │
│    │                                      ▼                             │
│    │                      Qdrant Hybrid Search (dense+sparse RRF)       │
│    │                                      │                             │
│    │                        Neo4j Graph Expansion (optional)            │
│    │                                      │                             │
│    │                                      ▼                             │
│    │                      Cross-Encoder Reranking                       │
│    │                                      │                             │
│    │                                      ▼                             │
│    │                      Context Assembly (token-budgeted)             │
│    │                                      │                             │
│    │                           ┌──────────┼──────────┐                  │
│    │                           ▼          ▼          ▼                  │
│    │                        CRAG      Reflection  Compression           │
│    │                       Eval        Loop      (optional)             │
│    │                           │          │          │                  │
│    │                           └──────────┼──────────┘                  │
│    │                                      ▼                             │
│    │                      LLM Generation (streaming)                    │
│    │                                      │                             │
│    │                                      ▼                             │
│    │                      NLI Grounding + Confidence Score              │
│    │                                      │                             │
│    │                                      ▼                             │
│    └────────────────────── Response to Client                           │
│                                                                         │
│  Feedback Loop: Expert Feedback ──► Enricher ──► Qdrant (self-improving)│
└─────────────────────────────────────────────────────────────────────────┘
```

### Progressive Retrieval Flow

The system implements a multi-pass retrieval strategy:

1. **Pass 1 — Initial retrieval** — Hybrid search with user query, top-K = 50.
2. **HyDE expansion** — Generate a hypothetical answer, use it as a secondary query, merge results via RRF.
3. **CRAG evaluation** — Assess retrieval quality; if insufficient, trigger corrective retrieval with query decomposition.
4. **Reflection loop** — LLM reflects on its own answer, may request additional context for up to `REFLECTION_DEPTH` iterations.
5. **NLI grounding** — Verify each generated factual claim against retrieved context; flag hallucinations.

### Streaming ETL Pipeline

The ETL pipeline processes data sources in a continuous, incremental fashion:

1. Extractors poll Confluence/Jira/GitLab APIs for changes since last checkpoint.
2. Semantic chunker splits documents at natural boundaries (paragraphs, sections) preserving HTML structure as Markdown.
3. Hash versioner identifies new/changed chunks via SHA-256 comparison.
4. Embedder produces dense (1024-dim), sparse (BM25), and ColBERT multi-vectors.
5. Indexer upserts into Qdrant in batches of 64, with WAL checkpointing for resume capability.
6. Entity extractor identifies named entities and relationships; Neo4j loader creates/merges graph nodes.

---

## Component Interactions

| Interaction                        | Protocol    | Description                                              |
|:-----------------------------------|:-----------|:---------------------------------------------------------|
| Client → Proxy                     | HTTP/SSE   | OpenAI-compatible chat API with streaming                |
| Proxy → Qdrant                     | gRPC/REST  | Hybrid search queries and payload updates                |
| Proxy → Neo4j                      | Bolt       | Graph traversal for entity relationships                 |
| Proxy → Redis                      | Redis      | Multi-tier caching (embeddings, rerank, responses)       |
| Proxy → LLM Backend                | HTTP       | vLLM/llama.cpp/OpenAI-compatible API                     |
| Proxy → SLM Backend                | HTTP       | Lightweight model for classification and extraction      |
| ETL → Confluence/Jira/GitLab       | HTTPS      | API polling with pagination and rate limiting            |
| ETL → Qdrant                       | gRPC/REST  | Batch upsert of embedded chunks                          |
| ETL → Neo4j                        | Bolt       | Entity and relationship creation/merge                   |
| HITL Dashboard → Proxy             | HTTP       | Feedback submission and review API                       |
| MCP Client → MCP Server            | STDIO/HTTP | Tool invocation, resource access, prompt execution       |
| Prometheus → Proxy                 | HTTP       | Metrics scraping at `/metrics`                           |
| Grafana → Prometheus               | HTTP       | Dashboard queries                                        |
| MLflow → MinIO                     | S3        | Artifact storage for models, datasets, and checkpoints   |

---

## Deployment Topology

### Docker Compose (Development / Single-Server)

```
┌──────────────────────────────────────────────────────────┐
│  Host (single machine)                                   │
│                                                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐               │
│  │  Nginx   │  │ RAG Proxy│  │  vLLM   │               │
│  │  :80     │  │  :8080   │  │  :8000  │               │
│  └────┬─────┘  └────┬─────┘  └──────────┘               │
│       │             │                                    │
│       │    ┌────────┼────────┐                           │
│       │    ▼        ▼        ▼                           │
│       │  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐            │
│       │  │Qdrant│ │Neo4j │ │Redis │ │MinIO │            │
│       │  │:6333 │ │:7687 │ │:6379 │ │:9000 │            │
│       │  └──────┘ └──────┘ └──────┘ └──────┘            │
│       │                                                 │
│  ┌────┴─────┐  ┌──────────┐  ┌──────────┐              │
│  │Prometheus│  │ Grafana  │  │ MLflow   │              │
│  │  :9090   │  │  :3000   │  │  :5000   │              │
│  └──────────┘  └──────────┘  └──────────┘              │
│                                                          │
│  Volumes:                                                │
│    qdrant_data/  neo4j_data/  redis_data/               │
│    minio_data/   logs/                                   │
└──────────────────────────────────────────────────────────┘
```

All services are defined in `proxy/docker-compose.yml` (development) and `deploy/docker/docker-compose.prod.yml` (production with SSL, resource limits, and health checks).

### Kubernetes (Production)

```
┌──────────────────────────────────────────────────────────┐
│  Kubernetes Cluster                                      │
│                                                          │
│  ┌─────────────────────────────────────────────────┐    │
│  │  Namespace: rag-system                           │    │
│  │                                                  │    │
│  │  ┌──────────┐  ┌──────────────┐                 │    │
│  │  │ Ingress  │  │ HPA: 3-10    │                 │    │
│  │  │ (TLS)    │──│ RAG Proxy    │                 │    │
│  │  └──────────┘  │ Pods         │                 │    │
│  │                └──────┬───────┘                 │    │
│  │                       │                         │    │
│  │  ┌────────────────────┼─────────────────────┐  │    │
│  │  │  StatefulSet:      │                     │  │    │
│  │  │  Qdrant (3 nodes)  │  PVC: 100Gi each    │  │    │
│  │  └────────────────────┼─────────────────────┘  │    │
│  │                       │                         │    │
│  │  ┌──────────┐  ┌──────┴───────┐  ┌──────────┐ │    │
│  │  │ Neo4j    │  │ Redis        │  │ MinIO    │ │    │
│  │  │ (1 node) │  │ (sentinel)   │  │ (tenant) │ │    │
│  │  └──────────┘  └──────────────┘  └──────────┘ │    │
│  │                                                  │    │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐      │    │
│  │  │ vLLM     │  │Prometheus│  │ Grafana  │      │    │
│  │  │ (GPU)    │  │          │  │          │      │    │
│  │  └──────────┘  └──────────┘  └──────────┘      │    │
│  └──────────────────────────────────────────────────┘    │
│                                                          │
│  Network Policies:                                       │
│    • Proxy → Qdrant, Neo4j, Redis, LLM                  │
│    • Prometheus → All /metrics endpoints                │
│    • Ingress → Proxy only                               │
│    • All other traffic denied by default                │
└──────────────────────────────────────────────────────────┘
```

The Helm chart at `deploy/k8s/helm/rag-system/` includes:

| Resource            | Purpose                                             |
|:--------------------|:----------------------------------------------------|
| HorizontalPodAutoscaler | Auto-scale proxy pods based on CPU/memory       |
| NetworkPolicy     | Isolate services to minimum required connectivity   |
| Secret             | LLM API keys, DB passwords, MinIO credentials      |
| ConfigMap          | Non-sensitive proxy configuration                   |
| ServiceMonitor     | Prometheus Operator integration                     |
| PersistentVolumeClaims | Qdrant, Neo4j, Redis, MinIO data volumes        |

---

## Air-Gapped Operation

The system is designed for fully offline environments:

1. **Model pre-download** — `scripts/download_models_offline.py` fetches all required models (LLM, SLM, embedder, reranker) from the internet once, then transfers via removable media.
2. **No external API calls** — All embedding, reranking, and generation happens locally.
3. **Local mirror** — Python package dependencies can be served from a local PyPI mirror.
4. **Container registry** — Docker images are built once and transferred as `.tar` archives.

---

## Related Documents

| Document | Purpose |
|:---------|:--------|
| [Architecture Decision Records](../adr/) | 14 ADRs covering all major design decisions |
| [C4 Diagrams](../diagrams/) | L1 (Context), L2 (Containers), L3 (Components) |
| [Knowledge Graph Strategy](knowledge-graph-strategy.md) | Neo4j entity extraction and graph enrichment |
| [Deployment Guide](deployment-guide.md) | Docker + K8s production deployment |
| [Operations Guide](operations-guide.md) | Monitoring, backup, scaling |
| [Model Evolution](model-evolution.md) | Fine-tuning, EvalGate, canary deployment |
