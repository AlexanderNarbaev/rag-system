# Troubleshooting Guide

**Version:** v2.1.0 | **Last Updated:** 2026-07-06

Comprehensive troubleshooting reference for the RAG Knowledge Assistant. Covers startup, query, retrieval, LLM,
embedding, auth, cache, graph, performance, deployment, federation, and model evolution issues.

---

## Quick Diagnostic Commands

Run these first when something is wrong:

```bash
# Proxy health check (all components)
curl -s http://localhost:8080/v1/health | python3 -m json.tool

# Liveness / readiness probes (K8s-compatible)
curl -s http://localhost:8080/v1/health/live
curl -s http://localhost:8080/v1/health/ready

# All containers status
docker-compose -f proxy/docker-compose.yml ps

# Recent logs across all services
docker-compose -f proxy/docker-compose.yml logs --tail=100

# Prometheus metrics
curl -s http://localhost:8080/metrics | grep -E 'rag_requests_total|circuit_breaker_state|rag_cache_hits_total'

# Check PID on proxy port
ss -tlnp | grep 8080
```

---

## 1. Startup Issues

### 1.1 Proxy Won't Start — Port Already in Use

**Symptom:**

```
OSError: [Errno 98] Address already in use
ERROR:    [Errno 98] error while attempting to bind on address ('0.0.0.0', 8080)
```

```
docker logs rag-proxy | grep -i "address already in use"
```

**Root cause:** Another process is already bound to port 8080.

**Solution:**

```bash
# Find the offending process
ss -tlnp | grep 8080
# or
lsof -i :8080

# Option 1: kill the process
kill -9 <PID>

# Option 2: change proxy port
echo "PORT=8081" >> proxy/.env
# Also update port mapping in docker-compose.yml:
#   ports:
#     - "8081:8080"   # host:container

# Option 3: change host port only (container stays on 8080):
#   ports:
#     - "8081:8080"
docker-compose -f proxy/docker-compose.yml up -d rag-proxy
```

### 1.2 Qdrant Connection Refused

**Symptom:**

```
qdrant_client.http.exceptions.ResponseHandlingException: Failed to connect
ConnectionRefusedError: [Errno 111] Connection refused
```

Proxy health: `"qdrant": "unhealthy"`.

**Root cause:** Qdrant is not running, not reachable at the configured host/port, or the proxy's `.env` does not match
the Docker service name.

**Solution:**

```bash
# 1. Verify Qdrant is running
docker ps | grep qdrant
docker logs rag-qdrant --tail 20

# 2. Check connectivity from host
curl http://localhost:6333/health
curl http://localhost:6333/collections

# 3. Check connectivity from inside proxy container
docker exec rag-proxy curl -s http://qdrant:6333/health

# 4. Verify .env matches docker-compose service name
grep QDRANT_HOST proxy/.env
# Must be: QDRANT_HOST=qdrant   (the docker-compose service name)

# 5. Wait longer for Qdrant to finish booting (large segments)
docker-compose -f proxy/docker-compose.yml restart qdrant
sleep 10
docker exec rag-proxy curl -s http://qdrant:6333/health
```

### 1.3 Model File Not Found (LLM Backend)

**Symptom:**

```
vLLM error: model '/models/model.gguf' not found
OSError: [Errno 2] No such file or directory: '/models/model.gguf'
```

`docker logs rag-vllm | tail -20`

**Root cause:** The model file path is incorrect, the volume mount is wrong, or the model has not been downloaded.

**Solution:**

```bash
# 1. Check what's in the mounted volume
docker exec rag-vllm ls -la /models/

# 2. Verify MODEL_PATH and MODEL_FILE in .env
grep MODEL_PATH proxy/.env
grep MODEL_FILE proxy/.env

# 3. Download the model first (air-gapped: pre-download on host)
python scripts/download_models_offline.py

# 4. Fix the volume mount in docker-compose.yml
#    - ${MODEL_PATH:-/path/to/models}:/models:ro
#    The left side is the HOST path, must exist and contain the model.
ls -la /path/to/models/

# 5. For llama.cpp (non-GPU), use llama-server directly:
#    llama-server -m /models/your-model.gguf --port 8000
```

### 1.4 Permission Denied — Model Cache / Logs

**Symptom:**

```
PermissionError: [Errno 13] Permission denied: '/app/cache'
PermissionError: [Errno 13] Permission denied: '/app/logs'
```

**Root cause:** The container user (UID 1000 by default) cannot write to the mounted host directories.

**Solution:**

```bash
# Fix permissions on the host side
sudo chown -R 1000:1000 /path/to/model_cache
sudo chown -R 1000:1000 proxy/logs/

# Or use world-writable (less secure, for dev only)
sudo chmod -R 777 /path/to/model_cache

# Verify the fix
docker exec rag-proxy touch /app/logs/test && docker exec rag-proxy rm /app/logs/test
```

### 1.5 Missing Dependencies / ModuleNotFoundError

**Symptom:**

```
ModuleNotFoundError: No module named 'fastapi'
ModuleNotFoundError: No module named 'langgraph'
ModuleNotFoundError: No module named 'qdrant_client'
```

**Root cause:** Docker image was not rebuilt after requirements change, or `requirements_proxy.txt` is outdated.

**Solution:**

```bash
# Rebuild the image from scratch
docker-compose -f proxy/docker-compose.yml build --no-cache rag-proxy

# If using local venv (not Docker):
pip install -r proxy/requirements_proxy.txt

# Check which packages are installed in the container
docker exec rag-proxy pip list | grep -E 'fastapi|qdrant|langgraph'
```

### 1.6 Configuration Errors — Proxy Exits Immediately

**Symptom:** Container starts and exits in < 5 seconds with exit code 1.

```
docker logs rag-proxy
# KeyError / ValueError in config parsing
```

**Root cause:** `.env` file has syntax errors, missing required variables, or the file is not mounted.

**Solution:**

```bash
# 1. Print config (safely, secrets masked)
docker run --rm -v $(pwd)/proxy/.env:/app/.env:ro rag-proxy \
  python -c "from app.config import print_config; print_config()"

# 2. Check for common .env mistakes:
#    - Spaces around '=' signs (VAR = value  →  VAR=value)
#    - Missing quotes on values with special characters
#    - Trailing comments not working with all parsers

# 3. Validate .env syntax
python3 -c "
import os
from dotenv import load_dotenv
load_dotenv('proxy/.env')
print('OK: .env loaded successfully')
"

# 4. Check required vars
grep -E '^(LLM_ENDPOINT|LLM_MODEL_NAME|EMBEDDER_MODEL)' proxy/.env
```

### 1.7 Database Initialization Failure (SQLite)

**Symptom:**

```
sqlite3.OperationalError: unable to open database file
sqlite3.OperationalError: database is locked
```

**Root cause:** The SQLite DB directory does not exist, is not writable, or another process has an exclusive lock.

**Solution:**

```bash
# 1. Ensure the data directory exists and is writable
mkdir -p proxy/data
chmod 755 proxy/data

# 2. Check USER_DB_PATH in .env
grep USER_DB_PATH proxy/.env
# Default: USER_DB_PATH=./data/users.db

# 3. If "database is locked", check for stale lock files
ls -la proxy/data/users.db*
# Remove stale journal if DB is not in use
rm -f proxy/data/users.db-journal proxy/data/users.db-wal proxy/data/users.db-shm

# 4. Reset the user DB (wipe all users, only for dev)
rm proxy/data/users.db
docker-compose -f proxy/docker-compose.yml restart rag-proxy
```

---

## 2. Query Issues

### 2.1 Empty Results / No Chunks Found

**Symptom:**

```json
{"choices":[{"message":{"content":"I don't have enough information to answer this question."}}]}
```

Proxy response has `rag_confidence: 0` or `rag_sources: []`.

**Root cause:** No matching chunks in Qdrant. Collections may be empty, embeddings may not match the query, or filter
conditions are too restrictive.

**Solution:**

```bash
# 1. Check if the collection has any vectors
curl -s http://localhost:6333/collections/knowledge_base | python3 -c "
import sys, json
data = json.load(sys.stdin)
result = data.get('result', data)
print(f\"Vectors: {result.get('vectors_count', 'N/A')}\")
print(f\"Segments: {result.get('segments_count', 'N/A')}\")
"

# 2. Run an exact search to verify data exists
curl -X POST http://localhost:6333/collections/knowledge_base/points/scroll \
  -H 'Content-Type: application/json' \
  -d '{"limit": 5, "with_payload": true}' | python3 -m json.tool | head -40

# 3. Check if ETL has indexed any documents
python3 -c "
import json
with open('etl/wal/etl_wal.json') as f:
    wal = json.load(f)
    print('Completed sources:', wal.get('completed_sources', []))
    print('Total chunks indexed:', wal.get('total_chunks', 'N/A'))
"

# 4. Run ETL if collections are empty
python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml

# 5. Try with version filter removed
curl -X POST http://localhost:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"rag-proxy","messages":[{"role":"user","content":"test query"}],"max_tokens":200}'
```

### 2.2 Slow Responses (> 5 seconds)

**Symptom:** p95 latency exceeds the 5-second SLO. `rag_request_duration_seconds` histogram shows high values.

**Root cause:** LLM backend overloaded, Qdrant disk I/O bottleneck, reranker processing too many chunks, or embedding on
CPU.

**Solution:**

