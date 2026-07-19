# Configuration Reference

**Version:** v2.0.0 | **Last Updated:** 2026-07-12

Complete reference for all configuration options in the RAG System. Covers proxy environment variables (`proxy/.env`),
ETL pipeline settings (`etl/config/etl_config.yaml`), and Docker Compose overrides.

---

## Proxy Configuration (proxy/.env)

All proxy settings are loaded from environment variables. Copy the example file to get started:

```bash
cp .env.example proxy/.env
```

### Qdrant (Vector Database)

| Variable          | Type   | Default          | Description                                             |
|-------------------|--------|------------------|---------------------------------------------------------|
| `QDRANT_HOST`     | string | `localhost`      | Qdrant server hostname. Use `qdrant` in Docker Compose. |
| `QDRANT_PORT`     | int    | `6333`           | Qdrant HTTP API port.                                   |
| `COLLECTION_NAME` | string | `knowledge_base` | Primary collection for hybrid search.                   |

**Example:**

```ini
QDRANT_HOST=qdrant
QDRANT_PORT=6333
COLLECTION_NAME=knowledge_base
```

---

### Embedding Model

| Variable                  | Type   | Default | Description                                                                             |
|---------------------------|--------|---------|-----------------------------------------------------------------------------------------|
| `EMBEDDER_MODEL`          | string | `""`    | **REQUIRED.** HuggingFace model ID or local path.                                       |
| `EMBEDDER_DEVICE`         | string | `cpu`   | Device for inference: `cpu` or `cuda`.                                                  |
| `EMBEDDER_ENDPOINT`       | string | `""`    | Remote embedding service URL (OpenAI `/v1/embeddings` compatible). Empty = local model. |
| `EMBEDDER_API_KEY`        | string | `""`    | API key for remote embedder.                                                            |
| `EMBEDDER_FALLBACK_LOCAL` | bool   | `true`  | Fall back to local SentenceTransformer if remote unavailable.                           |

**Recommended models:**

| Model                                    | Dims | Context | Size    | Use Case                                        |
|------------------------------------------|------|---------|---------|-------------------------------------------------|
| `BAAI/bge-m3`                            | 1024 | 8192    | ~2 GB   | Production (multilingual, dense+sparse+ColBERT) |
| `intfloat/multilingual-e5-large`         | 1024 | 512     | ~1.3 GB | Good multilingual quality                       |
| `sentence-transformers/all-MiniLM-L6-v2` | 384  | 256     | ~90 MB  | Lightweight / testing                           |

**Example:**

```ini
EMBEDDER_MODEL=BAAI/bge-m3
EMBEDDER_DEVICE=cpu
```

**Remote embedder example:**

```ini
EMBEDDER_ENDPOINT=http://embedder-service:8080/v1
EMBEDDER_API_KEY=your-api-key
EMBEDDER_FALLBACK_LOCAL=true
```

**GPUStack embedder example:**

```ini
EMBEDDER_ENDPOINT=http://<gpu-host>:80/v1
EMBEDDER_API_KEY=gpustack_<your-api-key>
EMBEDDER_FALLBACK_LOCAL=true
```

---

### Reranker (Cross-Encoder)

| Variable                  | Type   | Default | Description                                                   |
|---------------------------|--------|---------|---------------------------------------------------------------|
| `RERANKER_MODEL`          | string | `""`    | **REQUIRED.** HuggingFace model ID or local path.             |
| `RERANKER_MAX_LENGTH`     | int    | `512`   | Maximum token length per chunk for reranking.                 |
| `RERANKER_BATCH_SIZE`     | int    | `32`    | Batch size for reranker inference. Reduce if OOM.             |
| `RERANKER_ENDPOINT`       | string | `""`    | Remote reranker service URL (Cohere `/v1/rerank` compatible). |
| `RERANKER_API_KEY`        | string | `""`    | API key for remote reranker.                                  |
| `RERANKER_FALLBACK_LOCAL` | bool   | `true`  | Fall back to local CrossEncoder if remote unavailable.        |

**Recommended models:**

| Model                                  | Context | Size    | Use Case                   |
|----------------------------------------|---------|---------|----------------------------|
| `cross-encoder/ms-marco-MiniLM-L-6-v2` | 512     | ~90 MB  | Fast, English-focused      |
| `BAAI/bge-reranker-v2-m3`              | 8192    | ~1.5 GB | Multilingual, high quality |
| `mixedbread-ai/mxbai-rerank-large-v1`  | 512     | ~1.3 GB | High accuracy              |

**Example:**

```ini
RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2
RERANKER_MAX_LENGTH=512
RERANKER_BATCH_SIZE=32
```

**GPUStack reranker example:**

```ini
RERANKER_ENDPOINT=http://<gpu-host>:80/v1
RERANKER_API_KEY=gpustack_<your-api-key>
RERANKER_FALLBACK_LOCAL=true
```

---

### LLM (Primary Language Model)

