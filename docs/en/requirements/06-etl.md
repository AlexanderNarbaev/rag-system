# Block F. ETL Pipeline (FR-40 — FR-57)

---

## FR-40. Extraction from 6 data sources

**Description:**
The ETL pipeline extracts data from:

1. **Confluence** — pages, comments, attachments
2. **Jira** — tickets, descriptions, comments
3. **GitLab** — README, wiki, issues, merge requests
4. **Documents** — PDF, DOCX, MD, TXT, HTML
5. **Books** — PDF books with OCR
6. **Chats** — chat logs (Telegram, Slack)

**Acceptance criteria:**

1. Each extractor returns a list of documents with metadata
2. Each document has: id, title, content, source_type, metadata
3. Incremental extraction — only changed documents

**Status:** ✅ Confirmed (`tests/etl/test_etl_requirements.py::TestFR40Extractors`, `tests/etl/test_extractors.py`)
**Priority:** CRITICAL
**Reference:** AGENTS.md

---

## FR-41. Semantic chunking

**Description:**
Documents are split into chunks with semantic awareness:

- By headings (H1-H6)
- By paragraphs with context preservation
- With overlap (50-100 tokens between chunks)
- Preserving the structure of tables and code

Each chunk includes ACL metadata: `access_level`
(public/internal/confidential/restricted), `allowed_groups`, `allowed_users`.
Default values: public/empty lists. Real values are extracted from the
source metadata (e.g., Confluence space permissions).

**Acceptance criteria:**

1. Chunks do not break sentences
2. Each chunk contains context (section heading, document name)
3. Overlap between adjacent chunks — 50-100 tokens

**Status:** ✅ Confirmed (`tests/etl/test_etl_requirements.py::TestFR41SemanticChunking`,
`tests/etl/test_semantic_chunker.py`)
**Priority:** CRITICAL
**Reference:** AGENTS.md

---

## FR-42. HTML → Markdown conversion ✅

**Description:**
HTML content from Confluence/Jira is converted to Markdown with structure preserved:
headings, lists, tables, code blocks, links.

**Acceptance criteria:**

1. HTML with headings → Markdown with `#`, `##`, `###`
2. HTML tables → Markdown tables
3. HTML code → Markdown code blocks
4. Links are preserved

**Status:** ✅ Confirmed
**Priority:** CRITICAL
**Reference:** extractors/

---

## FR-43. Table extraction ✅

**Description:**
Tables from documents are extracted in structured form. Supported: HTML tables,
Markdown tables, CSV-like structures.

**Acceptance criteria:**

1. A table from HTML → structured object (rows, columns, cells)
2. A table from Markdown → structured object
3. Tables are indexed separately from text

**Status:** ✅ Confirmed (`etl/chunker/table_extractor.py`)
**Priority:** HIGH
**Reference:** roadmap Phase 5.3

---

## FR-44. WAL-based incremental extraction

**Description:**
A Write-Ahead Log tracks the state of each ETL stage. On failure, ETL
resumes from the last successful stage rather than from the beginning.

**Acceptance criteria:**

1. ETL failure at the embedding stage — a rerun starts from embedding (not extraction)
2. The WAL file contains a checkpoint for each stage
3. On successful completion — the WAL is cleared

**Status:** ✅ Confirmed (`tests/etl/test_etl_requirements.py::TestFR44WALIncremental`,
`tests/etl/test_wal_manager.py`)
**Priority:** CRITICAL
**Reference:** ADR-005, ADR-011

---

## FR-45. SHA-256 content-addressable chunks

**Description:**
Each chunk is hashed with SHA-256 over its content. The hash is used as:

- The point ID in Qdrant (Point ID)
- The deduplication key
- The versioning key (if the content changed — new hash = new version)

**Acceptance criteria:**

1. Identical content → identical hash → one point in Qdrant
2. Changed content → different hash → new point in Qdrant
3. The hash is used as the Point ID in Qdrant

