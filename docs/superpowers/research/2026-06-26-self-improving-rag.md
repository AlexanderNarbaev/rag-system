# Self-Improving RAG: Research Report for v0.5 Planning

> Date: 2026-06-26 | Sources: arXiv, LangChain, LangGraph, GitHub

---

## 1. Corrective RAG (CRAG)

### Current State of the Art

**CRAG** (Yan et al., 2024, arxiv:2401.15884) is the first paper to explicitly design corrective strategies for when retrieval fails:

- **Retrieval Evaluator**: Lightweight T5-large (0.77B) fine-tuned to score each (query, doc) pair. Uses thresholds: Correct / Incorrect / Ambiguous.
- **Correct**: Retrieved docs decomposed into "knowledge strips", irrelevant strips filtered, relevant recomposed.
- **Incorrect**: All docs discarded. Query rewritten. Web search fetches fresh knowledge (inapplicable for air-gap).
- **Ambiguous**: Internal refined knowledge + web search combined.

**Results**: On PopQA, CRAG improved RAG by 7.0% and Self-RAG by 6.9% accuracy. CRAG *without any training of the generator LM* outperformed Self-RAG (which requires instruction tuning) by 20% on PopQA.

### How Our System Compares

| CRAG Feature | Our System |
|---|---|
| Retrieval evaluator (confidence on docs) | Reranker provides per-doc relevance scores — similar, lighter |
| Web search for correction | Not implemented (air-gap constraint) |
| Knowledge strip decomposition | Not implemented |
| Plug-and-play design | Fully plug-and-play via USE_LANGGRAPH |

### What to Implement for v0.5
1. **Knowledge Strip Decomposition**: Split chunks into sentence groups, score each with reranker, filter below-threshold strips, recompose.
2. **Confidence-gated Path Selection**: If no chunk scores above threshold, escalate to different retrieval strategy.
3. **LLM-based document relevance grader**: Add graph node using SLM to grade each document's relevance.

**Paper**: https://arxiv.org/abs/2401.15884 | **Code**: https://github.com/HuskyInSalt/CRAG

---

## 2. Self-RAG

### Current State of the Art

**Self-RAG** (Asai et al., Oct 2023, arxiv:2310.11511) trains a single LM to generate reflection tokens:

- `<Retrieve>`: Whether retrieval is needed (yes/no/continue)
- `<ISREL>`: Rates each passage as relevant/irrelevant
- `<ISSUP>`: Generation fully/partially/no support by passage
- `<ISUSE>`: Output usefulness (1-5 scale)

**Results**: 7B Self-RAG outperformed ChatGPT on fact verification + open-domain QA.

**Token cost**: Very expensive. Each passage requires separate LM call for relevance, support, usefulness.

### How Our System Compares

| Self-RAG Feature | Our System |
|---|---|
| Trained reflection tokens | Not applicable (no fine-tuning) |
| `<Retrieve>` decision | Intent classifier + dynamic top-k |
| `<ISREL>` grading | Reranker (cross-encoder), more efficient |
| `<ISSUP>` factuality check | Confidence heuristics + optional SLM verification |
| `<ISUSE>` usefulness rating | Not implemented |

### What to Implement for v0.5
1. **`<ISUSE>` equivalent**: Add graph node for SLM to rate answer usefulness (1-5). If < 3, rewrite and regenerate.
2. **`<ISSUP>` equivalent**: NLI-style entailment check — "Given context C, is statement S fully supported, partially supported, or unsupported?"
3. **Multi-generation comparison**: Generate 2-3 candidates in parallel, SLM picks best.

**Paper**: https://arxiv.org/abs/2310.11511

---

## 3. Adaptive RAG

### Current State of the Art

**Adaptive-RAG** (Jeong et al., NAACL 2024, arxiv:2403.14403) proposes classifier-based routing:
- **Level A**: Answerable by LLM alone (no retrieval)
- **Level B**: Requires single-step retrieval
- **Level C**: Requires multi-step iterative retrieval

