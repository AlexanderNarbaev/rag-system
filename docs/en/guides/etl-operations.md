# ETL Operations Guide

**Version:** v2.3.0

Hands-on operations guide for the RAG ETL pipeline: streaming vs batch mode, remote services
configuration, incremental extraction, WAL backends, OCR/multimodal setup, and troubleshooting.

---

## Quick Start

```bash
# Streaming mode (default) — extract→chunk→embed→index in one pass, no disk storage
make etl-run-streaming

# Batch mode — extract→collect→chunk→index with disk persistence
make etl-run-batch

# Test connectivity to all sources before a full run
make etl-test-connection

# Clean raw data and chunk files after successful indexing
make etl-cleanup

# Run with custom config
python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml --mode streaming

# Run only specific source
python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml --mode streaming --source confluence

# Reset WAL and force full reindex
python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml --mode batch --reset-wal --force-reindex

# Start webhook server only (real-time ingestion)
python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml --webhook-only

# Start stream consumer only
python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml --consumer-only
```

---

## Streaming vs Batch Mode

The ETL pipeline has two operating modes, configured via `pipeline.mode` in `etl_config.yaml`
or the `--mode` CLI flag (which overrides the config).

### Streaming Mode (Default)

```
Extract → Chunk → Embed → Index
  └────── single document at a time ──────┘
         (generator, no disk storage)
```

- **Flow:** Documents are yielded from source directories via generators, chunked immediately,
  embedded via the remote API (with semaphore-based backpressure), and indexed to Qdrant atomically
  via `live_upsert()` — all in a single pass.
- **Disk usage:** Zero. Nothing is written to disk; everything flows through memory.
- **Resilience:** WAL checkpoints are updated after each document. If interrupted, re-running
  skips already-indexed chunks by comparing SHA-256 hashes.
- **Backpressure:** `streaming.max_concurrent_api_calls` (default 10) limits concurrent embedder
  API calls via `asyncio.Semaphore`.
- **Progress logging:** Every N documents (`streaming.progress_interval`, default 50).

**When to use:**
- High-volume ingestion (thousands of documents)
- Memory-constrained environments where you don't want raw data piling up
- When you have a remote embedder that can handle concurrent requests

**Configuration:**
```yaml
pipeline:
  mode: streaming
  batch_size: 10

streaming:
  progress_interval: 50
  max_concurrent_api_calls: 10
```

### Batch Mode

```
Extract (parallel) → Collect → Chunk → Index
  ├── Confluence      └─ all docs in memory ─┘
  ├── Jira
  └── GitLab
```

- **Flow:** All sources are extracted in parallel (ThreadPoolExecutor), then all documents are
  collected into memory, chunked in a single pass, and indexed in a single pass.
- **Disk usage:** Raw data and chunks are saved to disk by default (configurable).
- **Resilience:** Each stage is checkpointed. Use `--skip-extract`, `--skip-chunk`,
  `--skip-graph`, `--skip-index` to resume from any stage.
- **Parallel extraction:** Confluence, Jira, and GitLab run simultaneously with graceful
  degradation — one failure doesn't stop the others.

**When to use:**
- Small to medium knowledge bases (<10k documents)
- When you need intermediate artifacts (raw data, chunks) for inspection
- When running on a machine with ample RAM

**Configuration:**
```yaml
pipeline:
  mode: batch
  save_raw: true
  save_chunks: true
```

### CLI Overrides

| Flag | Effect |
|------|--------|
| `--mode streaming` | Force streaming mode (overrides config) |
| `--mode batch` | Force batch mode |
| `--timeout 300` | Override request timeout (seconds) |
| `--test-connection` | Test connections to all sources and exit |
| `--skip-extract` | Skip extraction (use existing raw data) |
| `--skip-chunk` | Skip chunking (use existing chunks) |
| `--skip-graph` | Skip graph building |
| `--skip-index` | Skip indexing |
| `--force-reindex` | Ignore WAL, reindex everything |
| `--reset-wal` | Reset all WAL checkpoints before run |
| `--cleanup-after-index` | Clean raw data after indexing |
| `--dry-run` | Show what would be cleaned (with `--cleanup-after-index`) |
| `--webhook-only` | Start only the webhook server |
| `--consumer-only` | Start only the stream consumer |
| `--quality-report path.json` | Generate extraction quality report |

