# Integration Guide

**Implementation Status:** Implemented. The RAG system exposes an OpenAI-compatible API, an embeddable chat widget, a Tools SDK, and an MCP server for IDE integration.

---

## 1. Overview

The RAG system provides multiple integration points:

| Integration | Method | Use Case |
|-------------|--------|----------|
| **OpenAI-Compatible API** | REST / SSE | Any OpenAI client, chat applications, custom code |
| **Chat Widget** | HTML/JS | Embed RAG chat in web pages, dashboards, wikis |
| **Tools SDK** | Python decorator | Custom tool definitions for agentic orchestration |
| **Declarative Tools** | YAML/JSON | No-code tool definitions for HTTP and shell integrations |
| **OpenAPI Auto-Discovery** | OpenAPI spec | Automatic tool generation from API specifications |
| **MCP Server** | STDIO / HTTP | IDE integration (OpenCode, Claude Desktop) |

All integrations communicate through the proxy layer at `http://<host>:8080/v1`.

---

## 2. OpenAI-Compatible API

The proxy is a drop-in replacement for any OpenAI-compatible client. No special client code is needed.

### 2.1 Endpoint

```
POST /v1/chat/completions
```

### 2.2 Basic Request

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "your-model-name",
    "messages": [
      {"role": "user", "content": "How does the auth service work?"}
    ]
  }'
```

### 2.3 Streaming

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "your-model-name",
    "messages": [{"role": "user", "content": "Explain the ETL pipeline"}],
    "stream": true
  }'
```

### 2.4 RAG-Specific Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `rag_version` | `string` | Request a specific document version |
| `rag_force_refresh` | `bool` | Bypass response cache for fresh results |

### 2.5 Response Extensions

The proxy adds RAG metadata to the response:

```json
{
  "choices": [...],
  "rag_feedback_id": "fb-abc123",
  "rag_confidence": 0.87,
  "rag_sources": [
    {"title": "Auth Service ADR", "source": "confluence", "relevance": 0.92}
  ]
}
```

### 2.6 Other Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/models` | GET | List available models |
| `/v1/health` | GET | Health check (Qdrant + LLM status) |
| `/v1/health/live` | GET | Liveness probe (K8s-compatible) |
| `/v1/health/ready` | GET | Readiness probe |
| `/v1/feedback` | POST | Submit expert feedback |
| `/v1/tools` | GET | List available tools |
| `/metrics` | GET | Prometheus metrics |

---

## 3. Chat Systems Integration

### 3.1 OpenWebUI

Point OpenWebUI to the RAG proxy as an OpenAI-compatible endpoint:

1. Open OpenWebUI Settings → Connections
2. Set **API Base URL** to `http://<rag-proxy-host>:8080/v1`
3. Set **API Key** to your RAG API key (or leave empty if `AUTH_ENABLED=false`)
4. The model list will populate automatically from `/v1/models`

### 3.2 Any OpenAI-Compatible Client

Any client that supports the OpenAI API format works:

- **Python (openai library)**

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8080/v1",
    api_key="your-api-key",
)

response = client.chat.completions.create(
    model="your-model-name",
    messages=[{"role": "user", "content": "What is the deployment process?"}],
)
print(response.choices[0].message.content)
```

- **Python (openai — streaming)**

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8080/v1",
    api_key="your-api-key",
)

stream = client.chat.completions.create(
    model="your-model-name",
    messages=[{"role": "user", "content": "Explain the ETL pipeline"}],
    stream=True,
)
for chunk in stream:
    content = chunk.choices[0].delta.content
    if content:
        print(content, end="", flush=True)
```

- **Node.js (openai package)**

```javascript
import OpenAI from "openai";

const client = new OpenAI({
  baseURL: "http://localhost:8080/v1",
  apiKey: "your-api-key",
});

const response = await client.chat.completions.create({
  model: "your-model-name",
  messages: [{ role: "user", content: "What is the deployment process?" }],
});
console.log(response.choices[0].message.content);
```

- **curl**

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-api-key" \
  -d '{"model":"your-model-name","messages":[{"role":"user","content":"Hello"}]}'
