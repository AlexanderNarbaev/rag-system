# Deployment

The RAG System is deployed as two separate components that communicate over the network:

1. **RAG Proxy** — Docker Compose stack with the proxy, Qdrant, Neo4j, Redis, vLLM, and HITL dashboard
2. **ETL Pipeline** — Python application that runs on a schedule to extract and index data

## Guides

| Guide | Description |
|-------|-------------|
| [Proxy Deployment](deploy_proxy.md) | Docker Compose setup, configuration, scaling, air-gapped deployment |
| [ETL Deployment](deploy_etl.md) | Pipeline configuration, scheduling, source system setup |

## Architecture

```
┌──────────────────────┐         ┌──────────────────────┐
│    ETL Machine        │         │   Proxy Machine       │
│                       │         │                       │
│  extractors/ ──┐      │         │  ┌─────────────────┐  │
│  chunker/     │      │   API   │  │   rag-proxy     │  │
│  graph_builder/      │◄────────┼──│   :8080         │  │
│  indexer/ ─────┘      │         │  └───────┬─────────┘  │
│                       │         │          │            │
│  → pushes to Qdrant,  │         │  ┌───────┴─────────┐  │
│    Neo4j via API       │         │  │ qdrant  :6333   │  │
│                       │         │  │ redis   :6379   │  │
│                       │         │  │ neo4j   :7687   │  │
│                       │         │  │ vllm    :8000   │  │
│                       │         │  └─────────────────┘  │
└──────────────────────┘         └──────────────────────┘
```

The ETL machine writes to the same Qdrant and Neo4j instances that the proxy reads from. In a typical setup, both components run on separate machines but share the Qdrant and Neo4j endpoints via internal network.