| Variable            | Type   | Default                    | Description                                          |
|---------------------|--------|----------------------------|------------------------------------------------------|
| `LLM_ENDPOINT`      | string | `http://localhost:8000/v1` | **REQUIRED.** OpenAI-compatible endpoint URL.        |
| `LLM_MODEL_NAME`    | string | `""`                       | **REQUIRED.** Model identifier sent in API requests. |
| `LLM_API_KEY`       | string | `None`                     | API key (only if backend requires it).               |
| `LLM_PROVIDER_TYPE` | string | `openai`                   | Provider type: `openai`, `anthropic`, `generic`.     |
| `REQUEST_TIMEOUT`   | int    | `120`                      | Timeout in seconds for LLM calls.                    |
| `MAX_RETRIES`       | int    | `3`                        | Retry attempts on transient failures.                |
| `RETRY_DELAY`       | float  | `1.0`                      | Delay between retries in seconds.                    |

**Example (vLLM):**

```ini
LLM_ENDPOINT=http://vllm:8000/v1
LLM_MODEL_NAME=Llama-3.1-70B-Instruct
LLM_API_KEY=
REQUEST_TIMEOUT=120
```

**Example (Ollama):**

```ini
LLM_ENDPOINT=http://localhost:11434/v1
LLM_MODEL_NAME=llama3.1:70b
LLM_PROVIDER_TYPE=generic
```

**Example (OpenAI API):**

```ini
LLM_ENDPOINT=https://api.openai.com/v1
LLM_MODEL_NAME=gpt-4o
LLM_API_KEY=sk-...
LLM_PROVIDER_TYPE=openai
```

**Example (GPUStack):**

```ini
LLM_ENDPOINT=http://<gpu-host>:80/v1
LLM_MODEL_NAME=Qwen3-635B-AWQ-T
LLM_API_KEY=gpustack_<your-api-key>
LLM_PROVIDER_TYPE=openai
```

---

### SLM (Small Language Model)

SLM handles lightweight tasks: intent classification, query decomposition, entity extraction. Leave `SLM_ENDPOINT` empty
to disable (heuristic fallback is used).

| Variable         | Type   | Default | Description                             |
|------------------|--------|---------|-----------------------------------------|
| `SLM_ENDPOINT`   | string | `""`    | SLM API endpoint URL. Empty = disabled. |
| `SLM_MODEL_NAME` | string | `""`    | SLM model identifier.                   |
| `SLM_API_KEY`    | string | `None`  | SLM API key.                            |
| `SLM_MAX_TOKENS` | int    | `256`   | Maximum tokens for SLM responses.       |

**Recommended SLM models:**

| Model                              | Params | Context | Use Case                          |
|------------------------------------|--------|---------|-----------------------------------|
| `Qwen/Qwen2.5-3B-Instruct`         | 3B     | 32K     | Best balance of speed and quality |
| `gemma-2b-it`                      | 2B     | 8K      | Fastest, lightweight              |
| `microsoft/Phi-3-mini-4k-instruct` | 3.8B   | 4K      | Strong reasoning                  |

**Example:**

```ini
SLM_ENDPOINT=http://slm:8000/v1
SLM_MODEL_NAME=Qwen/Qwen2.5-3B-Instruct
SLM_MAX_TOKENS=256
```

---

### SLM Local (llama.cpp Subprocess)

For air-gapped deployments, run SLM locally via llama.cpp subprocess.

| Variable                    | Type   | Default                            | Description                                     |
|-----------------------------|--------|------------------------------------|-------------------------------------------------|
| `SLM_LOCAL_ENABLED`         | bool   | `false`                            | Enable local llama.cpp subprocess mode.         |
| `SLM_LOCAL_BINARY`          | string | `llama.cpp/build/bin/llama-server` | Path to llama-server binary.                    |
| `SLM_LOCAL_MODEL_PATH`      | string | `""`                               | Path to `.gguf` model file.                     |
| `SLM_LOCAL_CONTEXT_SIZE`    | int    | `4096`                             | Context size in tokens.                         |
| `SLM_LOCAL_THREADS`         | int    | `4`                                | CPU threads for inference.                      |
| `SLM_LOCAL_PORT`            | int    | `8081`                             | Port for local llama-server. `0` = auto-assign. |
| `SLM_LOCAL_STARTUP_TIMEOUT` | int    | `60`                               | Max seconds to wait for server ready.           |

**Example:**

```ini
SLM_LOCAL_ENABLED=true
SLM_LOCAL_BINARY=/usr/local/bin/llama-server
SLM_LOCAL_MODEL_PATH=/opt/models/slm-model.gguf
SLM_LOCAL_CONTEXT_SIZE=4096
SLM_LOCAL_THREADS=8
SLM_LOCAL_PORT=8081
```

---

### Retrieval Parameters

| Variable                  | Type | Default | Description                                   |
|---------------------------|------|---------|-----------------------------------------------|
| `MAX_CHUNKS_RETRIEVAL`    | int  | `50`    | Chunks fetched from Qdrant before reranking.  |
| `MAX_CHUNKS_AFTER_RERANK` | int  | `20`    | Chunks passed to LLM context after reranking. |

**Example:**

```ini
MAX_CHUNKS_RETRIEVAL=50
MAX_CHUNKS_AFTER_RERANK=20
```

!!! tip
Reduce `MAX_CHUNKS_RETRIEVAL` to 20 and `MAX_CHUNKS_AFTER_RERANK` to 10 if you experience OOM errors on the proxy.

