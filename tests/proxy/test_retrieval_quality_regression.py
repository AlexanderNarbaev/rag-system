"""CI regression tests for retrieval quality.

Asserts that computed MRR, Recall@k, nDCG@k, and Precision@k
do not regress below defined baseline thresholds when evaluated
against synthetic datasets. No real Qdrant required — uses
pre-computed retrieval results.
"""

import copy

import pytest

from proxy.app.core.evaluation import (
    compute_all_metrics,
    compute_mrr,
    compute_ndcg_at_k,
    compute_precision_at_k,
    compute_recall_at_k,
)
from proxy.app.core.retrieval_evaluator import RetrievalEvaluator

MRR_BASELINE = 0.75
RECALL_AT_5_BASELINE = 0.80
NDCG_AT_5_BASELINE = 0.70
PRECISION_AT_5_BASELINE = 0.50


def _build_synthetic_eval_dataset(
    queries_spec: list[tuple[list[str], set[str]]],
) -> tuple[list[list[str]], list[set[str]]]:
    retrieved = []
    relevant = []
    for r, s in queries_spec:
        retrieved.append(r)
        relevant.append(s)
    return retrieved, relevant


@pytest.fixture
def good_retrieval_pairs():
    """Synthetic dataset with strong retrieval performance.

    All relevant docs appear in the top-5 positions. Expected metrics
    well above baselines: MRR ~1.0, Recall@5 ~1.0, nDCG@5 ~0.95+.
    """
    return _build_synthetic_eval_dataset(
        [
            (["d1", "d2", "d3", "d5", "d7", "d9", "d10"], {"d1", "d2", "d3"}),
            (["d4", "d1", "d6", "d8", "d2"], {"d1", "d2", "d4"}),
            (["d5", "d7", "d1", "d3", "d6", "d9"], {"d1"}),
            (["d2", "d5", "d8", "d1", "d9"], {"d1", "d2", "d8"}),
            (["d3", "d1", "d4", "d7", "d2", "d5"], {"d1", "d2", "d3"}),
        ],
    )


@pytest.fixture
def moderate_retrieval_pairs():
    """Synthetic dataset with mixed retrieval performance.

    Some relevant docs are ranked lower or missing. Metrics should
    fall below baseline thresholds to catch regressions.
    """
    return _build_synthetic_eval_dataset(
        [
            (["x1", "x2", "x3", "x4", "x5", "d1"], {"d1", "d2"}),
            (["y1", "d1", "y2", "y3", "y4"], {"d1", "d2"}),
            (["z1", "z2", "z3", "z4", "z5", "z6", "z7", "z8", "z9", "d1"], {"d1", "d2"}),
            (["w1", "w2", "w3", "w4", "w5"], {"d1", "d2"}),
            (["v1", "d1", "v2", "d2", "v3"], {"d1", "d2"}),
        ],
    )


@pytest.fixture
def edge_case_pairs():
    """Synthetic dataset covering edge cases: empty lists, single items, duplicates."""
    return _build_synthetic_eval_dataset(
        [
            ([], {"d1"}),
            (["d1"], {"d1"}),
            (["x1", "x2", "x3"], {"d1", "d2", "d3"}),
            (["d1", "d2", "d3"], {"d1", "d2", "d3", "d4", "d5"}),
            (["d1", "d2", "d3"], set()),
        ],
    )


@pytest.fixture
def baseline_holdout_dataset():
    """Fixed synthetic dataset used as CI baseline.

    This dataset represents the expected retrieval quality from a healthy
    system. Any code change that causes metrics to drop below the defined
    thresholds on this dataset should be investigated.
    """
    return _build_synthetic_eval_dataset(
        [
            (["d1", "d2", "d4", "d5", "d7", "d9", "d12"], {"d1", "d2", "d4"}),
            (["d3", "d1", "d6", "d8", "d2", "d11", "d13"], {"d1", "d2", "d3", "d6"}),
            (["d5", "d7", "d1", "d3", "d6", "d9", "d14"], {"d1", "d5"}),
            (["d2", "d5", "d1", "d8", "d9", "d4", "d10"], {"d1", "d2", "d4", "d8"}),
            (["d3", "d1", "d4", "d7", "d2", "d5", "d6"], {"d1", "d2", "d3", "d4", "d7"}),
        ],
    )


