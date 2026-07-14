# MCP Server Guide

**Implementation Status:** Implemented. The MCP server provides IDE integration via the Model Context Protocol, exposing
RAG tools to OpenCode, Claude Desktop, and other MCP-compatible clients.

---

## 1. What is MCP (Model Context Protocol)

The Model Context Protocol (MCP) is an open protocol that enables AI assistants and IDE tools to interact with external
data sources and tools through a standardized interface. Instead of building custom integrations for each AI tool, MCP
provides a single server that any compatible client can connect to.

**Key concepts:**

- **Tools** — callable functions the AI can invoke (e.g., search the knowledge base)
- **Resources** — data the AI can read (e.g., document contents, configuration)
- **Prompts** — pre-defined prompt templates for common tasks
- **Transports** — communication methods (STDIO for local, HTTP for remote)

The RAG system's MCP server exposes the knowledge base search and retrieval capabilities as MCP tools, allowing
IDE-integrated AI assistants to search corporate documentation, retrieve specific documents, and provide context-aware
answers.

---

## 2. Setting Up the MCP Server

### 2.1 Prerequisites

```bash
# Install dependencies (included in proxy requirements)
pip install fastmcp

# Verify the server module exists
python -c "import mcp_server.server; print('MCP server module OK')"
```

### 2.2 Running the MCP Server

**STDIO transport** (for local IDE integration):

```bash
# The MCP client launches the server automatically
python -m mcp_server.server
```

**Streamable HTTP transport** (for remote/shared access):

```bash
# Start as an HTTP server
python -m mcp_server.server --transport http --port 8081
```

### 2.3 Configuration

The MCP server reads configuration from environment variables:

| Variable        | Default                    | Description                           |
|-----------------|----------------------------|---------------------------------------|
| `RAG_PROXY_URL` | `http://localhost:8080/v1` | RAG proxy API endpoint                |
| `MCP_TRANSPORT` | `stdio`                    | Transport type: `stdio` or `http`     |
| `MCP_PORT`      | `8081`                     | HTTP port (when using HTTP transport) |
| `MCP_HOST`      | `0.0.0.0`                  | HTTP bind address                     |

---

## 3. Available Tools

The MCP server exposes the following tools to connected clients:

### 3.1 `search_knowledge_base`

Hybrid search (dense + sparse with RRF fusion) across all indexed documents.

| Parameter   | Type      | Required | Description                    |
|-------------|-----------|----------|--------------------------------|
| `query`     | `string`  | yes      | Search query text              |
| `top_k`     | `integer` | no       | Number of results (default: 5) |
| `namespace` | `string`  | no       | Tenant namespace filter        |
| `version`   | `string`  | no       | Document version filter        |

**Example usage in IDE:**
> "Search the knowledge base for authentication architecture decisions"

### 3.2 `get_document`

Retrieve a specific document by its source ID.

| Parameter | Type     | Required | Description                           |
|-----------|----------|----------|---------------------------------------|
| `doc_id`  | `string` | yes      | Document ID (chunk hash or source ID) |

**Example usage in IDE:**
> "Get the document with ID CONFL-12345"

### 3.3 `list_sources`

List available data sources with document counts.

No parameters required.

**Example usage in IDE:**
> "What data sources are available in the knowledge base?"

### 3.4 `get_graph_context`

Retrieve Neo4j graph context for an entity (requires `GRAPH_ENABLED=true`).

| Parameter | Type      | Required | Description                        |
|-----------|-----------|----------|------------------------------------|
| `entity`  | `string`  | yes      | Entity name to look up             |
| `depth`   | `integer` | no       | Graph traversal depth (default: 2) |

**Example usage in IDE:**
> "What's the graph context around the 'AuthService' entity?"

### 3.5 `submit_feedback`

Submit expert feedback for HITL quality improvement.

| Parameter     | Type     | Required | Description                          |
|---------------|----------|----------|--------------------------------------|
| `feedback_id` | `string` | yes      | Feedback ID from a previous response |
| `rating`      | `string` | yes      | `positive` or `negative`             |
| `correction`  | `string` | no       | Corrected answer text                |

### 3.6 `get_confidence`

Get confidence score for a query-answer pair.

| Parameter | Type     | Required | Description      |
|-----------|----------|----------|------------------|
| `query`   | `string` | yes      | Original query   |
| `answer`  | `string` | yes      | Generated answer |

---

## 4. Available Resources

The MCP server also exposes read-only resources:

| Resource URI   | Description                                                   |
|----------------|---------------------------------------------------------------|
| `rag://config` | Current proxy configuration (non-sensitive)                   |
| `rag://health` | System health status                                          |
| `rag://stats`  | Knowledge base statistics (document counts, source breakdown) |