---

### Redis Cache

| Variable    | Type   | Default                  | Description                                               |
|-------------|--------|--------------------------|-----------------------------------------------------------|
| `USE_REDIS` | bool   | `false`                  | Enable Redis-backed semantic cache.                       |
| `REDIS_URL` | string | `redis://localhost:6379` | Redis connection URL. Use `redis://redis:6379` in Docker. |

**Example:**

```ini
USE_REDIS=true
REDIS_URL=redis://redis:6379
```

---

### LangGraph Agentic Orchestration

| Variable              | Type | Default | Description                                      |
|-----------------------|------|---------|--------------------------------------------------|
| `USE_LANGGRAPH`       | bool | `false` | Enable multi-step agentic retrieval loops.       |
| `MAX_RETRIEVAL_LOOPS` | int  | `3`     | Maximum iteration count for the LangGraph agent. |

**Example:**

```ini
USE_LANGGRAPH=true
MAX_RETRIEVAL_LOOPS=3
```

---

### Neo4j Knowledge Graph

| Variable              | Type   | Default                 | Description                                           |
|-----------------------|--------|-------------------------|-------------------------------------------------------|
| `GRAPH_ENABLED`       | bool   | `false`                 | Enable GraphRAG entity expansion.                     |
| `NEO4J_URI`           | string | `bolt://localhost:7687` | Neo4j Bolt protocol URI.                              |
| `NEO4J_USER`          | string | `neo4j`                 | Neo4j username.                                       |
| `NEO4J_PASSWORD`      | string | `neo4j`                 | Neo4j password. **Change in production.**             |
| `USE_GRAPH_EXPANSION` | bool   | `false`                 | Enable entity-based graph traversal during retrieval. |

**Example:**

```ini
GRAPH_ENABLED=true
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=change-this-password
USE_GRAPH_EXPANSION=true
```

---

### Authentication & JWT

| Variable                      | Type   | Default | Description                                                               |
|-------------------------------|--------|---------|---------------------------------------------------------------------------|
| `AUTH_ENABLED`                | bool   | `false` | Enable JWT authentication on all endpoints.                               |
| `JWT_SECRET`                  | string | `""`    | Secret for HS256 signing. Min 32 bytes. Generate: `openssl rand -hex 32`. |
| `JWT_ALGORITHM`               | string | `HS256` | Algorithm: `HS256` (local) or `RS256` (Keycloak/OIDC).                    |
| `JWT_PUBLIC_KEY`              | string | `""`    | PEM public key for RS256 verification.                                    |
| `TOKEN_EXPIRE_HOURS`          | int    | `24`    | Token expiration in hours.                                                |
| `ACCESS_TOKEN_MINUTES`        | int    | `60`    | Short-lived access token lifetime in minutes.                             |
| `REFRESH_TOKEN_DAYS`          | int    | `7`     | Refresh token lifetime in days.                                           |
| `TOKEN_BLACKLIST_MAX_ENTRIES` | int    | `10000` | Max entries in token blacklist (LRU eviction).                            |
| `AUTH_VALID_USERS`            | string | `"{}"`  | JSON dict of valid users for login endpoint.                              |

**Example:**

```ini
AUTH_ENABLED=true
JWT_SECRET=$(openssl rand -hex 32)
JWT_ALGORITHM=HS256
ACCESS_TOKEN_MINUTES=60
REFRESH_TOKEN_DAYS=7
```

---

### User Database (SQLite)

| Variable        | Type   | Default           | Description                                            |
|-----------------|--------|-------------------|--------------------------------------------------------|
| `USER_DB_PATH`  | string | `./data/users.db` | Path to SQLite user database.                          |
| `BCRYPT_ROUNDS` | int    | `12`              | Password hashing rounds. Higher = slower, more secure. |

---

### RBAC (Role-Based Access Control)

| Variable       | Type | Default | Description                       |
|----------------|------|---------|-----------------------------------|
| `RBAC_ENABLED` | bool | `false` | Enable role-based access control. |

Roles: `admin`, `expert`, `user`, `read_only`.

---

### Keycloak OIDC

| Variable             | Type   | Default     | Description                                 |
|----------------------|--------|-------------|---------------------------------------------|
| `KEYCLOAK_URL`       | string | `""`        | Keycloak base URL. Enables RS256 OIDC mode. |
| `KEYCLOAK_REALM`     | string | `master`    | Keycloak realm name.                        |
| `KEYCLOAK_CLIENT_ID` | string | `rag-proxy` | Keycloak client ID.                         |

**Example:**

```ini
KEYCLOAK_URL=https://keycloak.company.com
KEYCLOAK_REALM=rag
KEYCLOAK_CLIENT_ID=rag-proxy
```

---

### LDAP / Active Directory

| Variable              | Type   | Default                   | Description                                          |
|-----------------------|--------|---------------------------|------------------------------------------------------|
| `AD_ENABLED`          | bool   | `false`                   | Enable LDAP/AD authentication.                       |
| `AD_URL`              | string | `""`                      | LDAP server URL (e.g., `ldap://ad.company.com:389`). |
| `AD_BASE_DN`          | string | `""`                      | Base DN for user search.                             |
| `AD_USER_DN_TEMPLATE` | string | `cn={username},{base_dn}` | User DN template.                                    |
| `AD_GROUP_DN`         | string | `""`                      | Group DN for authorization.                          |

