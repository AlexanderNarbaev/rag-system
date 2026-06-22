"""Tests for proxy/app/model_evolution/metrics_gen.py — generation evaluation metrics."""

import pytest

from proxy.app.model_evolution.metrics_gen import (
    GenerationMetrics,
    compute_all_gen_metrics,
    compute_bertscore,
    compute_bleu,
    compute_generation_metrics,
    compute_hallucination_rate,
    compute_perplexity,
    compute_rouge_l,
)


class TestComputeBLEU:
    def test_perfect_match(self):
        refs = ["the cat sits on the mat"]
        hyps = ["the cat sits on the mat"]
        result = compute_bleu(refs, hyps)
        assert "bleu_1" in result
        assert "bleu_4" in result
        assert result["bleu_1"] == pytest.approx(1.0, abs=0.01)
        assert result["bleu_4"] == pytest.approx(1.0, abs=0.01)

    def test_partial_match(self):
        refs = ["the cat sits on the mat"]
        hyps = ["the dog sits on the floor"]
        result = compute_bleu(refs, hyps)
        # "the", "sits", "on", "the" overlap → some n-grams match
        assert 0.0 < result["bleu_1"] < 1.0
        assert 0.0 <= result["bleu_4"] < result["bleu_1"]

    def test_no_overlap(self):
        refs = ["the cat sits on the mat"]
        hyps = ["x y z w v u"]
        result = compute_bleu(refs, hyps)
        assert result["bleu_1"] == 0.0
        assert result["bleu_4"] == 0.0

    def test_multiple_references(self):
        refs = ["the cat sits on the mat", "the dog runs fast"]
        hyps = ["the cat sits on the mat", "a dog runs quickly"]
        result = compute_bleu(refs, hyps)
        assert "bleu_1" in result
        assert "bleu_4" in result
        assert 0.0 < result["bleu_1"] < 1.0


class TestComputeROUGEL:
    def test_perfect_match(self):
        refs = ["the cat sits on the mat"]
        hyps = ["the cat sits on the mat"]
        result = compute_rouge_l(refs, hyps)
        assert result["rouge_l_precision"] == pytest.approx(1.0)
        assert result["rouge_l_recall"] == pytest.approx(1.0)
        assert result["rouge_l_f1"] == pytest.approx(1.0)

    def test_partial_match(self):
        refs = ["the cat sits on the mat"]
        hyps = ["the dog sits on the mat"]
        # LCS: "sits on the mat" = 4 tokens; ref=6, hyp=6
        result = compute_rouge_l(refs, hyps)
        assert 0.0 < result["rouge_l_f1"] < 1.0
        assert 0.0 < result["rouge_l_precision"] < 1.0
        assert 0.0 < result["rouge_l_recall"] < 1.0

    def test_empty_strings(self):
        refs = [""]
        hyps = [""]
        result = compute_rouge_l(refs, hyps)
        assert result["rouge_l_f1"] == 1.0


class TestComputeBertScore:
    def test_token_overlap_fallback(self):
        refs = ["the cat sits on the mat"]
        hyps = ["the cat sits on the mat"]
        result = compute_bertscore(refs, hyps)
        assert "bert_score_precision" in result
        assert "bert_score_recall" in result
        assert "bert_score_f1" in result
        assert result["bert_score_f1"] == pytest.approx(1.0)
        assert "fallback" in result

    def test_partial_overlap(self):
        refs = ["the cat sits on the mat"]
        hyps = ["the dog runs on the floor"]
        result = compute_bertscore(refs, hyps)
        assert 0.0 < result["bert_score_f1"] < 1.0


class TestGenerationMetrics:
    def test_dataclass_fields(self):
        m = GenerationMetrics(bleu=0.5, rouge_l=0.6, bert_score_f1=0.7)
        assert m.bleu == 0.5
        assert m.rouge_l == 0.6
        assert m.bert_score_f1 == 0.7

    def test_compute_generation_metrics_returns_dataclass(self):
        refs = ["the cat sits on the mat"]
        hyps = ["the cat sits on the mat"]
        result = compute_generation_metrics(refs, hyps)
        assert isinstance(result, GenerationMetrics)
        assert result.bleu == pytest.approx(1.0, abs=0.01)
        assert result.rouge_l == pytest.approx(1.0, abs=0.01)
        assert result.bert_score_f1 == pytest.approx(1.0, abs=0.01)

    def test_compute_generation_metrics_partial(self):
        refs = ["the cat sits on the mat"]
        hyps = ["the cat sits on the floor"]
        result = compute_generation_metrics(refs, hyps)
        assert 0.0 < result.bleu < 1.0
        assert 0.0 < result.rouge_l < 1.0
        assert 0.0 < result.bert_score_f1 < 1.0


class TestAllGenMetrics:
    def test_returns_all_required_keys(self):
        refs = ["the cat sits on the mat"]
        hyps = ["the cat sits on the mat"]
        contexts = ["the cat is a small domesticated animal"]
        result = compute_all_gen_metrics(refs, hyps, contexts)
        assert "bleu_1" in result
        assert "bleu_4" in result
        assert "rouge_l_f1" in result
        assert "bert_score_f1" in result
        assert "hallucination_rate" in result
        assert "num_samples" in result

    def test_all_values_in_range(self):
        refs = ["the cat sits on the mat", "hello world"]
        hyps = ["the dog sits on the mat", "hello there"]
        contexts = [
            "the cat is a small animal that sits on mats",
            "hello world is a common programming phrase",
        ]
        result = compute_all_gen_metrics(refs, hyps, contexts)
        for key, value in result.items():
            if key == "num_samples":
                assert value == 2
            else:
                assert 0.0 <= value <= 1.0, f"{key} = {value}"

    def test_hallucination_rate_zero_for_good_grounding(self):
        # Answer tokens all appear in context
        answers = ["the cat sits on the mat"]
        contexts = ["the cat sits on the mat every day"]
        assert compute_hallucination_rate(answers, contexts) == 0.0

    def test_hallucination_rate_detects_ungrounded(self):
        answers = ["the zebra flies to the moon"]
        contexts = ["the cat sits on the mat"]
        rate = compute_hallucination_rate(answers, contexts)
        assert rate > 0.0

    def test_compute_perplexity_requires_model(self):
        with pytest.raises(ValueError, match="model"):
            compute_perplexity(None, ["test text"])