---

## 5. Using with OpenCode

### 5.1 Configuration

Add the MCP server to your `opencode.json`:

```json
{
  "providers": {
    "rag-system": {
      "name": "RAG System",
      "base_url": "http://localhost:8080/v1",
      "api_key": "${RAG_API_KEY}",
      "models": ["your-model-name"]
    }
  },
  "mcp_servers": {
    "rag-system": {
      "type": "streamableHttp",
      "url": "http://localhost:8081/mcp",
      "description": "RAG System — corporate knowledge base search"
    }
  },
  "model": "rag-system/your-model-name"
}
```

### 5.2 STDIO Transport (Local)

For local development where the MCP server runs on the same machine:

```json
{
  "mcp_servers": {
    "rag-system": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "mcp_server.server"],
      "env": {
        "RAG_PROXY_URL": "http://localhost:8080/v1"
      }
    }
  }
}
```

### 5.3 Usage Examples

Once configured, OpenCode can use RAG tools directly:

- **Search:** "Search the knowledge base for the authentication architecture"
- **Retrieve:** "Get the document with source ID CONFL-12345"
- **List:** "List all available data sources"
- **Graph:** "What's the graph context around the 'AuthService' entity?"
- **Feedback:** "Submit positive feedback for this answer"

---

## 6. Using with Claude Desktop

### 6.1 Configuration

**macOS:** Edit `~/Library/Application Support/Claude/claude_desktop_config.json`

**Windows:** Edit `%APPDATA%\Claude\claude_desktop_config.json`

**STDIO transport:**

```json
{
  "mcpServers": {
    "rag-system": {
      "command": "python",
      "args": ["-m", "mcp_server.server"],
      "env": {
        "RAG_PROXY_URL": "http://localhost:8080/v1"
      }
    }
  }
}
```

**HTTP transport (remote server):**

```json
{
  "mcpServers": {
    "rag-system": {
      "url": "http://rag-proxy.internal.company.com:8081/mcp"
    }
  }
}
```

### 6.2 Usage

After restarting Claude Desktop, the RAG tools appear in the tools menu. Claude can:

1. Search the corporate knowledge base when answering questions
2. Retrieve specific documents for detailed information
3. Explore entity relationships via the knowledge graph
4. Submit feedback to improve answer quality

---

## 7. Troubleshooting

### 7.1 Server Won't Start

```bash
# Check if the module is importable
python -c "import mcp_server.server; print('OK')"

# Check if fastmcp is installed
pip show fastmcp

# Run with verbose logging
MCP_LOG_LEVEL=DEBUG python -m mcp_server.server
```

### 7.2 Client Can't Connect

**STDIO transport:**

- Verify the `command` and `args` are correct in the client config
- Check that the Python path is correct (use full path if needed)
- Ensure `RAG_PROXY_URL` is reachable from the MCP server process

**HTTP transport:**

```bash
# Test the HTTP endpoint directly
curl http://localhost:8081/mcp

# Check if the port is open
netstat -tlnp | grep 8081
```

### 7.3 Tools Return Errors

```bash
# Verify the RAG proxy is healthy
curl http://localhost:8080/v1/health

# Check if tools are enabled
curl http://localhost:8080/v1/tools

# Review proxy logs
docker logs rag-proxy --tail 50
```

### 7.4 Graph Context Unavailable

The `get_graph_context` tool requires Neo4j to be enabled:

```bash
# Verify Neo4j is running
docker ps | grep neo4j

# Check graph configuration
grep GRAPH_ENABLED proxy/.env
# Should be: GRAPH_ENABLED=true
```

### 7.5 Common Error Messages

| Error                 | Cause             | Fix                                          |
|-----------------------|-------------------|----------------------------------------------|
| `Connection refused`  | Proxy not running | Start the proxy: `docker-compose up -d`      |
| `Tool not found`      | Tools not enabled | Set `TOOLS_ENABLED=true` in `.env`           |
| `401 Unauthorized`    | API key mismatch  | Verify `RAG_API_KEY` matches proxy config    |
| `504 Gateway Timeout` | LLM backend slow  | Increase `REQUEST_TIMEOUT` in `.env`         |
| `Neo4j not available` | Graph disabled    | Set `GRAPH_ENABLED=true` and configure Neo4j |

---

## See Also

- [Integration Guide](integration-guide.md) — All integration methods
- [OpenCode Integration](integration-opencode.md) — Detailed OpenCode setup
- [Deployment Guide](deployment-guide.md) — Production deployment
- [Tools SDK Guide](agentic-tools-sdk.md) — Python tool definitions