---

### Rate Limiting

| Variable                | Type | Default | Description                               |
|-------------------------|------|---------|-------------------------------------------|
| `RATE_LIMIT_ENABLED`    | bool | `false` | Enable token bucket rate limiting per IP. |
| `RATE_LIMIT_PER_MINUTE` | int  | `60`    | Requests per minute per IP.               |
| `RATE_LIMIT_BURST`      | int  | `10`    | Burst capacity above the rate limit.      |

**Example:**

```ini
RATE_LIMIT_ENABLED=true
RATE_LIMIT_PER_MINUTE=60
RATE_LIMIT_BURST=10
```

---

### Observability

| Variable          | Type   | Default  | Description                                                 |
|-------------------|--------|----------|-------------------------------------------------------------|
| `METRICS_ENABLED` | bool   | `true`   | Enable Prometheus `/metrics` endpoint.                      |
| `LOG_FORMAT`      | string | `text`   | Log format: `text` or `json`.                               |
| `LOG_LEVEL`       | string | `INFO`   | Log level: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. |
| `LOG_REQUESTS`    | bool   | `true`   | Log incoming HTTP requests.                                 |
| `LOG_DIR`         | string | `./logs` | Directory for log files.                                    |

**Example (production):**

```ini
METRICS_ENABLED=true
LOG_FORMAT=json
LOG_LEVEL=INFO
LOG_REQUESTS=true
```

---

### OpenTelemetry Tracing

| Variable                       | Type   | Default                           | Description                               |
|--------------------------------|--------|-----------------------------------|-------------------------------------------|
| `OTEL_ENABLED`                 | bool   | `false`                           | Enable OpenTelemetry distributed tracing. |
| `OTEL_EXPORTER_ENDPOINT`       | string | `http://localhost:4318/v1/traces` | OTLP HTTP collector endpoint.             |
| `OTEL_SERVICE_NAME`            | string | `rag-proxy`                       | Service name in traces.                   |
| `OTEL_BATCH_TIMEOUT`           | int    | `5`                               | Batch export timeout in seconds.          |
| `OTEL_MAX_ATTRIBUTES_PER_SPAN` | int    | `128`                             | Max attributes per span.                  |

---

### CORS

| Variable       | Type   | Default | Description                                   |
|----------------|--------|---------|-----------------------------------------------|
| `CORS_ORIGINS` | string | `*`     | Allowed CORS origins. Comma-separated or `*`. |

**Example:**

```ini
CORS_ORIGINS=https://app.company.com,https://dashboard.company.com
```

---

### Input Sanitization & Security

| Variable                      | Type   | Default | Description                                               |
|-------------------------------|--------|---------|-----------------------------------------------------------|
| `SANITIZE_INPUT`              | bool   | `true`  | Sanitize user inputs (SQL injection, XSS, length limits). |
| `SENSITIVE_SECRETS`           | string | `""`    | Comma-separated secret values to mask in logs.            |
| `AUDIT_ENABLED`               | bool   | `true`  | Enable audit logging for security events.                 |
| `NAMESPACE_ISOLATION_ENABLED` | bool   | `false` | Enable namespace-based data isolation.                    |

---

### Confidence Scoring

| Variable                          | Type  | Default | Description                                             |
|-----------------------------------|-------|---------|---------------------------------------------------------|
| `CONFIDENCE_THRESHOLD`            | float | `0.5`   | Minimum confidence before escalation or "I don't know". |
| `CONFIDENCE_THRESHOLD_CALIBRATED` | float | `0`     | Calibrated threshold. `0` = use heuristic fallback.     |
| `MAX_VERIFY_LOOPS`                | int   | `2`     | Max retry loops for verification cascade.               |
| `NLI_GROUNDING_ENABLED`           | bool  | `true`  | Enable NLI-based fact verification against context.     |

---

### Self-Correction (CRAG)

| Variable                     | Type   | Default   | Description                                           |
|------------------------------|--------|-----------|-------------------------------------------------------|
| `SELF_CRITIQUE_ENABLED`      | bool   | `true`    | Enable self-critique of generated answers.            |
| `COMPRESSION_STRATEGY`       | string | `keyword` | Context compression: `perplexity`, `keyword`, `none`. |
| `REORDER_ENABLED`            | bool   | `true`    | Reorder context chunks by relevance.                  |
| `CRAG_DECOMPOSITION_ENABLED` | bool   | `true`    | Enable query decomposition for corrective RAG.        |
| `NLI_MODEL_ENABLED`          | bool   | `false`   | Use NLI model for grounding (requires more VRAM).     |

---

### HyDE & Reflection (Level 5 RAG)

| Variable                      | Type | Default | Description                                              |
|-------------------------------|------|---------|----------------------------------------------------------|
| `HYDE_ENABLED`                | bool | `true`  | Enable Hypothetical Document Embeddings query expansion. |
| `REFLECTION_ENABLED`          | bool | `true`  | Enable self-reflection and answer regeneration.          |
| `REFLECTION_DEPTH`            | int  | `2`     | Number of reflection iterations.                         |
| `HALLUCINATION_CHECK_ENABLED` | bool | `false` | Enable full hallucination detection pipeline.            |

