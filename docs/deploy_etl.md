# ETL Deployment Guide

The ETL pipeline runs on a dedicated machine (or the same machine as the proxy in small deployments). It extracts data from Confluence, Jira, GitLab, and other sources, chunks documents semantically, extracts entities for the knowledge graph, and indexes everything into Qdrant.

---

## Prerequisites

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| **Python** | 3.11 | 3.12 |
| **RAM** | 8 GB | 16+ GB |
| **Disk** | 50 GB SSD | 200+ GB NVMe |
| **CPU** | 4 cores | 8+ cores |
| **Network** | Access to source systems | — |
| **Qdrant** | Running and accessible | Port 6333, 6334 |
| **Neo4j** (optional) | Running and accessible | Port 7687 |

The ETL machine must have network access to:
- Qdrant server (default: `http://<qdrant-host>:6333`)
- Neo4j server (optional, default: `bolt://<neo4j-host>:7687`)
- Source systems: Confluence, Jira, GitLab

---

## Installation

```bash
# Clone the repo (or transfer tarball in air-gapped env)
cd /opt
git clone https://github.com/AlexanderNarbaev/rag-system.git
cd rag-system

# Install ETL dependencies
cd etl
pip install -r requirements_etl.txt

# For air-gapped:
pip install --no-index --find-links /opt/pip-offline -r requirements_etl.txt
```

---

## Configuration

Edit `etl/config/etl_config.yaml`. All options:

### WAL (Write-Ahead Log)

Controls incremental checkpointing and resume capability.

```yaml
wal:
  wal_file: "./wal/etl_wal.json"    # Path to WAL file
  use_lock: true                     # File-based locking for concurrent safety
  lock_timeout: 30                   # Lock acquisition timeout (seconds)
```

The WAL file tracks:
- `last_confluence_sync` — timestamp of last successful Confluence extraction
- `last_jira_sync` — timestamp of last successful Jira extraction
- `last_gitlab_sync` — timestamp of last successful GitLab extraction
- `total_indexed` — total number of chunks indexed
- `completed_sources` — list of sources that completed in the last run
- `last_successful_run` — timestamp of the last complete run

**Recovery:** If the ETL crashes, delete `wal/etl_wal.json` to force a full reindex, or run with `--sources` to skip completed sources.

### Confluence

```yaml
confluence:
  url: "https://confluence.internal.company.com"
  username: "etl_bot"
  token: "your_personal_access_token"   # Personal Access Token or password
  space_keys:                           # List of space keys; null or omit for all
    - "DEV"
    - "OPS"
    - "QA"
  output_dir: "./raw_data/confluence"
  incremental: true                     # Only fetch changed pages since last run
  download_attachments: true            # Download and index attached files
  max_versions: 0                       # 0 = all versions; N = keep latest N
  api_version: "2"                      # "2" (CQL) or "1" (legacy)
```

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `url` | string | *required* | Confluence base URL |
| `username` | string | *required* | Bot account username |
| `token` | string | *required* | Personal Access Token or password |
| `space_keys` | list | `null` | Space keys to extract; omit for all accessible spaces |
| `incremental` | bool | `true` | Only extract pages modified since last run |
| `download_attachments` | bool | `true` | Download and index PDFs, images (OCR), Office docs |
| `max_versions` | int | `0` | Keep only the latest N versions per page |
| `api_version` | string | `"2"` | Confluence REST API version |

### Jira

```yaml
jira:
  url: "https://jira.internal.company.com"
  username: "etl_bot"
  token: "your_api_token"
  jql: "project in (DEV, OPS) ORDER BY updated DESC"
  output_dir: "./raw_data/jira"
  incremental: true
  download_attachments: true
  max_issues_per_run: 0                 # 0 = no limit
  fields: "*all"
  expand: "changelog,renderedBody"
```

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `url` | string | *required* | Jira base URL |
| `username` | string | *required* | Bot account username |
| `token` | string | *required* | API token or password |
| `jql` | string | *required* | JQL query for filtering issues |
| `incremental` | bool | `true` | Only extract issues updated since last run |
| `download_attachments` | bool | `true` | Download and index attached files |
| `max_issues_per_run` | int | `0` | Limit issues per run (0 = unlimited) |
| `fields` | string | `"*all"` | Jira fields to include in output |
| `expand` | string | — | Additional Jira API expansions |