---

## Remote Embedder / Reranker / SLM Configuration

The ETL pipeline can use remote ML services instead of loading models locally. This is
essential for air-gapped or resource-constrained ETL machines.

### Configuration

All remote services are configured in `etl_config.yaml` under `remote_services`:

```yaml
remote_services:
  embedder:
    endpoint: "${EMBEDDER_ENDPOINT:-http://rag-proxy:8080/v1}"
    model: "${EMBEDDER_MODEL:-BAAI/bge-m3}"
    api_key: "${EMBEDDER_API_KEY:-}"
    timeout: 60
    batch_size: 64
    max_retries: 5
    retry_delay: 2.0
    retry_max_delay: 30.0
    connection_pool_size: 16

  reranker:
    endpoint: "${RERANKER_ENDPOINT:-http://rag-proxy:8080/v1}"
    model: "${RERANKER_MODEL:-BAAI/bge-reranker-v2-m3}"
    api_key: "${RERANKER_API_KEY:-}"
    timeout: 30

  slm:
    endpoint: "${SLM_ENDPOINT:-http://rag-proxy:8080/v1}"
    model: "${SLM_MODEL:-qwen2.5-3b}"
    api_key: "${SLM_API_KEY:-}"
    timeout: 30
```

Environment variables (`${VAR:-default}`) are expanded at config load time.

### RemoteEmbedder Features

The `RemoteEmbedder` class is a drop-in replacement for SentenceTransformer with the same
`encode()` interface. It communicates via the OpenAI-compatible `/v1/embeddings` endpoint.

**Retry logic:**
- Exponential backoff with jitter (configurable: constant, linear, exponential)
- Retryable HTTP statuses: 429, 500, 502, 503, 504
- Configurable max attempts, base delay, and max delay

**Connection pooling:**
- HTTP connection pool via `requests.Session` with `HTTPAdapter`
- Configurable `connection_pool_size` (default 16)

**Async support:**
- `encode_async()` with `aiohttp` for non-blocking embedding
- `asyncio.Semaphore` for concurrency control (backpressure)
- Used by streaming pipeline for parallel chunk embedding

**Graceful degradation:**
- Returns `None` for sparse/ColBERT embeddings (not supported remotely)
- Tracks health state via `is_healthy` property
- On failure, marks `_healthy = False` and raises

### Environment Variables (Quick Override)

```bash
export EMBEDDER_ENDPOINT="http://gpu-server:8080/v1"
export EMBEDDER_MODEL="BAAI/bge-m3"
export EMBEDDER_API_KEY="sk-..."

export RERANKER_ENDPOINT="http://gpu-server:8080/v1"
export RERANKER_MODEL="BAAI/bge-reranker-v2-m3"

export SLM_ENDPOINT="http://gpu-server:8080/v1"
export SLM_MODEL="qwen2.5-3b"
```

### Target Architectures

| Setup | Embedder | Reranker | SLM | Notes |
|-------|----------|----------|-----|-------|
| **Single GPU server** | vLLM on GPU | vLLM on GPU | vLLM on GPU | Same endpoint, different models |
| **Separate services** | GPUStack / TEI | GPUStack / TEI | llama.cpp | Different endpoints |
| **RAG Proxy passthrough** | Proxy → GPU server | Proxy → GPU server | Proxy → SLM server | Centralized routing |
| **Air-gapped (local)** | `embedder_device: cuda` | `embedder_device: cpu` | (none) | Loads SentenceTransformer locally |

---

## Incremental Extraction Setup

The ETL pipeline uses WAL (Write-Ahead Log) checkpoints to track extraction progress,
enabling delta-only ingestion without re-processing entire sources.

### How It Works

1. **Extraction:** Each source records `last_run` timestamp in WAL after successful extraction.
2. **Indexing:** Each chunk is content-addressed via SHA-256 hash. `LiveVectorLake` compares
   hashes and only indexes changed chunks.
3. **Idempotent insertions:** Qdrant point IDs are UUID v5 derived from chunk hashes,
   so re-indexing the same content produces the same point ID (idempotent upsert).

### WAL Pipeline Names