**Status:** ✅ Confirmed (`tests/etl/test_etl_requirements.py::TestFR45ContentAddressable`,
`tests/etl/test_hash_versioning.py`)
**Priority:** CRITICAL
**Reference:** ADR-005

---

## FR-46. Hot/cold storage stratification

**Description:**

- **Hot storage** — current document versions in Qdrant (fast access)
- **Cold storage** — previous versions in Parquet files (cheap storage)
- When a specific version is requested (`rag_version`) — search both hot and cold

**Acceptance criteria:**

1. Current version — in Qdrant (hot)
2. Old version — in Parquet (cold)
3. `rag_version="v1"` — finds chunks even if v1 is in cold storage

**Status:** ✅ Confirmed (`tests/etl/test_etl_requirements.py::TestFR46HotColdStorage`,
`tests/etl/test_live_vector_lake.py`)
**Priority:** HIGH
**Reference:** ADR-005

---

## FR-47. Version tracking

**Description:**
Each chunk has a `version` field (string). When a document is updated, the old chunk
is marked as stale, and the new one gets a new version. The system tracks the
version history.

**Acceptance criteria:**

1. An updated document — old chunks get `stale=true`, new ones get `version=current`
2. A `rag_version` request — returns chunks of only the specified version
3. Without `rag_version` — returns chunks of the current version

**Status:** ✅ Confirmed (`tests/etl/test_etl_requirements.py::TestFR47VersionTracking`)
**Priority:** HIGH
**Reference:** ADR-005

---

## FR-48. RAPTOR hierarchical indexing

**Description:**
Hierarchical indexing: chunks are clustered, and a summary is generated for each
cluster. Cluster summaries are clustered again — and so on up to the top of the
tree. During search, the system can answer at different levels of detail.

**Acceptance criteria:**

1. The summary tree is built (root → cluster → chunks)
2. Search at the top level — returns general summaries
3. Search at the bottom level — returns specific chunks

**Status:** ✅ Confirmed (`tests/etl/test_etl_requirements.py::TestFR48RaptorTree`)
**Priority:** HIGH
**Reference:** roadmap Phase 2

---

## FR-49. Code-aware chunking (AST-based)

**Description:**
Source code is split into chunks by AST structure:

- Python — by functions and classes
- JavaScript/TypeScript — by functions and classes
- Java — by methods and classes

Each chunk preserves context (file name, function/class name, imports).

**Acceptance criteria:**

1. A Python file with 3 functions — 3 chunks (one per function)
2. Each chunk contains the function name in metadata
3. Imports are duplicated in each chunk (for context)

**Status:** ✅ Confirmed (`tests/etl/test_etl_requirements.py::TestFR49CodeChunking`,
`tests/etl/test_code_chunker.py`)
**Priority:** HIGH
**Reference:** roadmap Phase 5.2

---

## FR-50. Image OCR extraction

**Description:**
The system extracts text from images (document scans, photos) using OCR.
Supported: Tesseract, EasyOCR, PaddleOCR.

**Acceptance criteria:**

1. An image with text → text extracted
2. A PDF with scans → text extracted
3. OCR quality ≥ 90% for clear images

**Status:** ✅ Confirmed (`tests/etl/test_etl_requirements.py::TestFR50ImageOCR`, `tests/etl/test_image_extractor.py`,
`tests/etl/test_ocr.py`)
**Priority:** HIGH
**Reference:** NFR-P09

---

## FR-51. Quality metrics for chunks

**Description:**
The system computes quality metrics for each chunk:

- Semantic coherence — cosine similarity of sentences within a chunk
- Information density — number of unique terms
- Completeness — whether the chunk contains a complete thought

**Acceptance criteria:**

1. Each chunk has a `quality_score` (0-1)
2. Chunks with quality_score below the threshold — are filtered or enriched
3. Metrics are logged

**Status:** ✅ Confirmed (`tests/etl/test_etl_requirements.py::TestFR51QualityMetrics`,
`tests/etl/test_chunk_quality.py`)
**Priority:** HIGH
**Reference:** quality_metrics.py

