# RAG System — Streamlit Dashboard

Web-based management interface for monitoring, configuration, and administration
of the RAG proxy system.

## Features

- **System Status** — Real-time health checks for Qdrant, Neo4j, Redis, and LLM services
- **Metrics** — Prometheus metrics visualization (requests, latency, cache hits)
- **Configuration** — View and edit `.env` settings with sensitive value masking
- **Feedback** — Browse and analyze user feedback entries
- **Tools** — List and inspect registered tools
- **Logs** — View and filter recent log entries with download support

## Quick Start

```bash
# Install dependencies
pip install -r dashboard/requirements.txt

# Start dashboard (from project root)
make dashboard

# Or run directly
streamlit run dashboard/app.py --server.port 8501
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `PROXY_URL` | `http://localhost:8080` | RAG proxy endpoint |
| `QDRANT_HOST` | `localhost` | Qdrant server host |
| `QDRANT_PORT` | `6333` | Qdrant server port |
| `NEO4J_HOST` | `localhost` | Neo4j server host |
| `NEO4J_HTTP_PORT` | `7474` | Neo4j HTTP port |
| `REDIS_HOST` | `localhost` | Redis server host |
| `REDIS_PORT` | `6379` | Redis server port |
| `LLM_ENDPOINT` | `http://localhost:8000/v1` | LLM API endpoint |
| `LOG_DIR` | `./proxy/logs` | Log directory path |

## Access

Open browser at: `http://localhost:8501`

## Architecture

The dashboard communicates with the RAG proxy via its REST API:

- `/v1/health` — Service health status
- `/metrics` — Prometheus metrics
- `/v1/feedback` — Feedback entries
- `/v1/tools` — Registered tools

Configuration is managed by reading/writing the `proxy/.env` file directly.
