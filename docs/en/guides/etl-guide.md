# ETL Pipeline Guide

## Overview

The ETL (Extract, Transform, Load) pipeline ingests data from corporate knowledge sources into the RAG system. It runs
as a standalone process, separate from the proxy layer, on a dedicated ETL machine.

### Pipeline Stages

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│ Extract  │───>│  Chunk   │───>│  Graph   │───>│  Index   │───>│  Done    │
│          │    │          │    │(optional)│    │          │    │          │
│Confluence│    │Semantic  │    │ Entity   │    │ Qdrant   │    │  WAL     │
│Jira      │    │Markdown  │    │ Relation │    │ Hybrid   │    │ Updated  │
│GitLab    │    │HTML      │    │ Neo4j    │    │ Dense +  │    │          │
│Books/Docs│    │Overlap   │    │          │    │ Sparse   │    │          │
└──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘
```

### Key Design Principles

- **Incremental by default** — SHA-256 content-addressable chunks, WAL-based checkpointing
- **Air-gapped compatible** — all models pre-downloaded, no external API calls at runtime
- **Graceful degradation** — Neo4j unavailable? Skip graph expansion. Embedder OOM? Skip indexing.
- **Resume capable** — WAL checkpoints allow restarting from last successful stage

## Architecture

### Directory Structure

```
etl/
├── extractors/          # Data source extractors
│   ├── base_extractor.py    # Base extractor ABC
│   ├── confluence.py        # Confluence API extractor
│   ├── jira.py              # Jira API extractor
│   ├── gitlab.py            # GitLab API extractor
│   ├── book_extractor.py    # EPUB/PDF/DOCX extractor
│   ├── doc_extractor.py     # Markdown/RST/AsciiDoc extractor
│   ├── chat_extractor.py    # Chat export extractor
│   └── image_extractor.py   # Image extraction + captioning
├── chunker/             # Text chunking
│   ├── semantic_chunker.py  # Semantic chunking with metadata enrichment
│   └── hash_versioning.py   # SHA-256 versioning and change detection
├── graph_builder/       # Knowledge graph
│   ├── entity_extractor.py  # NER + relation extraction
│   ├── neo4j_loader.py      # Neo4j graph loader
│   └── schema.yaml          # Graph schema definition
├── indexer/             # Qdrant indexing
│   ├── qdrant_hybrid.py     # Dense + sparse + ColBERT indexing
│   ├── live_vector_lake.py  # Hot/cold storage with rollback
│   └── wal_manager.py       # Write-ahead log manager
├── scheduler/           # ETL orchestration
│   └── run_etl.py           # Main pipeline orchestrator
├── config/
│   └── etl_config.yaml      # Pipeline configuration
└── requirements_etl.txt
```

## Configuration Reference

All configuration is in `etl/config/etl_config.yaml`. Key sections:

### Source Configurations

| Source         | Key Settings                             | Description                             |
|----------------|------------------------------------------|-----------------------------------------|
| **Confluence** | `url`, `username`, `token`, `space_keys` | API endpoint, credentials, space filter |
| **Jira**       | `url`, `username`, `token`, `jql`        | API endpoint, credentials, JQL query    |
| **GitLab**     | `url`, `token`, `project_ids`            | API endpoint, PAT, project filter       |

### Chunking Settings

| Setting            | Default | Description                       |
|--------------------|---------|-----------------------------------|
| `max_tokens`       | 8000    | Maximum tokens per chunk          |
| `overlap_tokens`   | 200     | Token overlap between chunks      |
| `min_chunk_tokens` | 100     | Minimum chunk size before merging |
| `use_slm`          | false   | Use SLM for metadata enrichment   |

### Embedding/Indexing Settings

| Setting           | Default          | Description                             |
|-------------------|------------------|-----------------------------------------|
| `embedder_model`  | `BAAI/bge-m3`    | Embedding model name                    |
| `embedder_device` | `cpu`            | Device for embeddings (`cpu` or `cuda`) |
| `qdrant_host`     | `localhost`      | Qdrant server host                      |
| `qdrant_port`     | `6333`           | Qdrant server port                      |
| `collection_name` | `knowledge_base` | Qdrant collection name                  |
| `batch_size`      | `100`            | Batch size for upserts                  |

### Graph Settings (Optional)

| Setting               | Default                 | Description                            |
|-----------------------|-------------------------|----------------------------------------|
| `graph.enabled`       | `false`                 | Enable graph extraction                |
| `graph.use_spacy`     | `true`                  | Use spaCy for NER                      |
| `graph.spacy_model`   | —                       | spaCy model name (REQUIRED if enabled) |
| `graph.neo4j.enabled` | `false`                 | Enable Neo4j loading                   |
| `graph.neo4j.uri`     | `bolt://localhost:7687` | Neo4j connection URI                   |

### Environment Variables

For sensitive values (tokens, passwords), use environment variables or `etl/.env`:

```bash
cp etl/.env.example etl/.env
# Edit etl/.env with your credentials
```

See `etl/.env.example` for all available environment variables.

## Running ETL

### Full Pipeline

```bash
# Using Makefile (recommended)
make etl

# Direct invocation
cd etl && python scheduler/run_etl.py --config config/etl_config.yaml
```

### Individual Sources

```bash
# Confluence only
make etl-confluence

# Jira only
make etl-jira

# GitLab only
make etl-gitlab
```

### Pipeline Options