Classifier trained on automatically labeled data. Balances accuracy and latency.

### How Our System Compares

| Adaptive-RAG Feature | Our System |
|---|---|
| Complexity classifier (A/B/C) | Intent classifier (GREETING/FACTUAL/PROCEDURAL/COMPARISON/SUMMARIZATION) |
| Dynamic strategy selection | Dynamic top-k based on intent |
| Multi-step retrieval | LangGraph rewrite→retrieve→check→retry loop |
| No-retrieval fallback | IntentType.GREETING → skips retrieval |

**Verdict**: Our VERIFY_CASCADE (generate → check_confidence → escalate) is a more sophisticated post-generation check than any published adaptive RAG paper.

### What to Implement for v0.5
1. **Query complexity scoring**: Extend intent classifier to output 1-10 score, not just category.
2. **Latency budget allocation**: Track time-per-strategy, dynamically switch based on deadlines.
3. **Confidence-based routing documentation**: Write up VERIFY_CASCADE as original design principle.

**Paper**: https://arxiv.org/abs/2403.14403 | **Code**: https://github.com/starsuzi/Adaptive-RAG

---

## 4. Agentic RAG Patterns

### Current State of the Art

**LangGraph-based Agentic RAG** (blog.langchain.dev, Feb 2024) formalizes three architectures:
1. **Chain**: Linear RAG pipeline
2. **Router**: LLM routes to different retrievers based on question type
3. **State Machine**: Graph with loops, conditional edges, state feedback

Production trends:
- **Tool-use RAG**: LLMs use retrieval as a named tool (function calling pattern)
- **Multi-agent RAG**: Separate agents for retrieval, verification, synthesis
- **LangGraph** has become dominant framework for agentic RAG with state-machine orchestration

### How Our System Compares

We implement a **7-node LangGraph state machine**: `classify_intent → rewrite_query → retrieve → check_sufficiency → graph_expand → rerank → generate`. This covers adaptive retrieval, corrective loops, optional graph expansion, and graceful degradation.

### What to Implement for v0.5
1. **Tool definition for retrieval**: Expose retrieval as a named function for LLM function calling.
2. **Streaming state visibility**: Expose graph state transitions in streaming responses.
3. **Parallel retrieval branches**: Run multiple strategies in parallel, merge results.

**Blog**: https://blog.langchain.dev/agentic-rag-with-langgraph/

---

## 5. Active Learning & Feedback Loops

### Current State of the Art

- **ATLAS** (Izacard et al., 2023): Jointly trains retriever and reader
- **REPLUG** (Shi et al., 2023): Ensemble retrieval + LM scoring, fine-tune retriever
- **RA-DIT** (Lin et al., 2024): Dual instruction tuning for retriever + LLM
- **Reranker fine-tuning**: Production systems collect thumbs-up/down → fine-tune cross-encoder
- **ALCE benchmark** (Gao et al., EMNLP 2023): Evaluates citation quality

### How Our System Compares

Our **self-enrichment pipeline** is more sophisticated than most industry approaches — it actively closes the loop by adding verified Q&A pairs back into Qdrant.

**Gap**: We don't use feedback to *improve the reranker* or *improve retrieval ranking*. Feedback only adds new content.

### What to Implement for v0.5
1. **Reranker fine-tuning from feedback**: Collect (query, correct_doc) pairs, periodically fine-tune MiniLM.
2. **Implicit feedback signals**: Track dwell time, copy-to-clipboard, re-queries.
3. **Query reformulation learning**: Track which rewrites produced better results.
4. **Feedback-driven chunk pruning**: Flag chunks with repeated negative feedback.

**ALCE**: https://arxiv.org/abs/2305.14627 | **RAG Survey**: https://arxiv.org/abs/2402.19473

---

## 6. Confidence & Grounding

### Current State of the Art

