# RAG System Architecture
<!-- excalidraw-architect: knowledge-graph v1 -->
<!-- direction: LR -->

## Services
- fastapi-proxy: FastAPI Proxy [type: fastapi] [domain: proxy] — OpenAI-compatible API with hybrid retrieval, reranking, multi-provider LLM routing
- qdrant: Qdrant [type: qdrant] [domain: storage] — Vector DB — hybrid search (dense+sparse), RRF fusion
- neo4j: Neo4j [type: neo4j] [domain: storage] — Graph DB — entity relationships, multi-hop traversal
- redis: Redis [type: redis] [domain: storage] — Cache — embedding cache, rerank results, response cache
- etl-pipeline: ETL Pipeline [type: python] [domain: etl] — Data extraction, chunking, embedding, indexing for Confluence, Jira, GitLab
- hitl-dashboard: HITL Dashboard [type: streamlit] [domain: hitl] — Streamlit expert dashboard for feedback and quality control
- mcp-server: MCP Server [type: python] [domain: integration] — Model Context Protocol server for OpenCode/Claude Desktop integration
- llm-backend: LLM Backend [type: vllm] [domain: inference] — Multi-provider LLM backend: vLLM, llama.cpp, OpenAI-compatible
- slm-router: SLM Router [type: python] [domain: proxy] — Lightweight SLM for intent classification, query decomposition, entity extraction
- reranker: Reranker [type: python] [domain: proxy] — Cross-encoder reranker (MiniLM-L-6-v2)

## Dependencies
- etl-pipeline -> qdrant : "indexes vectors"
- etl-pipeline -> neo4j : "loads graph"
- fastapi-proxy -> qdrant : "hybrid search"
- fastapi-proxy -> neo4j : "graph expansion" [style: dashed]
- fastapi-proxy -> redis : "cache" [style: dashed]
- fastapi-proxy -> llm-backend : "generate"
- fastapi-proxy -> slm-router : "query routing"
- fastapi-proxy -> reranker : "rerank"
- fastapi-proxy -> hitl-dashboard : "HITL API"
- mcp-server -> fastapi-proxy : "calls proxy API"
