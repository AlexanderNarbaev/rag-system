# Block E. HyDE, CRAG, Self-Reflection, Grounding (FR-32 — FR-39)

---

## FR-32. HyDE — Hypothetical Document Embeddings

**Description:**
Before search, the system generates a "hypothetical document" — a text that could
answer the question. The embedding of this document is used for search instead of
(or in addition to) the embedding of the question itself. This improves sparse
search because the hypothetical document contains more relevant terms.

**Acceptance criteria:**

1. HyDE search returns results different from regular search
2. Merging results (HyDE + regular) yields more complete context
3. The log contains "HyDE expansion: N additional results"

**Status:** ✅ Confirmed (`tests/proxy/test_quality_pipeline.py::TestFR32HyDE`)
**Priority:** HIGH
**Reference:** rag-maturity-assessment L5.3

---

## FR-33. CRAG — Corrective Retrieval-Augmented Generation

**Description:**
After search, the system evaluates the quality of results using 4 factors:

- Score distribution (0.4) — distribution of relevance scores
- Coverage ratio (0.3) — coverage of query aspects
- Result count (0.2) — number of results found
- Recency decay (0.1) — document freshness

Based on the evaluation, the system decides: USE (use), REWRITE (rewrite the query),
EXPAND (expand the search), FALLBACK (do not answer).

**Acceptance criteria:**

1. High confidence → USE → the answer is generated from the retrieved context
2. Low confidence → REWRITE → the query is rewritten and search is repeated
3. Very low confidence → FALLBACK → the system reports insufficiency
4. The log contains "Retrieval quality: confidence=X.XXX, action=USE/REWRITE/EXPAND/FALLBACK"

**Status:** ✅ Confirmed (`tests/proxy/test_quality_pipeline.py::TestFR33CRAG`)
**Priority:** HIGH
**Reference:** rag-maturity-assessment L5.1

---

## FR-34. Self-reflection (post-generation critique)

**Description:**
After generating the answer, the system sends the answer back to the LLM with a prompt:
"Assess whether this answer is supported by the context. Score 0-10." If the score is < 5,
the answer is flagged as unreliable.

**Acceptance criteria:**

1. An answer supported by the context — self-reflection score ≥ 5
2. An answer not supported by the context — self-reflection score < 5, log: "Self-critique failed"
3. The self-reflection score is recorded in metrics

**Status:** ✅ Confirmed (`tests/proxy/test_quality_pipeline.py::TestFR34SelfReflection`)
**Priority:** HIGH
**Reference:** rag-maturity-assessment L5.4

---

## FR-35. NLI-based answer grounding

**Description:**
The system checks the "groundedness" of the answer using:

1. Cosine similarity between the answer embedding and the context embedding
2. NLI classification (entailment/contradiction/neutral)

Answers with a grounding score < 0.70 are flagged for review.

**Acceptance criteria:**

1. An answer entailed by the context — grounding score ≥ 0.70
2. An answer contradicting the context — grounding score < 0.70, flagged for review
3. The log contains "Grounding score: X.XXX"

**Status:** ✅ Confirmed (`tests/proxy/test_quality_pipeline.py::TestFR35NLIGrounding`)
**Priority:** HIGH
**Reference:** rag-maturity-assessment L5.5

---

## FR-36. Hallucination detection

**Description:**
The system analyzes the answer for statements not supported by the context.
Each statement is checked individually. Unsupported statements are flagged.

**Acceptance criteria:**

1. An answer with hallucinations — hallucination_score > 0 (there are unsupported claims)
2. An answer without hallucinations — hallucination_score = 0
3. Flagged statements are recorded in the log

**Status:** ✅ Confirmed (`tests/proxy/test_quality_pipeline.py::TestFR36HallucinationDetection`)
**Priority:** HIGH
**Reference:** rag-maturity-assessment L5.5

---

## FR-37. Corrective re-generation

**Description:**
If the answer fails verification (low confidence, grounding score, or hallucinations
detected), the system:

1. Expands the context (retrieves more chunks)
2. Modifies the prompt (adds "answer only based on the context")
3. Lowers the temperature (for a more deterministic answer)
4. Regenerates the answer

**Acceptance criteria:**

1. An answer that failed verification — triggers re-generation
2. The re-generated answer — passes verification (or the system reports failure)
3. Maximum 2 re-generation attempts

**Status:** ✅ Confirmed (`tests/proxy/test_quality_pipeline.py::TestFR37CorrectiveRegeneration`)
**Priority:** HIGH
**Reference:** rag-maturity-assessment L5.6

---

## FR-38. LLMLingua token-level compression ✅

**Description:**
The system compresses the context at the token level, removing "low-significance"
tokens while preserving key information. Target compression: 2-5×, information loss < 5%.

**Acceptance criteria:**

1. The compressed context is 2-5 times shorter than the original
2. Key facts are preserved (check: the LLM answers correctly on the compressed context)
3. Compression latency < 100ms for a 10K-token context

**Status:** ✅ Confirmed (`proxy/app/core/compression.py`,
`tests/proxy/test_quality_pipeline.py::TestFR38LLMLinguaCompression`)
**Priority:** HIGH
**Reference:** rag-maturity-assessment L5

---

## FR-39. LongContextReorder ✅

**Description:**
To combat the "lost in the middle" effect (the LLM remembers information in the middle
of the context less well), the system reorders chunks: the most relevant — at the
beginning and end, less relevant — in the middle.

**Acceptance criteria:**

1. The most relevant chunk — first in the context
2. The second most relevant — last
3. The rest — in the middle, sorted by relevance

**Status:** ✅ Confirmed (`proxy/app/core/reorder.py`,
`tests/proxy/test_quality_pipeline.py::TestFR39LongContextReorder`)
**Priority:** HIGH
**Reference:** rag-maturity-assessment L5