```

---

## 4. IDE Integration

### 4.1 OpenCode (via MCP Server)

Configure OpenCode to use the RAG MCP server in `opencode.json`:

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

See [MCP Server Guide](mcp-server-guide.md) for detailed setup.

### 4.2 Claude Desktop (via MCP Server)

Add the RAG MCP server to Claude Desktop's configuration:

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

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

For Streamable HTTP transport (remote server):

```json
{
  "mcpServers": {
    "rag-system": {
      "url": "http://rag-proxy.internal.company.com:8081/mcp"
    }
  }
}
```

---

## 5. Widget Integration

### 5.1 Embedding the Widget

The RAG chat widget can be embedded in any web page. Two methods are available:

**Method 1: Standalone JavaScript (recommended)**

```html
<script src="http://localhost:8080/v1/widget.js"></script>
<div id="rag-chat"></div>
<script>
  RAGChatWidget.init({
    container: 'rag-chat',
    endpoint: 'http://localhost:8080/v1/chat/completions',
    token: 'your-jwt-token',  // optional
    model: 'your-model-name', // optional
  });
</script>
```

**Method 2: Full HTML Page (iframe)**

```html
<iframe
  src="http://localhost:8080/v1/widget"
  width="720"
  height="560"
  frameborder="0"
  title="RAG Chat"
></iframe>
```

### 5.2 Widget Configuration

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `container` | `string` | required | CSS selector or element ID for the widget root |
| `endpoint` | `string` | `/v1/chat/completions` | Chat completions endpoint URL |
| `token` | `string` | `null` | JWT Bearer token for authenticated requests |
| `model` | `string` | `null` | Model name override |

### 5.3 Customizing Appearance

The widget uses CSS custom properties. Override them to match your design:

```css
:root {
  --rag-bg: #1a1a2e;          /* Widget background */
  --rag-surface: #16213e;      /* Header and input area */
  --rag-border: #2a3a5c;       /* Border color */
  --rag-text: #e0e0e0;         /* Text color */
  --rag-accent: #4fc3f7;       /* Accent color (logo, links) */
  --rag-user-bg: #1b3a5c;      /* User message bubble */
  --rag-assistant-bg: #16213e;  /* Assistant message bubble */
  --rag-error: #ef5350;         /* Error message color */
  --rag-radius: 8px;           /* Border radius */
}
```

---

## 6. Tools Integration

The Tools system enables the RAG proxy to call external services and execute actions during agentic orchestration.

### 6.1 Creating Custom Tools with `@tool` Decorator

```python
from proxy.app.tools.sdk import tool, ToolContext

@tool(
    name="search_confluence",
    description="Search Confluence pages by CQL query",
    category="live_source",
    tags=["confluence", "search"],
    timeout=15.0,
)
async def search_confluence(
    query: str,
    max_results: int = 5,
    ctx: ToolContext = None,
) -> str:
    """Search Confluence pages by CQL query."""
    # Implementation: call Confluence REST API
    return f"Found {max_results} results for '{query}'"
```

Type hints are automatically converted to JSON Schema. The function name becomes the tool name, the docstring becomes the description.

### 6.2 Declarative Tools (YAML/JSON)

Create YAML or JSON files in the declarative tools directory (`TOOLS_DECLARATIVE_DIR`):

**HTTP tool example** (`tools/search_confluence.yaml`):

```yaml
tools:
  - name: search_confluence
    type: http
    description: Search Confluence pages via REST API
    category: live_source
    tags: [confluence, search]
    version: "1.0.0"
    visibility: user
    parameters:
      query:
        type: string
        description: CQL search query
        required: true
      max_results:
        type: integer
        description: Maximum results to return
        default: 5
    http:
      method: GET
      url_template: "{{CONFLUENCE_API_URL}}/rest/api/content/search?cql={{query}}&limit={{max_results}}"
      headers:
        Authorization: "Bearer {{CONFLUENCE_API_TOKEN}}"
      response_path: results
      allowed_hosts:
        - confluence.internal.company.com
