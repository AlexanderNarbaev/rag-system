# RAG System — Terminal UI (TUI)

Terminal-based management interface built with Textual for monitoring,
configuration, and administration of the RAG proxy system.

## Features

- **Status Panel** — Real-time service health indicators (Qdrant, Neo4j, Redis, LLM)
- **Log Viewer** — Live log streaming with filtering
- **Config Editor** — Interactive .env file editing with validation
- **Quick Actions** — Restart services, clear cache, run tests with single keystrokes

## Quick Start

```bash
# Install dependencies
pip install -r tui/requirements.txt

# Start TUI (from project root)
make tui

# Or run directly
python tui/app.py
```

## Keyboard Shortcuts

| Key      | Action                |
|----------|-----------------------|
| `q`      | Quit                  |
| `r`      | Refresh status        |
| `l`      | View logs             |
| `c`      | Edit configuration    |
| `d`      | Clear cache           |
| `t`      | Run tests             |
| `Escape` | Close modal / Go back |
| `Ctrl+S` | Save configuration    |

## Configuration

| Variable          | Default                    | Description        |
|-------------------|----------------------------|--------------------|
| `PROXY_URL`       | `http://localhost:8080`    | RAG proxy endpoint |
| `QDRANT_HOST`     | `localhost`                | Qdrant server host |
| `QDRANT_PORT`     | `6333`                     | Qdrant server port |
| `NEO4J_HOST`      | `localhost`                | Neo4j server host  |
| `NEO4J_HTTP_PORT` | `7474`                     | Neo4j HTTP port    |
| `REDIS_HOST`      | `localhost`                | Redis server host  |
| `REDIS_PORT`      | `6379`                     | Redis server port  |
| `LLM_ENDPOINT`    | `http://localhost:8000/v1` | LLM API endpoint   |
| `LOG_DIR`         | `./proxy/logs`             | Log directory path |

## Architecture

The TUI communicates with the RAG proxy via its REST API:

- `/v1/health` — Service health status
- `/metrics` — Prometheus metrics
- `/v1/tools` — Registered tools

Configuration is managed by reading/writing the `proxy/.env` file directly.

## Dependencies

- **textual** — Modern TUI framework
- **rich** — Rich text and formatting
- **requests** — HTTP client for API communication
