# RAG Best Practices & Architectural Patterns — Research Report

> Date: 2026-06-26 | Sources: Anthropic, NirDiamant/RAG_Techniques, arXiv, Pinecone, Azure AI Search, Microsoft

## 1. Chunking Strategies

**Key Findings:**

The field has moved decisively beyond fixed-size chunking. **Anthropic's Contextual Retrieval** (Sep 2024) demonstrated that the single biggest problem in RAG is *loss of context during chunking* — a chunk saying "revenue grew by 3%" is useless without knowing which company and which quarter. Their solution: prepend an LLM-generated 50-100 token contextual summary to each chunk before embedding, reducing retrieval failures by **35%** (embeddings alone) to **49%** (combined with BM25).

**NirDiamant's RAG Techniques repo** catalogs 5 distinct chunking approaches: fixed-size, proposition chunking (LLM breaks text into atomic factual statements), semantic chunking (NLP-based topic boundary detection), contextual chunk headers (document/section context prepended), and relevant segment extraction (dynamic multi-chunk segments). The consensus: semantic chunking + contextual headers is the current pragmatic sweet spot.

The **arXiv RAG Survey** (2312.10997) documents Modular RAG patterns where chunking strategy is *dynamically selected* based on document type — technical docs get sentence-level chunking, narrative docs get paragraph-level.

**Key techniques recommended:**
- Contextual chunk headers (Anthropic method): 50-100 token context prepended before embedding
- Semantic chunking over fixed-size for technical documents
- Proposition chunking for knowledge-dense content (especially tables, specifications)
- Overlap of 10-20% between chunks to avoid boundary information loss

**Sources:**
- https://www.anthropic.com/news/contextual-retrieval
- https://github.com/NirDiamant/RAG_Techniques
- https://arxiv.org/abs/2312.10997

**How this applies to our system:** bge-m3's 8192-token context window means you can embed relatively large chunks (up to 500-1000 tokens). An Anthropic-style contextual prepending pipeline during ETL would be a high-impact, low-cost improvement. The chunker already does semantic chunking — adding contextual headers before the embedding step would directly improve Qdrant retrieval quality.

---

## 2. Retrieval Strategies

**Key Findings:**

Hybrid search (dense + sparse) consistently outperforms pure vector or pure keyword search. **Anthropic's experiments** show that embeddings + BM25 alone improved on embeddings-only across ALL tested datasets. Their final stack (Contextual Embeddings + Contextual BM25 + Reranking) achieved a **67% reduction** in retrieval failures vs. baseline.

The **Azure AI Search team** describes two retrieval tiers in 2025: "agentic retrieval" (LLM-planned, multi-query decomposition, parallel execution) and "classic RAG" (hybrid query + semantic ranking). The industry is rapidly converging on agentic orchestration for complex queries.

**Pinecone's build-up** emphasizes that vector search loses information because meaning gets compressed into a single 768/1024/1536-dim vector — justifying two-stage retrieval (fast retrieval from vector DB → slow but accurate reranker on top candidates).

**Recent arXiv papers** show the frontier moving in several directions:
- **Hybrid-IR** (Jun 2026): dual-path retrieval with graph-based + dense retrieval, iterative retrieve-reason loops for medical QA
- **ColBERT late interaction**: stores per-token embeddings enabling fine-grained matching without the latency of full cross-encoding
- **Fusion retrieval** with RRF (Reciprocal Rank Fusion) remains the dominant result-merging algorithm

**Key techniques recommended:**
- Dense + sparse hybrid mandatory (bge-m3 already provides both)
- Multi-hop retrieval via Neo4j graph traversal for entity-rich queries
- Multi-query / sub-query decomposition is now table-stakes for complex questions
- ColBERT late interaction as an optional precision layer above hybrid search

**Sources:**
- https://www.anthropic.com/news/contextual-retrieval
- https://www.pinecone.io/learn/series/rag/rerankers/
- https://learn.microsoft.com/en-us/azure/search/retrieval-augmented-generation-overview