@pytest.fixture
def precomputed_baseline_metrics():
    """Pre-computed metric values for the baseline holdout dataset.

    These serve as a secondary validation: metrics must match these
    exact values (within tolerance). If they change, either the
    evaluation code was modified or the math is regressing.
    """
    return {
        "mrr": pytest.approx(1.0, abs=1e-3),
        "recall@5": pytest.approx(0.950, abs=1e-3),
        "recall@10": pytest.approx(1.0, abs=1e-3),
        "recall@20": pytest.approx(1.0, abs=1e-3),
        "ndcg@5": pytest.approx(0.931, abs=1e-3),
        "ndcg@10": pytest.approx(0.959, abs=1e-3),
        "precision@5": pytest.approx(0.680, abs=1e-3),
    }


class TestMRRRegression:
    """MRR must not drop below the baseline threshold."""

    def test_mrr_above_baseline_with_good_retrieval(self, good_retrieval_pairs):
        retrieved, relevant = good_retrieval_pairs
        mrr = compute_mrr(retrieved, relevant)
        assert mrr >= MRR_BASELINE, f"MRR {mrr:.4f} below baseline {MRR_BASELINE}"

    def test_mrr_below_baseline_with_poor_retrieval(self, moderate_retrieval_pairs):
        retrieved, relevant = moderate_retrieval_pairs
        mrr = compute_mrr(retrieved, relevant)
        assert mrr < MRR_BASELINE, f"MRR {mrr:.4f} unexpectedly above baseline {MRR_BASELINE}"

    def test_mrr_edge_cases_produce_valid_range(self, edge_case_pairs):
        retrieved, relevant = edge_case_pairs
        mrr = compute_mrr(retrieved, relevant)
        assert 0.0 <= mrr <= 1.0, f"MRR {mrr:.4f} outside valid [0.0, 1.0]"

    def test_mrr_empty_input_returns_zero(self):
        assert compute_mrr([], []) == 0.0

    def test_mrr_identical_results_match_previous(self, good_retrieval_pairs):
        retrieved, relevant = good_retrieval_pairs
        first = compute_mrr(retrieved, relevant)
        second = compute_mrr(copy.deepcopy(retrieved), copy.deepcopy(relevant))
        assert first == pytest.approx(second)


class TestRecallAt5Regression:
    """Recall@5 must not drop below the baseline threshold."""

    def test_recall_at_5_above_baseline_with_good_retrieval(self, good_retrieval_pairs):
        retrieved, relevant = good_retrieval_pairs
        recalls = [compute_recall_at_k(r, s, 5) for r, s in zip(retrieved, relevant, strict=True)]
        avg_recall = sum(recalls) / len(recalls)
        assert avg_recall >= RECALL_AT_5_BASELINE, f"Recall@5 {avg_recall:.4f} below baseline {RECALL_AT_5_BASELINE}"

    def test_recall_at_5_below_baseline_with_moderate_retrieval(self, moderate_retrieval_pairs):
        retrieved, relevant = moderate_retrieval_pairs
        recalls = [compute_recall_at_k(r, s, 5) for r, s in zip(retrieved, relevant, strict=True)]
        avg_recall = sum(recalls) / len(recalls)
        assert avg_recall < RECALL_AT_5_BASELINE, (
            f"Recall@5 {avg_recall:.4f} unexpectedly above baseline {RECALL_AT_5_BASELINE}"
        )

    def test_recall_at_5_edge_cases_valid_range(self, edge_case_pairs):
        retrieved, relevant = edge_case_pairs
        for r, s in zip(retrieved, relevant, strict=True):
            assert 0.0 <= compute_recall_at_k(r, s, 5) <= 1.0

    def test_recall_at_5_empty_relevant_returns_one(self):
        assert compute_recall_at_k(["d1", "d2"], set(), 5) == 1.0

    def test_recall_at_5_empty_retrieved_returns_zero(self):
        assert compute_recall_at_k([], {"d1"}, 5) == 0.0


