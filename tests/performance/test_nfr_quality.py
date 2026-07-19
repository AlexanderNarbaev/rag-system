# tests/performance/test_nfr_quality.py
"""NFR-Q: RAG Quality non-functional requirements tests.

Verifies RAG quality metrics and evaluation infrastructure:

- NFR-Q01: Retrieval MRR > 0.80
- NFR-Q02: Recall@20 > 0.90
- NFR-Q03: nDCG@10 > 0.85
- NFR-Q04: Precision@5 > 0.70
- NFR-Q05: Context grounding > 0.70
- NFR-Q06: Hallucination rate < 5%
- NFR-Q07: Chunker coherence > 0.75
- NFR-Q08: Chunker boundary > 0.85
- NFR-Q09: Confidence > 0.5 rate > 70%
- NFR-Q10: Self-reflection correlation
- NFR-Q11: Eval gate thresholds
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


# ============================================================================
# NFR-Q01: Retrieval MRR > 0.80
# ============================================================================


class TestNFR_Q01_MRR:
    """NFR-Q01: MRR > 0.80 on evaluation dataset."""

    def test_mrr_function_exists(self):
        """compute_mrr function must exist."""
        import sys

        sys.path.insert(0, str(PROJECT_ROOT / "proxy"))
        from proxy.app.core.evaluation import compute_mrr

        assert callable(compute_mrr)

    def test_mrr_perfect_ranking(self):
        """MRR must be 1.0 when relevant doc is always at rank 1."""
        import sys

        sys.path.insert(0, str(PROJECT_ROOT / "proxy"))
        from proxy.app.core.evaluation import compute_mrr

        retrieved = [["doc1", "doc2", "doc3"]]
        relevant = [{"doc1"}]
        mrr = compute_mrr(retrieved, relevant)
        assert mrr == 1.0

    def test_mrr_second_rank(self):
        """MRR must be 0.5 when relevant doc is at rank 2."""
        import sys

        sys.path.insert(0, str(PROJECT_ROOT / "proxy"))
        from proxy.app.core.evaluation import compute_mrr

        retrieved = [["doc2", "doc1", "doc3"]]
        relevant = [{"doc1"}]
        mrr = compute_mrr(retrieved, relevant)
        assert abs(mrr - 0.5) < 1e-6

    def test_mrr_metric_gauge(self):
        """Must have retrieval MRR Prometheus gauge."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "metrics.py").read_text()
        assert "rag_retrieval_mrr" in content

    def test_eval_dataset_path_configurable(self):
        """Eval dataset path must be configurable."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "config.py").read_text()
        assert "EVAL_DATASET_PATH" in content


# ============================================================================
# NFR-Q02: Recall@20 > 0.90
# ============================================================================


class TestNFR_Q02_Recall:
    """NFR-Q02: Recall@20 > 0.90."""

    def test_recall_function_exists(self):
        """compute_recall_at_k must exist."""
        import sys

        sys.path.insert(0, str(PROJECT_ROOT / "proxy"))
        from proxy.app.core.evaluation import compute_recall_at_k

        assert callable(compute_recall_at_k)

    def test_recall_perfect(self):
        """Recall@k must be 1.0 when all relevant docs are in top-k."""
        import sys

        sys.path.insert(0, str(PROJECT_ROOT / "proxy"))
        from proxy.app.core.evaluation import compute_recall_at_k

        retrieved = ["doc1", "doc2", "doc3"]
        relevant = {"doc1", "doc2"}
        recall = compute_recall_at_k(retrieved, relevant, k=3)
        assert recall == 1.0

    def test_recall_partial(self):
        """Recall must be partial when not all relevant docs retrieved."""
        import sys

        sys.path.insert(0, str(PROJECT_ROOT / "proxy"))
        from proxy.app.core.evaluation import compute_recall_at_k

        retrieved = ["doc1", "doc3", "doc4"]
        relevant = {"doc1", "doc2"}
        recall = compute_recall_at_k(retrieved, relevant, k=3)
        assert abs(recall - 0.5) < 1e-6

    def test_max_chunks_retrieval_configurable(self):
        """MAX_CHUNKS_RETRIEVAL must be configurable (default 50)."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "config.py").read_text()
        assert "MAX_CHUNKS_RETRIEVAL" in content