```

**Shell tool example** (`tools/get_git_status.yaml`):

```yaml
tools:
  - name: get_git_status
    type: shell
    description: Get git status of the current repository
    category: devops
    tags: [git, status]
    shell:
      command: "git status --short"
      allowed_commands: [git]
      allowed_paths: [/opt/repos]
      working_dir: /opt/repos/main
```

### 6.3 OpenAPI Auto-Discovery

Configure OpenAPI specs in the environment:

```bash
# In .env:
TOOLS_OPENAPI_SPECS='[{"name":"petstore","url":"https://petstore3.swagger.io/api/v3/openapi.json","mode":"auto"}]'
```

The system automatically:
1. Fetches and parses the OpenAPI spec
2. Converts GET endpoints to search tools
3. Converts POST/PUT/DELETE endpoints to action tools
4. Generates handlers that perform the actual HTTP requests
5. Resolves `$ref` pointers and extracts parameters from schemas

### 6.4 Tool Discovery API

List all available tools:

```bash
curl http://localhost:8080/v1/tools
```

Get a specific tool's details:

```bash
curl http://localhost:8080/v1/tools/search_confluence
```

Filter by category or tag:

```bash
curl "http://localhost:8080/v1/tools?category=live_source&tag=search"
```

---

## 7. Authentication

### 7.1 JWT Authentication

When `AUTH_ENABLED=true`, all endpoints require a Bearer token:

```bash
# Login to get a token
curl -X POST http://localhost:8080/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "user", "password": "pass"}'

# Use the token
curl http://localhost:8080/v1/chat/completions \
  -H "Authorization: Bearer <access_token>"
```

### 7.2 API Key Authentication

When using with OpenAI-compatible clients, pass the API key as the Bearer token:

```python
client = OpenAI(
    base_url="http://localhost:8080/v1",
    api_key="your-api-key",  # forwarded to LLM backend
)
```

### 7.3 Role-Based Access Control

| Role | Visible Tools | Access Level |
|------|---------------|-------------|
| `admin` | All tools (public, user, expert, admin) | Full access |
| `expert` | public, user, expert tools | Expert-level tools |
| `user` | public, user tools | Standard user tools |
| `read_only` | public tools only | Read-only access |

---

## 8. Examples

### 8.1 Python — Full RAG Query with Feedback

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8080/v1", api_key="key")

# Query with RAG enrichment
response = client.chat.completions.create(
    model="your-model-name",
    messages=[{"role": "user", "content": "How do I deploy the service?"}],
)

answer = response.choices[0].message.content
print(answer)

# Submit feedback
import requests
requests.post("http://localhost:8080/v1/feedback", json={
    "rag_feedback_id": response.rag_feedback_id,
    "rating": "positive",
})
```

### 8.2 JavaScript — Streaming with Widget

```javascript
// In a web page
<script src="http://localhost:8080/v1/widget.js"></script>
<div id="rag-chat"></div>
<script>
  RAGChatWidget.init({
    container: 'rag-chat',
    endpoint: 'http://localhost:8080/v1/chat/completions',
    token: localStorage.getItem('rag_token'),
  });
</script>
```

### 8.3 Docker Compose — Full Stack

```yaml
services:
  rag-proxy:
    build: ./proxy
    ports:
      - "8080:8080"
    env_file: ./proxy/.env
    depends_on:
      - qdrant
      - redis

  qdrant:
    image: qdrant/qdrant:latest
    ports:
      - "6333:6333"
    volumes:
      - qdrant_data:/qdrant/storage

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

volumes:
  qdrant_data:
```

---

## See Also

- [MCP Server Guide](mcp-server-guide.md) — IDE integration via MCP
- [Tools SDK Guide](agentic-tools-sdk.md) — Python `@tool` decorator reference
- [Declarative Tools Guide](agentic-tools-declarative.md) — YAML/JSON tool definitions
- [OpenAPI Auto-Discovery](agentic-tools-openapi.md) — Automatic tool generation
- [Deployment Guide](deployment-guide.md) — Production deployment
- [Authentication & RBAC](access-control-rbac.md) — Access control configuration