### GitLab

```yaml
gitlab:
  url: "https://gitlab.internal.company.com"
  token: "your_personal_access_token"
  project_ids: null                     # null = all accessible projects
  output_dir: "./raw_data/gitlab"
  incremental: true
  fetch_commits: true
  fetch_files: true
  fetch_merge_requests: true
  max_commits_per_project: 1000
  since_date: null                      # ISO date: "2025-01-01T00:00:00Z"
  file_paths_filter:
    - "*.py"
    - "*.md"
    - "Dockerfile"
    - "*.yaml"
    - "*.yml"
    - "*.sql"
```

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `url` | string | *required* | GitLab base URL |
| `token` | string | *required* | Personal Access Token with `read_api`, `read_repository` |
| `project_ids` | list | `null` | Specific project IDs; omit for all accessible |
| `incremental` | bool | `true` | Only extract changes since last run |
| `fetch_commits` | bool | `true` | Extract commit messages and diffs |
| `fetch_files` | bool | `true` | Extract file contents (filtered by `file_paths_filter`) |
| `fetch_merge_requests` | bool | `true` | Extract MR titles, descriptions, and discussions |
| `max_commits_per_project` | int | `1000` | Limit commits per project per run |
| `since_date` | string | `null` | Only process data after this ISO date |
| `file_paths_filter` | list | — | Glob patterns for files to index |

### Chunking

```yaml
chunking:
  max_tokens: 8000                     # Maximum chunk size (for embedder context window)
  overlap_tokens: 200                  # Overlap between adjacent chunks
  min_chunk_tokens: 100                # Minimum chunk size (smaller merged with neighbor)
  use_slm: false                       # Use SLM for chunk enrichment
  slm_endpoint: "http://localhost:8080/v1/completions"
  output_dir: "./chunks"               # Directory for JSON chunk files
```

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `max_tokens` | int | `8000` | Maximum tokens per chunk (BGE-m3 limit is 8192) |
| `overlap_tokens` | int | `200` | Token overlap between consecutive chunks |
| `min_chunk_tokens` | int | `100` | Minimum chunk size; smaller chunks merged |
| `use_slm` | bool | `false` | Use SLM for chunk metadata enrichment |
| `output_dir` | string | `"./chunks"` | Directory for chunk JSON files |

The semantic chunker (`MDKeyChunker`) splits documents by markdown headers and sections, respecting document structure. It produces chunks that are:

- **Self-contained** — each chunk has enough context to be understood independently
- **Versioned** — SHA-256 hashed, content-addressable
- **Tracked** — chunk IDs linked to source documents and versions

### Indexing

```yaml
indexing:
  qdrant_host: "localhost"
  qdrant_port: 6333
  collection_name: "knowledge_base"
  embedder_model: "BAAI/bge-m3"
  embedder_device: "cpu"               # "cpu" or "cuda"
  batch_size: 100
  hot_dir: "./hot_chunks"              # Hot storage (current versions)
  cold_dir: "./cold_chunks"            # Cold storage (historical versions, Parquet)
  lake_dir: "./cold_lake"              # LiveVectorLake cold storage
  use_delta: false                     # Use Delta Lake format
  version_wal: "./wal/version_wal.json"
```

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `qdrant_host` | string | `"localhost"` | Qdrant server hostname |
| `qdrant_port` | int | `6333` | Qdrant gRPC port |
| `collection_name` | string | `"knowledge_base"` | Qdrant collection name |
| `embedder_model` | string | `"BAAI/bge-m3"` | Sentence-transformers model for embeddings |
| `embedder_device` | string | `"cpu"` | Device for embedding: `cpu`, `cuda`, `cuda:0` |
| `batch_size` | int | `100` | Chunks per embedding batch |
| `hot_dir` | string | `"./hot_chunks"` | Hot storage for current active chunks |
| `cold_dir` | string | `"./cold_chunks"` | Cold storage for historical versions |
| `lake_dir` | string | `"./cold_lake"` | LiveVectorLake cold storage |
| `use_delta` | bool | `false` | Use Delta Lake format for cold storage |
| `version_wal` | string | `"./wal/version_wal.json"` | WAL for chunk version tracking |