```bash
# 1. Check latency breakdown from metrics
curl -s http://localhost:8080/metrics | grep -E 'rag_request_duration_seconds|rag_phase'

# 2. Identify bottleneck phase (embedding vs retrieval vs LLM)
#    Look at logs for timing:
docker logs rag-proxy --tail 100 | grep -E 'duration|elapsed|timeout'

# 3. Reduce retrieval count
# In proxy/.env:
MAX_CHUNKS_RETRIEVAL=20    # was 50
MAX_CHUNKS_AFTER_RERANK=5  # was 20

# 4. Move embedder to GPU (if available)
EMBEDDER_DEVICE=cuda
RERANKER_BATCH_SIZE=8      # reduce if OOM

# 5. Use SLM for fast path (intent, decomposition)
SLM_ENDPOINT=http://vllm:8000/v1
SLM_MODEL_NAME=your-slm-model

# 6. Check Qdrant optimization status
curl -s http://localhost:6333/collections/knowledge_base | python3 -c "
import sys, json
data = json.load(sys.stdin).get('result', {})
print('Segments:', data.get('segments_count'))
print('Indexed vectors:', data.get('indexed_vectors_count', 'N/A'))
"

# 7. Force segment optimization if many unindexed segments
curl -X POST http://localhost:6333/collections/knowledge_base/optimizers \
  -H 'Content-Type: application/json' \
  -d '{"indexing_threshold": 10000}'
```

### 2.3 Timeout Errors (504 / Read Timed Out)

**Symptom:**

```
aiohttp.client_exceptions.ServerTimeoutError
asyncio.TimeoutError
Read timed out
```

Proxy returns `{"error": "LLM request failed after 3 attempts: ..."}`.

**Root cause:** LLM backend taking too long to generate, `REQUEST_TIMEOUT` too short, or backend overloaded.

**Solution:**

```bash
# 1. Increase timeout in proxy/.env
REQUEST_TIMEOUT=300   # 5 minutes (was 120)
MAX_RETRIES=2

# 2. Check LLM backend queue depth / concurrent requests
docker logs rag-vllm --tail 30 | grep -E 'queue|waiting|pending'

# 3. Reduce max_tokens on proxy side
curl -X POST http://localhost:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"rag-proxy","messages":[{"role":"user","content":"test"}],"max_tokens":500}'

# 4. Check backend health directly
curl -s http://localhost:8000/health

# 5. For vLLM, reduce context length
#    In docker-compose.yml vllm command:
#    --max-model-len 32768   (reduce from 65536)

# 6. For llama.cpp, check if model is fully loaded:
docker logs rag-vllm | grep -i 'model loaded'
```

### 2.4 Streaming Hangs Mid-Response

**Symptom:** SSE stream stops partway, client waits indefinitely. `curl -N` hangs.

**Root cause:** LLM backend crashed mid-generation, network buffer overflow, or proxy connection closed before stream
completes.

**Solution:**

```bash
# 1. Check LLM backend for OOM / crash during generation
docker logs rag-vllm --tail 50 | grep -iE 'error|killed|oom|segfault'

# 2. Test streaming directly to backend
curl -N -X POST http://localhost:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"your-model","messages":[{"role":"user","content":"Hello"}],"stream":true,"max_tokens":100}'

# 3. Check proxy SSE config
grep -E 'SSE_CHUNK_SIZE|STREAM_BUFFER_SIZE' proxy/.env
# Defaults: SSE_CHUNK_SIZE=4, STREAM_BUFFER_SIZE=1
# Increase buffer if network is unreliable:
STREAM_BUFFER_SIZE=4

# 4. Check for GPU OOM events
nvidia-smi
dmesg | grep -i 'out of memory'

# 5. Restart LLM backend
docker-compose -f proxy/docker-compose.yml restart vllm
```

### 2.5 500 Internal Server Error

**Symptom:**

```
HTTP 500 Internal Server Error
{"detail": "Internal server error"}
```

**Root cause:** Unhandled exception in proxy code — often a missing dependency, config issue, or external service
failure.

**Solution:**

```bash
# 1. Get full traceback from proxy logs
docker logs rag-proxy --tail 100 | grep -A 20 'Traceback'

# 2. Check for common 500 causes:
#    - Circuit breaker open on a dependency
curl -s http://localhost:8080/metrics | grep circuit_breaker_state
#    State: 0=closed, 1=open, 2=half_open

# 3. Check health of all components
curl -s http://localhost:8080/v1/health | python3 -m json.tool

# 4. Reset circuit breakers (after fixing the underlying issue)
curl -X POST http://localhost:8080/v1/admin/reset-circuit-breakers

# 5. Check for unset required config
docker exec rag-proxy python3 -c "
from app.config import *
required = ['LLM_ENDPOINT','LLM_MODEL_NAME','EMBEDDER_MODEL']
for v in required:
    val = globals().get(v)
    if not val:
        print(f'MISSING: {v}')
"
```

### 2.6 Rate Limit Exceeded (429)

**Symptom:**

```
HTTP 429 Too Many Requests
{"error": "Rate limit exceeded"}
Retry-After: 5
```

**Root cause:** Client is sending requests faster than `RATE_LIMIT_PER_MINUTE` allows.

**Solution:**

```bash
# 1. Increase limits in .env
RATE_LIMIT_ENABLED=true
RATE_LIMIT_PER_MINUTE=120   # was 60
RATE_LIMIT_BURST=20         # was 10

# 2. Check who is being rate-limited
docker logs rag-proxy | grep -i 'rate limit'

# 3. Disable rate limiting (dev only)
RATE_LIMIT_ENABLED=false

# 4. Or add client IP to whitelist (requires code change)
#    See app/rate_limiter.py — modify _extract_key() to skip certain IPs
```

---

## 3. Retrieval Issues

### 3.1 No Chunks Found Despite Data Being Present

**Symptom:** `hybrid_search` returns `[]`, but `scroll` shows vectors exist.

**Root cause:** Version filter mismatch, namespace isolation filtering out results, or RRF fusion dropping all results.

**Solution:**

```bash
# 1. Check if version filter is the cause — search without it
curl -X POST http://localhost:6333/collections/knowledge_base/points/search \
  -H 'Content-Type: application/json' \
  -d '{"vector": {"name": "dense", "vector": [0.1, 0.2, ...]}, "limit": 5, "with_payload": true}'

# 2. Check namespace filtering
grep NAMESPACE_ISOLATION_ENABLED proxy/.env
# If enabled, verify the user's namespace matches document namespace

# 3. Verify sparse vector support — search with only sparse
# Check if the collection has sparse vectors configured:
curl -s http://localhost:6333/collections/knowledge_base | \
  python3 -c "import sys,json; d=json.load(sys.stdin).get('result',{}); print('Sparse config:', d.get('config',{}).get('params',{}).get('sparse_vectors'))"

# 4. Try with explicit dense-only search (skip RRF)
#    In code, pass sparse_vec=None
```

### 3.2 Low Relevance Scores

**Symptom:** Chunks returned but RRF scores < 0.01, reranker scores < -5.

**Root cause:** Wrong embedding model, mismatch between query language and document language, embedding dimension
mismatch, or outdated index.

**Solution:**

```bash
# 1. Verify embedder model matches collection creation
grep EMBEDDER_MODEL proxy/.env
# Must be the same model used when creating the collection
# e.g., BAAI/bge-m3 (1024-dim dense + sparse)

# 2. Check embedding dimension
python3 -c "
from sentence_transformers import SentenceTransformer
m = SentenceTransformer('BAAI/bge-m3')
v = m.encode('test')
print(f'Dimension: {len(v)}')  # Should be 1024 for bge-m3
"

# 3. Verify document language matches query language
#    bge-m3 supports cross-lingual natively, but check CROSS_LINGUAL_ENABLED:
grep CROSS_LINGUAL_ENABLED proxy/.env

# 4. Tune HNSW parameters for better recall
curl -X PATCH http://localhost:6333/collections/knowledge_base \
  -H 'Content-Type: application/json' \
  -d '{
    "hnsw_config": {"m": 32, "ef_construct": 200},
    "optimizers_config": {"indexing_threshold": 10000}
  }'

# 5. Increase search EF for better recall (slower)
curl -X POST http://localhost:6333/collections/knowledge_base/points/search \
  -H 'Content-Type: application/json' \
  -d '{"vector": [0.1,...], "limit": 50, "params": {"hnsw_ef": 256}}'

# 6. Re-run ETL with correct embedding model
python scripts/init_collections.py --qdrant-recreate
python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml --full
```

### 3.3 Wrong Documents Returned

**Symptom:** Search returns documents from wrong projects, teams, or time periods.

**Root cause:** Filter conditions are wrong or missing, namespace isolation not configured, or RBAC access filter is too
permissive.

**Solution:**

```bash
# 1. Check RBAC and namespace isolation
grep -E 'RBAC_ENABLED|NAMESPACE_ISOLATION_ENABLED|AUTH_ENABLED' proxy/.env

# 2. Verify user context (what namespace/doc-level is applied)
#    Decode the JWT to check claims:
python3 -c "
import jwt
token = '$(curl -s -X POST http://localhost:8080/v1/auth/login -H 'Content-Type: application/json' -d '{\"username\":\"test\",\"password\":\"test\"}' | python3 -c 'import sys,json; print(json.load(sys.stdin)[\"access_token\"])')'
print(jwt.decode(token, options={'verify_signature': False}))
"

# 3. Check payload filter being applied
#    Look at retrieval logs with debug level:
grep -A3 'filter_conditions' proxy/logs/*.log

# 4. Verify document payload has correct namespace/access_level
curl -s http://localhost:6333/collections/knowledge_base/points/scroll \
  -H 'Content-Type: application/json' \
  -d '{"limit": 5, "with_payload": true}' | \
  python3 -c "import sys,json; [print(p['payload'].get('namespace','NO_NAMESPACE'), '|', p['payload'].get('access_level','NO_LEVEL')) for p in json.load(sys.stdin)['result']['points']]"
```

