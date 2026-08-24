# Research Sources & Best Practices Integration

> **Status:** Living document. Last full review: 2026-08-24.
> This guide catalogues the external sources studied during the project audit and maps every distilled
> practice to its implementation status in this repository. Use it as the traceability bridge between
> industry knowledge and our codebase.

## 1. Purpose and Method

During the 2026-08 audit wave, 36 external sources were reviewed (Habr engineering articles, an arXiv
paper, practitioner blogs, and methodology resources). Each source was distilled into concrete
practices, and each practice was classified against the actual codebase:

| Status | Meaning |
|--------|---------|
| ✅ Implemented | The practice exists in code with tests or configuration |
| 🟡 Partial | Foundations exist; a gap or hardening step remains |
| 📋 Backlog | Accepted as a roadmap item, not yet implemented |

The consolidated backlog lives in [§5](#5-adoption-roadmap-prioritized-backlog). Nothing in this
document changes runtime behavior by itself.

---

## 2. Group A — AI Engineering Process & Harness Engineering

### 2.1 Meta-Harness: End-to-End Optimization of Model Harnesses (arXiv:2603.28052)
<https://arxiv.org/abs/2603.28052>

- Outer-loop search over *harness code* (what the system stores/retrieves/presents), not just prompts;
  evolutionary candidates scored via execution traces.
- +7.7 pts over SOTA context management with 4× fewer context tokens; transfers across models.
- **Status:** 🟡 Our `EvalGate` + `proxy/app/shared/ab_test.py` provide the scoring loop;
  automated candidate search over pipeline configs is a backlog item (see §5, B3).

### 2.2 My AI Adoption Journey (Mitchell Hashimoto)
<https://mitchellh.com/writing/my-ai-adoption-journey>

- Six-step agent maturity ladder; forced reproduction builds expertise; split planning vs execution.
- Harness engineering rule: every observed agent mistake becomes an AGENTS.md rule or a programmed gate.
- **Status:** ✅ Multi-agent framework implements steps 1–5 (`artifacts/state/`, verification commands,
  protected zones); mistake-to-gate conversion is standing team policy.

### 2.3 «Красная книга AI-инженера» (oleg.guru/redbook)
<https://oleg.guru/redbook/ru/>

- Ch.1 Two processes, one task: coprocessor model replaces boss/subordinate framing; HITL experts are
  semantic verifiers, not rubber stamps. → ✅ matches dual-model routing + HITL dashboard design.
- Ch.2 Shared state as IPC: specs are the only human-AI channel; addressability (`spec://module/doc#section`)
  cuts correction cost ~10×. → 🟡 compliance doc has stable FR IDs; anchor-citation convention documented here.
- Ch.3 Memory architecture: WAL-as-checkpoint (overwrite each session, ≤1 page, date-first, stale >24h =
  warning); decisions need rationale + revisit condition; constraints section prevents local optimizations.
  → ✅ `session_checkpoint.json` pattern; 🟡 staleness warnings and rationale links on protected zones.

### 2.4 Jimmy Song — AI Native Infrastructure (jimmysong.io)
<https://jimmysong.io/book/ai-native-infra/>

- Three planes: Intent / Execution / Governance with closed feedback loops; tokens as first-class
  governed resource; validation-first loops; agents as primary execution unit.
- Observability must span GPU → KV-cache → TTFT → cost-per-token, not just GPU utilization.
- Agent reliability framework: fault tolerance, recovery, observability, security, state management.
- **Status:** 🟡 Intent/Execution/Governance maps to chat API+orchestrator / Qdrant+vLLM+Neo4j /
  EvalGate+canary+audit. Token budgets exist (`token_optimizer.py`) but are not yet quota-governed per user (§5, B2).
  Orchestrator-level liveness probes absent (§5, B5).

### 2.5 СТРАТУМ methodology (aistratum.ru)
<https://aistratum.ru/>

- LLMs as deterministic compute nodes; PLA layered prompt architecture (static blocks first, dynamic last —
  cache-friendly ordering); RIL layer institutionalizes LLM-as-a-Judge QA gates.
- **Status:** ✅ Prompt assembly order already static-first (`context/builder.py`, harness principle #3);
  🟡 judge verdicts inform confidence scoring but do not hard-gate emission (§5, B4).

### 2.6 Agent Harness: what Anthropic/OpenAI/LangChain actually build (Habr 1023316)
<https://habr.com/ru/articles/1023316/>

- Context rot: quality drops when key content sits mid-window; mitigations = compaction, observation
  masking, just-in-time retrieval, sub-agents returning short summaries.
- Tiered memory: lightweight index always loaded → detail files on demand → raw transcripts search-only;
  memory is a hint, re-verify against live state.
- **Status:** ✅ `context/compression` + LongContextReorder + LLMLingua-style compression implement the
  mitigations; memory-as-hint codified in harness principles.

### 2.7 Stratum digest: making stochastic LLM deterministic (Habr 1043198)
<https://habr.com/ru/articles/1043198/>

- Cyrillic token tax: RU text costs 1.5–2× more tokens than EN — budgeting must be BPE-aware per language.
- Self-audit family (Chain-of-Verification, Reflexion, Self-Consistency) raises output quality measurably.
- **Status:** ✅ BPE-aware counting in `token_optimizer.py`; ✅ self-verification signals in
  `confidence.py` / `hallucination.py`. RU-aware budget profiles: 🟡 (§5, B2).

### 2.8 Postgres Pro: meta-harness optimization survey (Habr 1045532)
<https://habr.com/ru/companies/postgrespro/articles/1045532/>

- Optimization frontier moved prompts → RAG params → whole harness (workflow stage order, tool profiles,
  verifiers); score trajectories, not only answers (OPRO / TextGrad / GEPA lineage).
- Genetic-Pareto optimizer gained +24.9%/+17.6% by reordering workflow stages.
- **Status:** 📋 Backlog: trajectory-level rewards from HITL feedback feeding orchestrator-topology search (§5, B3).

---

## 3. Group B — RAG Architecture Practice

### 3.1 Wiki bot: Confluence → Qdrant+Elastic hybrid RRF (Habr 980004)
<https://habr.com/ru/articles/980004/>

- HTML→Markdown before chunking (raw HTML ≈ zero information for LLMs); hybrid dense+BM25 fused by RRF
  fixes pure-dense relevance failures; RRF k≈60.
- **Status:** ✅ Exact stack match: `etl/extractors/confluence.py` cleaning + `retrieval.py` hybrid RRF.

### 3.2 MTS Web Services RAG assistant, parts 1–2 (Habr 970392, 970476)
<https://habr.com/ru/companies/ru_mts/articles/970476/>

- Anti-hallucination contract: answer only from provided context, cite source URL, explicit refusal fallback.
- Chunk sizing follows embedder tokenization (~10% overlap); metadata schema includes URL + last-updated;
  incremental reindex of changed chunks only.
- **Status:** ✅ `rag_sources` extension + grounding module enforce the contract; ✅ WAL-incremental ETL +
  SHA-256 content-addressed chunks; chunk-size guidance captured in ETL guide.

### 3.3 Knowledge graphs in legal-domain RAG (Habr 1012556)
<https://habr.com/ru/articles/1012556/>

- Vector-RAG loses relations at chunk boundaries; contradictory versions need relation-aware disambiguation;
  adopt graphs only where metrics prove value.
- **Status:** ✅ Neo4j expansion is optional (`GRAPH_ENABLED`) behind graceful degradation; evaluation
  pipeline (MRR/nDCG) is the adoption gate — exactly the recommended discipline.

### 3.4 Self-hosted Hybrid RAG for regulated industries (Habr 1024696)
<https://habr.com/ru/articles/1024696/>

- Full sovereignty stack: Docling scan normalization → BGE-M3 dense+sparse → Qdrant built-in RRF →
  bge-reranker-v2-m3; LangGraph low-score → reformulate-and-retry loop; model ladder sized to hardware.
- **Status:** ✅ Core retrieval/rerank identical; 📋 Backlog: Docling preprocessing for PDF-heavy sources,
  reformulate-retry orchestrator node (§5, A2/A4).

### 3.5 Proxy-Pointer RAG (Towards Data Science)
<https://towardsdatascience.com/proxy-pointer-rag-multimodal-answers-without-multimodal-embeddings/>

- Section-tree parsing instead of sliding windows; images/tables stored as artifacts referenced by relative
  paths; text-only embeddings suffice — relevance judged at synthesis time.
- **Status:** 📋 Backlog upgrade path for `etl/chunker` enabling grounded multimodal answers through the
  existing text-only embedding stack (§5, A1).

### 3.6 NOUZ local MCP knowledge server (Habr 1033746)
<https://habr.com/ru/articles/1033746/>

- Typed maturity labels per node (raw log ≠ verified fact); reference-vector drift detection as KB-health monitor;
  MCP exposes only explicitly released context.
- **Status:** 🟡 MCP server exists; maturity labels + drift monitoring are backlog (§5, A5).

### 3.7 RAG for business: architecture & costs (Habr 1029740)
<https://habr.com/ru/articles/1029740/>

- RAG vs fine-tuning trade-off; chunking sweet spot 500–1500 chars with 10–20% overlap; source quality
  governs answer quality.
- **Status:** ✅ Semantic chunker defaults consistent; used as onboarding reference.

---

## 4. Group C/D — Serving Efficiency, Evaluation & Governance

### 4.1 Quantization fundamentals (Habr 1015510) & MoE quant shootout (Habr 1033808)

- Quantization = lossy weight compression; naive round-to-nearest breaks on outliers; newer formats ≠ better —
  verify per model (Q4_K_M beat a trendy variant by 9.7 pts perplexity on Qwen MoE).
- **Status:** 📋 Backlog: mandate quant-vs-FP16 quality benchmarks in EvalGate before recommending any
  quantized deployment profile (§5, A3).

### 4.2 Speculative decoding: MTP / EAGLE-3 / DFlash (Habr 1036120)

- Draft-head speculation yields 1.5–2× lossless speedup; worst case no slowdown; generation is memory-bound.
- **Status:** 📋 Backlog: llama.cpp/vLLM speculative flags benchmark in performance suite (§5, A3).

### 4.3 Open LLM leaderboard battle test RU/EN (Habr 1021388)

- LLM-judge bias is systematic (+15–30 pts inflation; self-preference even blind): use one strong judge,
  not committees; Value Score = 70%·quality + 30%·log-cost; automated artifact checks (CJK-in-Cyrillic etc.).
- **Status:** 🟡 RAGAS regression testing exists; Value Score formula and artifact checks are backlog (§5, B1/B4).

### 4.4 Controlled evolution of RAG configs («genomes», Habr 1019018)

- Lifecycle candidate → evaluated → pending_approval → active over prompt/routing/cache-policy genomes;
  nothing reaches production without human sign-off.
- **Status:** ✅ Canary + promote machinery + HITL approval implement the same lifecycle for adapters;
  extending it to prompt/cache-policy genomes: 📋 (§5, B3).

### 4.5 Structural safety gates (Camunda PocketOS incident, Habr 1036626)

- Prompt prohibitions are advisory, not enforced: remove capabilities, add human-approval state-machine
  gates, graduated autonomy. Key question: “is there a way the agent still can?”
- **Status:** ✅ Tool sandboxing + RBAC enforce by capability; destructive admin ops
  (promote/rollback/canary-split) sit behind admin role — additional approval-gate hardening: 🟡 (§5, B6).

### 4.6 Local AI assistant as a real backend (Habr 1048252)

- Production LLM call = contract + request_id + structured logs + per-stage timings + sources + honest refusal.
- **Status:** ✅ Request IDs, structured logging, `rag_sources`, refusal behavior all present; 🟡 per-stage
  latency breakdown in response extensions (§5, A6).

### 4.7 Yandex Eda architecture review at scale (Habr 1003700)

- RFC-driven mandatory review + tech radar prevents tool zoo; rejected RFC can yield no-code solutions.
- **Status:** ✅ Strategic Steering Committee + `[STRATEGIC_NEEDED]` gates mirror this governance.

### 4.8 GraphRAG book (Neo4j authors, Habr/piter 1013810)

- KG structures entities/relations → grounded prompts; NL→Cypher translation; agentic graph application.
- **Status:** ✅ Graph builder + multi-hop traversal shipped; NL→Cypher for live graph queries: 📋 (§5, A7).

### 4.9 Adjacent references

| Source | Takeaway | Status |
|--------|----------|--------|
| CodeFox CLI local review (Habr 1006258) | Air-gapped diff-only review bot; baseline mode ignores old debt | ✅ philosophy shared; optional CI integration idea |
| Claude×NotebookLM orchestration (Habr 1007062) | Delegate heavy analysis; citations ground answers | ✅ dual-model routing embodies it |
| DRAG with KNEE adaptive top-k (Habr 1016438) | Hierarchical tree + knee-point pruning sets top_k per query | 📋 §5, A8 |
| Tokenomics / FinOps (jimmysong blog) | Tokens become managed quotas like CPU once was | 🟡 §5, B2 |
| Obsidian PKS case (Habr 1028272) | Wrapper-note linking without duplication | ✅ payload linking analogous |
| Developer→CTO path (OTUS 1027428) | Focus/horizon/leadership shifts | ✅ informs 23-role hierarchy |
| system-design.space | Curated SD/AI-eng learning tracks | reference material for onboarding |

---

## 5. Adoption Roadmap (Prioritized Backlog)

Derived from the audit above. Each item lists target modules and the practice origin (§ refs).

### Priority 1 — high value, contained scope

| ID | Item | Target modules | Origin |
|----|------|----------------|--------|
| A1 | Section-tree chunking with artifact pointers (images/tables) | `etl/chunker/`, `etl/indexer/` | §3.5 |
| A2 | Query-reformulate retry node on low rerank scores | `core/orchestrator/` | §3.4 |
| A3 | Quantization + speculative-decoding benchmark matrix | `scripts/run_benchmarks.py`, EvalGate | §4.1–4.2 |
| A4 | Docling evaluation for scanned PDFs | `etl/extractors/` | §3.4 |
| B1 | Value Score (70/30 quality/log-cost) in registry comparisons | `model_evolution/` registry | §4.3 |
| B2 | Per-user/per-KB token budget quotas + RU-aware budget profiles | `shared/config.py`\*, `token_optimizer.py` | §2.4/2.7/4.9 |
| B6 | Human-approval gates for destructive admin operations | `api/admin.py`, `auth/rbac.py` | §4.5 |

\* protected zone — requires Strategic Steering Committee approval.

### Priority 2 — strategic, larger scope

| ID | Item | Target modules | Origin |
|----|------|----------------|--------|
| A5 | Maturity labels + reference-drift KB health monitor | `confidence.py`, ETL payloads | §3.6 |
| A6 | Per-stage latency breakdown in chat extensions + Prometheus histograms | `api/chat.py`, `shared/metrics.py` | §4.6 |
| A7 | NL→Cypher live graph queries | `live_sources.py` | §4.8 |
| A8 | Knee-point adaptive top-k replacing static rag_top_k | `retrieval.py`, `rerank.py` | §4.9 |
| B3 | Genome lifecycle for prompt/routing/cache configs + trajectory-level scoring | `model_evolution/`, `ab_test.py` | §2.1/2.8/4.4 |
| B4 | LLM-as-a-Judge hard gate before response emission + artifact checks | `confidence.py`, eval suite | §2.5/4.3 |
| B5 | Orchestrator reliability: per-node checkpoint/recovery, five-dimension audit | `orchestrator/`, chaos tests | §2.4 |

### Maintenance rules

1. New external research goes through this document first: add source, distill practices, classify status.
2. When a backlog item ships, flip its marker to ✅ with commit reference in the changelog.
3. Re-review this page at each wave completion (Doc-Sync Reflector owns EN/RU parity).

## See also

- [Development Roadmap](roadmap.md) — feature-level plan
- [Performance & Quality](performance-quality.md) — tuning and resilience detail
- [Compliance Requirements](compliance-requirements.md) — FR/NFR traceability