---

### Self-Enrichment

| Variable             | Type | Default | Description                                           |
|----------------------|------|---------|-------------------------------------------------------|
| `ENRICHMENT_ENABLED` | bool | `false` | Feed accepted Q&A pairs back into the knowledge base. |

---

### Multi-Modal RAG

| Variable                    | Type   | Default                  | Description                                      |
|-----------------------------|--------|--------------------------|--------------------------------------------------|
| `MULTI_MODAL_ENABLED`       | bool   | `true`                   | Enable multi-modal retrieval support.            |
| `COLBERT_ENABLED`           | bool   | `true`                   | Enable ColBERT late-interaction vectors.         |
| `IMAGE_MODEL`               | string | `clip-ViT-B-32`          | CLIP model for image embeddings.                 |
| `IMAGE_EXTRACTION_ENABLED`  | bool   | `false`                  | Extract and embed images from documents.         |
| `AST_LANGUAGES`             | string | `python,javascript,java` | Languages for AST-based code chunking.           |
| `TABLE_EXTRACTION_ENABLED`  | bool   | `false`                  | Extract and index tables from documents.         |
| `CODE_CHUNKING_ENABLED`     | bool   | `false`                  | Enable AST-aware code chunking.                  |
| `COLD_STORAGE_MAX_VERSIONS` | int    | `5`                      | Max document versions to retain in cold storage. |

---

### Token Optimizer

| Variable                  | Type | Default | Description                                            |
|---------------------------|------|---------|--------------------------------------------------------|
| `TOKEN_OPTIMIZER_ENABLED` | bool | `true`  | Enable BPE-aware token counting and budget allocation. |

---

### vLLM Prefix Caching

| Variable                 | Type | Default | Description                                                                 |
|--------------------------|------|---------|-----------------------------------------------------------------------------|
| `PREFIX_CACHING_ENABLED` | bool | `false` | Enable prefix caching support (requires `--enable-prefix-caching` in vLLM). |

---

### Response Compression

| Variable               | Type | Default | Description                                 |
|------------------------|------|---------|---------------------------------------------|
| `COMPRESSION_ENABLED`  | bool | `true`  | Enable gzip/brotli response compression.    |
| `COMPRESSION_MIN_SIZE` | int  | `500`   | Minimum response size in bytes to compress. |
| `COMPRESSION_LEVEL`    | int  | `6`     | Gzip compression level (1-9).               |

---

### SSE Streaming

| Variable             | Type | Default | Description                     |
|----------------------|------|---------|---------------------------------|
| `SSE_CHUNK_SIZE`     | int  | `4`     | Number of tokens per SSE chunk. |
| `STREAM_BUFFER_SIZE` | int  | `1`     | Stream buffer size.             |

---

### Model Warm-Up

| Variable            | Type | Default | Description                                |
|---------------------|------|---------|--------------------------------------------|
| `WARMUP_ENABLED`    | bool | `true`  | Enable model warm-up on first request.     |
| `WARMUP_ON_STARTUP` | bool | `true`  | Warm up models during application startup. |

---

### Tools / Function Calling

| Variable                   | Type   | Default               | Description                                          |
|----------------------------|--------|-----------------------|------------------------------------------------------|
| `TOOLS_ENABLED`            | bool   | `false`               | Enable tool calling support.                         |
| `LIVE_SOURCES_ENABLED`     | bool   | `false`               | Enable live source tools (Confluence, Jira, GitLab). |
| `TOOLS_PARALLEL_EXECUTION` | bool   | `true`                | Execute independent tools in parallel.               |
| `TOOLS_MAX_CONCURRENCY`    | int    | `10`                  | Maximum concurrent tool executions.                  |
| `TOOLS_DECLARATIVE_DIR`    | string | `./tools/declarative` | Directory for YAML/JSON tool definitions.            |
| `TOOLS_OPENAPI_SPECS`      | string | `""`                  | JSON array of OpenAPI spec URLs for auto-discovery.  |

**Example:**

```ini
TOOLS_ENABLED=true
LIVE_SOURCES_ENABLED=true
TOOLS_PARALLEL_EXECUTION=true
TOOLS_MAX_CONCURRENCY=10
TOOLS_OPENAPI_SPECS='[{"name":"petstore","url":"https://example.com/openapi.json","mode":"auto"}]'
```

---

### Live Source APIs

| Variable               | Type   | Default | Description                                |
|------------------------|--------|---------|--------------------------------------------|
| `CONFLUENCE_API_URL`   | string | `""`    | Confluence base URL.                       |
| `CONFLUENCE_API_TOKEN` | string | `""`    | Confluence API token.                      |
| `CONFLUENCE_API_USER`  | string | `""`    | Confluence username (if using basic auth). |
| `JIRA_API_URL`         | string | `""`    | Jira base URL.                             |
| `JIRA_API_TOKEN`       | string | `""`    | Jira API token.                            |
| `JIRA_API_USER`        | string | `""`    | Jira username.                             |
| `GITLAB_API_URL`       | string | `""`    | GitLab base URL.                           |
| `GITLAB_API_TOKEN`     | string | `""`    | GitLab personal access token.              |