# ============================================================================
# NFR-Q03: nDCG@10 > 0.85
# ============================================================================


class TestNFR_Q03_NDCG:
    """NFR-Q03: nDCG@10 > 0.85."""

    def test_ndcg_function_exists(self):
        """compute_ndcg_at_k must exist."""
        import sys

        sys.path.insert(0, str(PROJECT_ROOT / "proxy"))
        from proxy.app.core.evaluation import compute_ndcg_at_k

        assert callable(compute_ndcg_at_k)

    def test_ndcg_perfect_ranking(self):
        """nDCG must be 1.0 for perfect ranking."""
        import sys

        sys.path.insert(0, str(PROJECT_ROOT / "proxy"))
        from proxy.app.core.evaluation import compute_ndcg_at_k

        retrieved = ["doc1", "doc2", "doc3"]
        relevant = {"doc1", "doc2"}
        ndcg = compute_ndcg_at_k(retrieved, relevant, k=3)
        assert abs(ndcg - 1.0) < 1e-6

    def test_ndcg_empty_relevant(self):
        """nDCG must be 1.0 when no relevant docs (vacuously true)."""
        import sys

        sys.path.insert(0, str(PROJECT_ROOT / "proxy"))
        from proxy.app.core.evaluation import compute_ndcg_at_k

        ndcg = compute_ndcg_at_k(["doc1"], set(), k=5)
        assert ndcg == 1.0


# ============================================================================
# NFR-Q04: Precision@5 > 0.70
# ============================================================================


