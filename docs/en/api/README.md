# API Documentation — RAG System

Machine-readable and human-readable API documentation for the RAG Proxy.

## Files

| File | Description | How to generate |
|------|-------------|-----------------|
| [`openapi.json`](openapi.json) | OpenAPI 3.1 spec (machine-readable) | `make export-openapi` |
| [`reference.md`](reference.md) | Human-readable API reference (Markdown) | Auto-generated with spec |
| [`../../api_reference.md`](../api_reference.md) | Detailed hand-written API guide with examples | Manual |

## Quick Start

### Generate / Update the Spec

```bash
# From project root
make export-openapi

# Or run directly
python scripts/export_openapi.py
```

### Validate Only (CI-friendly)

```bash
python scripts/export_openapi.py --validate-only
```

### Custom Output Directory

```bash
python scripts/export_openapi.py --output-dir ./api-docs
```

## Spec Details

The OpenAPI spec is extracted directly from the FastAPI application source code at
`proxy/app/main.py`. It includes all registered routers:

| Tag | Router | Prefix |
|-----|--------|--------|
| `chat` | `api/chat.py` | `/v1/chat` |
| `models` | `main.py` | `/v1/models` |
| `health` | `api/health.py` | `/v1/health` |
| `auth` | `api/auth_endpoints.py` | `/v1/auth` |
| `feedback` | `api/feedback.py` | `/v1/feedback` |
| `tools` | `api/tools.py` | `/v1/tools` |
| `admin` | `api/admin.py` | `/v1/admin` |
| `files` | `api/files.py` | `/v1/files` |
| `widget` | `api/widget.py` | `/v1/widget` |
| `metrics` | `api/metrics.py` | `/metrics` |

## Using the Spec

### Swagger UI (live)

When the proxy is running, interactive docs are available at:

```
http://localhost:8080/docs      # Swagger UI
http://localhost:8080/redoc     # ReDoc
http://localhost:8080/openapi.json  # Live spec
```

### Client Code Generation

Use the spec to auto-generate typed API clients:

```bash
# Python client (openapi-python-client)
openapi-python-client generate --path docs/en/api/openapi.json

# TypeScript client (openapi-typescript)
npx openapi-typescript docs/en/api/openapi.json -o src/api.d.ts

# Go client (oapi-codegen)
oapi-codegen -package ragclient docs/en/api/openapi.json > client.go
```

### Postman / Insomnia

Import `openapi.json` directly into Postman or Insomnia for API exploration.

## CI Integration

The CI pipeline includes an optional OpenAPI validation step that:

1. Extracts the spec from the FastAPI app
2. Validates structural integrity (paths, operations, schemas)
3. Fails on critical errors; warns on missing summaries/descriptions
4. Uploads the spec as a build artifact

See `.github/workflows/ci.yml` for the `openapi` job.

## Keeping Docs in Sync

The spec is **auto-generated from source code** — it is always in sync with the actual API
as long as routers are properly registered in `proxy/app/main.py`.

To update after changing API routes:

```bash
make export-openapi
git add docs/en/api/openapi.json docs/en/api/reference.md
git commit -m "docs: update OpenAPI spec"
```