### 3.4 Version Conflicts

**Symptom:** Old document version showing in results. Newly indexed documents not appearing.

**Root cause:** WAL-based incremental indexing didn't reindex modified documents. Content hash unchanged due to
whitespace-only change.

**Solution:**

```bash
# 1. Force full reindex to pick up all changes
python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml --full

# 2. Check WAL for last successful run
python3 -c "
import json
wal = json.load(open('etl/wal/etl_wal.json'))
import datetime
ts = wal.get('last_successful_run', 0)
if ts:
    print('Last run:', datetime.datetime.fromtimestamp(ts).isoformat())
print('Sources:', wal.get('completed_sources', []))
"

# 3. Check if specific document was indexed
curl -X POST http://localhost:6333/collections/knowledge_base/points/scroll \
  -H 'Content-Type: application/json' \
  -d '{"filter": {"must": [{"key": "doc_id", "match": {"value": "CONF-1234"}}]}, "limit": 5, "with_payload": true}'

# 4. Bypass WAL for a single source reindex
python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml \
  --sources confluence --force
```

### 3.5 Circuit Breaker Open on Qdrant

**Symptom:**

```
WARNING: Qdrant circuit breaker OPEN — returning empty dense results
CircuitBreakerOpenError: Circuit breaker 'qdrant' is OPEN
```

Prometheus: `circuit_breaker_state{name="qdrant"} 1`

**Root cause:** Qdrant has failed 5+ consecutive calls. Network issue, Qdrant OOM, or collection corruption.

**Solution:**

```bash
# 1. Check Qdrant health directly
curl -s http://localhost:6333/health
docker logs rag-qdrant --tail 50 | grep -iE 'error|panic|oom'

# 2. Fix the underlying Qdrant issue first, then close the circuit
#    Wait for Qdrant to recover:
curl -s http://localhost:6333/collections/knowledge_base | python3 -m json.tool

# 3. Manually reset the circuit breaker
curl -X POST http://localhost:8080/v1/admin/reset-circuit-breakers

# 4. Or wait for cooldown (default 30s) — breaker auto-transitions to HALF_OPEN
#    Monitor with:
watch -n 2 'curl -s http://localhost:8080/metrics | grep circuit_breaker_state'
```

---

## 4. LLM Issues

### 4.1 LLM Connection Refused

**Symptom:**

```
aiohttp.client_exceptions.ClientConnectorError: Cannot connect to host vllm:8000
ConnectionRefusedError: [Errno 111] Connection refused
LLMError: LLM request failed after 3 attempts
```

**Root cause:** LLM backend (vLLM, llama.cpp, etc.) is not running or not reachable at `LLM_ENDPOINT`.

**Solution:**

```bash
# 1. Check LLM backend status
docker ps | grep vllm
docker logs rag-vllm --tail 30

# 2. Test connectivity
curl -s http://localhost:8000/health
curl -s http://localhost:8000/v1/models

# 3. From inside proxy container
docker exec rag-proxy curl -s http://vllm:8000/health

# 4. Verify LLM_ENDPOINT in .env
grep LLM_ENDPOINT proxy/.env
# Must match the docker-compose service name and port:
#   LLM_ENDPOINT=http://vllm:8000/v1    (Docker DNS)
#   LLM_ENDPOINT=http://localhost:8000/v1  (host network)

# 5. Wait for model to finish loading (can take minutes)
docker logs rag-vllm -f | grep -i 'model loaded\|ready\|Uvicorn running'

# 6. Fall back to alternative backend
#    Edit .env: LLM_ENDPOINT=http://localhost:8081/v1
#    Start llama.cpp server:
#    llama-server -m /models/your-model.gguf --port 8081
```

### 4.2 Context Length Exceeded

**Symptom:**

```
LLM returned 400: This model's maximum context length is 8192 tokens.
However, you requested 12000 tokens.
LLMError: context length exceeded
```

**Root cause:** The assembled context (system prompt + retrieved chunks + conversation history) exceeds the model's
`max_model_len`.

**Solution:**

```bash
# 1. Reduce chunks retrieved and kept after rerank
MAX_CHUNKS_RETRIEVAL=20    # was 50
MAX_CHUNKS_AFTER_RERANK=5  # was 20

# 2. Enable token budget optimization
TOKEN_OPTIMIZER_ENABLED=true
COMPRESSION_STRATEGY=keyword

# 3. Increase model's context window (if hardware allows)
#    In docker-compose.yml vllm command:
#    --max-model-len 32768   (from 8192)

# 4. Check actual token usage from metrics
curl -s http://localhost:8080/metrics | grep rag_prompt_tokens

# 5. Enable context compression (LLMLingua / keyword-based)
grep COMPRESSION_STRATEGY proxy/.env
# Options: "perplexity", "keyword", "none"
```

### 4.3 Invalid Model Name

**Symptom:**

```
LLM returned 400: The model `rag-proxy` does not exist.
LLM returned 404: Model not found
```

**Root cause:** `LLM_MODEL_NAME` in `.env` does not match any model loaded in the backend. The proxy passes `rag-proxy`
as the model name to the LLM backend.

**Solution:**

```bash
# 1. List models available in the backend
curl -s http://localhost:8000/v1/models | python3 -m json.tool

# 2. Set LLM_MODEL_NAME to match an available model
#    In proxy/.env:
LLM_MODEL_NAME=/models/your-model-name
# or the short name the backend recognizes

# 3. Check what model vLLM actually loaded
docker logs rag-vllm | grep -i 'model'

# 4. Restart proxy after config change
docker-compose -f proxy/docker-compose.yml restart rag-proxy
```

### 4.4 Provider Type Mismatch

**Symptom:**

```
Unknown provider type 'xyz', falling back to openai
LLM returned 400: Invalid request format
LLMError: Failed to extract content
```

**Root cause:** `LLM_PROVIDER_TYPE` is set incorrectly, or the adapter sends the wrong request format for the backend.

**Solution:**

```bash
# 1. Check current provider type
grep LLM_PROVIDER_TYPE proxy/.env

# 2. Supported values:
#    openai   → vLLM, llama.cpp (OpenAI-compatible API), Ollama, LiteLLM
#    anthropic → Claude API
#    ollama    → Ollama (with minor adjustments)
#    generic   → custom REST endpoint

# 3. For vLLM or llama.cpp:
LLM_PROVIDER_TYPE=openai

# 4. Test the raw endpoint format matches expectations
curl -X POST http://localhost:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "your-model",
    "messages": [{"role": "user", "content": "Hello"}],
    "max_tokens": 50
  }'
```

### 4.5 LLM Backend Out of Memory

**Symptom:**

```
docker logs rag-vllm:
CUDA out of memory. Tried to allocate 2.00 GiB
RuntimeError: CUDA out of memory
torch.cuda.OutOfMemoryError
```

Container exits with code 137 (OOMKilled by kernel).

**Root cause:** Model + KV cache exceeds available GPU VRAM. Large batch sizes or long context windows consume too much
memory.

**Solution:**

```bash
# 1. Check GPU memory
nvidia-smi

# 2. Reduce GPU memory utilization in vLLM
#    In docker-compose.yml vllm command:
--gpu-memory-utilization 0.70   # was 0.90, leave 30% headroom
--max-model-len 16384           # reduce context window

# 3. Use a quantized model (GGUF for llama.cpp, AWQ/GPTQ for vLLM)
#    Smaller footprint:
--model /models/model-Q4_K_M.gguf   # 4-bit quantization

# 4. For llama.cpp, offload fewer layers to GPU:
llama-server -m /models/model.gguf --n-gpu-layers 20 --port 8000

# 5. For embedder, force CPU:
EMBEDDER_DEVICE=cpu

# 6. Check if there's a memory leak (growing over time)
docker stats rag-vllm --no-stream
# Watch RES column over multiple requests
```

---

## 5. Embedding Issues

### 5.1 Embedding Model File Not Found

**Symptom:**

```
OSError: [Errno 2] No such file or directory: 'BAAI/bge-m3'
OSError: model not found
sentence_transformers.SentenceTransformer.__init__: model not found
```

**Root cause:** Model not downloaded. Air-gapped environment without pre-cached models.

**Solution:**

```bash
# 1. Download models on a machine with internet access
python scripts/download_models_offline.py

# 2. Verify the model cache directory
ls -la /path/to/model_cache/
# Should contain: models--BAAI--bge-m3/ (for HuggingFace cache)

# 3. Check EMBEDDER_MODEL in .env
grep EMBEDDER_MODEL proxy/.env
# Must be: EMBEDDER_MODEL=BAAI/bge-m3

# 4. For air-gapped, pre-copy models to the cache:
#    On internet machine:
python3 -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-m3')"
cp -r ~/.cache/huggingface/hub/models--BAAI--bge-m3 /path/to/model_cache/

#    Then mount in docker-compose:
#    volumes:
#      - /path/to/model_cache:/root/.cache/huggingface/hub:ro

# 5. Use remote embedding service instead:
EMBEDDER_ENDPOINT=http://localhost:8081/v1
EMBEDDER_MODEL=BAAI/bge-m3    # model name the remote service expects
EMBEDDER_FALLBACK_LOCAL=false  # don't fall back to local
```

### 5.2 CUDA Out of Memory During Embedding

**Symptom:**

```
RuntimeError: CUDA out of memory. Tried to allocate 256.00 MiB
torch.cuda.OutOfMemoryError: CUDA out of memory.
```

Embedding fails during bulk indexing or large batch retrieval.

**Root cause:** Embedding model loaded on GPU competes with LLM for VRAM. Large batch sizes exhaust memory.

**Solution:**

