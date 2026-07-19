# Architecture

**Version:** v2.0.0 | **Last Updated:** 2026-07-10

This document describes the system architecture of the RAG Knowledge Assistant — an OpenAI-compatible proxy with a full
ETL pipeline for corporate knowledge retrieval.

---

## 1. System Overview

The system consists of two main components that run on separate machines:

| Component        | Purpose                                                                          | Port        |
|------------------|----------------------------------------------------------------------------------|-------------|
| **ETL Pipeline** | Extract data from sources, chunk, embed, index into vector/graph stores          | N/A (batch) |
| **RAG Proxy**    | Serve OpenAI-compatible API with hybrid retrieval, reranking, and LLM generation | `8080`      |

These components share Qdrant and Neo4j as storage backends but run independently. The ETL pipeline populates the
databases; the proxy queries them at serving time.

### Supporting Services

| Service            | Purpose                                                  | Optional |
|--------------------|----------------------------------------------------------|----------|
| **Redis**          | Multi-tier cache (embeddings, rerank results, responses) | Yes      |
| **Neo4j**          | Knowledge graph for entity-based context expansion       | Yes      |
| **HITL Dashboard** | Streamlit expert review interface                        | Yes      |
| **MCP Server**     | Model Context Protocol server for IDE integration        | Yes      |
| **MLflow + MinIO** | Model experiment tracking and artifact storage           | Yes      |

---

## 2. Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         ETL Pipeline (separate machine)                  │
│                                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌────────────┐  │
│  │  Extractors   │→│   Chunker    │→│   Embedder   │→│  Indexer   │  │
│  │              │  │              │  │              │  │            │  │
│  │ • Confluence │  │ • Semantic   │  │ • BAAI/bge-m3│  │ • Qdrant   │  │
│  │ • Jira       │  │ • Hash-based │  │ • 1024-dim   │  │ • Neo4j    │  │
│  │ • GitLab     │  │ • Code-aware │  │ • Dense+     │  │ • WAL      │  │
│  │ • Documents  │  │ • Table      │  │   Sparse     │  │            │  │
│  │ • Books      │  │              │  │              │  │            │  │
│  │ • Chats      │  │              │  │              │  │            │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  └────────────┘  │
│                                                                         │
│  ┌──────────────────────────────────────────────────────┐              │
│  │  Graph Builder                                        │              │
│  │  • Entity Extractor (spaCy NER)                       │              │
│  │  • Neo4j Loader (10 entity types, 9 relation types)   │              │
│  └──────────────────────────────────────────────────────┘              │
└─────────────────────────────────────────────────────────────────────────┘
            │                    │
            ▼                    ▼
┌─────────────────┐    ┌─────────────────┐
│     Qdrant       │    │     Neo4j        │
│  Vector Database  │    │  Graph Database  │
│                   │    │                  │
│  • Dense vectors  │    │  • Entities      │
│  • Sparse vectors │    │  • Relations     │
│  • Hybrid search  │    │  • Multi-hop     │
│  • RRF fusion     │    │    traversal     │
└─────────────────┘    └─────────────────┘
            │                    │
            ▼                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    RAG Proxy (FastAPI :8080)                             │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │              LangGraph Orchestrator (optional)                     │  │
│  │                                                                    │  │
│  │  rewrite → retrieve → check → rerank → graph_expand               │  │
│  │     → build → generate → call_tools → reflect → check             │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │
│  │  Retrieval   │  │  Reranker   │  │   Context   │  │    LLM      │  │
│  │              │  │              │  │   Builder   │  │   Router    │  │
│  │ • Dense      │  │ • MiniLM     │  │             │  │             │  │
│  │ • Sparse     │  │ • Cross-     │  │ • Dedup     │  │ • vLLM      │  │
│  │ • ColBERT    │  │   encoder    │  │ • Version   │  │ • llama.cpp │  │
│  │ • RRF fusion │  │ • Fine-      │  │ • Token     │  │ • Anthropic │  │
│  │              │  │   tunable    │  │   budget    │  │ • Ollama    │  │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘  │
│                                                                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │
│  │    Auth      │  │   Cache     │  │  Confidence │  │   Tools     │  │
│  │              │  │              │  │   Scoring   │  │  Registry   │  │
│  │ • JWT        │  │ • Redis      │  │             │  │             │  │
│  │ • RBAC       │  │ • In-memory  │  │ • NLI       │  │ • SDK       │  │
│  │ • LDAP/AD    │  │ • Multi-tier │  │ • Heuristic │  │ • Declarat. │  │
│  │ • Keycloak   │  │              │  │ • CRAG      │  │ • OpenAPI   │  │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────┐
│   LLM Backend        │
│                      │
│  • vLLM              │
│  • llama.cpp         │
│  • Anthropic Claude  │
│  • Ollama            │
│  • Any OpenAI-compat │
└─────────────────────┘
```

---

## 3. Data Flow

### 3.1 ETL Pipeline Flow

```
Data Sources → Extract → Chunk → Embed → Index
     │                                      │
     │                                      ▼
     │                               ┌──────────┐
     └── Entity Extraction ──────────│  Qdrant  │
                                     │  Neo4j   │
                                     └──────────┘