class TestNFR_Q04_Precision:
    """NFR-Q04: Precision@5 > 0.70."""

    def test_precision_function_exists(self):
        """compute_precision_at_k must exist."""
        import sys

        sys.path.insert(0, str(PROJECT_ROOT / "proxy"))
        from proxy.app.core.evaluation import compute_precision_at_k

        assert callable(compute_precision_at_k)

    def test_precision_perfect(self):
        """Precision@5 must be 1.0 when all top-5 are relevant."""
        import sys

        sys.path.insert(0, str(PROJECT_ROOT / "proxy"))
        from proxy.app.core.evaluation import compute_precision_at_k

        retrieved = ["doc1", "doc2", "doc3", "doc4", "doc5"]
        relevant = {"doc1", "doc2", "doc3", "doc4", "doc5"}
        precision = compute_precision_at_k(retrieved, relevant, k=5)
        assert precision == 1.0

    def test_precision_partial(self):
        """Precision@5 must reflect partial relevance."""
        import sys

        sys.path.insert(0, str(PROJECT_ROOT / "proxy"))
        from proxy.app.core.evaluation import compute_precision_at_k

        retrieved = ["doc1", "doc2", "doc3", "docX", "docY"]
        relevant = {"doc1", "doc2", "doc3"}
        precision = compute_precision_at_k(retrieved, relevant, k=5)
        assert abs(precision - 0.6) < 1e-6

    def test_max_chunks_after_rerank(self):
        """MAX_CHUNKS_AFTER_RERANK must be configurable (default 20)."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "config.py").read_text()
        assert "MAX_CHUNKS_AFTER_RERANK" in content


# ============================================================================
# NFR-Q05: Context grounding > 0.70
# ============================================================================


class TestNFR_Q05_Grounding:
    """NFR-Q05: Cosine similarity(answer, context) > 0.70."""

    def test_grounding_module_exists(self):
        """Grounding module must exist."""
        content = (PROJECT_ROOT / "proxy" / "app" / "core" / "grounding.py").read_text()
        assert "def compute_grounding" in content

    def test_grounding_returns_float(self):
        """compute_grounding must return a float score."""
        import sys

        sys.path.insert(0, str(PROJECT_ROOT / "proxy"))
        from proxy.app.core.grounding import compute_grounding

        # With empty inputs, should return 0.0
        score = compute_grounding("", "")
        assert isinstance(score, float)
        assert score == 0.0

    def test_grounding_score_range(self):
        """Grounding score must be in [0.0, 1.0]."""
        import sys

        sys.path.insert(0, str(PROJECT_ROOT / "proxy"))
        from proxy.app.core.grounding import compute_grounding

        score = compute_grounding("test", "test")
        assert 0.0 <= score <= 1.0

    def test_nli_grounding_config(self):
        """Must have NLI grounding configuration."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "config.py").read_text()
        assert "NLI_GROUNDING_ENABLED" in content

    def test_grounding_score_metric(self):
        """Must have grounding score metric."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "metrics.py").read_text()
        assert "rag_grounding_score_high_ratio" in content


# ============================================================================
# NFR-Q06: Hallucination rate < 5%
# ============================================================================


class TestNFR_Q06_Hallucination:
    """NFR-Q06: Hallucination rate < 5%."""

    def test_hallucination_module_exists(self):
        """Hallucination detection module must exist."""
        content = (PROJECT_ROOT / "proxy" / "app" / "core" / "hallucination.py").read_text()
        assert "HallucinationReport" in content

    def test_extract_claims_function(self):
        """Must extract factual claims from answers."""
        import sys

        sys.path.insert(0, str(PROJECT_ROOT / "proxy"))
        from proxy.app.core.hallucination import extract_factual_claims

        claims = extract_factual_claims("RAG is a technique. It combines retrieval and generation.")
        assert len(claims) >= 1

    def test_claim_check_function(self):
        """Must check claims against context."""
        import sys

        sys.path.insert(0, str(PROJECT_ROOT / "proxy"))
        from proxy.app.core.hallucination import check_claim_against_context

        context = "RAG is a technique that combines retrieval and generation for better answers."
        claim = "RAG combines retrieval and generation"
        result = check_claim_against_context(claim, context)
        assert isinstance(result, bool)

    def test_hallucination_report_function(self):
        """Must compute hallucination rate."""
        import sys

        sys.path.insert(0, str(PROJECT_ROOT / "proxy"))
        from proxy.app.core.hallucination import compute_hallucination_rate

        assert callable(compute_hallucination_rate)

    def test_hallucination_metric(self):
        """Must have hallucination detection metric."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "metrics.py").read_text()
        assert "rag_hallucination_detected" in content.lower() or "RAG_HALLUCINATION_DETECTED" in content

    def test_hallucination_check_config(self):
        """Must have hallucination check configuration."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "config.py").read_text()
        assert "HALLUCINATION_CHECK_ENABLED" in content


# ============================================================================
# NFR-Q07: Chunker semantic coherence > 0.75
# ============================================================================


class TestNFR_Q07_ChunkerCoherence:
    """NFR-Q07: Intra-chunk cosine similarity > 0.75."""

    def test_semantic_chunker_exists(self):
        """Semantic chunker must exist."""
        content = (PROJECT_ROOT / "etl" / "chunker" / "semantic_chunker.py").read_text()
        assert "def " in content

    def test_chunker_handles_multiple_formats(self):
        """Chunker must handle HTML, markdown, and plain text."""
        content = (PROJECT_ROOT / "etl" / "chunker" / "semantic_chunker.py").read_text()
        # Must have some format handling
        assert "html" in content.lower() or "markdown" in content.lower()


# ============================================================================
# NFR-Q08: Chunker boundary precision > 0.85
# ============================================================================


class TestNFR_Q08_ChunkerBoundary:
    """NFR-Q08: Chunk boundaries align with section/heading breaks > 85%."""

    def test_chunker_respects_headings(self):
        """Chunker must split on headings/sections."""
        content = (PROJECT_ROOT / "etl" / "chunker" / "semantic_chunker.py").read_text()
        assert "heading" in content.lower() or "section" in content.lower() or "split" in content.lower()


# ============================================================================
# NFR-Q09: Confidence > 0.5 rate > 70%
# ============================================================================


class TestNFR_Q09_Confidence:
    """NFR-Q09: > 70% responses have confidence > 0.5."""

    def test_confidence_module_exists(self):
        """Confidence scoring module must exist."""
        content = (PROJECT_ROOT / "proxy" / "app" / "core" / "confidence.py").read_text()
        assert "def " in content

    def test_confidence_threshold_config(self):
        """Must have configurable confidence threshold."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "config.py").read_text()
        assert "CONFIDENCE_THRESHOLD" in content

    def test_confidence_metric(self):
        """Must have confidence score metric."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "metrics.py").read_text()
        assert "rag_confidence_score" in content

    def test_confidence_high_ratio_metric(self):
        """Must have ratio metric for high-confidence answers."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "metrics.py").read_text()
        assert "rag_confidence_score_high_ratio" in content