```bash
# 1. Move embedder to CPU
EMBEDDER_DEVICE=cpu

# 2. Or reduce GPU memory for embedder by using half precision
#    The SentenceTransformer loads in float32 by default.
#    Use model_kwargs: {"torch_dtype": "float16"}
#    (requires code change in retrieval.py around embedder initialization)

# 3. Reduce ETL batch size
#    In etl/config/etl_config.yaml:
indexing:
  batch_size: 25    # was 100

# 4. Check GPU memory split
nvidia-smi
# Look for processes using GPU memory:
#   - vLLM (LLM backend): uses most VRAM
#   - embedder: ~2-4 GB for bge-m3
#   - reranker: ~500 MB for MiniLM

# 5. Use remote embedder on a separate machine
EMBEDDER_ENDPOINT=http://embedder-host:8081/v1
EMBEDDER_FALLBACK_LOCAL=false
```

### 5.3 Dimension Mismatch

**Symptom:**

```
Qdrant error: Wrong input: Vector dimension 768 does not match collection dimension 1024
qdrant_client.http.exceptions.UnexpectedResponse: dimension mismatch
```

**Root cause:** The embedding model produces vectors of a different dimension than what the Qdrant collection was
created with.

**Solution:**

```bash
# 1. Check current collection vector dimension
curl -s http://localhost:6333/collections/knowledge_base | \
  python3 -c "import sys,json; d=json.load(sys.stdin).get('result',{}); print('Dense dim:', d.get('config',{}).get('params',{}).get('vectors',{}).get('size','N/A'))"

# 2. Check embedding model output dimension
python3 -c "
from sentence_transformers import SentenceTransformer
m = SentenceTransformer('BAAI/bge-m3')
print(f'Dimension: {len(m.encode(\"test\"))}')  # 1024 for bge-m3
"

# 3. Fix: recreate collection with correct dimension or change model
#    Option A: Recreate collection (wipes all data)
python scripts/init_collections.py --qdrant-recreate

#    Option B: Change model to match existing collection
EMBEDDER_MODEL=sentence-transformers/all-MiniLM-L6-v2  # 384-dim
# or
EMBEDDER_MODEL=intfloat/multilingual-e5-large          # 1024-dim

# 4. Re-run ETL after fix
python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml --full
```

### 5.4 Slow Encoding / High Embedding Latency

**Symptom:** `hybrid_search` takes > 1 second, mostly in `_compute_dense_embedding`.

**Root cause:** Embedding model on CPU, no batching, or disk-swapping due to memory pressure.

**Solution:**

```bash
# 1. Move embedder to GPU
EMBEDDER_DEVICE=cuda

# 2. Use cache to avoid re-encoding identical queries
#    Check cache hit rate:
curl -s http://localhost:8080/metrics | grep rag_cache_hits_total

# 3. Use remote embedding service for horizontal scaling
EMBEDDER_ENDPOINT=http://embedder-host:8081/v1
#    The remote service can batch and use GPU efficiently.

# 4. For bulk ETL, increase batch size (GPU only)
#    In etl/config/etl_config.yaml:
indexing:
  batch_size: 200    # larger batches = better GPU utilization

# 5. Check if embedder is on slow disk (HDD instead of SSD)
lsblk -d -o name,rota,size,type | grep disk
# ROTA=1 means rotational (HDD) — models load slower
```

---

## 6. Authentication & RBAC Issues

### 6.1 Invalid Token (401 Unauthorized)

**Symptom:**

```json
{"detail": "Invalid token: Signature verification failed"}
{"detail": "Invalid token: Not enough segments"}
{"detail": "Authentication required"}
```

**Root cause:** Token is malformed, signed with wrong key, or algorithm mismatch (`HS256` vs `RS256`).

**Solution:**

```bash
# 1. Check AUTH_ENABLED and JWT config
grep -E 'AUTH_ENABLED|JWT_SECRET|JWT_ALGORITHM|JWT_PUBLIC_KEY' proxy/.env

# 2. Decode token without verification to inspect claims
python3 -c "
import jwt
token = '$TOKEN'
try:
    print(jwt.decode(token, options={'verify_signature': False}))
except Exception as e:
    print(f'Token is malformed: {e}')
"

# 3. Verify signature with the correct key
python3 -c "
import jwt
token = '$TOKEN'
secret = '$(grep JWT_SECRET proxy/.env | cut -d= -f2)'
try:
    payload = jwt.decode(token, secret, algorithms=['HS256'])
    print('Valid:', payload)
except jwt.InvalidSignatureError:
    print('Signature mismatch — wrong secret')
except jwt.ExpiredSignatureError:
    print('Token has expired')
"

# 4. For Keycloak/RS256, ensure public key is correct
grep JWT_PUBLIC_KEY proxy/.env
# Can leave empty to auto-discover from JWKS endpoint

# 5. Test token creation and validation
curl -X POST http://localhost:8080/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"test","password":"test"}'
```

### 6.2 Token Expired

**Symptom:**

```json
{"detail": "Token has expired"}
```

**Root cause:** Access token TTL (`ACCESS_TOKEN_MINUTES`, default 60) has elapsed.

**Solution:**

```bash
# 1. Refresh using the refresh token
REFRESH_TOKEN='your-refresh-token'
curl -X POST http://localhost:8080/v1/auth/refresh \
  -H 'Content-Type: application/json' \
  -d "{\"refresh_token\": \"$REFRESH_TOKEN\"}"

# 2. Increase token lifetimes in .env
ACCESS_TOKEN_MINUTES=120    # 2 hours (was 60)
REFRESH_TOKEN_DAYS=14       # 2 weeks (was 7)

# 3. Check when the token expires
python3 -c "
import jwt, datetime
token = '$TOKEN'
payload = jwt.decode(token, options={'verify_signature': False})
exp = datetime.datetime.fromtimestamp(payload['exp'])
now = datetime.datetime.now()
print(f'Expires: {exp.isoformat()}')
print(f'Remaining: {(exp - now).total_seconds():.0f}s')
"
```

### 6.3 Refresh Token Failed

**Symptom:**

```json
{"detail": "Invalid refresh token"}
{"detail": "Refresh token not found or already used"}
```

**Root cause:** Refresh token has been consumed (one-time use), expired, or the user DB entry was deleted.

**Solution:**

```bash
# 1. Refresh tokens are one-time use — get a new pair by re-authenticating
curl -X POST http://localhost:8080/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"your-user","password":"your-password"}'

# 2. Check the user DB for stored refresh tokens
sqlite3 proxy/data/users.db "SELECT user_id, substr(token_hash,1,10), created_at, expires_at FROM refresh_tokens WHERE expires_at > datetime('now') LIMIT 5;"

# 3. If user DB is corrupted, recreate it
rm proxy/data/users.db
docker-compose -f proxy/docker-compose.yml restart rag-proxy
# Re-register users afterwards
```

### 6.4 Keycloak Unreachable

**Symptom:**

```
WARNING: Failed to fetch JWKS from Keycloak: timed out
WARNING: Failed to fetch JWKS from Keycloak: [Errno 111] Connection refused
```

Token validation falls back to `JWT_PUBLIC_KEY`.

**Root cause:** Keycloak server is down, network unreachable, or config (URL/realm) is wrong.

**Solution:**

```bash
# 1. Verify Keycloak connectivity
curl -s http://keycloak:8080/auth/realms/your-realm/.well-known/openid-configuration
# or from host:
curl -s "${KEYCLOAK_URL}/realms/${KEYCLOAK_REALM}/.well-known/openid-configuration"

# 2. Check config
grep -E 'KEYCLOAK_URL|KEYCLOAK_REALM|KEYCLOAK_CLIENT_ID' proxy/.env

# 3. If Keycloak is permanently down, fall back to HS256 local mode:
#    Clear KEYCLOAK_URL and set JWT_SECRET
KEYCLOAK_URL=
JWT_SECRET=your-256-bit-secret
JWT_ALGORITHM=HS256
AUTH_VALID_USERS='{"alice":{"password":"hash","roles":["admin"]}}'

# 4. Restart proxy
docker-compose -f proxy/docker-compose.yml restart rag-proxy
```

### 6.5 LDAP/AD Timeout

**Symptom:**

```
LDAP connection timeout (5s)
ldap.SERVER_DOWN: {'desc': "Can't contact LDAP server"}
```

**Root cause:** AD/LDAP server unreachable, wrong URL, or network latency.

**Solution:**

```bash
# 1. Check AD config
grep -E 'AD_ENABLED|AD_URL|AD_BASE_DN|AD_USER_DN_TEMPLATE' proxy/.env

# 2. Test LDAP connectivity from proxy host
ldapsearch -H "$AD_URL" -x -b "$AD_BASE_DN" -D "$AD_USER_DN_TEMPLATE" -w password -l 5

# 3. Increase timeout (requires code change in ldap_auth.py)
#    Default timeout is 5s. Increase in the ldap.initialize() call.

# 4. Disable AD fallback if LDAP is unavailable
AD_ENABLED=false

# 5. Check network from proxy container to AD
docker exec rag-proxy timeout 3 nc -zv ad-server 389
```

### 6.6 Permission Denied (403 Forbidden)

**Symptom:**

```json
{"detail": "Role 'user' is not sufficient. Required: 'admin'"}
{"detail": "Role 'read_only' is not sufficient. Required: 'expert'"}
```

**Root cause:** User's role does not meet the endpoint's minimum role requirement.

**Solution:**

