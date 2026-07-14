# ADR-013: Standalone MCP Server for IDE Integration

**Status:** Accepted  
**Date:** 2026-07-10  
**Author:** Architecture Design  
**Scope:** MCP server exposing RAG tools to OpenCode, Claude Desktop, and other MCP clients

---

## Context

Developers need RAG capabilities integrated into their IDE workflow. The Model Context Protocol (MCP) provides a
standardized way to expose tools to AI-powered IDEs.

Requirements:

- Expose RAG search, chat, and feedback as MCP tools
- Support STDIO transport (for OpenCode, Claude Desktop)
- Support HTTP transport (for web-based clients)
- Installable via pip or as standalone script
- Works with air-gapped environments

## Decision

Create a standalone MCP server using FastMCP framework:

1. **Three tools**: `rag_search`, `rag_chat`, `rag_feedback`
2. **One resource**: `rag://collections` (list available collections)
3. **One prompt**: `rag_help` (usage instructions)
4. **Dual transport**: STDIO (default) and HTTP
5. **Standalone deployment**: Can run independently of main proxy

## Architecture

```
OpenCode/Claude Desktop → MCP Server (STDIO/HTTP) → RAG Proxy (8080)
```

## Tool Definitions

| Tool           | Description                   | Parameters                                 |
|----------------|-------------------------------|--------------------------------------------|
| `rag_search`   | Search corporate documents    | `query: str`, `limit: int = 5`             |
| `rag_chat`     | Ask questions about knowledge | `message: str`, `context: str = ""`        |
| `rag_feedback` | Submit answer feedback        | `query: str`, `answer: str`, `rating: str` |

## Client Configuration

### OpenCode (opencode.json)

```json
{
  "mcp": {
    "rag-system": {
      "type": "local",
      "command": ["python", "/path/to/mcp_server/server.py"],
      "env": { "RAG_PROXY_URL": "http://localhost:8080" }
    }
  }
}
```

### Claude Desktop

```json
{
  "mcpServers": {
    "rag-system": {
      "command": "python",
      "args": ["/path/to/mcp_server/server.py"],
      "env": { "RAG_PROXY_URL": "http://localhost:8080" }
    }
  }
}
```

## Consequences

### Positive

- Developers get RAG capabilities directly in IDE
- Standard MCP protocol works with any MCP client
- Standalone deployment (can run without main proxy)
- Easy to install and configure

### Negative

- Additional service to manage
- Network latency for remote proxies
- No caching (each request goes to proxy)

### Mitigations

- Run MCP server on same machine as IDE (STDIO transport)
- Proxy handles caching internally
- Health check endpoint for monitoring