class TestNDCGRegression:
    """nDCG@k must stay above baseline for good retrieval."""

    def test_ndcg_at_5_above_baseline_good_retrieval(self, good_retrieval_pairs):
        retrieved, relevant = good_retrieval_pairs
        ndcgs = [compute_ndcg_at_k(r, s, 5) for r, s in zip(retrieved, relevant, strict=True)]
        avg = sum(ndcgs) / len(ndcgs)
        assert avg >= NDCG_AT_5_BASELINE, f"nDCG@5 {avg:.4f} below baseline {NDCG_AT_5_BASELINE}"

    def test_ndcg_at_5_below_baseline_moderate_retrieval(self, moderate_retrieval_pairs):
        retrieved, relevant = moderate_retrieval_pairs
        ndcgs = [compute_ndcg_at_k(r, s, 5) for r, s in zip(retrieved, relevant, strict=True)]
        avg = sum(ndcgs) / len(ndcgs)
        assert avg < NDCG_AT_5_BASELINE, f"nDCG@5 {avg:.4f} unexpectedly above baseline {NDCG_AT_5_BASELINE}"

    def test_ndcg_edge_cases_valid_range(self, edge_case_pairs):
        retrieved, relevant = edge_case_pairs
        for r, s in zip(retrieved, relevant, strict=True):
            assert 0.0 <= compute_ndcg_at_k(r, s, 5) <= 1.0

    def test_ndcg_perfect_ranking_is_one(self):
        assert compute_ndcg_at_k(["d1", "d2", "d3"], {"d1", "d2", "d3"}, 3) == pytest.approx(1.0)

    def test_ndcg_no_relevant_is_one(self):
        assert compute_ndcg_at_k(["d1", "d2"], set(), 5) == 1.0


class TestPrecisionRegression:
    """Precision@k must stay above baseline for good retrieval."""

    def test_precision_at_5_above_baseline_good_retrieval(self, good_retrieval_pairs):
        retrieved, relevant = good_retrieval_pairs
        precisions = [compute_precision_at_k(r, s, 5) for r, s in zip(retrieved, relevant, strict=True)]
        avg = sum(precisions) / len(precisions)
        assert avg >= PRECISION_AT_5_BASELINE, f"Precision@5 {avg:.4f} below baseline {PRECISION_AT_5_BASELINE}"

    def test_precision_at_5_valid_range(self, moderate_retrieval_pairs):
        retrieved, relevant = moderate_retrieval_pairs
        for r, s in zip(retrieved, relevant, strict=True):
            assert 0.0 <= compute_precision_at_k(r, s, 5) <= 1.0

    def test_precision_empty_inputs(self):
        assert compute_precision_at_k([], {"d1"}, 5) == 0.0
        assert compute_precision_at_k(["d1"], set(), 5) == 0.0

    def test_precision_zero_k(self):
        assert compute_precision_at_k(["d1", "d2"], {"d1"}, 0) == 0.0

    def test_precision_perfect_match(self):
        assert compute_precision_at_k(["d1", "d2", "d3"], {"d1", "d2"}, 3) == pytest.approx(2 / 3)