```bash
# 1. Check your current role
curl -s http://localhost:8080/v1/auth/me \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# 2. Role hierarchy:
#    admin     → all endpoints (chat, feedback, admin config/metrics, warmup)
#    expert    → chat + feedback + enrichment
#    user      → chat + widget
#    read_only → models list + health

# 3. Verify RBAC is enabled
grep RBAC_ENABLED proxy/.env

# 4. Check endpoint-role mapping in app/rbac.py _PERMISSION_MAP
#    If an endpoint has no mapping, access is denied by default.

# 5. To grant temporary admin access, create an admin token:
python3 -c "
from app.auth import create_mock_token
token = create_mock_token(
    user_id='admin-temp',
    username='admin',
    roles=['admin'],
    access_level='confidential',
)
print(token)
"
```

---

## 7. Cache Issues (Redis)

### 7.1 Redis Connection Refused

**Symptom:**

```
redis.exceptions.ConnectionError: Error 111 connecting to redis:6379. Connection refused.
Failed to connect to Redis at redis://redis:6379
```

Cache calls silently fall back to in-memory cache.

**Root cause:** Redis is not running, wrong URL, or network issue.

**Solution:**

```bash
# 1. Check Redis status
docker ps | grep redis
docker logs rag-redis --tail 20

# 2. Test connectivity
redis-cli -h localhost -p 6379 PING
# or from inside proxy container:
docker exec rag-proxy redis-cli -h redis PING

# 3. Check REDIS_URL in .env
grep -E 'USE_REDIS|REDIS_URL' proxy/.env
# Must be: REDIS_URL=redis://redis:6379

# 4. If Redis is down, restart it
docker-compose -f proxy/docker-compose.yml restart redis

# 5. If Redis is permanently unavailable, disable it:
USE_REDIS=false
# Cache will use in-memory only (restarts flush the cache)
```

### 7.2 Stale Cache / Wrong Answers

**Symptom:** Proxy returns cached responses even after documents were updated. `rag_force_refresh` doesn't help.

**Root cause:** Cache TTL is too long, cache key doesn't include version/namespace, or `rag_force_refresh` is not being
honored.

**Solution:**

```bash
# 1. Force bypass cache on a specific request
curl -X POST http://localhost:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"rag-proxy","messages":[{"role":"user","content":"query"}],"rag_force_refresh":true}'

# 2. Clear the entire Redis cache
docker exec rag-redis redis-cli FLUSHDB

# 3. Clear specific cache keys (embedding cache)
docker exec rag-redis redis-cli KEYS "embed:*" | xargs docker exec -i rag-redis redis-cli DEL

# 4. Reduce cache TTL for faster invalidation
#    In cache.py, the default TTL is 3600s (1 hour). Reduce:
#    cache_manager.set_sync(key, value, ttl=300)  # 5 minutes

# 5. Check cache hit rate
curl -s http://localhost:8080/metrics | grep rag_cache
```

### 7.3 Redis Memory Limit Reached

**Symptom:**

```
redis.exceptions.ResponseError: OOM command not allowed when used memory > 'maxmemory'
```

Redis logs: `Can't save in background: fork: Cannot allocate memory`.

**Root cause:** Redis has exceeded its `maxmemory` and the eviction policy is `noeviction`.

**Solution:**

```bash
# 1. Check current memory usage
docker exec rag-redis redis-cli INFO memory | grep -E 'used_memory_human|maxmemory_human|maxmemory_policy'

# 2. Set an eviction policy (LRU)
docker exec rag-redis redis-cli CONFIG SET maxmemory-policy allkeys-lru

# 3. Increase maxmemory
docker exec rag-redis redis-cli CONFIG SET maxmemory 2gb

# 4. Or in docker-compose.yml permanently:
#    redis:
#      command: redis-server --appendonly yes --maxmemory 2gb --maxmemory-policy allkeys-lru

# 5. Flush if memory is critically full
docker exec rag-redis redis-cli FLUSHDB

# 6. Check stream sizes (if streaming ETL is filling memory)
docker exec rag-redis redis-cli XLEN etl:events
docker exec rag-redis redis-cli XTRIM etl:events MAXLEN ~ 10000
```

### 7.4 Redis AOF Corruption

**Symptom:**

```
Redis log: Bad file format reading the append only file
Redis log: AOF file is corrupted
Redis fails to start or starts with empty data.
```

**Root cause:** Unclean shutdown, disk full during AOF write, or filesystem corruption.

**Solution:**

```bash
# 1. Check and repair the AOF file
docker exec rag-redis redis-check-aof --fix /data/appendonly.aof

# 2. If repair fails, start fresh (data loss)
docker-compose -f proxy/docker-compose.yml stop redis
docker exec rag-redis rm -f /data/appendonly.aof /data/dump.rdb
docker-compose -f proxy/docker-compose.yml start redis

# 3. Rebuild the AOF from current data
docker exec rag-redis redis-cli BGREWRITEAOF

# 4. Check AOF size and last rewrite
docker exec rag-redis redis-cli INFO persistence | grep -E 'aof_current_size|aof_last_rewrite_time'

# 5. Restore from backup if available
#    See docs/en/guides/disaster-recovery-runbook.md
```

---

## 8. Graph Issues (Neo4j)

### 8.1 Neo4j Connection Refused

**Symptom:**

```
neo4j.exceptions.ServiceUnavailable: Unable to retrieve routing information
neo4j.exceptions.ServiceUnavailable: Connection to neo4j:7687 refused
WARNING: Neo4j connection failed: ... Graph expansion disabled.
```

**Root cause:** Neo4j is not running, not reachable, or credentials are wrong.

**Solution:**

```bash
# 1. Check Neo4j status
docker ps | grep neo4j
docker logs rag-neo4j --tail 30

# 2. Wait for Neo4j to be ready (can take 30-60s on first start)
until docker exec rag-neo4j cypher-shell -u neo4j -p password "RETURN 1" 2>/dev/null; do
  echo "Waiting for Neo4j..."
  sleep 5
done

# 3. Check connectivity from proxy
docker exec rag-proxy curl -s http://neo4j:7474

# 4. Verify credentials in .env
grep -E 'GRAPH_ENABLED|NEO4J_URI|NEO4J_USER|NEO4J_PASSWORD' proxy/.env
# Default: NEO4J_URI=bolt://neo4j:7687

# 5. Change default password on first run
docker exec rag-neo4j cypher-shell -u neo4j -p neo4j "ALTER CURRENT USER SET PASSWORD FROM 'neo4j' TO 'newpassword'"
# Then update NEO4J_PASSWORD in .env

# 6. Increase connection timeout
#    In docker-compose.yml neo4j environment:
#    NEO4J_dbms_connector_bolt_advertised__address=neo4j:7687
```

### 8.2 APOC Not Installed

**Symptom:**

```
There is no procedure with the name apoc.meta.graph
Unknown function 'apoc.text.levenshteinSimilarity'
```

**Root cause:** The APOC plugin library is not installed in the Neo4j container.

**Solution:**

```bash
# 1. Check installed plugins
docker exec rag-neo4j ls /plugins/

# 2. Download APOC to the plugins directory
#    On host, download apoc-5.x.x-core.jar to neo4j_plugins volume
docker exec rag-neo4j bash -c '
  cd /plugins && \
  wget https://github.com/neo4j/apoc/releases/download/5.24.0/apoc-5.24.0-core.jar
'

# 3. Enable APOC in neo4j.conf
#    Add to docker-compose.yml neo4j environment:
NEO4J_dbms_security_procedures_unrestricted=apoc.*
NEO4J_dbms_security_procedures_allowlist=apoc.*

# 4. Restart Neo4j
docker-compose -f proxy/docker-compose.yml restart neo4j

# 5. Verify APOC is available
docker exec rag-neo4j cypher-shell -u neo4j -p password \
  "CALL apoc.help('apoc') YIELD name RETURN name LIMIT 5"
```

### 8.3 Graph Expansion Slow

**Symptom:** `graph_expand_query` takes > 3 seconds. Retrieval pipeline stalls at graph step.

**Root cause:** Large graph, missing indexes, or complex Cypher queries scanning all nodes.

**Solution:**

```bash
# 1. Check if graph expansion is the bottleneck — disable temporarily
USE_GRAPH_EXPANSION=false

# 2. Check existing indexes
docker exec rag-neo4j cypher-shell -u neo4j -p password \
  "SHOW INDEXES YIELD name, type, labelsOrTypes, properties"

# 3. Create missing indexes
docker exec rag-neo4j cypher-shell -u neo4j -p password "
CREATE INDEX entity_name_idx IF NOT EXISTS FOR (n:Entity) ON (n.name);
CREATE INDEX entity_type_idx IF NOT EXISTS FOR (n:Entity) ON (n.type);
"

# 4. Check entity count
docker exec rag-neo4j cypher-shell -u neo4j -p password \
  "MATCH (n:Entity) RETURN count(n) as total_entities"

# 5. Increase Neo4j heap (if OOM during graph queries)
#    In docker-compose.yml:
NEO4J_dbms_memory_heap_initial__size=2G
NEO4J_dbms_memory_heap_max__size=4G
NEO4J_dbms_memory_pagecache_size=2G

# 6. Limit graph expansion depth
#    In retrieval.py graph_expand_query, reduce max_entities
```

### 8.4 Entity Extraction Failures

**Symptom:**

```
WARNING: Entity extraction returned 0 entities
graph_expand_query returns ""
```

**Root cause:** SLM/routing model not configured, text too short for entity extraction, or non-English content.

**Solution:**

```bash
# 1. Check SLM configuration
grep -E 'SLM_ENDPOINT|SLM_MODEL_NAME' proxy/.env

# 2. If SLM is not configured, enable heuristic entity extraction
#    graph_expand_query already falls back to keyword-based extraction
#    (words > 3 chars as keywords)

# 3. For better extraction, deploy a lightweight SLM:
SLM_ENDPOINT=http://vllm:8000/v1
SLM_MODEL_NAME=Qwen2.5-1.5B-Instruct

# 4. Check if graph data exists
docker exec rag-neo4j cypher-shell -u neo4j -p password \
  "MATCH (n:Entity) RETURN n.name, n.type LIMIT 10"

# 5. Rebuild graph from ETL
python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml --steps graph
```

