# MCP Server

The Model Context Protocol (MCP) server exposes RAG system tools to MCP-compatible clients such as OpenCode, Claude Desktop, and other AI assistants.

## Overview

The MCP server provides:

- **Tools** — search the knowledge base, query document versions, check system health
- **Resources** — access indexed documents, ADRs, and configuration
- **Prompts** — pre-built prompt templates for common RAG interactions

## Architecture

```
┌──────────┐   MCP Protocol (STDIO/HTTP)   ┌──────────────┐
│  Client   │ ◄──────────────────────────► │  MCP Server  │
│ (OpenCode,│                               │  (FastMCP)   │
│  Claude)  │                               └──────┬───────┘
└──────────┘                                       │
                                                    │ OpenAI API
                                                    ▼
                                            ┌──────────────┐
                                            │  RAG Proxy   │
                                            │    :8080     │
                                            └──────────────┘
```

## Configuration

### OpenCode Integration

Add to `opencode.json`:

```json
{
  "mcpServers": {
    "rag-system": {
      "command": "python",
      "args": ["-m", "mcp_server.server"],
      "cwd": "/path/to/rag-system",
      "env": {
        "RAG_PROXY_URL": "http://localhost:8080/v1"
      }
    }
  }
}
```

### Claude Desktop Integration

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "rag-system": {
      "command": "python",
      "args": ["-m", "mcp_server.server"],
      "cwd": "/path/to/rag-system"
    }
  }
}
```

## Available Tools

| Tool | Description |
|------|-------------|
| `search_knowledge_base` | Hybrid search across all indexed documents |
| `get_document` | Retrieve a specific document by ID |
| `list_sources` | List available data sources and their sync status |
| `health_check` | Check proxy and dependency health |

## Transport Modes

- **STDIO** — default mode for desktop clients (Claude Desktop, OpenCode)
- **Streamable HTTP** — for remote or server-based clients

See [Integration with OpenCode](../guides/integration-opencode.md) for detailed setup instructions and usage examples.
