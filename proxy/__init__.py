"""RAG Proxy — OpenAI-compatible API for corporate knowledge retrieval.

Provides a FastAPI-based proxy with hybrid search (dense + sparse RRF),
cross-encoder reranking, multi-provider LLM routing, and optional
LangGraph-based agentic orchestration. Supports vLLM, llama.cpp, and
any OpenAI-compatible backend through pluggable provider adapters.
"""