---

## 9. Performance Issues

### 9.1 High Latency (p95 > 5s)

**Symptom:** SLO breach. `rag_request_duration_seconds` p95 consistently above 5s.

**Root cause:** LLM backend overloaded, Qdrant disk I/O, reranker processing too many chunks, or network latency.

**Solution:**

```bash
# 1. Identify bottleneck from phase timing
#    Each phase has its own metric. Check:
curl -s http://localhost:8080/metrics | grep -E 'rag_phase.*seconds|rag_retrieval_duration|rag_llm_duration'

# 2. If LLM generation is the bottleneck (> 80% of time):
#    - Reduce max_tokens
#    - Use smaller/faster model
#    - Enable prefix caching on vLLM (--enable-prefix-caching)

# 3. If retrieval is the bottleneck:
#    - Reduce MAX_CHUNKS_RETRIEVAL
#    - Use remote embedder
#    - Optimize Qdrant HNSW parameters

# 4. If reranking is the bottleneck:
#    - Reduce MAX_CHUNKS_AFTER_RERANK
#    - Increase RERANKER_BATCH_SIZE (GPU only)
#    - Disable ContextReordering (REORDER_ENABLED=false)

# 5. Check for network latency between services
docker exec rag-proxy ping -c 5 qdrant
docker exec rag-proxy ping -c 5 vllm

# 6. Enable response compression for large payloads
grep COMPRESSION_ENABLED proxy/.env
# Should be: COMPRESSION_ENABLED=true
```

### 9.2 Memory Leak

**Symptom:** Proxy/Reranker memory usage grows over hours/days without decreasing.

```
docker stats rag-proxy  # Watch RES column
```

**Root cause:** Embedding cache growing unbounded, Python objects accumulating in LangGraph state, or unreleased GPU
tensors.

**Solution:**

```bash
# 1. Check memory growth pattern
watch -n 30 'docker stats rag-proxy --no-stream'

# 2. Check in-memory cache size
#    The InMemoryCache has no size limit — keys accumulate.
#    Add a max size limit or reduce TTL.

# 3. Enable periodic cache cleanup (if code supports it)
#    Restart proxy to clear in-memory state:
docker-compose -f proxy/docker-compose.yml restart rag-proxy

# 4. Check for GPU memory leak
nvidia-smi -l 1  # Watch memory over time

# 5. Reduce WORKERS to 1 (shared embedder state)
grep WORKERS proxy/.env
# Must be: WORKERS=1 (multiple workers duplicate embedder in memory)

# 6. Enable garbage collection logging for debugging
#    Add to proxy code:
#    import gc; gc.set_debug(gc.DEBUG_LEAK)
```

### 9.3 CPU Spike

**Symptom:** Proxy CPU usage spikes to 100% for extended periods.

**Root cause:** Dense encoding on CPU, reranker processing large batches, or compression on large responses.

**Solution:**

```bash
# 1. Check CPU usage by container
docker stats --no-stream

# 2. Move compute to GPU
EMBEDDER_DEVICE=cuda

# 3. Reduce compression level
COMPRESSION_LEVEL=1    # fastest (was 6)
# or disable for internal traffic
COMPRESSION_MIN_SIZE=50000

# 4. Reduce reranker batch
RERANKER_BATCH_SIZE=8

# 5. Disable heavy features (HyDE, reflection) if not needed
HYDE_ENABLED=false
REFLECTION_ENABLED=false

# 6. Limit concurrent requests (via rate limiter)
RATE_LIMIT_ENABLED=true
RATE_LIMIT_PER_MINUTE=60
```

### 9.4 Disk I/O Saturation

**Symptom:** System `iowait` > 20%. Qdrant segment optimization hogging disk.

**Root cause:** Qdrant optimizing segments, SQLite WAL checkpointing, or logs filling disk.

**Solution:**

```bash
# 1. Check disk utilization
iostat -x 1 5

# 2. Check Qdrant storage
du -sh /var/lib/docker/volumes/*qdrant*/_data/

# 3. Increase Qdrant indexing threshold (optimize less frequently)
curl -X PATCH http://localhost:6333/collections/knowledge_base \
  -H 'Content-Type: application/json' \
  -d '{"optimizers_config": {"indexing_threshold": 50000, "memmap_threshold": 50000}}'

# 4. Move Qdrant storage to faster disk (NVMe)
#    In docker-compose.yml, bind-mount to NVMe path:
#    volumes:
#      - /mnt/nvme/qdrant:/qdrant/storage

# 5. Rotate and compress old logs
find proxy/logs/ -name "*.log" -mtime +7 -exec gzip {} \;

# 6. Check SQLite WAL size (can grow large)
ls -la proxy/data/users.db-wal
# If large, run VACUUM:
sqlite3 proxy/data/users.db "PRAGMA wal_checkpoint(TRUNCATE); VACUUM;"
```

### 9.5 Qdrant Segment Count Too High

**Symptom:** `segments_count` in Qdrant is > 200. Search latency increases linearly with segment count.

**Root cause:** Many small segment files from incremental indexing. Optimizer hasn't merged them.

**Solution:**

```bash
# 1. Check segment count
curl -s http://localhost:6333/collections/knowledge_base | \
  python3 -c "import sys,json; d=json.load(sys.stdin).get('result',{}); print('Segments:', d.get('segments_count'), 'Indexed:', d.get('indexed_vectors_count','N/A'))"

# 2. Force segment optimization
curl -X POST http://localhost:6333/collections/knowledge_base/optimizers \
  -H 'Content-Type: application/json' \
  -d '{"indexing_threshold": 5000}'

# 3. Wait for optimization to complete (check segment count dropping)
watch -n 5 'curl -s http://localhost:6333/collections/knowledge_base | python3 -c "import sys,json; print(json.load(sys.stdin).get(\"result\",{}).get(\"segments_count\",\"?\"))"'

# 4. Permanently increase the threshold to merge more aggressively
curl -X PATCH http://localhost:6333/collections/knowledge_base \
  -H 'Content-Type: application/json' \
  -d '{"optimizers_config": {"indexing_threshold": 20000, "default_segment_number": 2}}'
```

---

## 10. Deployment Issues (Docker / Kubernetes)

### 10.1 Image Pull Errors

**Symptom:**

```
ErrImagePull: pull access denied for rag-proxy
ImagePullBackOff: repository does not exist or may require 'docker login'
```

**Root cause:** Docker can't pull the image — either it's local-only (not pushed), wrong tag, or private registry
requires authentication.

**Solution:**

```bash
# 1. Build locally instead of pulling
docker-compose -f proxy/docker-compose.yml build rag-proxy
docker-compose -f proxy/docker-compose.yml up -d

# 2. Check the image name/tag in docker-compose.yml
grep 'image:' proxy/docker-compose.yml

# 3. For private registries, authenticate first
docker login your-registry.example.com
# Or in K8s, create an image pull secret:
kubectl create secret docker-registry regcred \
  --docker-server=your-registry.example.com \
  --docker-username=user \
  --docker-password=token

# 4. Verify image exists locally or remotely
docker images | grep rag-proxy
docker pull your-registry/rag-proxy:v2.0
```

### 10.2 CrashLoopBackOff

**Symptom (K8s):**

```
kubectl get pods
NAME         READY   STATUS             RESTARTS   AGE
rag-proxy-0  0/1     CrashLoopBackOff   6          10m
```

**Root cause:** Container exits immediately after starting — config error, missing volume, or dependency not ready.

**Solution:**

```bash
# 1. Get logs from the crashing pod
kubectl logs rag-proxy-0 --previous
kubectl describe pod rag-proxy-0

# 2. Common K8s causes:
#    - ConfigMap/Secret not mounted
#    - PersistentVolumeClaim not bound
#    - Readiness probe failing
#    - Port conflicts

# 3. Debug by overriding the entrypoint
kubectl run debug --rm -it --image=rag-proxy:latest --restart=Never -- sh
# Inside: check env vars, volumes, network

# 4. Check events for the namespace
kubectl get events --sort-by='.lastTimestamp' | tail -20

# 5. For Docker, same approach:
docker-compose -f proxy/docker-compose.yml up rag-proxy  # run in foreground to see errors
```

### 10.3 OOMKilled

**Symptom:**

```
State: Terminated
  Reason: OOMKilled
  Exit Code: 137
```

Container killed by kernel OOM killer.

**Root cause:** Container exceeded its memory limit. LLM model too large, embedding cache unbounded, or memory leak.

**Solution:**

```bash
# 1. Check memory limits in deployment
# K8s:
kubectl describe pod rag-proxy-0 | grep -A5 'Limits\|Requests'
# Docker:
docker inspect rag-proxy | grep -A5 Memory

# 2. Increase memory limit
# K8s (in deployment.yaml):
#   resources:
#     limits:
#       memory: "16Gi"   # increase from 8Gi
#     requests:
#       memory: "8Gi"

# 3. Reduce memory usage (see Section 4.5 and 9.2)
#    - Move embedder to CPU
#    - Reduce chunk counts
#    - Use smaller/quantized models

# 4. Monitor memory usage before OOM
kubectl top pod rag-proxy-0
docker stats rag-proxy --no-stream

# 5. Add a memory limit warning via Prometheus
#    Alert: container_memory_usage_bytes / container_spec_memory_limit_bytes > 0.85
```

