# RAG MCP Server

MCP (Model Context Protocol) server exposing the RAG knowledge base to
MCP-compatible clients like OpenCode and Claude Desktop.

## Quick Start

```bash
cd mcp_server
pip install -r requirements.txt

# STDIO transport (local OpenCode)
python server.py

# Streamable HTTP transport (remote)
MCP_TRANSPORT=http MCP_PORT=8000 python server.py
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `QDRANT_HOST` | `localhost` | Qdrant server host |
| `QDRANT_PORT` | `6333` | Qdrant HTTP port |
| `COLLECTION_NAME` | `knowledge_base` | Qdrant collection name |
| `EMBEDDER_MODEL` | `BAAI/bge-m3` | Sentence-transformers model |
| `EMBEDDER_DEVICE` | `cpu` | Device for embedder (`cpu`, `cuda`) |
| `GRAPH_ENABLED` | `false` | Enable Neo4j graph features |
| `NEO4J_URI` | `bolt://localhost:7687` | Neo4j connection URI |
| `NEO4J_USER` | `neo4j` | Neo4j username |
| `NEO4J_PASSWORD` | `password` | Neo4j password |
| `MCP_TRANSPORT` | `stdio` | Transport: `stdio` or `http` |
| `MCP_HOST` | `0.0.0.0` | Host for HTTP transport |
| `MCP_PORT` | `8000` | Port for HTTP transport |
| `LOG_LEVEL` | `INFO` | Logging level |

## Transport Modes

### STDIO (local OpenCode)

The default mode. OpenCode launches the server as a subprocess and
communicates via stdin/stdout.

### Streamable HTTP (remote OpenCode)

Set `MCP_TRANSPORT=http` and the server runs as an HTTP service.
Connect from a remote OpenCode instance:

```json
{
  "mcpServers": {
    "rag-knowledge": {
      "type": "http",
      "url": "http://rag-host:8000/mcp"
    }
  }
}
```

## OpenCode Configuration

Add to `opencode.json` in your project root or user config:

```jsonc
{
  // ... existing config ...
  "mcpServers": {
    "rag-knowledge": {
      "type": "stdio",
      "command": "python",
      "args": ["mcp_server/server.py"],
      "cwd": "/path/to/rag-system"
    }
  }
}
```

Or for a remote instance:

```jsonc
{
  "mcpServers": {
    "rag-knowledge": {
      "type": "http",
      "url": "http://rag-host.example.com:8000/mcp"
    }
  }
}
```

## Available Tools

| Tool | Parameters | Description |
|------|-----------|-------------|
| `rag_search` | `query`, `top_k=10`, `source_type=None` | Hybrid search in Qdrant, returns ranked results |
| `rag_get_context` | `query`, `max_tokens=5000`, `source_type=None` | Assembles deduplicated context with metadata |
| `rag_list_sources` | — | Lists all data sources and document counts |
| `rag_get_document` | `doc_id` | Retrieves a document by Qdrant point ID |
| `rag_get_entities` | `entity_name` | Queries Neo4j for entity relationships |
| `rag_search_graph` | `query`, `max_hops=2` | Graph-enhanced search with traversal |

## Available Resources

| URI Pattern | Description |
|-------------|-------------|
| `knowledge://sources` | List of all indexed sources |
| `knowledge://document/{doc_id}` | Specific document content |
| `knowledge://entity/{entity_name}` | Entity with relationships |

## Available Prompts

| Prompt | Parameters | Description |
|--------|-----------|-------------|
| `rag_search_prompt` | `query` | Reusable RAG search prompt template |
| `rag_code_review_prompt` | `code`, `context` | Code review with KB context |

## Graceful Degradation

- **Qdrant unavailable** — tools return `{"error": "Qdrant is unavailable"}` instead of crashing
- **Neo4j unavailable** — graph tools return error messages; `GRAPH_ENABLED=false` skips init entirely
- **Embedder unavailable** — falls back to text-only scroll on Qdrant
- All errors are logged with full context, tools never raise exceptions to the MCP client
