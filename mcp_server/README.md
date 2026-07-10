# RAG System MCP Server

A standalone MCP server that exposes RAG (Retrieval-Augmented Generation) tools to MCP-compatible clients like OpenCode, Claude Desktop, and other AI assistants.

## Overview

This server provides:
- **rag_search** — Search your corporate knowledge base for relevant documents
- **rag_chat** — Ask questions and get AI-generated answers from your documents
- **rag_feedback** — Submit feedback to improve answer quality
- **rag://collections** — Resource listing available document collections
- **rag_help** — Prompt with usage guidance

## Installation

### From source (recommended)

```bash
cd mcp_server
pip install -r requirements.txt
```

### Or install dependencies directly

```bash
pip install fastmcp>=0.4.0 httpx>=0.25.0
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RAG_PROXY_URL` | `http://localhost:8080` | URL of the RAG proxy service |
| `MCP_TRANSPORT` | `stdio` | Transport mode: `stdio` or `http` |

### OpenCode Configuration

Add to your `opencode.json`:

```json
{
  "mcpServers": {
    "rag-system": {
      "command": "python",
      "args": ["/path/to/rag-system/mcp_server/server.py"],
      "env": {
        "RAG_PROXY_URL": "http://localhost:8080"
      }
    }
  }
}
```

### Claude Desktop Configuration

Add to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS or `%APPDATA%\Claude\claude_desktop_config.json` on Windows):

```json
{
  "mcpServers": {
    "rag-system": {
      "command": "python",
      "args": ["/path/to/rag-system/mcp_server/server.py"],
      "env": {
        "RAG_PROXY_URL": "http://localhost:8080"
      }
    }
  }
}
```

### HTTP Transport (for remote access)

To run as an HTTP server:

```bash
MCP_TRANSPORT=http python mcp_server/server.py
```

This starts the server on `0.0.0.0:3000`.

## Usage Examples

### Searching for documents

```
Use rag_search to find information about deployment procedures
```

### Asking questions

```
Use rag_chat to ask: "What is the recommended backup strategy for production?"
```

### Submitting feedback

```
Use rag_feedback to mark an answer as helpful with rating "positive"
```

## Development

### Running locally

```bash
# Start the RAG proxy first
make run

# In another terminal, start the MCP server
make mcp-server
```

### Testing the server

```bash
python -c "from mcp_server.server import mcp; print('MCP server OK')"
```

## Troubleshooting

### Server won't start

1. Check that `fastmcp` is installed: `pip show fastmcp`
2. Verify the proxy is running: `curl http://localhost:8080/v1/health`
3. Check environment variables are set correctly

### Connection refused errors

1. Ensure the RAG proxy is running on the expected port
2. Check `RAG_PROXY_URL` environment variable
3. Verify network connectivity to the proxy

### No tools available in client

1. Restart the MCP client after configuration changes
2. Check the server logs for errors
3. Verify the configuration file path is correct

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  MCP Client     │────▶│  MCP Server     │────▶│  RAG Proxy      │
│  (OpenCode,     │     │  (This server)  │     │  (FastAPI)      │
│   Claude, etc.) │     │                 │     │                 │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

The MCP server acts as a bridge between MCP-compatible clients and the RAG proxy service, translating MCP tool calls into HTTP requests to the proxy's OpenAI-compatible API.