| Pipeline | Constant | What It Tracks |
|----------|----------|----------------|
| Confluence extractor | `confluence_extractor` | `last_run`, `space_keys`, `total_pages` |
| Jira extractor | `jira_extractor` | `last_run`, `offset` |
| GitLab extractor | `gitlab_extractor` | `last_run`, `last_id` |
| Indexing | `indexing` | `added`, `deleted`, `hash_map` |
| Graph builder | `graph_builder` | `last_run` |

### Incremental Confluence Extraction

When `confluence.incremental: true` is set:
- The extractor fetches only pages updated since the last `last_run` timestamp.
- Per-space delta tracking prevents re-processing unchanged spaces.
- The `since_date` parameter is automatically populated from the WAL checkpoint.

### Resume After Interruption

```bash
# WAL snapshots are saved on SIGTERM/SIGINT via atexit handler
# Resume from where it left off:
python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml

# Reset a specific pipeline checkpoint while keeping last_run:
wal = WALManager(Path("./wal/etl_wal.json"))
wal.reset_pipeline("indexing", keep_last_run=True)

# Full reset:
python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml --reset-wal
```

---

## WAL Backend Options

The WAL supports three storage backends, configured via `wal.wal_backend` or the `WAL_BACKEND`
environment variable.

### File Backend (Default)

```yaml
wal:
  wal_backend: "file"
  wal_file: "./wal/etl_wal.json"
  use_lock: true
  lock_timeout: 30
```

- **Storage:** Local JSON file with file-based locking (`filelock` package, optional).
- **Stale lock recovery:** Locks older than 10 minutes are automatically released.
- **Corruption recovery:** Corrupted JSON files are reinitialized as empty.
- **Best for:** Single-machine ETL, air-gapped environments, simple deployments.

```bash
export WAL_BACKEND=file
```

### Redis Backend

```yaml
wal:
  wal_backend: "redis"
  redis_host: "redis.internal"
  redis_port: 6379
```

- **Storage:** Each checkpoint stored as a Redis key under `etl:wal:{checkpoint_name}`.
- **Advantages:** No file locking, multi-worker safe, centralized checkpoint storage.
- **Limitations:** Requires Redis connectivity; falls back to empty state on connection failure.
- **Best for:** Multi-worker ETL, distributed deployments, Kubernetes.

```bash
export WAL_BACKEND=redis
export REDIS_HOST=redis.internal
export REDIS_PORT=6379
```

### Proxy Backend

```yaml
wal:
  wal_backend: "proxy"
  proxy_url: "http://proxy.internal:8080"
```

- **Storage:** Checkpoints are POSTed/GETed to the proxy's `/v1/admin/etl/wal` API.
- **Advantages:** Centralized state in the RAG proxy, no additional infrastructure.
- **Limitations:** Requires proxy to be running; single point of failure for checkpoint storage.
- **Best for:** Deployments where the proxy is always available, simple centralized state.

```bash
export WAL_BACKEND=proxy
export PROXY_URL=http://proxy.internal:8080
```

### Migrating Between Backends

Currently there is no automatic migration. To change backends:

1. Export existing checkpoints from the file WAL:
   ```bash
   python -c "
   import json
   with open('./wal/etl_wal.json') as f:
       print(json.dumps(json.load(f), indent=2))
   "
   ```
2. Switch the backend in config.
3. The first run will start fresh WAL state in the new backend.

---

## OCR and Multimodal Extraction

The ETL pipeline supports extracting text from images and PDFs via OCR, captioning images
with CLIP/BLIP, and measuring extraction quality.

### Configuration

```yaml
multimodal:
  # FR-09: OCR pipeline
  ocr_enabled: true
  ocr_languages: "rus+eng"
  ocr_confidence_threshold: 60
  ocr_primary_engine: "tesseract"

  # FR-10: Image embedding
  image_extraction_enabled: false
  clip_model: "openai/clip-vit-base-patch32"
  blip_model: "Salesforce/blip-image-captioning-base"
  image_collection_suffix: "_images"

  # FR-11: PDF embedded image extraction
  pdf_image_extraction_enabled: false

  # FR-12: Quality metrics
  quality_report_enabled: false
```

### OCR Pipeline (FR-09)

- **Primary engine:** Tesseract (`pytesseract`) — best for documents, supports 100+ languages.
- **Fallback engine:** EasyOCR — better for non-Latin scripts and complex layouts.
- **Confidence threshold:** Only text with confidence >= `ocr_confidence_threshold` is included.
- **Multi-page:** Supports TIFF frames and rendered PDF pages via `process_multi_page_ocr()`.

