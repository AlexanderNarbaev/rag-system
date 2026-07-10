# RAG System v2.0 — Documentation

<div class="hero" markdown>

**Production-ready self-correcting RAG system.** Deploy on-prem, air-gapped. Query Confluence, Jira, GitLab — get answers with hallucination detection, NLI verification, and agentic tool integration.

[Quick Start](#quick-start){ .md-button .md-button--primary }
[API Reference](api_reference.md){ .md-button }
[Deploy](guides/deployment-guide.md){ .md-button }

</div>

---

## Quick Start

### 1. Clone & Install

```bash
git clone https://github.com/AlexanderNarbaev/rag-system.git
cd rag-system
make install-dev
```

### 2. Configure

```bash
cd proxy
cp .env.example .env
# Edit .env — set LLM_ENDPOINT, LLM_MODEL_NAME, QDRANT_HOST
```

### 3. Start Services

```bash
docker compose up -d     # Qdrant + Redis + Neo4j + Proxy
```

### 4. Test

```bash
# Health check
curl http://localhost:8080/v1/health

# First query
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "rag-proxy",
    "messages": [{"role": "user", "content": "What is the company vacation policy?"}]
  }'
```

**Prerequisites:** Docker 24+, Python 3.11+, 16 GB RAM, 20 GB free disk.

---

## Usage Scenarios

### Basic RAG Query

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "rag-proxy",
    "messages": [{"role": "user", "content": "Explain the deployment process"}],
    "temperature": 0.3
  }'
```

### Streaming Response

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "rag-proxy",
    "messages": [{"role": "user", "content": "Summarize the Q3 report"}],
    "stream": true
  }'
```

### Agentic Tool Calling

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "rag-proxy",
    "messages": [{"role": "user", "content": "What Jira tickets are blocking the release?"}],
    "tools": [{"type": "function", "function": {"name": "jira_search"}}]
  }'
```

### Python Client (OpenAI SDK)

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8080/v1", api_key="not-needed")

response = client.chat.completions.create(
    model="rag-proxy",
    messages=[{"role": "user", "content": "What is our security policy?"}],
    temperature=0.3,
)
print(response.choices[0].message.content)
```

### Federated Search

```bash
curl -X POST http://localhost:8081/v1/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "employee benefits policy",
    "federation_mode": "auto"
  }'
```

### Embeddable Widget

```html
<script src="http://localhost:8080/v1/widget.js"></script>
<rag-chat
  api-url="http://localhost:8080/v1"
  placeholder="Ask me anything...">
</rag-chat>
```

---

## Architecture

```
┌──────────────────────────────────────────────────────┐
│                    RAG Proxy :8080                     │
│                                                        │
│  ┌─────────────────────────────────────────────────┐  │
│  │         LangGraph Orchestrator (10 nodes)         │  │
│  │                                                   │  │
│  │  rewrite → retrieve → check → rerank             │  │
│  │     ↓                                              │  │
│  │  graph_expand → build → generate                  │  │
│  │     ↓                                              │  │
│  │  call_tools → self_reflection → confidence        │  │
│  └─────────────────────────────────────────────────┘  │
│                                                        │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐            │
│  │  Qdrant  │  │  Neo4j   │  │  Redis   │            │
│  │  Vector  │  │  Graph   │  │  Cache   │            │
│  └──────────┘  └──────────┘  └──────────┘            │
└──────────────────────────────────────────────────────┘
```

| Component | Technology | Role |
|-----------|-----------|------|
| **Orchestrator** | LangGraph, 10 nodes | Agentic query pipeline with self-correction |
| **Retrieval** | Qdrant hybrid (dense+sparse+ColBERT) | Multi-vector search, RRF fusion |
| **Reranker** | Cross-encoder (MiniLM-L-6-v2) | Precision filtering, fine-tunable |
| **Graph** | Neo4j (10 entity types, 9 relations) | Entity extraction, multi-hop traversal |
| **Cache** | Redis multi-tier | Embedding, rerank, response caching |
| **LLM** | vLLM / llama.cpp / OpenAI-compatible / Anthropic | Response generation |
| **SLM** | ~2-3B params: Llama, Gemma, Qwen | Intent classification, entity extraction |
| **Auth** | JWT + Keycloak OIDC + LDAP/AD | SSO, RBAC (4 roles), token pairs |

### RAG Maturity: Level 5 — Self-Correcting

| Level | Capability | Status |
|-------|-----------|--------|
| 1 | Naive RAG — single dense retrieval | ✅ Exceeded |
| 2 | Advanced RAG — hybrid, rerank, dedup, versioning | ✅ Implemented |
| 3 | GraphRAG — Neo4j entity extraction, multi-hop | ✅ Implemented |
| 4 | Agentic — 10-node LangGraph, retrieval loops, tool calling | ✅ Implemented |
| 5 | Self-Correcting — CRAG, HyDE, self-reflection, NLI | ✅ Implemented |

**Composite score: 4.5/5.0.** [Full assessment →](guides/rag-maturity-assessment.md)

---

## Navigation

### Getting Started

| I want to... | Go to... |
|-------------|---------|
| Understand the architecture | [Architecture](architecture.md) |
| Deploy the proxy | [Proxy Deployment](deploy_proxy.md) |
| Deploy the ETL pipeline | [ETL Deployment](deploy_etl.md) |
| Call the API | [API Reference](api_reference.md) |
| Set up a dev environment | [Development Guide](guides/development-guide.md) |
| Integrate with IDE | [OpenCode Integration](guides/integration-opencode.md) |
| Set up air-gapped | [Deployment Guide](guides/deployment-guide.md) |