**LiveVectorLake** stratifies chunks into:
- **Hot** — current versions, always in Qdrant
- **Cold** — historical versions, stored as Parquet files, loaded on demand

### Knowledge Graph (Optional)

```yaml
graph:
  enabled: false                       # Enable graph construction
  use_spacy: true                      # Use spaCy for NER
  spacy_model: "ru_core_news_sm"       # or "en_core_web_sm"
  use_slm: false                       # Use SLM for relation extraction
  slm_endpoint: "http://localhost:8080/v1/completions"
  cache_dir: "./entity_cache"          # Entity extraction cache
  neo4j:
    enabled: false
    uri: "bolt://localhost:7687"
    user: "neo4j"
    password: "your_neo4j_password"
    database: "neo4j"
```

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `enabled` | bool | `false` | Enable graph construction |
| `use_spacy` | bool | `true` | Use spaCy for named entity recognition |
| `spacy_model` | string | `"ru_core_news_sm"` | spaCy model for NER |
| `use_slm` | bool | `false` | Use SLM for relation extraction (higher quality, slower) |
| `cache_dir` | string | `"./entity_cache"` | Cache extracted entities |
| `neo4j.enabled` | bool | `false` | Load entities and relations into Neo4j |
| `neo4j.uri` | string | — | Neo4j Bolt URI |
| `neo4j.user` | string | `"neo4j"` | Neo4j username |
| `neo4j.password` | string | — | Neo4j password |
| `neo4j.database` | string | `"neo4j"` | Neo4j database name |

---

## Running the ETL Pipeline

### Full Run

```bash
cd etl
python scheduler/run_etl.py --config config/etl_config.yaml
```

### Partial Run (Specific Sources)

```bash
# Only Confluence and Jira
python scheduler/run_etl.py --config config/etl_config.yaml --sources confluence,jira

# Only GitLab
python scheduler/run_etl.py --config config/etl_config.yaml --sources gitlab
```

### Full Reindex (Ignore WAL)

```bash
python scheduler/run_etl.py --config config/etl_config.yaml --full
```

This deletes all existing chunks, clears the WAL, and re-extracts everything from scratch. **Warning:** this may take hours depending on data volume.

### Dry Run

```bash
python scheduler/run_etl.py --config config/etl_config.yaml --dry-run
```

Shows what would be extracted without making any changes.

### Via Docker

```bash
# Build the ETL image
docker build -f Dockerfile.etl -t rag-etl .

# Run with mounted volumes for WAL persistence
docker run --rm --network=host \
  -v $(pwd)/wal:/app/etl/wal \
  -v $(pwd)/chunks:/app/etl/chunks \
  -v $(pwd)/raw_data:/app/etl/raw_data \
  rag-etl --config /app/etl/config/etl_config.yaml
```

---

## Scheduling

The ETL is designed to run on a schedule. Use cron or systemd timers:

### Cron (Every 4 Hours)

```cron
# /etc/cron.d/rag-etl
0 */4 * * * rag cd /opt/rag-system/etl && python scheduler/run_etl.py --config config/etl_config.yaml >> /var/log/rag-etl.log 2>&1
```

### systemd Timer

```ini
# /etc/systemd/system/rag-etl.service
[Unit]
Description=RAG System ETL Pipeline
After=network.target

[Service]
Type=oneshot
User=rag
WorkingDirectory=/opt/rag-system/etl
ExecStart=/usr/bin/python3 scheduler/run_etl.py --config config/etl_config.yaml
StandardOutput=journal
StandardError=journal

# /etc/systemd/system/rag-etl.timer
[Unit]
Description=RAG System ETL Pipeline Timer

[Timer]
OnCalendar=*-*-* 00/4:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
systemctl enable rag-etl.timer
systemctl start rag-etl.timer
```