```bash
# Install OCR dependencies
apt-get install tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng
pip install pytesseract easyocr Pillow

# Enable in config
export OCR_ENABLED=true
export OCR_LANGUAGES="rus+eng"
export OCR_PRIMARY_ENGINE="tesseract"
```

### PDF Embedded Image Extraction (FR-11)

When `pdf_image_extraction_enabled: true`, the doc extractor:
1. Extracts embedded images from PDFs.
2. Runs OCR on each image.
3. Appends OCR text to the extracted content under `[OCR from embedded images]` markers.

### Quality Report (FR-12)

Generate an extraction quality report to assess OCR and table extraction accuracy:

```bash
python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml --quality-report quality_report.json
```

Report includes:
- Per-document OCR confidence scores and page counts
- Table extraction quality metrics
- Overall extraction quality score

---

## Troubleshooting

### UUID Point ID Mismatches

**Symptom:** Duplicate points in Qdrant, or chunks that should be deduplicated aren't.

**Cause:** Qdrant point IDs are UUID v5 derived from SHA-256 chunk hashes using
`uuid.uuid5(uuid.NAMESPACE_OID, chunk_hash)`. If the chunk hash changes (e.g., different
chunking parameters), the UUID changes.

**Fix:**
```bash
# Check collection point count
curl http://localhost:6333/collections/knowledge_base | python3 -m json.tool

# Force full reindex if chunking parameters changed
python etl/scheduler/run_etl.py --mode batch --reset-wal --force-reindex
```

### WAL Lock Issues

**Symptom:** `OSError: Cannot create lock file` or pipeline hangs at startup.

**Causes:**
1. Stale lock file from a crashed process.
2. Permission issues on the WAL directory.
3. Concurrent ETL processes competing for the same lock.

**Fixes:**
```bash
# Check for stale lock file
ls -la ./wal/etl_wal.json.lock

# Remove stale lock manually (only if no ETL is running)
rm -f ./wal/etl_wal.json.lock

# Check directory permissions
ls -la ./wal/
chmod 755 ./wal/

# Enable automatic stale lock recovery (default: 10 min)
# In etl_config.yaml:
# wal:
#   use_lock: true
#   lock_timeout: 30

# For multi-worker setups, switch to Redis WAL backend
export WAL_BACKEND=redis
```

**Prevention:**
- WAL checkpoints are saved on SIGTERM/SIGINT via `atexit` handler. The lock is released
  when the process exits cleanly.
- Stale locks (>10 minutes) are automatically detected and released.
- Use Redis WAL backend for multi-worker deployments.

### Embedding Errors

**Symptom:** `RetryExhaustedError: All 5 retry attempts exhausted` or embedding returns
empty vectors.

**Causes:**
1. Remote embedder service is down.
2. Network timeout.
3. API key expired or missing.
4. Model not loaded on the remote service.

**Diagnosis:**
```bash
# Test embedder endpoint directly
curl -X POST http://rag-proxy:8080/v1/embeddings \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${EMBEDDER_API_KEY}" \
  -d '{"input": ["test"], "model": "BAAI/bge-m3", "encoding_format": "float"}'

# Check embedder health via proxy
curl http://localhost:8080/v1/health | python3 -m json.tool | grep embedder
```

**Fixes:**
```yaml
# Increase retry tolerance
remote_services:
  embedder:
    max_retries: 10       # more attempts
    retry_delay: 5.0      # longer base delay
    retry_max_delay: 120.0 # higher cap
    timeout: 120           # longer timeout for large batches
    batch_size: 32         # smaller batches if OOM on embedder side

# Fall back to local embedder (comment out remote_services.embedder.endpoint)
# The pipeline will load SentenceTransformer locally:
# remote_services:
#   embedder:
#     endpoint: ""  # empty → local
```

### Extraction Failures

**Symptom:** `All extractors failed — pipeline cannot continue`.

**Causes:**
1. All source URLs unreachable.
2. Invalid API tokens.
3. SSL certificate errors in corporate environments.

