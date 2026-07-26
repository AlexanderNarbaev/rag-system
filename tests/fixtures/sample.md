# RAG System Overview

Retrieval-Augmented Generation (RAG) combines a large language model with an
external knowledge base to produce grounded, citation-backed answers.

## Hybrid Search

The retriever uses a hybrid of dense embeddings (BAAI/bge-m3, 1024-dim) and
sparse lexical vectors, fused via Reciprocal Rank Fusion (RRF).

## Cross-Encoder Reranking

After retrieval, a cross-encoder reranker (MiniLM-L-6-v2) reorders the top-k
chunks by query–chunk relevance before they are passed to the LLM.

## Context Assembly

The reranked chunks are deduplicated, reordered, and budgeted against the LLM
context window before being formatted with metadata headers.