**How this applies to our system:** bge-m3 already provides dense (1024-dim), sparse (lexical), and ColBERT embeddings — we're ahead of most. Qdrant's hybrid search with RRF is the right fusion method. Consider storing ColBERT token-level embeddings in Qdrant's multi-vector collections for late interaction scoring on top-k results before the cross-encoder reranker.

---

## 3. Reranking

**Key Findings:**

Reranking is the **highest-ROI single improvement** you can add to a RAG pipeline. Pinecone's experiments demonstrate retrieval with reranking surfaces relevant chunks from position 23 to position 1 — documents that would never reach the LLM become top-ranked.

The two-stage retrieval architecture (fast first-stage → accurate second-stage) is the de facto standard. **Pinecone's article** explains the fundamental tradeoff: bi-encoders compress all meaning into one vector (information loss), while cross-encoders process query+document jointly at inference (higher accuracy, but O(n) transformer calls per query).

Beyond cross-encoders:
- **Cohere Rerank**: API-based, state-of-the-art quality but requires internet
- **BGE-Reranker-v2-m3** (BAAI): open-source, used by Pinecone, compatible with bge-m3 ecosystem
- **RankLLM**: LLM-based reranking using listwise prompting, emerging as competitive with cross-encoders
- **ColBERT late interaction**: token-level matching, faster than cross-encoders but more accurate than bi-encoders — a potential middle tier

**Anthropic** found that reranking reduces the retrieval failure rate by an additional 18 percentage points after contextual retrieval is already applied. The stack is *additive* — each improvement compounds.

**Key techniques recommended:**
- Cross-encoder reranker (bge-reranker-v2-m3 pairs naturally with bge-m3 embeddings)
- Rerank top 50-150 candidates down to top 5-20 for the LLM
- Consider ColBERT late interaction as an intermediate precision layer

**Sources:**
- https://www.pinecone.io/learn/series/rag/rerankers/
- https://www.anthropic.com/news/contextual-retrieval

**How this applies to our system:** Current cross-encoder reranker (MiniLM-L-6-v2) is solid but consider upgrading to bge-reranker-v2-m3 for better consistency with bge-m3 embeddings. The two-stage flow (Qdrant hybrid → reranker → LLM) is architecturally correct. Consider adding a ColBERT late-interaction tier between Qdrant retrieval and the cross-encoder reranker.

---

## 4. Query Transformation

**Key Findings:**

**HyDE** (Hypothetical Document Embeddings) and its indexing-time variant **HyPE** (Hypothetical Prompt Embeddings) are the most validated query transformation techniques. HyPE precomputes hypothetical queries per chunk at indexing time (e.g., "What was ACME's revenue growth in Q2 2023?" → retrieves the chunk that says "grew by 3%"). This transforms retrieval into question-question matching, improving context precision by up to **42 percentage points** and claim recall by up to **45 points** — with **no runtime overhead**.

**Step-back prompting** (from DeepMind) generates broader, more abstract queries first to retrieve foundational context, then combines with specific retrieval. Effective for complex reasoning but adds latency.

**Query decomposition** (sub-query breakdown) is now built into Microsoft's agentic retrieval and LangChain/LlamaIndex frameworks. Complex queries get decomposed into 2-5 focused sub-queries executed in parallel.

**Key techniques recommended:**
- HyPE (index-time) over HyDE (query-time) for air-gapped environments — no runtime LLM cost
- Query decomposition for multi-faceted questions
- Step-back prompting reserved for reasoning-heavy queries

**Sources:**
- https://github.com/NirDiamant/RAG_Techniques (HyDE, HyPE, Query Transformations sections)

**How this applies to our system:** SLM router already does intent classification and query decomposition. Adding HyPE during ETL (generating hypothetical questions per chunk and embedding them) would be a powerful index-time enhancement. Since we're air-gapped, HyPE is far more practical than HyDE.

---

## 5. Context Engineering

**Key Findings:**

The **"Lost in the Middle"** paper (Liu et al., 2023, TACL) is the foundational text here. LLMs exhibit a U-shaped performance curve: they use information at the *beginning* and *end* of the context window well, but performance degrades significantly for information in the middle. This applies to both multi-document QA and key-value retrieval tasks, even for explicitly long-context models.

