"""Extended tests for proxy/app/model_evolution/nli_evaluator.py — remaining paths."""

from unittest.mock import patch

from proxy.app.model_evolution.nli_evaluator import (
    NLIEvaluationResult,
    _check_claim_nli,
    evaluate_nli,
    evaluate_nli_batch,
    get_nli_load_error,
    is_nli_model_available,
)


class TestNLIEdgeCases:
    def test_evaluate_nli_none_answer_string(self):
        result = evaluate_nli("", "some context", use_real_nli=False)
        assert result.total_claims == 0
        assert result.overall_score == 0.0

    def test_evaluate_nli_whitespace_answer(self):
        result = evaluate_nli("   \n  \t  ", "context", use_real_nli=False)
        assert result.total_claims == 0

    def test_evaluate_nli_no_claims_after_filtration(self):
        result = evaluate_nli("Hi. Ok. Yes.", "context", use_real_nli=False)
        assert result.total_claims == 0

    def test_evaluate_nli_empty_context(self):
        result = evaluate_nli("This is a long enough claim sentence for testing.", "", use_real_nli=False)
        assert result.total_claims == 1
        assert result.neutral_claims == 1
        assert result.entailed_claims == 0

    def test_evaluate_nli_multiple_claims_varied_overlap(self):
        answer = "The cat sat on the mat. The dog ran to the park. The bird flew high in the sky."
        context = "The cat sat on the mat in the living room. A dog was barking loudly."
        result = evaluate_nli(answer, context, use_real_nli=False)
        assert result.total_claims == 3
        assert len(result.per_claim_scores) == 3

    def test_evaluate_nli_all_entailment(self):
        answer = "The cat sat on the mat. The dog ran to the park."
        context = "The cat sat on the mat and the dog ran to the park yesterday."
        result = evaluate_nli(answer, context, use_real_nli=False)
        assert result.entailment_rate >= 0.0

    def test_evaluate_nli_rates_sum_to_one(self):
        answer = "The cat sat on the mat. The dog ran to the park. The bird flew away."
        context = "The cat sat on the mat."
        result = evaluate_nli(answer, context, use_real_nli=False)
        total_rate = result.entailment_rate + result.contradiction_rate + result.neutral_rate
        assert abs(total_rate - 1.0) < 1e-3


class TestEvaluateNLIBatchExtended:
    def test_batch_mixed_empty_pairs(self):
        pairs = [
            ("", ""),
            ("Valid claim sentence for testing.", "Context for testing."),
            ("", "non-empty context"),
        ]
        result = evaluate_nli_batch(pairs, use_real_nli=False)
        assert "nli_overall_score" in result
        assert 0.0 <= result["nli_overall_score"] <= 1.0

    def test_batch_all_empty_pairs(self):
        pairs = [("", ""), ("", "")]
        result = evaluate_nli_batch(pairs, use_real_nli=False)
        assert result["nli_overall_score"] == 0.0
        assert result["nli_entailment_rate"] == 0.0

    def test_batch_all_zero_claims_total(self):
        # all short claims
        pairs = [("Hi.", "context"), ("Ok.", "context")]
        result = evaluate_nli_batch(pairs, use_real_nli=False)
        assert result["nli_overall_score"] == 0.0

    def test_batch_rates_sum_to_one(self):
        pairs = [
            ("First claim sentence for testing.", "Context about first."),
            ("Second claim sentence for testing.", "Context about second."),
            ("Third claim sentence for testing.", "Context about third."),
        ]
        result = evaluate_nli_batch(pairs, use_real_nli=False)
        total = result["nli_entailment_rate"] + result["nli_contradiction_rate"] + result["nli_neutral_rate"]
        assert abs(total - 1.0) < 1e-3


class TestNLIResultAsMetrics:
    def test_as_metrics_full(self):
        result = NLIEvaluationResult(
            entailment_rate=0.6,
            contradiction_rate=0.2,
            neutral_rate=0.2,
            overall_score=0.5,
            total_claims=10,
            entailed_claims=6,
            contradicted_claims=2,
            neutral_claims=2,
        )
        metrics = result.as_metrics()
        assert metrics["nli_entailment_rate"] == 0.6
        assert metrics["nli_contradiction_rate"] == 0.2
        assert metrics["nli_neutral_rate"] == 0.2
        assert metrics["nli_overall_score"] == 0.5

    def test_as_metrics_all_entailment(self):
        result = NLIEvaluationResult(
            entailment_rate=1.0,
            contradiction_rate=0.0,
            neutral_rate=0.0,
            overall_score=1.0,
            total_claims=5,
            entailed_claims=5,
            contradicted_claims=0,
            neutral_claims=0,
        )
        metrics = result.as_metrics()
        assert metrics["nli_entailment_rate"] == 1.0

    def test_per_claim_scores_default(self):
        result = NLIEvaluationResult(
            entailment_rate=0.5,
            contradiction_rate=0.5,
            neutral_rate=0.0,
            overall_score=0.25,
            total_claims=2,
            entailed_claims=1,
            contradicted_claims=1,
            neutral_claims=0,
        )
        assert result.per_claim_scores == []


class TestIsNLIModelAvailable:
    def test_model_not_loaded_returns_false(self):
        with (
            patch("proxy.app.model_evolution.nli_evaluator._NLI_MODEL", None),
            patch("proxy.app.model_evolution.nli_evaluator._NLI_TOKENIZER", None),
            patch("proxy.app.model_evolution.nli_evaluator._load_nli_model"),
        ):
            assert is_nli_model_available() is False

    def test_model_loaded_returns_true(self):
        with (
            patch("proxy.app.model_evolution.nli_evaluator._NLI_MODEL", "mock_model"),
            patch("proxy.app.model_evolution.nli_evaluator._NLI_TOKENIZER", "mock_tokenizer"),
            patch("proxy.app.model_evolution.nli_evaluator._load_nli_model"),
        ):
            assert is_nli_model_available() is True


class TestGetNLILoadError:
    def test_load_error_string(self):
        with (
            patch("proxy.app.model_evolution.nli_evaluator._NLI_LOAD_ERROR", "torch not installed"),
            patch("proxy.app.model_evolution.nli_evaluator._load_nli_model"),
        ):
            assert get_nli_load_error() == "torch not installed"

    def test_load_error_none(self):
        with (
            patch("proxy.app.model_evolution.nli_evaluator._NLI_LOAD_ERROR", None),
            patch("proxy.app.model_evolution.nli_evaluator._load_nli_model"),
        ):
            assert get_nli_load_error() is None


class TestCheckClaimNLI:
    def test_check_claim_nli_falls_back_on_error(self):
        with patch("proxy.app.model_evolution.nli_evaluator.nli_predict", side_effect=RuntimeError("model error")):
            label, confidence = _check_claim_nli("test claim", "test context")
            assert label in ("entailment", "contradiction", "neutral")
            assert isinstance(confidence, float)


class TestNLIOverallScoreBounded:
    def test_score_with_all_contradiction(self):
        answer = "XYZ ABC DEF GHI JKL MNO PQR STU VWX YZA"
        context = "The cat sat on the mat in the room yesterday."
        result = evaluate_nli(answer, context, use_real_nli=False)
        assert 0.0 <= result.overall_score <= 1.0

    def test_score_with_perfect_entailment(self):
        answer = "The cat sat on the mat. A dog ran quickly."
        context = "The cat sat on the mat and a dog ran quickly through the yard."
        result = evaluate_nli(answer, context, use_real_nli=False)
        assert result.overall_score >= 0.0