---

### I18N / Multi-Language

| Variable                      | Type   | Default          | Description                                |
|-------------------------------|--------|------------------|--------------------------------------------|
| `I18N_ENABLED`                | bool   | `true`           | Enable internationalization support.       |
| `DEFAULT_LANGUAGE`            | string | `en`             | Default language code.                     |
| `SUPPORTED_LANGUAGES`         | string | `en,ru,de,fr,zh` | Comma-separated supported language codes.  |
| `MULTILINGUAL_INTENT_ENABLED` | bool   | `true`           | Enable multilingual intent classification. |
| `CROSS_LINGUAL_ENABLED`       | bool   | `true`           | Enable cross-lingual retrieval.            |

---

### Model Evolution

| Variable                  | Type | Default | Description                            |
|---------------------------|------|---------|----------------------------------------|
| `MODEL_EVOLUTION_ENABLED` | bool | `false` | Enable fine-tuning pipeline endpoints. |

#### MLflow

| Variable                 | Type   | Default                 | Description                       |
|--------------------------|--------|-------------------------|-----------------------------------|
| `MLFLOW_TRACKING_URI`    | string | `http://localhost:5000` | MLflow tracking server URL.       |
| `MLFLOW_EXPERIMENT_NAME` | string | `rag-system`            | MLflow experiment name.           |
| `MLFLOW_ARTIFACT_ROOT`   | string | `s3://rag-artifacts`    | Artifact storage root (S3/MinIO). |

#### MinIO

| Variable            | Type   | Default          | Description                                 |
|---------------------|--------|------------------|---------------------------------------------|
| `MINIO_ENDPOINT`    | string | `localhost:9000` | MinIO S3 API endpoint.                      |
| `MINIO_ACCESS_KEY`  | string | `CHANGE_ME`     | MinIO access key. **Change in production.** |
| `MINIO_SECRET_KEY`  | string | `CHANGE_ME`     | MinIO secret key. **Change in production.** |
| `MINIO_BUCKET`      | string | `rag-artifacts`  | Bucket for model artifacts.                 |
| `MINIO_DOCS_BUCKET` | string | `rag-documents`  | Bucket for uploaded documents.              |
| `MINIO_SECURE`      | bool   | `false`          | Use HTTPS for MinIO connection.             |

#### Training

| Variable           | Type   | Default | Description                                 |
|--------------------|--------|---------|---------------------------------------------|
| `TRAINING_PROFILE` | string | `dev`   | Training profile: `dev`, `staging`, `prod`. |

#### Hot-Reload

| Variable                    | Type | Default | Description                             |
|-----------------------------|------|---------|-----------------------------------------|
| `HOT_RELOAD_ENABLED`        | bool | `false` | Enable hot-reload of trained adapters.  |
| `HOT_RELOAD_WATCH_INTERVAL` | int  | `5`     | Check for new adapters every N seconds. |
| `HOT_RELOAD_SIGNAL_ENABLED` | bool | `true`  | Accept SIGHUP for manual reload.        |

#### Canary Deployment

| Variable                   | Type | Default | Description                          |
|----------------------------|------|---------|--------------------------------------|
| `CANARY_ENABLED`           | bool | `false` | Enable canary deployment.            |
| `CANARY_PHASE_DURATION_5`  | int  | `300`   | Duration at 5% traffic (seconds).    |
| `CANARY_PHASE_DURATION_25` | int  | `600`   | Duration at 25% traffic (seconds).   |
| `CANARY_PHASE_DURATION_50` | int  | `900`   | Duration at 50% traffic (seconds).   |
| `CANARY_PHASE_DURATION_75` | int  | `1200`  | Duration at 75% traffic (seconds).   |
| `CANARY_COOLDOWN_SECONDS`  | int  | `3600`  | Cooldown between rollouts (seconds). |

#### Eval Gate Thresholds

| Variable                          | Type  | Default | Description                          |
|-----------------------------------|-------|---------|--------------------------------------|
| `EVAL_GATE_LLM_BERTSCORE_MIN`     | float | `0.70`  | Minimum BERTScore for LLM promotion. |
| `EVAL_GATE_LLM_HALLUCINATION_MAX` | float | `0.05`  | Maximum hallucination rate for LLM.  |
| `EVAL_GATE_LLM_ROUGE_L_MIN`       | float | `0.35`  | Minimum ROUGE-L for LLM promotion.   |
| `EVAL_GATE_SLM_F1_MIN`            | float | `0.85`  | Minimum F1 for SLM promotion.        |
| `EVAL_GATE_SLM_ACCURACY_MIN`      | float | `0.90`  | Minimum accuracy for SLM promotion.  |
| `EVAL_GATE_RERANKER_MRR_MIN`      | float | `0.75`  | Minimum MRR for reranker promotion.  |
| `EVAL_GATE_RERANKER_NDCG_MIN`     | float | `0.70`  | Minimum nDCG for reranker promotion. |

---

### SSL / TLS