```

1. **Extract**: Connectors pull raw data from Confluence, Jira, GitLab, local files (documents, books, chat logs).
2. **Chunk**: Semantic chunker splits documents into overlapping segments with SHA-256 content addressing for
   deduplication.
3. **Embed**: BAAI/bge-m3 generates dense (1024-dim) and sparse vectors for each chunk.
4. **Index**: Vectors stored in Qdrant with hybrid search (dense + sparse + ColBERT). Entities extracted via spaCy NER
   and loaded into Neo4j.
5. **WAL**: Write-ahead log tracks processing state for incremental updates and crash recovery.

### 3.2 Query Flow

```
Client → API → [Auth] → [Cache Check] → Hybrid Search → Access Control
                                                                    │
       ┌────────────────────────────────────────────────────────────┘
       ▼
  Reranker → Dedup → Context Builder → Token Budget → LLM → Response
       │                                                        │
       │                                                        ▼
       │                                              ┌──────────────┐
       └──────────────────────────────────────────────│  Confidence  │
                                                      │  + Feedback  │
                                                      └──────────────┘
```

1. **Request**: Client sends OpenAI-compatible chat completion request.
2. **Auth**: JWT validation and RBAC role check (if `AUTH_ENABLED=true`).
3. **Cache**: Check Redis/in-memory cache for previous response (if `rag_force_refresh` not set).
4. **Hybrid Search**: Qdrant performs dense + sparse + ColBERT search with RRF fusion.
5. **Access Control**: Post-retrieval row-level filtering based on user roles and document ACLs.
6. **Reranking**: Cross-encoder (MiniLM-L-6-v2) scores and filters top-50 to top-20 chunks.
7. **Deduplication**: SHA-256 content-hash based dedup, version-aware filtering.
8. **Context Assembly**: Token-budgeted context construction with compression.
9. **LLM Generation**: Provider adapter routes to configured backend (vLLM, llama.cpp, etc.).
10. **Confidence**: Heuristic + optional NLI-based grounding score.
11. **Response**: OpenAI-compatible JSON with RAG extensions (`rag_feedback_id`, `rag_confidence`, `rag_sources`).

### 3.3 Agentic Flow (when `USE_LANGGRAPH=true`)

When the LangGraph orchestrator is enabled, the query goes through a 10-node state graph:

```
rewrite → retrieve → check → rerank → graph_expand
   → build → generate → call_tools → reflect → check