**Anthropic** found that passing top-20 chunks is better than top-10 or top-5, but beyond ~20 chunks, "more information can be distracting." The sweet spot appears to be 15-25 chunks after reranking.

**LongContextReorder** (LangChain) places the most relevant chunks at the beginning and end of the prompt, with lower-relevance chunks in the middle — directly countering the U-shaped curve. This is a simple post-processing step with significant impact.

**Contextual compression** (NirDiamant's technique) uses an LLM to summarize/extract query-relevant portions from retrieved chunks, preserving key information. The **arXiv prior dominance paper** (Jun 2026) demonstrated that SLMs actually *outperform* large models at strict factual extraction from context, and that large models are more prone to overriding retrieved evidence with parametric priors.

**Key techniques recommended:**
- LongContextReorder: place best chunks at start and end of prompt
- Contextual compression via SLM for token budget management
- Token budget allocation: ~40% to most relevant, ~20% each to supporting chunks, ~20% buffer

**Sources:**
- https://arxiv.org/abs/2307.03172 (Lost in the Middle)
- https://www.anthropic.com/news/contextual-retrieval
- https://github.com/NirDiamant/RAG_Techniques
- https://arxiv.org/abs/2606.23695 (Prior Dominance)

**How this applies to our system:** Context builder (`context_builder.py`) already does dedup, versioning, and token-budgeted assembly. Adding LongContextReorder would directly counter the "lost in the middle" effect. The prior dominance finding supports the dual-model architecture: SLM is actually better at factual extraction from retrieved context, while LLM handles composition and reasoning.

---

## 6. Multi-modal RAG

**Key Findings:**

Multi-modal RAG is rapidly maturing in 2025-2026. The **VL-RAG** paper (ECCV 2026) introduces a hybrid retrieval framework that jointly uses text and visual embeddings, achieving 60% Recall@1 on visually homogeneous document sets (invoices, where all documents look identical).

**NirDiamant's catalog** covers two approaches: (1) multi-modal with captioning (extract/caption images, tables, PDFs; store alongside text), and (2) ColPali (convert documents to images, retrieve via vision embeddings, pass to VLM). The captioning approach is more practical for air-gapped environments.

**ColBERT and ColPali** represent the vanguard of multi-modal retrieval — ColPali treats document pages as images and uses vision-language models for end-to-end retrieval without OCR preprocessing.

**Key techniques recommended:**
- Image/table captioning during ETL, captions embedded alongside text
- PDF → text extraction + image extraction + table extraction as parallel indexing paths
- Knowledge graph extraction for structured data (schemas, entity relationships)

**Sources:**
- https://github.com/NirDiamant/RAG_Techniques
- https://arxiv.org/abs/2606.25343 (VL-RAG)

**How this applies to our system:** ETL pipeline already handles Confluence, Jira, GitLab. For documents with images/tables, the captioning approach is the right fit — use the SLM or a small vision model to generate descriptive captions during indexing. Neo4j graph extraction for table data and schema information adds a structured retrieval path.

---

## 7. Production RAG Failures

**Key Findings:**

The most common production failures:

1. **Stale facts in retrieval** — **MemStrata** paper (Jun 2026): when facts change, embedding similarity cannot distinguish old from new (AUROC 0.59). RAG serves superseded values **15-40%** of the time. Solution: temporal validity tracking.

2. **Context pollution from poison + hallucination** — **TRACE** and **Poisoned Playbooks** (Jun 2026): single poisoned documents systematically alter agent behavior. The agent doesn't randomly fail — it *reliably* adopts the poisoned information.

3. **Retrieval-state lock-in** — When repeated LLM samples agree, it's often because they condition on the same *defective retrieval state*. Agreement-based confidence metrics fail — **42% of dense-retrieval errors carry zero answer dispersion**.

4. **Prior dominance** — Large models override retrieved evidence with parametric priors. Commercial API models override explicit evidence in **nearly half of adversarial conflicts**. SLMs show better contextual adherence.

5. **The RAG "70% problem"** — MVP RAG works ~70% of the time. Getting to 90%+ requires systematic attention to each pipeline stage.

**Key techniques recommended:**
- Content-addressable chunking (SHA-256 hashes) with version tracking — already have this
- Retrieval confidence as a separate signal from answer confidence
- Feedback-driven enrichment (closed loop from HITL corrections back to the index)
- Temporal validity tracking for evolving knowledge bases

**Sources:**
- https://arxiv.org/abs/2606.26511 (MemStrata)
- https://arxiv.org/abs/2606.22728 (Retrieval-state lock-in)
- https://arxiv.org/abs/2606.23695 (Prior Dominance)

---

## 8. Air-gapped / On-premise RAG

**Key Findings:**

Air-gapped RAG is an under-documented but critical deployment pattern.

**Embedding models** can run entirely locally (bge-m3, E5, GTE models all have local implementations).

**LLM backends** require local inference: vLLM (high throughput, PagedAttention), llama.cpp (CPU-friendly, GGUF quantization), or Ollama (easiest setup). vLLM supports 200+ model architectures and multi-node distributed inference.

**Reranking models** need to be local too: bge-reranker-v2-m3, MiniLM cross-encoders, or jina-reranker-v2 all run locally. Cohere Rerank is not an option.

**Model downloads** must happen before air-gapping. Our `download_models_offline.py` script addresses this.

**Monitoring** requires local stack: Prometheus + Grafana (not SaaS observability).

The key tradeoff: air-gapped systems cannot use the best API-based rerankers (Cohere), the largest LLMs (GPT-4, Claude), or managed vector DBs. But the quality gap has narrowed dramatically — bge-m3 + bge-reranker-v2-m3 + Llama-3/DeepSeek competitive with commercial stacks on most benchmarks.

**Key techniques recommended:**
- Pre-download all models before deployment
- Run embedding and reranking on same GPU as inference (vLLM supports embedding models)
- Quantize LLMs aggressively (INT4/INT8) using vLLM's quantization support
- Fall back to in-memory caching when Redis is unavailable

**Sources:**
- https://docs.vllm.ai/en/stable/
- https://www.pinecone.io/learn/series/rag/embedding-models-rundown/

---

## 9. Dual-model Architectures (SLM + LLM)

**Key Findings:**

The dual-model pattern (small model for routing/preprocessing, large model for generation) is increasingly validated:

**Industry adoption:** LangChain, LlamaIndex, and Microsoft Azure all ship dual-model patterns. The SLM handles query classification, decomposition, entity extraction, and tool selection. The LLM handles final generation with full context.

**Research validation:** The **Prior Dominance** paper (Jun 2026) found that SLMs match or outperform high-capacity architectures for strict factual extraction from context. Large models are more prone to *ignoring* retrieved evidence in favor of parametric knowledge.

**Cost/latency economics:** SLMs (1.5B-8B parameters) run 5-20x faster than full-scale LLMs (70B+). For routing tasks, the SLM path keeps p50 latency under 500ms vs 2-5 seconds for the LLM path.

**Cascading confidence:** SLM-first with LLM escalation — the SLM handles simple questions entirely; complex or low-confidence cases escalate to the LLM. This mirrors the "system 1 / system 2" cognitive architecture.

**Key techniques recommended:**
- SLM for: intent classification, query decomposition, entity extraction, factuality verification
- LLM for: final response generation, multi-hop reasoning, complex synthesis
- Confidence-based escalation from SLM to LLM
- Expand SLM role: verify LLM outputs against evidence, handle simple queries end-to-end

**Sources:**
- https://arxiv.org/abs/2606.23695 (Prior Dominance)

---

## Top 5 Actionable Recommendations

1. **Add contextual chunk headers** (Anthropic method): During ETL, prepend 50-100 token context to each chunk before embedding. Low cost, 35-49% retrieval improvement.

2. **Implement LongContextReorder**: Place best reranked chunks at start and end of prompt, lower-relevance chunks in the middle.

3. **Upgrade reranker to bge-reranker-v2-m3**: Better ecosystem fit with bge-m3 embeddings. Add ColBERT late-interaction tier.

4. **Add HyPE during ETL**: Generate hypothetical questions per chunk during indexing. Transforms retrieval into question-question matching with zero runtime cost.

5. **Expand SLM responsibilities**: Let SLM verify LLM outputs against evidence, handle simple queries end-to-end, perform factuality checks.