class TestBaselineHoldoutRegression:
    """Fixed holdout dataset — exact metrics must match within tolerance.

    If this test fails, either the evaluation code changed or there's
    a numerical regression in the metric computation.
    """

    @pytest.mark.regression
    def test_baseline_mrr_exact(self, baseline_holdout_dataset, precomputed_baseline_metrics):
        retrieved, relevant = baseline_holdout_dataset
        mrr = compute_mrr(retrieved, relevant)
        assert mrr == precomputed_baseline_metrics["mrr"]

    @pytest.mark.regression
    def test_baseline_recall_at_5_exact(self, baseline_holdout_dataset, precomputed_baseline_metrics):
        retrieved, relevant = baseline_holdout_dataset
        recalls = [compute_recall_at_k(r, s, 5) for r, s in zip(retrieved, relevant, strict=True)]
        avg = sum(recalls) / len(recalls)
        assert avg == precomputed_baseline_metrics["recall@5"]

    @pytest.mark.regression
    def test_baseline_recall_at_10_exact(self, baseline_holdout_dataset, precomputed_baseline_metrics):
        retrieved, relevant = baseline_holdout_dataset
        recalls = [compute_recall_at_k(r, s, 10) for r, s in zip(retrieved, relevant, strict=True)]
        avg = sum(recalls) / len(recalls)
        assert avg == precomputed_baseline_metrics["recall@10"]

    @pytest.mark.regression
    def test_baseline_recall_at_20_exact(self, baseline_holdout_dataset, precomputed_baseline_metrics):
        retrieved, relevant = baseline_holdout_dataset
        recalls = [compute_recall_at_k(r, s, 20) for r, s in zip(retrieved, relevant, strict=True)]
        avg = sum(recalls) / len(recalls)
        assert avg == precomputed_baseline_metrics["recall@20"]

    @pytest.mark.regression
    def test_baseline_ndcg_at_5_exact(self, baseline_holdout_dataset, precomputed_baseline_metrics):
        retrieved, relevant = baseline_holdout_dataset
        ndcgs = [compute_ndcg_at_k(r, s, 5) for r, s in zip(retrieved, relevant, strict=True)]
        avg = sum(ndcgs) / len(ndcgs)
        assert avg == precomputed_baseline_metrics["ndcg@5"]

    @pytest.mark.regression
    def test_baseline_ndcg_at_10_exact(self, baseline_holdout_dataset, precomputed_baseline_metrics):
        retrieved, relevant = baseline_holdout_dataset
        ndcgs = [compute_ndcg_at_k(r, s, 10) for r, s in zip(retrieved, relevant, strict=True)]
        avg = sum(ndcgs) / len(ndcgs)
        assert avg == precomputed_baseline_metrics["ndcg@10"]

    @pytest.mark.regression
    def test_baseline_precision_at_5_exact(self, baseline_holdout_dataset, precomputed_baseline_metrics):
        retrieved, relevant = baseline_holdout_dataset
        precisions = [compute_precision_at_k(r, s, 5) for r, s in zip(retrieved, relevant, strict=True)]
        avg = sum(precisions) / len(precisions)
        assert avg == precomputed_baseline_metrics["precision@5"]

    def test_compute_all_metrics_above_baselines(self, baseline_holdout_dataset):
        retrieved, relevant = baseline_holdout_dataset
        metrics = compute_all_metrics(retrieved, relevant)
        assert metrics["mrr"] >= MRR_BASELINE, f"MRR {metrics['mrr']:.4f} below baseline {MRR_BASELINE}"
        assert metrics["recall@5"] >= RECALL_AT_5_BASELINE, (
            f"Recall@5 {metrics['recall@5']:.4f} below baseline {RECALL_AT_5_BASELINE}"
        )
        assert metrics["ndcg@5"] >= NDCG_AT_5_BASELINE, (
            f"nDCG@5 {metrics['ndcg@5']:.4f} below baseline {NDCG_AT_5_BASELINE}"
        )
        assert metrics["num_queries"] == 5.0