| Variable        | Type   | Default | Description                                                 |
|-----------------|--------|---------|-------------------------------------------------------------|
| `SSL_VERIFY`    | bool   | `true`  | Verify SSL certificates. Set `false` for self-signed certs. |
| `SSL_CERT_PATH` | string | `""`    | Path to corporate CA bundle.                                |

---

### Server Settings

| Variable  | Type   | Default   | Description                                  |
|-----------|--------|-----------|----------------------------------------------|
| `HOST`    | string | `0.0.0.0` | Bind address.                                |
| `PORT`    | int    | `8080`    | Listen port.                                 |
| `RELOAD`  | bool   | `false`   | Enable hot reload (development only).        |
| `WORKERS` | int    | `1`       | Uvicorn worker count. Keep at 1 per replica. |

---

### Graceful Shutdown

| Variable                    | Type | Default | Description                                 |
|-----------------------------|------|---------|---------------------------------------------|
| `GRACEFUL_SHUTDOWN_ENABLED` | bool | `true`  | Enable graceful shutdown on SIGTERM.        |
| `SHUTDOWN_TIMEOUT`          | int  | `30`    | Max seconds to wait for in-flight requests. |

---

### A/B Testing

| Variable          | Type | Default | Description                                    |
|-------------------|------|---------|------------------------------------------------|
| `AB_TEST_ENABLED` | bool | `false` | Enable A/B test harness for pipeline variants. |

---

### Admin Alerts

| Variable               | Type   | Default | Description                             |
|------------------------|--------|---------|-----------------------------------------|
| `ADMIN_ALERT_ENABLED`  | bool   | `false` | Alert admins on low-confidence answers. |
| `ADMIN_ALERT_ENDPOINT` | string | `""`    | Webhook URL for admin alerts.           |

---

### Retrieval Evaluation

| Variable            | Type   | Default                    | Description                 |
|---------------------|--------|----------------------------|-----------------------------|
| `EVAL_DATASET_PATH` | string | `./data/eval_dataset.json` | Path to evaluation dataset. |

---

### Dependency Scanning

| Variable                  | Type | Default | Description                               |
|---------------------------|------|---------|-------------------------------------------|
| `DEPENDENCY_SCAN_ENABLED` | bool | `false` | Enable dependency vulnerability scanning. |

---

## ETL Configuration (etl/config/etl_config.yaml)

The ETL pipeline is configured via YAML. Copy and edit the example:

```bash
cp etl/config/etl_config.yaml etl/config/etl_config.local.yaml
```

### Global Settings

```yaml
global:
  timeout: 30              # Global request timeout (seconds)
  connect_timeout: 10      # Connection timeout (seconds)
  max_retries: 3           # Maximum retry attempts
  retry_delay: 2           # Delay between retries (seconds)
```

### WAL (Write-Ahead Log)

```yaml
wal:
  wal_file: "./wal/etl_wal.json"   # Path to WAL file
  use_lock: true                    # Use file locking
  lock_timeout: 30                  # Lock timeout (seconds)
```

### Confluence

```yaml
confluence:
  url: "https://confluence.internal.company.com"
  username: ""                       # Empty for Bearer token auth
  token: "your_personal_access_token"
  verify_ssl: false                  # False for self-signed certificates
  ca_bundle: ""                      # Path to corporate CA bundle
  space_keys:                        # List of space keys (null = all)
    - "DEV"
    - "OPS"
  output_dir: "./raw_data/confluence"
  incremental: true
  download_attachments: true
  max_versions: 0                    # 0 = all versions
  api_version: "2"                   # "2" or "1"
```

### Jira

```yaml
jira:
  url: "https://jira.internal.company.com"
  username: ""
  token: "your_api_token"
  verify_ssl: false
  ca_bundle: ""
  jql: "project in (DEV, OPS) ORDER BY updated DESC"
  output_dir: "./raw_data/jira"
  incremental: true
  download_attachments: true
  max_issues_per_run: 0              # 0 = unlimited
  fields: "*all"
  expand: "changelog,renderedBody"
```

### GitLab

```yaml
gitlab:
  url: "https://gitlab.internal.company.com"
  token: "your_personal_access_token"
  verify_ssl: false
  ca_bundle: ""
  project_ids: null                  # null = all projects, or list [1,2,3]
  output_dir: "./raw_data/gitlab"
  incremental: true
  fetch_commits: true
  fetch_files: true
  fetch_merge_requests: true
  max_commits_per_project: 1000
  since_date: null                   # ISO date, e.g. "2025-01-01T00:00:00Z"
  file_paths_filter:
    - "*.py"
    - "*.md"
    - "Dockerfile"
    - "*.yaml"
    - "*.yml"
    - "*.sql"
```

### Chunking

```yaml
chunking:
  max_tokens: 8000                   # Maximum chunk size (for embedder)
  overlap_tokens: 200                # Overlap between chunks
  min_chunk_tokens: 100              # Minimum chunk size (will be merged)
  use_slm: false                     # Use SLM for enrichment
  slm_endpoint: "http://localhost:8080/v1/completions"
  output_dir: "./chunks"
```

### Indexing

