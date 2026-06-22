# C4 Architecture Diagrams

The system architecture is documented at four levels using the C4 model. All diagrams are available as SVG images and editable `.excalidraw` source files.

## Level 1 — System Context

![C4 Level 1 — System Context](c4-level1-context.svg)

Shows the RAG System in the context of its users and external systems (11 nodes).

## Level 2 — Containers

![C4 Level 2 — Containers](c4-level2-containers.svg)

Decomposes the system into deployable containers: ETL Pipeline, RAG Proxy, Qdrant, Neo4j, Redis, vLLM (10 nodes).

## Level 3 — RAG Proxy Components

![C4 Level 3 — Proxy Components](c4-level3-proxy-components.svg)

Internal components of the RAG Proxy container: retrieval, reranker, context builder, LLM/SLM routers, orchestrator, cache, HITL logging (13 nodes).

## Level 3 — ETL Pipeline Components

![C4 Level 3 — ETL Components](c4-level3-etl-components.svg)

Internal components of the ETL Pipeline: extractors, chunker, graph builder, indexer, WAL manager, scheduler (14 nodes).

## Source Files

Editable `.excalidraw` files are available for each diagram:

- [`c4-level1-context.excalidraw`](c4-level1-context.excalidraw)
- [`c4-level2-containers.excalidraw`](c4-level2-containers.excalidraw)
- [`c4-level3-proxy-components.excalidraw`](c4-level3-proxy-components.excalidraw)
- [`c4-level3-etl-components.excalidraw`](c4-level3-etl-components.excalidraw)

Open these in [Excalidraw](https://excalidraw.com) to edit.