```bash
# Test connectivity to all configured sources and exit
python scheduler/run_etl.py --config config/etl_config.yaml --test-connection

# Skip specific stages
python scheduler/run_etl.py --config config/etl_config.yaml --skip-extract
python scheduler/run_etl.py --config config/etl_config.yaml --skip-chunk
python scheduler/run_etl.py --config config/etl_config.yaml --skip-graph
python scheduler/run_etl.py --config config/etl_config.yaml --skip-index

# Override request timeout (seconds)
python scheduler/run_etl.py --config config/etl_config.yaml --timeout 60

# Force full reindex (ignore WAL)
python scheduler/run_etl.py --config config/etl_config.yaml --force-reindex

# Reset WAL and start fresh
python scheduler/run_etl.py --config config/etl_config.yaml --reset-wal
```

**Full CLI reference:**

| Flag                | Description                                              |
|---------------------|----------------------------------------------------------|
| `--config PATH`     | Path to YAML config file (default: `etl_config.yaml`)    |
| `--timeout N`       | Override request timeout in seconds for all sources      |
| `--test-connection` | Test connectivity to all configured sources and exit     |
| `--skip-extract`    | Skip extraction phase (reuse existing raw data)          |
| `--skip-chunk`      | Skip chunking phase (reuse existing chunks)              |
| `--skip-graph`      | Skip graph building phase                                |
| `--skip-index`      | Skip indexing phase                                      |
| `--force-reindex`   | Force full reindex (ignore WAL, recreate collection)     |
| `--reset-wal`       | Reset all WAL checkpoints before run                     |
| `--streaming`       | Start streaming ETL (webhook + consumer) alongside batch |
| `--webhook-only`    | Start only webhook server                                |
| `--consumer-only`   | Start only stream consumer                               |

### Streaming Mode (Real-time)

```bash
# Start webhook server + stream consumer
python scheduler/run_etl.py --streaming

# Webhook server only
python scheduler/run_etl.py --webhook-only

# Stream consumer only
python scheduler/run_etl.py --consumer-only
```

## Adding a New Data Source

### Step 1: Create Extractor

Create `etl/extractors/my_source.py`:

```python
from etl.extractors.base_extractor import BaseExtractor, ExtractedDocument, ExtractorConfig

class MySourceExtractor(BaseExtractor):
    def __init__(self, config: ExtractorConfig):
        super().__init__(config)

    async def extract(self):
        """Yield ExtractedDocument objects."""
        # Connect to source API
        # Iterate over documents
        # Yield ExtractedDocument for each
        ...

    async def validate_connection(self) -> bool:
        """Test connectivity to the source."""
        ...

    def should_process(self, doc: ExtractedDocument, last_hash: str) -> bool:
        """Check if document needs processing (incremental)."""
        if not last_hash:
            return True
        return self.compute_hash(doc.content) != last_hash
```

### Step 2: Add Configuration

Add to `etl/config/etl_config.yaml`:

```yaml
my_source:
  url: "https://my-source.example.com"
  token: "your_token"
  output_dir: "./raw_data/my_source"
  incremental: true
```

### Step 3: Register in Orchestrator

Add extraction function in `etl/scheduler/run_etl.py`:

```python
from etl.extractors.my_source import MySourceExtractor

def run_extract_my_source(config: Dict, wal: WALManager) -> Path:
    my_config = config.get("my_source", {})
    extractor = MySourceExtractor(ExtractorConfig(
        source_name="my_source",
        source_type="my_source",
        base_url=my_config["url"],
        api_token=my_config.get("token", ""),
    ))
    # Run extraction and return output directory
    ...
```

### Step 4: Add to Pipeline

Call your extraction function in the `main()` function of `run_etl.py`.

## Scheduling ETL

### Using Cron

```bash
# Run ETL daily at 2 AM
0 2 * * * cd /path/to/rag-system && make etl >> /var/log/etl.log 2>&1

# Run Confluence every 6 hours
0 */6 * * * cd /path/to/rag-system && make etl-confluence
```

### Using systemd Timer

Create `/etc/systemd/system/etl.service`:

```ini
[Unit]
Description=RAG ETL Pipeline
After=network.target

[Service]
Type=oneshot
WorkingDirectory=/path/to/rag-system
ExecStart=/usr/bin/python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml
```

Create `/etc/systemd/system/etl.timer`:

```ini
[Unit]
Description=Run RAG ETL daily

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl enable --now etl.timer
```

## Monitoring and Troubleshooting

### WAL Checkpoints

The WAL file (`./wal/etl_wal.json`) tracks pipeline progress:

```json
{
  "confluence_extractor": {"last_run": "2025-06-01T00:00:00"},
  "jira_extractor": {"last_run": "2025-06-01T12:00:00"},
  "indexing": {"added": 150, "deleted": 5}
}
```

### Common Issues

| Issue                   | Cause              | Solution                                   |
|-------------------------|--------------------|--------------------------------------------|
| `Connection refused`    | Source API down    | Check source availability                  |
| `401 Unauthorized`      | Expired token      | Refresh API token                          |
| `OOM during indexing`   | Large batch size   | Reduce `batch_size` in config              |
| `ImportError: markdown` | Missing dependency | `pip install markdown`                     |
| `spaCy model not found` | Missing NER model  | `python -m spacy download ru_core_news_sm` |

### Logs

Logs are written to stdout by default. For production, redirect to file:

```bash
python scheduler/run_etl.py --config config/etl_config.yaml 2>&1 | tee /var/log/etl.log
```

## Running Tests

```bash
# All ETL tests
make test-etl

# Specific test
python -m pytest tests/etl/test_semantic_chunker.py -v

# With coverage
python -m pytest tests/etl/ --cov=etl --cov-report=html
```