```yaml
indexing:
  qdrant_host: "localhost"
  qdrant_port: 6333
  collection_name: "knowledge_base"
  embedder_model: ""                 # REQUIRED — e.g. BAAI/bge-m3
  embedder_device: "cpu"             # or "cuda"
  batch_size: 100
  hot_dir: "./hot_chunks"            # Current version chunks
  cold_dir: "./cold_chunks"          # History (Parquet)
  lake_dir: "./cold_lake"            # LiveVectorLake cold storage
  use_delta: false                   # Use Delta Lake (requires deltalake)
  version_wal: "./wal/version_wal.json"
  live_upsert_enabled: true          # Atomic chunk-level upserts
```

### Streaming ETL

```yaml
streaming:
  streaming_enabled: false           # Enable real-time streaming mode
  webhook_enabled: true              # Enable webhook server
  webhook_host: "0.0.0.0"
  webhook_port: 9000
  webhook_secret: ""                 # REQUIRED — shared secret for HMAC
  redis_host: "localhost"
  redis_port: 6379
  redis_stream_key: "etl:events"
  redis_consumer_group: "etl-workers"
```

### Schedule

```yaml
schedule:
  enabled: false                     # Enable scheduled ETL runs
  cron_expression: "0 2 * * *"       # Default: daily at 02:00
  timezone: "UTC"
  retry_on_failure: true
  max_retries: 3
  notify_on_failure: true
```

### Graph (Neo4j)

```yaml
graph:
  enabled: false                     # Enable graph building
  use_spacy: true                    # Use spaCy for NER
  spacy_model: ""                    # REQUIRED — e.g. ru_core_news_sm
  use_slm: false                     # Use SLM for relation extraction
  slm_endpoint: "http://localhost:8080/v1/completions"
  cache_dir: "./entity_cache"
  neo4j:
    enabled: false
    uri: "bolt://localhost:7687"
    user: "neo4j"
    password: "your_neo4j_password"
    database: "neo4j"
```

### SSL

```yaml
ssl:
  verify: true                       # false = disable cert verification
  cert_path: ""                      # Path to corporate CA bundle
```

---

## Docker Compose Environment Variables

When running via Docker Compose, some variables are overridden for container networking:

```yaml
# proxy/docker-compose.yml — rag-proxy service
environment:
  - QDRANT_HOST=qdrant              # Container name, not localhost
  - QDRANT_PORT=6333
  - NEO4J_URI=bolt://neo4j:7687     # Container name
  - REDIS_URL=redis://redis:6379    # Container name
  - MINIO_ENDPOINT=minio:9000       # Container name
```

These override any values set in `.env` when running inside Docker Compose.

---

## Quick Configuration Recipes

### Minimal Development Setup

```ini
# proxy/.env — minimal, no auth, no graph, no cache
QDRANT_HOST=localhost
EMBEDDER_MODEL=BAAI/bge-m3
RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2
LLM_ENDPOINT=http://localhost:8000/v1
LLM_MODEL_NAME=your-model-name
```

### Full Production Setup

```ini
# proxy/.env — all features enabled
QDRANT_HOST=qdrant
EMBEDDER_MODEL=BAAI/bge-m3
EMBEDDER_DEVICE=cuda
RERANKER_MODEL=BAAI/bge-reranker-v2-m3
LLM_ENDPOINT=http://vllm:8000/v1
LLM_MODEL_NAME=Llama-3.1-70B-Instruct
SLM_ENDPOINT=http://slm:8000/v1
SLM_MODEL_NAME=Qwen/Qwen2.5-3B-Instruct
USE_REDIS=true
REDIS_URL=redis://redis:6379
USE_LANGGRAPH=true
GRAPH_ENABLED=true
NEO4J_URI=bolt://neo4j:7687
NEO4J_PASSWORD=change-this
AUTH_ENABLED=true
JWT_SECRET=<generate-with-openssl>
RBAC_ENABLED=true
RATE_LIMIT_ENABLED=true
METRICS_ENABLED=true
LOG_FORMAT=json
LOG_LEVEL=INFO
TOOLS_ENABLED=true
MODEL_EVOLUTION_ENABLED=true
```

### Air-Gapped Setup

```ini
# proxy/.env — fully offline
EMBEDDER_MODEL=/opt/models/bge-m3
RERANKER_MODEL=/opt/models/ms-marco-MiniLM-L-6-v2
LLM_ENDPOINT=http://llama-cpp:8000/v1
LLM_MODEL_NAME=/opt/models/llama-3.1-8b-Q4_K_M.gguf
SLM_LOCAL_ENABLED=true
SLM_LOCAL_MODEL_PATH=/opt/models/slm-model.gguf
SSL_VERIFY=false
```

---

## Related Documents

| Document                                                                              | Coverage                                   |
|---------------------------------------------------------------------------------------|--------------------------------------------|
| [Deployment Guide](deployment-guide.md)                                               | Docker Compose, K8s, air-gapped deployment |
| [Operations Guide](operations-guide.md)                                               | Day-2 ops, monitoring, scaling             |
| [Troubleshooting](troubleshooting.md)                                                 | Common issues and resolutions              |
| [API Examples](api-examples.md)                                                       | curl, Python, JavaScript examples          |
| [.env.example](https://github.com/AlexanderNarbaev/rag-system/blob/main/.env.example) | Template with all variables                |