**Fixes:**
```yaml
# Disable SSL verification (corporate self-signed certs)
confluence:
  verify_ssl: false
  ca_bundle: "/etc/ssl/certs/corporate.pem"  # or use CA bundle

# Test each source individually
python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml --test-connection

# Run only one source to isolate
python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml --mode batch \
  --skip-jira --skip-gitlab
```

### "Collection not found" Error

**Symptom:** `qdrant_client.http.exceptions.UnexpectedResponse: Not found: Collection
knowledge_base doesn't exist!`

**Fix:**
```bash
# Create collection explicitly
python etl/scheduler/run_etl.py --mode batch --skip-extract --skip-chunk --skip-graph

# Or use the init script
python scripts/init_collections.py
```

### Streaming Pipeline Stalls

**Symptom:** Streaming mode makes no progress, CPU/network idle.

**Causes:**
1. Embedder service rate-limiting (429 responses triggering backoff).
2. All concurrent API slots saturated (semaphore exhausted).
3. Network connectivity issues.

**Fixes:**
```yaml
# Reduce concurrency
streaming:
  max_concurrent_api_calls: 3  # down from 10

# Increase retry tolerance
remote_services:
  embedder:
    max_retries: 10
    retry_delay: 5.0
```

---

## Data Retention and Cleanup

After successful indexing, raw data and chunk files can be cleaned up:

```yaml
etl:
  data_retention:
    raw_data_days: 7         # auto-delete raw extracts after N days (0 = keep forever)
    cleanup_after_run: false  # clean immediately after indexing
    keep_cold_storage: true   # preserve cold storage for versioning
```

```bash
# Manual cleanup after indexing (dry-run first)
python etl/scheduler/run_etl.py --mode batch --cleanup-after-index --dry-run

# Actual cleanup
python etl/scheduler/run_etl.py --mode batch --cleanup-after-index

# Or via Makefile
make etl-cleanup
```

Cleanup removes:
- Raw data directories (`confluence/`, `jira/`, `gitlab/`)
- Chunks output directory
- Optionally cold storage (if `keep_cold_storage: false`)
- Strips full text from hot chunk JSONs (keeps only hashes and metadata)

---

## Environment Variables Reference

| Variable | Config Path | Default | Description |
|----------|------------|---------|-------------|
| `EMBEDDER_ENDPOINT` | `remote_services.embedder.endpoint` | `http://rag-proxy:8080/v1` | Embedding API endpoint |
| `EMBEDDER_MODEL` | `remote_services.embedder.model` | `BAAI/bge-m3` | Embedding model name |
| `EMBEDDER_API_KEY` | `remote_services.embedder.api_key` | (empty) | Bearer token for embedder |
| `RERANKER_ENDPOINT` | `remote_services.reranker.endpoint` | `http://rag-proxy:8080/v1` | Reranker API endpoint |
| `RERANKER_MODEL` | `remote_services.reranker.model` | `BAAI/bge-reranker-v2-m3` | Reranker model name |
| `SLM_ENDPOINT` | `remote_services.slm.endpoint` | `http://rag-proxy:8080/v1` | SLM API endpoint |
| `SLM_MODEL` | `remote_services.slm.model` | `qwen2.5-3b` | SLM model name |
| `WAL_BACKEND` | `wal.wal_backend` | `file` | WAL storage backend (`file`/`redis`/`proxy`) |
| `REDIS_HOST` | `wal.redis_host` / `streaming.redis_host` | `localhost` | Redis host |
| `REDIS_PORT` | `wal.redis_port` / `streaming.redis_port` | `6379` | Redis port |
| `PROXY_URL` | `wal.proxy_url` | `http://localhost:8080` | Proxy URL for WAL backend |
| `OCR_ENABLED` | `multimodal.ocr_enabled` | `true` | Enable OCR pipeline |
| `OCR_LANGUAGES` | `multimodal.ocr_languages` | `rus+eng` | Tesseract language codes |
| `OCR_PRIMARY_ENGINE` | `multimodal.ocr_primary_engine` | `tesseract` | Primary OCR engine |

---

## See Also

- [ETL Pipeline Guide](etl-guide.md) — architecture and design overview
- [Extensibility & Data Sources](extensibility-data-sources.md) — adding new sources
- [Configuration Reference](configuration-reference.md) — all config options
- [Troubleshooting](troubleshooting.md) — general system troubleshooting
- [Index](index.md) — full documentation index