```

- **rewrite**: SLM-based query decomposition into sub-queries
- **retrieve**: Multi-step retrieval with configurable loops
- **check**: CRAG evaluator assesses retrieval quality
- **graph_expand**: Neo4j multi-hop entity traversal
- **generate**: LLM response generation
- **call_tools**: Execute registered tools (live Confluence/Jira/GitLab queries)
- **reflect**: Self-critique and hallucination detection
- **check**: Final confidence gating

---

## 4. Component Descriptions

### 4.1 ETL Pipeline

The ETL pipeline runs independently, typically on a separate machine from the proxy.

#### Extractors

| Extractor            | Source                           | Output                        |
|----------------------|----------------------------------|-------------------------------|
| `confluence.py`      | Confluence REST API              | Pages, attachments, metadata  |
| `jira.py`            | Jira REST API                    | Issues, comments, transitions |
| `gitlab.py`          | GitLab REST API                  | Repos, MRs, issues, wikis     |
| `doc_extractor.py`   | Local files (PDF, DOCX, MD, TXT) | Document text + metadata      |
| `book_extractor.py`  | E-books (EPUB, FB2)              | Chapter-level chunks          |
| `chat_extractor.py`  | Chat history exports             | Conversation threads          |
| `image_extractor.py` | Images in documents              | OCR text extraction           |

All extractors inherit from `base_extractor.py` which provides:

- Incremental extraction via content hashing
- Error handling and retry logic
- Metadata normalization

#### Chunker

- **`semantic_chunker.py`**: Splits documents by semantic boundaries (paragraphs, sections) with configurable overlap.
- **`hash_versioning.py`**: SHA-256 content-addressable chunks for deduplication and version tracking.
- **`code_chunker.py`**: AST-aware chunking for source code (Python, JavaScript, Java).
- **`table_extractor.py`**: Structured table extraction from documents.

#### Indexer

- **`qdrant_hybrid.py`**: Creates and manages Qdrant collections with dense, sparse, and ColBERT vector indexes.
  Implements RRF fusion for hybrid search.
- **`live_vector_lake.py`**: Real-time vector ingestion for streaming data sources.
- **`wal_manager.py`**: Write-ahead log for crash recovery and incremental processing. Tracks chunk states (pending,
  processing, indexed, failed).

#### Graph Builder

- **`entity_extractor.py`**: spaCy NER-based extraction of 10 entity types: Person, Document, Project, Component,
  Technology, Team, Meeting, Decision, Milestone, Issue.
- **`neo4j_loader.py`**: Loads entities and 9 relation types into Neo4j. Supports incremental updates.
- **`schema.yaml`**: Defines the graph schema (entity types, relation types, constraints).

#### Scheduler

- **`run_etl.py`**: Main orchestrator that runs the full pipeline (extract → chunk → embed → index → graph).
- **`stream_producer.py` / `stream_consumer.py`**: Kafka-based streaming ETL for real-time data sources.
- **`webhook_server.py`**: HTTP webhook receiver for push-based data ingestion.
- **`cold_storage_cleanup.py`**: Manages Parquet cold storage retention.

### 4.2 RAG Proxy

The proxy is a FastAPI application serving on port `8080`.

#### API Layer (`main.py`)

- OpenAI-compatible `/v1/chat/completions` endpoint (streaming + non-streaming)
- 25+ endpoints covering chat, models, health, auth, feedback, tools, admin, metrics
- Pydantic request/response models with validation
- Middleware stack: CORS → Auth → Correlation ID → Request ID → Logging → Rate Limit → Compression

#### Retrieval (`retrieval.py`)

- Hybrid search combining dense, sparse, and ColBERT vectors
- Reciprocal Rank Fusion (RRF) for score normalization
- Configurable `MAX_CHUNKS_RETRIEVAL` (default: 50)
- Graceful degradation: returns empty results on Qdrant failure

#### Reranker (`rerank.py`)

- Cross-encoder model (default: `cross-encoder/ms-marco-MiniLM-L-6-v2`)
- Batch processing with configurable `RERANKER_BATCH_SIZE` (default: 32)
- Configurable `MAX_CHUNKS_AFTER_RERANK` (default: 20)
- Remote reranker support with local fallback

#### Context Builder (`context.py`)

- Deduplication via SHA-256 content hashing
- Version-aware filtering (extract version from query or `rag_version` parameter)
- Token-budgeted assembly with configurable limits
- Metadata enrichment for source citations

#### LLM Router (`llm/provider.py`)

- Multi-provider adapter: vLLM, llama.cpp, Anthropic, Ollama, OpenAI-compatible
- Streaming and non-streaming completion
- Retry logic with exponential backoff
- Provider-specific feature translation (Anthropic `system` field, Ollama `options`)

#### Confidence Scoring (`confidence.py`)

- Heuristic scoring based on retrieval quality and context coverage
- Optional NLI-based grounding (entailment verification against context)
- CRAG evaluator for retrieval quality assessment
- Configurable thresholds for escalation

#### Token Optimizer (`token_optimizer.py`)

- BPE-aware token counting (tiktoken)
- 4 compression strategies: truncation, header enrichment, context expansion, hierarchical
- Smart budget allocation across system prompt, context, and response

### 4.3 Knowledge Graph

The knowledge graph enriches retrieval with entity relationships.

- **10 Entity Types**: Person, Document, Project, Component, Technology, Team, Meeting, Decision, Milestone, Issue
- **9 Relation Types**: authored_by, belongs_to, depends_on, related_to, mentions, created_by, assigned_to, reviewed_by,
  blocks
- **Multi-hop Traversal**: Cypher queries traverse relationships to find related entities within configurable depth
- **Graceful Degradation**: Neo4j unavailable → graph expansion skipped, proxy continues with vector search only

### 4.4 Caching

Multi-tier caching with configurable backends:

| Tier          | Backend           | TTL   | Content                    |
|---------------|-------------------|-------|----------------------------|
| **Embedding** | Redis / in-memory | 24h   | Query embeddings (MD5 key) |
| **Rerank**    | Redis / in-memory | 5 min | Reranked chunk indices     |
| **Response**  | Redis / in-memory | 1h    | Full LLM responses         |

When Redis is unavailable (`USE_REDIS=false` or connection failure), the system falls back to an in-memory LRU cache.
The proxy never crashes on cache failure.

---

## 5. Technology Stack

| Component       | Technology                                                 | Purpose                                      |
|-----------------|------------------------------------------------------------|----------------------------------------------|
| **LLM**         | Any OpenAI-compatible (vLLM, llama.cpp, Anthropic, Ollama) | Response generation                          |
| **SLM**         | Lightweight ~2-3B (Llama, Gemma, Qwen)                     | Query routing, entity extraction             |
| **Embeddings**  | BAAI/bge-m3                                                | Dense (1024-dim) + sparse + ColBERT          |
| **Vector DB**   | Qdrant                                                     | Hybrid search, RRF fusion                    |
| **Graph DB**    | Neo4j                                                      | Entity relationships, multi-hop traversal    |
| **Cache**       | Redis                                                      | Multi-tier caching                           |
| **Proxy**       | FastAPI + LangGraph                                        | OpenAI-compatible API, agentic orchestration |
| **ETL**         | Python, spaCy, BeautifulSoup, sentence-transformers        | Data extraction, chunking, indexing          |
| **Dashboard**   | Streamlit                                                  | HITL expert review                           |
| **MCP**         | FastMCP                                                    | Model Context Protocol server                |
| **Auth**        | JWT + Keycloak OIDC + LDAP/AD                              | SSO, RBAC (4 roles)                          |
| **Infra**       | Kubernetes + Helm                                          | HPA, probes, secrets                         |
| **Backup**      | S3/MinIO                                                   | Automated snapshots                          |
| **Fine-tuning** | LoRA/QLoRA, MLflow, MinIO                                  | Model training and tracking                  |

---

## 6. Deployment Architecture

### Air-Gapped Design

The system is designed to run fully offline:

1. **Pre-downloaded models**: All models (embedder, reranker, LLM, SLM) are downloaded via
   `scripts/download_models_offline.py` and stored locally.
2. **No external API calls**: All inference runs locally — no OpenAI, Cohere, or HuggingFace API calls at runtime.
3. **Offline Docker images**: All container images are pre-pulled and available locally.
4. **Local model serving**: vLLM or llama.cpp serves models on localhost.

### Docker Compose (Single Server)

```yaml
# proxy/docker-compose.yml
services:
  qdrant:    # Vector database (port 6333)
  neo4j:     # Graph database (port 7687)
  redis:     # Cache (port 6379)
  vllm:      # LLM backend (port 8000)
  rag-proxy: # FastAPI proxy (port 8080)