### Deep Dives

| I want to... | Go to... |
|-------------|---------|
| Understand architecture decisions | [Architecture Decision Records](adr/index.md) |
| See visual architecture | [C4 Diagrams](diagrams/index.md) |
| Understand knowledge graph | [Knowledge Graph Strategy](guides/knowledge-graph-strategy.md) |
| Understand access control | [Access Control & RBAC](guides/access-control-rbac.md) |
| Assess retrieval quality | [RAG Maturity Assessment](guides/rag-maturity-assessment.md) |
| Assess production readiness | [Production Checklist](guides/best-practices-checklist.md) |

### Features

| I want to... | Go to... |
|-------------|---------|
| Define custom tools (Python) | [Agentic Tools SDK](guides/agentic-tools-sdk.md) |
| Define tools in YAML/JSON | [Declarative Tools](guides/agentic-tools-declarative.md) |
| Auto-discover API tools | [OpenAPI Discovery](guides/agentic-tools-openapi.md) |
| Set up federated search | Deployment Guide |
| Fine-tune models | [Model Evolution](#) |
| Add a data source | [Extensibility Guide](guides/extensibility-data-sources.md) |

### Operations

| I want to... | Go to... |
|-------------|---------|
| Monitor in production | [Operations Guide](guides/operations-guide.md) |
| Tune performance | [Performance & Quality](guides/performance-quality.md) |
| Recover from failure | [Disaster Recovery Runbook](guides/disaster-recovery-runbook.md) |
| Debug an issue | [Troubleshooting](guides/troubleshooting.md) |
| See what's coming | [Roadmap](guides/roadmap.md) |

---

## API at a Glance

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `POST` | `/v1/chat/completions` | Optional | Main RAG endpoint (streaming + non-streaming) |
| `GET` | `/v1/models` | No | Available models |
| `GET` | `/v1/health` | No | Health (Qdrant + LLM status) |
| `GET` | `/v1/health/live` | No | K8s liveness probe |
| `GET` | `/v1/health/ready` | No | K8s readiness probe |
| `POST` | `/v1/feedback` | Expert | Expert feedback submission |
| `POST` | `/v1/auth/register` | No | Self-registration |
| `POST` | `/v1/auth/login` | No | JWT access + refresh tokens |
| `POST` | `/v1/auth/refresh` | JWT | Refresh token exchange |
| `POST` | `/v1/auth/logout` | JWT | Token revocation |
| `GET` | `/v1/auth/me` | JWT | User context |
| `GET` | `/v1/widget` | No | Embeddable chat widget (HTML) |
| `GET` | `/v1/widget.js` | No | Widget JavaScript |
| `GET` | `/v1/tools` | Optional | List tools (with filters) |
| `GET` | `/v1/tools/{name}` | Optional | Tool details |
| `POST` | `/v1/admin/models/train` | Admin | Trigger training |
| `GET` | `/v1/admin/models/status/{id}` | Admin | Training progress |
| `GET` | `/v1/admin/models` | Admin | Model registry |
| `POST` | `/v1/admin/models/promote` | Admin | Promote version |
| `POST` | `/v1/admin/models/rollback` | Admin | Rollback version |
| `POST` | `/v1/admin/models/evaluate` | Admin | Evaluate quality |
| `POST` | `/v1/admin/models/canary/split` | Admin | Canary traffic |
| `GET` | `/v1/admin/models/canary/status` | Admin | Canary status |
| `GET` | `/metrics` | No | Prometheus metrics |

[Full API Reference →](api_reference.md)

---

## Project Status

| Dimension | Ready | Details |
|-----------|-------|---------|
| **Code Quality** | 90% | ruff, mypy, pre-commit hooks |
| **Testing** | 90% | 2275 tests, 99%+ pass rate, E2E + chaos |
| **Security** | 90% | JWT + RBAC + LDAP + input sanitization |
| **Observability** | 90% | Prometheus + Grafana + structured logging |
| **Reliability** | 100% | Circuit breakers, graceful degradation, HA |
| **Performance** | 100% | HNSW, quantization, SSE TTFT, compression |
| **Operations** | 90% | K8s Helm, backup automation, DR runbook |
| **Documentation** | 100% | 10 ADRs, 4 C4 diagrams, 16 guides |
| **Overall** | **94%** (75/80) | Production-ready |

[Full assessment →](guides/best-practices-checklist.md)

---

## Design Principles

1. **Air-gapped first** — Models pre-downloaded. No external API calls. Fully offline.
2. **Graceful degradation** — Every component fails independently. Proxy never crashes.
3. **Incremental by default** — WAL checkpointing, SHA-256 content addressing.
4. **OpenAI compatibility** — Drop-in replacement. RAG extensions transparent.
5. **Dual-model routing** — SLM for fast preprocessing, LLM for generation.
6. **Multi-provider** — vLLM, llama.cpp, Anthropic, Ollama, OpenAI-compatible.
7. **Optional complexity** — LangGraph, Neo4j, Redis all optional.
8. **Token economy** — BPE counting, 4 compression strategies, budget allocation.