---

## Monitoring ETL Health

### Check WAL Status

```bash
python -c "
import json
wal = json.load(open('etl/wal/etl_wal.json'))
print('Last Confluence sync:', wal.get('last_confluence_sync', 'never'))
print('Last Jira sync:', wal.get('last_jira_sync', 'never'))
print('Last GitLab sync:', wal.get('last_gitlab_sync', 'never'))
print('Total indexed chunks:', wal.get('total_indexed', 0))
print('Last successful run:', wal.get('last_successful_run', 'never'))
print('Completed sources:', wal.get('completed_sources', []))
"
```

### Verify Qdrant Collection

```bash
curl http://localhost:6333/collections/knowledge_base | python -m json.tool
```

Look for:
- `vectors_count` — should increase after each ETL run
- `segments_count` — number of indexed segments
- `points_count` — total indexed points

### Monitor Disk Usage

```bash
# Check chunk storage
du -sh etl/chunks/ etl/hot_chunks/ etl/cold_chunks/ etl/cold_lake/

# Check raw data
du -sh etl/raw_data/confluence/ etl/raw_data/jira/ etl/raw_data/gitlab/

# Clean old cold chunks (older than 30 days)
find etl/cold_chunks/ -name "*.parquet" -mtime +30 -delete
```

---

## Troubleshooting

### WAL Corruption

```bash
# Symptom: "WAL file corrupted" or ETL hangs
rm etl/wal/etl_wal.json
python scheduler/run_etl.py --config config/etl_config.yaml --full
```

### API Rate Limits

```bash
# Symptom: "429 Too Many Requests"
# Add delay between API calls:
export ETL_RATE_LIMIT_DELAY=1.0

# For GitLab, reduce commit scope:
# Edit etl_config.yaml: gitlab.max_commits_per_project: 100
```

### Partial Reindex After Crash

```bash
# Check which sources completed:
python -c "import json; wal=json.load(open('etl/wal/etl_wal.json')); print(wal.get('completed_sources',[]))"

# Reindex only failed sources:
python scheduler/run_etl.py --config config/etl_config.yaml --sources jira,gitlab
```

### Disk Full

```bash
# Clean old data:
find etl/cold_chunks/ -name "*.parquet" -mtime +30 -delete
find etl/raw_data/ -name "*.json" -mtime +7 -delete

# Move cold storage to larger volume:
mkdir -p /mnt/cold_storage/rag_lake
ln -s /mnt/cold_storage/rag_lake etl/cold_lake
```

---

## Performance Tuning

| Scenario | Setting | Recommendation |
|----------|---------|---------------|
| High document volume (>100K) | `chunking.max_tokens` | Increase to `8000` to reduce chunk count |
| Memory-constrained machine | `indexing.batch_size` | Reduce to `50` |
| GPU available | `indexing.embedder_device` | Set to `cuda` for 10–50× speedup |
| Slow Confluence API | `confluence.max_versions` | Set to `1` (latest only) |
| Large GitLab repos | `gitlab.max_commits_per_project` | Reduce to `100` |
| Graph construction slow | `graph.use_slm` | Set to `false`, use spaCy only |

---

## Air-Gapped Deployment

On an internet-connected machine:

```bash
# Download spaCy models
python -m spacy download ru_core_news_sm
python -m spacy download en_core_web_sm

# Package for transfer
tar -czf spacy_models.tar.gz $(python -c "import spacy; print(spacy.util.get_package_path('ru_core_news_sm'))") \
  $(python -c "import spacy; print(spacy.util.get_package_path('en_core_web_sm'))")
```

On the air-gapped machine:

```bash
# Extract spaCy models
tar -xzf spacy_models.tar.gz -C /opt/
export SPACY_DATA=/opt/spacy_data

# Install offline packages
pip install --no-index --find-links /opt/pip-offline -r requirements_etl.txt
```