```

### Kubernetes (Production)

- **Helm chart**: `k8s/helm/rag-system/`
- **Horizontal Pod Autoscaler**: Scales proxy pods based on CPU/request rate
- **Liveness/Readiness probes**: `/v1/health/live` and `/v1/health/ready`
- **Secrets management**: Kubernetes secrets for JWT_SECRET, API keys, passwords
- **Network policies**: Restrict inter-service communication
- **Persistent volumes**: Qdrant, Neo4j, Redis data persistence

---

## 7. Security Model

### Authentication

| Method            | Status       | Description                                     |
|-------------------|--------------|-------------------------------------------------|
| **JWT (local)**   | Implemented  | Access + refresh token pairs, SQLite user store |
| **LDAP/AD**       | Implemented  | Enterprise directory authentication fallback    |
| **Keycloak OIDC** | Configurable | Corporate SSO integration                       |

### Authorization (RBAC)

| Role        | Rank | Permissions                                        |
|-------------|------|----------------------------------------------------|
| `admin`     | 4    | All endpoints, model management, training triggers |
| `expert`    | 3    | Chat + feedback submission                         |
| `user`      | 2    | Chat only                                          |
| `read_only` | 1    | Models list + health checks                        |

### Security Features

- **Input sanitization**: SQL injection, XSS, and length limit protection
- **Rate limiting**: Token bucket per IP (configurable `RATE_LIMIT_PER_MINUTE`, `RATE_LIMIT_BURST`)
- **Brute-force protection**: Login attempt rate limiting (5 attempts per 5 min, 15 min cooldown)
- **Secret masking**: Sensitive values redacted in logs
- **Row-level access control**: Document-level ACL filtering post-retrieval
- **Token blacklisting**: Revoked access tokens are blacklisted
- **CORS**: Configurable allowed origins
- **Compression**: gzip response compression

---

## 8. Key Design Principles

1. **Air-gapped first** — All models pre-downloaded. No external API calls at runtime.
2. **Graceful degradation** — Every component can fail independently. Neo4j unavailable → skip graph expansion. Reranker
   OOM → use raw scores. Redis down → in-memory cache. The proxy never crashes.
3. **Incremental by default** — WAL-based checkpointing. SHA-256 content-addressable chunks. Only changed documents
   reindexed.
4. **OpenAI compatibility** — Drop-in replacement for any OpenAI client. RAG extensions silently ignored by standard
   clients.
5. **Dual-model routing** — SLM (2-3B) for fast preprocessing. LLM for heavy generation.
6. **Multi-provider** — Pluggable backend adapters for vLLM, llama.cpp, Anthropic, Ollama, OpenAI-compatible.
7. **Optional complexity** — LangGraph, Neo4j, Redis all optional. Runs in simple RAG mode by default.
8. **Token economy** — BPE-aware counting, 4 compression strategies, smart budget allocation.