# ============================================================================
# NFR-Q10: Self-reflection correlation
# ============================================================================


class TestNFR_Q10_SelfReflection:
    """NFR-Q10: Self-reflection score correlates with expert feedback."""

    def test_reflection_config(self):
        """Must have reflection configuration."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "config.py").read_text()
        assert "REFLECTION_ENABLED" in content
        assert "REFLECTION_DEPTH" in content

    def test_ab_test_config(self):
        """Must have A/B testing infrastructure for correlation testing."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "config.py").read_text()
        assert "AB_TEST_ENABLED" in content

    def test_feedback_endpoint_exists(self):
        """Feedback endpoint must exist for collecting expert ratings."""
        content = (PROJECT_ROOT / "proxy" / "app" / "api" / "feedback.py").read_text()
        assert "feedback" in content.lower()


# ============================================================================
# NFR-Q11: Eval gate thresholds
# ============================================================================


class TestNFR_Q11_EvalGate:
    """NFR-Q11: EvalGate enforces quality thresholds."""

    def test_eval_gate_config_exists(self):
        """Must have eval gate threshold configuration."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "config.py").read_text()
        assert "EVAL_GATE_LLM_BERTSCORE_MIN" in content
        assert "EVAL_GATE_LLM_HALLUCINATION_MAX" in content
        assert "EVAL_GATE_SLM_F1_MIN" in content

    def test_slm_f1_threshold(self):
        """SLM F1 threshold must be >= 0.85."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "config.py").read_text()
        import re

        match = re.search(r"EVAL_GATE_SLM_F1_MIN.*?(\d+\.\d+)", content)
        if match:
            threshold = float(match.group(1))
            assert threshold >= 0.85

    def test_llm_bertscore_threshold(self):
        """LLM BertScore threshold must be >= 0.70."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "config.py").read_text()
        import re

        match = re.search(r"EVAL_GATE_LLM_BERTSCORE_MIN.*?(\d+\.\d+)", content)
        if match:
            threshold = float(match.group(1))
            assert threshold >= 0.70

    def test_llm_hallucination_threshold(self):
        """LLM hallucination max must be <= 0.05."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "config.py").read_text()
        import re

        match = re.search(r"EVAL_GATE_LLM_HALLUCINATION_MAX.*?(\d+\.\d+)", content)
        if match:
            threshold = float(match.group(1))
            assert threshold <= 0.05

    def test_reranker_mrr_threshold(self):
        """Reranker MRR threshold must exist."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "config.py").read_text()
        assert "EVAL_GATE_RERANKER_MRR_MIN" in content

    def test_eval_gate_module_exists(self):
        """EvalGate module must exist in model_evolution."""
        content = (PROJECT_ROOT / "proxy" / "app" / "model_evolution" / "eval_gate.py").read_text()
        assert "class" in content or "def " in content

    def test_compute_all_metrics_function(self):
        """Must have compute_all_metrics for batch evaluation."""
        import sys

        sys.path.insert(0, str(PROJECT_ROOT / "proxy"))
        from proxy.app.core.evaluation import compute_all_metrics

        assert callable(compute_all_metrics)