---

## FR-52. Chunk enrichment (SLM)

**Description:**
The SLM enriches chunks with metadata:

- Generates a chunk summary
- Extracts key entities
- Determines the topic

Enriched metadata is stored in the chunk payload in Qdrant.

**Acceptance criteria:**

1. Each chunk has a `summary` (generated by the SLM)
2. Each chunk has `entities` (extracted by the SLM)
3. Enrichment does not break existing metadata

**Status:** ✅ Confirmed (`tests/etl/test_etl_requirements.py::TestFR52ChunkEnrichment`,
`tests/etl/test_chunk_enricher.py`)
**Priority:** HIGH
**Reference:** chunk_enricher.py

---

## FR-53. Streaming pipeline

**Description:**
ETL works in streaming mode: documents are processed as they arrive
(rather than in batches). A webhook server receives notifications from
Confluence/Jira/GitLab and triggers processing immediately.

**Acceptance criteria:**

1. A webhook event → the document is processed within 5 seconds
2. A processed chunk is available for search immediately
3. A processing error — retry with exponential backoff

**Status:** ✅ Confirmed (`tests/etl/test_etl_requirements.py::TestFR53StreamingPipeline`,
`tests/etl/test_streaming_pipeline.py`)
**Priority:** HIGH
**Reference:** NFR-P10

---

## FR-54. Event pipeline

**Description:**
The system processes events from external sources:

- Confluence: page_created, page_updated, page_removed
- Jira: issue_created, issue_updated, comment_added
- GitLab: push, merge_request, wiki_updated

Each event triggers the corresponding ETL process.

**Acceptance criteria:**

1. A page_updated event → the document is reindexed
2. A page_removed event → chunks are deleted from Qdrant
3. An unknown event — logged, does not crash

**Status:** ✅ Confirmed (`tests/etl/test_etl_requirements.py::TestFR54EventPipeline`,
`tests/etl/test_event_pipeline.py`)
**Priority:** HIGH
**Reference:** event_pipeline.py

---

## FR-55. Webhook server

**Description:**
An HTTP server receives webhook notifications from external systems. Endpoints:

- `POST /webhook/confluence` — Confluence events
- `POST /webhook/jira` — Jira events
- `POST /webhook/gitlab` — GitLab events

**Acceptance criteria:**

1. A POST request with a valid payload — processed successfully
2. A POST request with an invalid payload — 400 Bad Request
3. The webhook secret is verified (HMAC signature)

**Status:** ✅ Confirmed (`tests/etl/test_etl_requirements.py::TestFR55WebhookServer`,
`tests/etl/test_webhook_server.py`)
**Priority:** HIGH
**Reference:** webhook_server.py

---

## FR-56. Task scheduler

**Description:**
The scheduler runs ETL tasks on a schedule:

- Full indexing — once a day
- Incremental — every 15 minutes
- Cleanup — once a week

**Acceptance criteria:**

1. Full indexing runs on a cron schedule
2. Incremental — every 15 minutes
3. A task error — retry up to 3 times

**Status:** ✅ Confirmed (`tests/etl/test_etl_requirements.py::TestFR56TaskScheduler`,
`tests/etl/test_task_scheduler.py`)
**Priority:** HIGH
**Reference:** task_scheduler.py

---

## FR-57. Cold storage cleanup

**Description:**
A scheduled task cleans up cold storage:

- Deletes versions older than 90 days
- Archives versions older than 30 days to S3/MinIO
- Logs the number of deleted/archived records

**Acceptance criteria:**

1. Versions > 90 days — are deleted
2. Versions 30-90 days — are archived to S3
3. The log contains the number of processed records

**Status:** ✅ Confirmed (`tests/etl/test_etl_requirements.py::TestFR57ColdStorageCleanup`,
`tests/etl/test_cold_storage_cleanup.py`)
**Priority:** MEDIUM
**Reference:** performance-quality 6.4