### 10.4 PVC Binding Issues

**Symptom (K8s):**

```
Warning: FailedScheduling: pod has unbound immediate PersistentVolumeClaims
Warning: ProvisioningFailed: storageclass.storage.k8s.io "fast-ssd" not found
```

**Root cause:** PersistentVolumeClaim cannot be bound — no matching PV, wrong storage class, or access mode mismatch.

**Solution:**

```bash
# 1. Check PVC status
kubectl get pvc
kubectl describe pvc qdrant-data

# 2. Verify storage class exists
kubectl get storageclass

# 3. Check available PVs
kubectl get pv

# 4. Fix storage class name in PVC
#    If using hostPath (dev only):
#    storageClassName: ""   # empty string = no dynamic provisioning

# 5. For Docker volumes, check disk space:
df -h /var/lib/docker/volumes/
docker system df
```

### 10.5 Ingress 502/504 Errors

**Symptom:** Nginx/Ingress returns 502 Bad Gateway or 504 Gateway Timeout.

**Root cause:** Proxy pod is not ready, connection refused, or request timeout.

**Solution:**

```bash
# 1. Check proxy pod status
kubectl get pods -l app=rag-proxy
kubectl logs -l app=rag-proxy --tail 20

# 2. Check service endpoints
kubectl get endpoints rag-proxy-service

# 3. Increase ingress proxy timeout (Nginx Ingress)
#    Add annotations to Ingress:
#    nginx.ingress.kubernetes.io/proxy-read-timeout: "300"
#    nginx.ingress.kubernetes.io/proxy-send-timeout: "300"
#    nginx.ingress.kubernetes.io/proxy-connect-timeout: "30"

# 4. Verify health probes
curl http://<ingress-ip>/v1/health/live
curl http://<ingress-ip>/v1/health/ready

# 5. Check ingress controller logs
kubectl logs -n ingress-nginx -l app.kubernetes.io/name=ingress-nginx --tail 50
```

---

## 11. Federation Issues

### 11.1 Silo Unreachable

**Symptom:**

```
FederationError: Silo 'europe-west' is unreachable
ConnectionError: Failed to connect to silo at http://rag-eu-west.example.com
```

**Root cause:** Remote RAG instance is down, DNS resolution fails, or network partition.

**Solution:**

```bash
# 1. Check silo health
curl -s http://rag-eu-west.example.com/v1/health
curl -s http://rag-eu-west.example.com/v1/health/ready

# 2. Check DNS resolution
nslookup rag-eu-west.example.com
dig rag-eu-west.example.com

# 3. Test connectivity from the proxy
docker exec rag-proxy curl -s --connect-timeout 5 http://rag-eu-west.example.com/v1/health

# 4. Check federation config
grep -E 'FEDERATION|SILO' proxy/.env

# 5. If the silo is permanently down, remove it from the federation config
#    or mark it as inactive to skip during queries
```

### 11.2 Circuit Breaker Open on Silo

**Symptom:**

```
FederationCircuitBreakerError: Circuit breaker for silo 'europe-west' is OPEN
All silos returned errors — federated query failed
```

**Root cause:** Silo has failed 5+ consecutive calls. The circuit breaker is protecting the system from cascading
failures.

**Solution:**

```bash
# 1. Check the silo's availability
curl -s http://rag-eu-west.example.com/v1/health

# 2. Wait for cooldown (default 30s) — circuit auto-transitions to HALF_OPEN

# 3. Reset the circuit breaker after fixing the silo
curl -X POST http://localhost:8080/v1/admin/reset-circuit-breakers

# 4. Check circuit breaker metrics
curl -s http://localhost:8080/metrics | grep circuit_breaker_state

# 5. Increase tolerance (not recommended unless silo is known to be flaky)
#    Configure per-broker thresholds in circuit_breaker.py:
#    failure_threshold=10  (was 5)
```

### 11.3 Federation Merge Returned 0 Chunks

**Symptom:**

```
WARNING: Federation merge returned 0 chunks from 3 silos
Question answered with "I don't have enough information"
```

**Root cause:** All silos returned empty results. Query may have no matches, or all silos have empty collections.

**Solution:**

```bash
# 1. Check each silo individually
for silo in rag-us rag-eu rag-asia; do
  echo "=== $silo ==="
  curl -s "http://$silo.example.com/v1/chat/completions" \
    -H 'Content-Type: application/json' \
    -d '{"model":"rag-proxy","messages":[{"role":"user","content":"test query"}],"max_tokens":50}' \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('choices',[{}])[0].get('message',{}).get('content','NO ANSWER')[:100])"
done

# 2. Verify collections on each silo
for silo in rag-us rag-eu rag-asia; do
  echo "=== $silo ==="
  curl -s "http://$silo.example.com:6333/collections/knowledge_base" | \
    python3 -c "import sys,json; print(json.load(sys.stdin).get('result',{}).get('vectors_count','0'), 'vectors')"
done

# 3. Check if namespace filtering is causing empty results
#    Federation may pass user context; check if namespace matches any silo's data.
```

### 11.4 JWT Extraction Failure

**Symptom:**

```
AuthError: Failed to extract user context from JWT in federated request
Authorization header missing in forwarded request to silo
```

**Root cause:** JWT token is not being forwarded to remote silos, or the silo can't validate it.

**Solution:**

```bash
# 1. Check if Authorization header is forwarded
#    Federation proxy should include:
#    Authorization: Bearer <token>
#    when making requests to silos.

# 2. Verify JWT public key / JWKS is consistent across all silos
#    All silos must trust the same issuer / signing key.

# 3. For HS256, ensure JWT_SECRET is identical across all silos

# 4. For RS256 (Keycloak), ensure all silos have KEYCLOAK_URL configured

# 5. Test token validation on each silo
TOKEN='your-jwt'
for silo in rag-us rag-eu; do
  echo "=== $silo ==="
  curl -s "http://$silo.example.com/v1/auth/me" \
    -H "Authorization: Bearer $TOKEN"
done
```

---

## 12. Model Evolution Issues

### 12.1 Training Job Stuck

**Symptom:**

```
POST /v1/admin/models/train returns 202
GET /v1/admin/models/status/{job_id}: status "running" for > 1 hour
```

**Root cause:** Training process hung, GPU allocation failed, or data loading is stuck.

**Solution:**

```bash
# 1. Check training job status
curl -s http://localhost:8080/v1/admin/models/status/<job_id> | python3 -m json.tool

# 2. Look for errors in MLflow
curl -s http://localhost:5000/api/2.0/mlflow/runs/search \
  -H 'Content-Type: application/json' \
  -d '{"experiment_ids": ["0"], "max_results": 5}'

# 3. Check training container logs (if running as separate process)
#    Docker:
docker logs rag-training 2>&1 | tail -50
#    K8s:
kubectl logs -l job=rag-training --tail 50

# 4. Check GPU availability
nvidia-smi
# If GPU is in use by another job, wait or stop that job

# 5. Manually cancel the job
curl -X POST http://localhost:8080/v1/admin/models/cancel/<job_id>

# 6. Check for OOM in training
dmesg | grep -i 'out of memory' | tail -5
```

### 12.2 MLflow Unreachable

**Symptom:**

```
requests.exceptions.ConnectionError: Failed to connect to mlflow:5000
MLflow tracking URI http://localhost:5000 is not reachable
```

**Root cause:** MLflow server is down, wrong URI, or MinIO dependency not healthy.

**Solution:**

```bash
# 1. Check MLflow status
docker ps | grep mlflow
docker logs rag-mlflow --tail 30

# 2. Test MLflow connectivity
curl -s http://localhost:5000/health
curl -s http://localhost:5000/api/2.0/mlflow/experiments/list

# 3. Check MinIO (artifact store dependency)
docker ps | grep minio
curl -s http://localhost:9000/minio/health/live

# 4. Verify MLFLOW_TRACKING_URI in .env
grep MLFLOW_TRACKING_URI proxy/.env
# Must be: MLFLOW_TRACKING_URI=http://mlflow:5000

# 5. Restart MLflow
docker-compose -f proxy/docker-compose.yml restart mlflow
docker-compose -f proxy/docker-compose.yml restart minio  # if needed
```

### 12.3 MinIO Access Denied

**Symptom:**

```
botocore.exceptions.ClientError: AccessDenied
S3 operation error: The Access Key Id you provided does not exist
```

**Root cause:** MinIO credentials are wrong, bucket doesn't exist, or IAM policy restricts access.

**Solution:**

```bash
# 1. Verify MinIO credentials
grep -E 'MINIO_ACCESS_KEY|MINIO_SECRET_KEY|MINIO_ENDPOINT|MINIO_BUCKET' proxy/.env
# Defaults: CHANGE_ME / CHANGE_ME

# 2. Test MinIO access
docker exec rag-minio mc alias set local http://localhost:9000 CHANGE_ME CHANGE_ME
docker exec rag-minio mc ls local/rag-artifacts

# 3. Create bucket if missing
docker exec rag-minio mc mb local/rag-artifacts

# 4. Check MinIO logs
docker logs rag-minio --tail 30

# 5. Test S3 API directly
curl -s http://localhost:9000/rag-artifacts \
  -H "Authorization: AWS $(echo -n 'GET\n\n\n\n/rag-artifacts' | openssl dgst -sha1 -hmac 'CHANGE_ME' -binary | base64)"

# 6. Reset MinIO credentials (wipe data)
docker-compose -f proxy/docker-compose.yml down -v minio
docker-compose -f proxy/docker-compose.yml up -d minio minio-create-bucket
```

### 12.4 OOM During Training

**Symptom:**

```
torch.cuda.OutOfMemoryError: CUDA out of memory. Tried to allocate 2.00 GiB
RuntimeError: CUDA out of memory
```