1. **Heuristic scoring**: Context relevance, answer length, uncertainty phrases. Fast but imprecise.
2. **NLI-based grounding**: DeBERTa fine-tuned on MNLI to check entailment per claim. Per-claim grounding score.
3. **Self-consistency**: Generate multiple answers, check agreement.
4. **SLM/LLM-as-judge**: Prompt smaller LM to evaluate the answer.
5. **Citation-based confidence**: If model can cite specific passages, confidence is higher.
6. **Semantic entailment graphs**: Decompose answer into atomic facts, check each against context.

### How Our System Compares

Our `confidence.py` uses heuristic scoring only. The optional SLM verification path exists but is minimal.

### What to Implement for v0.5
1. **NLI-based grounding checker**: Deploy DeBERTa-NLI or SLM prompt — "Given context C, is claim X entailed, contradicted, or neutral?" **Highest-impact confidence improvement.**
2. **Atomic fact decomposition**: Before NLI check, decompose answer into atomic claims. Per-claim confidence.
3. **Self-consistency sampling**: Generate 3 answers, compute semantic similarity.
4. **Confidence threshold calibration**: Build test set, calibrate precision/recall.

---

## 7. Token Optimization

### Current State of the Art

**Compression techniques:**
- **LLMLingua** (Jiang et al., EMNLP 2023): Coarse-to-fine compression using small LM. Up to **20x compression** with minimal performance loss.
- **LongLLMLingua**: Chunk-level coarse + token-level fine compression for 50K+ token contexts.
- **Selective Context**: Lexical units scored by self-information and filtered.
- **RECOMP**: Train compressor LM to summarize retrieved documents.

**Prefix caching:**
- **vLLM**: Automatic KV-cache sharing for identical prefixes.
- **SGLang**: RadixAttention — tree-structured prefix cache.

**Dynamic retrieval:**
- **Adaptive top-k**: Already implemented (greeting→0, factual→15, etc.)
- **FLARE**: Retrieve only when needed during generation, not all upfront.

### How Our System Compares

Our `token_optimizer.py` has BPE-aware counting, 4 compression strategies, smart budget allocation. Well ahead of basic systems but not as sophisticated as LLMLingua.

### What to Implement for v0.5
1. **LLMLingua-style compression**: Use SLM perplexity scores to prune redundant tokens. Cut usage by 50-80%.
2. **Prefix caching integration**: Enable `enable_prefix_caching=True` in vLLM config.
3. **Recursive context pruning**: Reranker scores paragraphs within long chunks, keep only top-scoring.
4. **Semantic deduplication**: Embedding cosine similarity across chunks, not just text-level.

**LLMLingua**: https://arxiv.org/abs/2310.05736 | **Code**: https://aka.ms/LLMLingua

---

## Summary: v0.5 Priority Implementation Order

### Phase 1: High Impact, Low Effort
1. **NLI-based grounding checker** — Entailment model or SLM prompt per-claim verification
2. **Prefix caching docs/config** — Enable vLLM prefix caching
3. **Confidence threshold calibration** — Build test set, calibrate precision/recall

### Phase 2: Medium Impact, Medium Effort
4. **Knowledge Strip Decomposition** — CRAG-style decompose → filter → recompose
5. **ISUSE/Self-critique node** — SLM rates answer usefulness, re-generates if low
6. **Reranker fine-tuning from feedback** — Use accepted feedback pairs periodically

### Phase 3: High Impact, High Effort
7. **LLMLingua-style learned compression** — SLM perplexity-based token pruning
8. **Recursive context pruning** — Paragraph-level scoring within long chunks
9. **Query complexity scoring** — Extend intent classifier to 1-10 granular

### Key URLs
- CRAG: https://arxiv.org/abs/2401.15884
- Self-RAG: https://arxiv.org/abs/2310.11511
- Adaptive-RAG: https://arxiv.org/abs/2403.14403
- LLMLingua: https://arxiv.org/abs/2310.05736
- ALCE: https://arxiv.org/abs/2305.14627
- LangGraph Agentic RAG: https://blog.langchain.dev/agentic-rag-with-langgraph/
- RAG Survey: https://arxiv.org/abs/2402.19473