class TestRetrievalEvaluatorRegression:
    """CRAG-style RetrievalEvaluator must produce consistent outputs."""

    @pytest.fixture
    def evaluator(self):
        return RetrievalEvaluator()

    def test_evaluate_quality_above_threshold_for_good_chunks(self, evaluator):
        chunks = [
            {"text": "retrieval augmented generation with external knowledge", "score": 0.92},
            {"text": "embedding models for dense retrieval", "score": 0.88},
            {"text": "hybrid search combining sparse and dense vectors", "score": 0.85},
            {"text": "reranking cross-encoder improves precision", "score": 0.82},
            {"text": "context assembly with token budgeting", "score": 0.79},
        ]
        score = evaluator.evaluate_quality("retrieval augmented generation techniques", chunks)
        assert score >= 0.70, f"Quality score {score:.4f} below 0.70 for good chunks"

    def test_evaluate_quality_below_threshold_for_poor_chunks(self, evaluator):
        chunks = [
            {"text": "gardening tips for tomatoes", "score": 0.12},
            {"text": "best hiking trails in Colorado", "score": 0.10},
            {"text": "recipe for chocolate cake", "score": 0.08},
        ]
        score = evaluator.evaluate_quality("retrieval augmented generation techniques", chunks)
        assert score < 0.40, f"Quality score {score:.4f} unexpectedly high for poor chunks"

    def test_action_boundaries_are_stable(self, evaluator):
        assert evaluator.get_action(0.85) == "USE"
        assert evaluator.get_action(0.70) == "USE"
        assert evaluator.get_action(0.69) == "REWRITE"
        assert evaluator.get_action(0.45) == "REWRITE"
        assert evaluator.get_action(0.40) == "REWRITE"
        assert evaluator.get_action(0.39) == "EXPAND"
        assert evaluator.get_action(0.25) == "EXPAND"
        assert evaluator.get_action(0.20) == "EXPAND"
        assert evaluator.get_action(0.19) == "FALLBACK"
        assert evaluator.get_action(0.00) == "FALLBACK"

    @pytest.mark.regression
    def test_decompose_preserves_structure(self, evaluator):
        chunks = [
            {"text": "important retrieval content", "score": 0.90, "source_id": "doc1", "version": "2.0"},
            {"text": "duplicate retrieval content", "score": 0.30, "source_id": "doc2", "version": "1.0"},
            {"text": "", "score": 0.50, "source_id": "doc3", "version": "1.0"},
            {"text": "another useful result", "score": 0.60, "source_id": "doc4", "version": "1.0"},
        ]
        result = evaluator.decompose_chunks(chunks)
        assert len(result) >= 2, f"Expected at least 2 chunks, got {len(result)}"
        assert all(c.get("text") for c in result), "All retained chunks must have non-empty text"
        assert all("source_id" in c for c in result), "Source metadata must be preserved"

    def test_evaluate_and_act_golden_path(self, evaluator):
        chunks = [
            {"text": "RAG architecture with retrieval pipeline", "score": 0.95},
            {"text": "embedding and vector search", "score": 0.90},
            {"text": "LLM generation with context", "score": 0.87},
        ]
        confidence, action, processed = evaluator.evaluate_and_act("RAG retrieval pipeline", chunks)
        assert action == "USE"
        assert confidence >= 0.70
        assert len(processed) > 0


class TestMetricInvariants:
    """Mathematical invariants that must always hold."""

    def test_mrr_bounded_zero_to_one(self, good_retrieval_pairs):
        retrieved, relevant = good_retrieval_pairs
        assert 0.0 <= compute_mrr(retrieved, relevant) <= 1.0

    def test_recall_monotonic_with_k(self):
        retrieved = ["d1", "d3", "d5", "d7", "d9", "d2", "d4", "d6", "d8", "d10"]
        relevant = {"d1", "d2", "d3", "d4"}
        r5 = compute_recall_at_k(retrieved, relevant, 5)
        r10 = compute_recall_at_k(retrieved, relevant, 10)
        assert r5 <= r10, f"Recall@5 ({r5}) should be <= Recall@10 ({r10})"

    def test_ndcg_perfect_vs_random(self):
        perfect = compute_ndcg_at_k(["d1", "d2", "d3", "x", "y"], {"d1", "d2", "d3"}, 5)
        random_order = compute_ndcg_at_k(["x", "y", "d1", "d2", "d3"], {"d1", "d2", "d3"}, 5)
        assert perfect >= random_order, f"Perfect order {perfect:.4f} should be >= random {random_order:.4f}"

    def test_mrr_ignores_elements_after_first_hit(self):
        retrieved = [["x", "d1", "a", "b"], ["x", "d1", "c", "d"]]
        relevant = [{"d1"}, {"d1"}]
        mrr1 = compute_mrr(retrieved, relevant)
        permuted = [["x", "d1", "c", "d"], ["x", "d1", "a", "b"]]
        mrr2 = compute_mrr(permuted, relevant)
        assert mrr1 == pytest.approx(mrr2)

    def test_recall_at_5_independent_of_results_beyond_k(self):
        retrieved_a = ["d1", "x1", "x2", "x3", "x4"]
        retrieved_b = ["d1", "x1", "x2", "x3", "x4", "d2", "d3", "d4"]
        relevant = {"d1", "d2", "d3", "d4"}
        assert compute_recall_at_k(retrieved_a, relevant, 5) == compute_recall_at_k(retrieved_b, relevant, 5)