Training exits with error, MLflow run marked as `FAILED`.

**Root cause:** Training batch size too large for available GPU memory, or model + optimizer + gradients exceed VRAM.

**Solution:**

```bash
# 1. Reduce training batch size
#    In the training config (via API request or env):
curl -X POST http://localhost:8080/v1/admin/models/train \
  -H 'Content-Type: application/json' \
  -d '{
    "trainer_type": "llm",
    "config": {
      "batch_size": 1,
      "max_seq_length": 256,
      "use_qlora": true,
      "load_in_4bit": true
    }
  }'

# 2. Use QLoRA (4-bit quantization) for LLM training:
#    use_qlora: true
#    load_in_4bit: true

# 3. Use LoRA (not full fine-tuning) to reduce memory:
#    use_lora: true
#    lora_r: 4       (was 8)

# 4. Use gradient checkpointing (enable in trainer code)

# 5. Use CPU offloading (slower but uses less VRAM)
#    Set TRAINING_PROFILE=dev which uses lower memory settings

# 6. Check available GPU memory before training
nvidia-smi --query-gpu=memory.free --format=csv
```

### 12.5 EvalGate Threshold Not Met

**Symptom:**

```
EvalGateError: Training failed quality gate
  - LLM BERTScore 0.65 < minimum 0.70
  - Reranker MRR 0.68 < minimum 0.75
```

Model cannot be promoted because it doesn't meet quality thresholds.

**Root cause:** Training run produced a model with lower quality than the baseline.

**Solution:**

```bash
# 1. Check which thresholds failed
curl -s http://localhost:8080/v1/admin/models/status/<job_id> | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d.get('eval_results',{}), indent=2))"

# 2. Adjust thresholds (only if the new model is genuinely acceptable)
#    In .env:
EVAL_GATE_LLM_BERTSCORE_MIN=0.65    # was 0.70
EVAL_GATE_RERANKER_MRR_MIN=0.65     # was 0.75

# 3. Or train for more epochs
curl -X POST http://localhost:8080/v1/admin/models/train \
  -H 'Content-Type: application/json' \
  -d '{"trainer_type": "llm", "config": {"epochs": 5}}'

# 4. Check baseline model metrics for comparison
curl -s http://localhost:8080/v1/admin/models | python3 -m json.tool

# 5. Force promotion (bypass gate — not recommended for production)
curl -X POST http://localhost:8080/v1/admin/models/promote \
  -H 'Content-Type: application/json' \
  -d '{"model_version": "<version>", "force": true}'
```

### 12.6 Adapter Hot-Reload Failure

**Symptom:**

```
AdapterError: Failed to load adapter from /models/adapters/checkpoint-1000
AdapterError: Version mismatch — adapter requires base model v3 but v2 is loaded
```

**Root cause:** Adapter checkpoint is incompatible with the currently loaded base model.

**Solution:**

```bash
# 1. Check current active adapter
curl -s http://localhost:8080/v1/admin/models | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print('Active adapters:', d.get('active_adapters',{}))"

# 2. Check adapter compatibility
#    Adapters are tied to a specific base model — verify the base model hasn't changed.

# 3. Manually reload adapter
curl -X POST http://localhost:8080/v1/admin/models/hot-reload \
  -H 'Content-Type: application/json' \
  -d '{"adapter_path": "/models/adapters/checkpoint-1000"}'

# 4. If hot-reload fails, restart proxy with the new adapter
docker-compose -f proxy/docker-compose.yml restart rag-proxy
# Then trigger warm-up:
curl -X POST http://localhost:8080/v1/admin/warmup

# 5. Check hot-reload interval (background watcher)
grep -E 'HOT_RELOAD_ENABLED|HOT_RELOAD_WATCH_INTERVAL' proxy/.env
# If enabled, adapters are auto-reloaded every HOT_RELOAD_WATCH_INTERVAL seconds
```

### 12.7 Canary Rollout Stuck

**Symptom:**

```
CanaryController: Phase 25% not progressing — waiting for metric validation
CanaryController: Cooldown active — cannot advance phase
```

**Root cause:** Canary metrics haven't stabilized, error rate is elevated, or cooldown period hasn't elapsed.

**Solution:**

```bash
# 1. Check canary status
curl -s http://localhost:8080/v1/admin/models/canary/status | python3 -m json.tool

# 2. Monitor canary vs baseline metrics
curl -s http://localhost:8080/metrics | grep -E 'canary|baseline'

# 3. Manually advance phase
curl -X POST http://localhost:8080/v1/admin/models/canary/advance \
  -H 'Content-Type: application/json' \
  -d '{"phase": "50"}'

# 4. If canary model is problematic, rollback immediately
curl -X POST http://localhost:8080/v1/admin/models/rollback

# 5. Check canary cooldown config
grep -E 'CANARY_PHASE_DURATION|CANARY_COOLDOWN|CANARY_ENABLED' proxy/.env

# 6. Disable canary entirely
CANARY_ENABLED=false
docker-compose -f proxy/docker-compose.yml restart rag-proxy
```

---

## Appendix A: Logging Configuration

### Enable Debug Logging

```bash
# In .env:
LOG_LEVEL=DEBUG
LOG_FORMAT=json    # structured logging for log aggregation

# Restart proxy
docker-compose -f proxy/docker-compose.yml restart rag-proxy

# Tail with filtering
docker logs rag-proxy -f 2>&1 | grep -E 'ERROR|WARN|duration'
```

### Masking Secrets in Logs

```bash
# Additional secrets to mask (comma-separated):
SENSITIVE_SECRETS=API_KEY,PERSONAL_TOKEN,PRIVATE_KEY
```

### Audit Logging

```bash
# Enable audit logging
AUDIT_ENABLED=true

# Audit logs stored in LOG_DIR/audit/
ls proxy/logs/audit/
```

---

## Appendix B: Useful Diagnostic One-Liners

```bash
# Full system health summary
echo "=== Proxy ===" && curl -s http://localhost:8080/v1/health | python3 -m json.tool
echo "=== Qdrant ===" && curl -s http://localhost:6333/collections/knowledge_base | python3 -c "import sys,json; d=json.load(sys.stdin).get('result',{}); print(f'Vectors: {d.get(\"vectors_count\",\"?\")} | Segments: {d.get(\"segments_count\",\"?\")}')"
echo "=== Neo4j ===" && docker exec rag-neo4j cypher-shell -u neo4j -p password "MATCH (n) RETURN count(n) as total_nodes" 2>/dev/null || echo "Neo4j: UNREACHABLE"
echo "=== Redis ===" && docker exec rag-redis redis-cli PING 2>/dev/null && docker exec rag-redis redis-cli INFO memory | grep used_memory_human
echo "=== LLM ===" && curl -s http://localhost:8000/health 2>/dev/null || echo "LLM: UNREACHABLE"
echo "=== GPU ===" && nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv,noheader 2>/dev/null || echo "GPU: N/A"
echo "=== Disk ===" && df -h /var/lib/docker/volumes/ | tail -n +2
echo "=== CB ===" && curl -s http://localhost:8080/metrics | grep circuit_breaker_state && echo "" || echo "No circuit breaker metrics"

# Recent errors from all services
docker-compose -f proxy/docker-compose.yml logs --tail=100 2>&1 | grep -iE 'error|exception|traceback|fatal|panic|oom' | tail -20

# Top memory consumers
docker stats --no-stream --format "table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}"

# Service restart history
docker ps -a --format "table {{.Names}}\t{{.Status}}" | grep rag-
```

---

## Appendix C: Common Fixes Quick Reference

| Problem                  | Symptom                   | Quick Fix                                  |
|--------------------------|---------------------------|--------------------------------------------|
| Proxy won't start        | `Address already in use`  | `kill $(lsof -ti:8080)` or change PORT     |
| Qdrant unreachable       | `Connection refused`      | `docker-compose up -d qdrant`              |
| Empty search results     | `0 chunks`                | Run ETL: `python etl/scheduler/run_etl.py` |
| Slow queries (>5s)       | p95 latency high          | Reduce `MAX_CHUNKS_RETRIEVAL` to 20        |
| LLM timeout              | `Read timed out`          | Increase `REQUEST_TIMEOUT` to 300          |
| CUDA OOM                 | `OutOfMemoryError`        | Set `EMBEDDER_DEVICE=cpu`                  |
| 401 Unauthorized         | `Invalid token`           | Check `JWT_SECRET` or re-login             |
| 403 Forbidden            | `Role not sufficient`     | Request higher role from admin             |
| 429 Rate limited         | `Rate limit exceeded`     | Wait or increase `RATE_LIMIT_PER_MINUTE`   |
| Redis connection refused | `Error 111`               | `docker-compose restart redis`             |
| Neo4j unreachable        | `ServiceUnavailable`      | Wait for Neo4j boot, check credentials     |
| Qdrant segments high     | `segments_count > 200`    | Lower `indexing_threshold` to merge        |
| ImagePullBackOff         | `pull access denied`      | `docker-compose build` instead             |
| CrashLoopBackOff         | Repeated restarts         | `kubectl logs <pod> --previous`            |
| OOMKilled                | Exit code 137             | Increase memory limit or reduce usage      |
| Training stuck           | Status "running" for > 1h | Check GPU: `nvidia-smi`                    |
| MLflow unreachable       | Connection refused        | `docker-compose restart mlflow`            |
| MinIO access denied      | `AccessDenied`            | Check credentials, create bucket           |
| Cache stale              | Old results               | `docker exec rag-redis redis-cli FLUSHDB`  |
| Circuit breaker open     | `OPEN` state              | Fix underlying service, then reset         |
