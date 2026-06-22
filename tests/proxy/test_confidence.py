"""Tests for confidence scorer."""
from proxy.app.confidence import ConfidenceReport, compute_confidence


def test_compute_confidence_high():
    context = (
        "Python is a programming language created by Guido van Rossum in 1991. "
        "It is widely used for web development, data science, and automation."
    )
    answer = (
        "Python is a programming language created in 1991 by Guido van Rossum. "
        "It is used for web development and data science."
    )
    report = compute_confidence(
        query="What is Python?",
        context=context,
        answer=answer,
        slm_available=False,
    )
    assert report.score > 0.5
    assert report.needs_review is False
    assert isinstance(report.uncertainties, list)


def test_compute_confidence_low_empty_context():
    report = compute_confidence(
        query="What is XYZ?",
        context="",
        answer="I don't know about XYZ.",
        slm_available=False,
    )
    assert report.score < 0.5
    assert report.needs_review is True


def test_compute_confidence_low_uncertainty_phrases():
    report = compute_confidence(
        query="Complex question",
        context="Some relevant context about the topic with enough detail to answer the question properly.",
        answer="I'm not sure about this, possibly the answer is unclear.",
        slm_available=False,
    )
    assert report.score <= 0.7


def test_confidence_report_fields():
    report = ConfidenceReport(score=0.8, needs_review=False, uncertainties=[])
    assert report.score == 0.8
    assert report.needs_review is False
    assert report.uncertainties == []


def test_compute_confidence_very_short_answer():
    report = compute_confidence(
        query="What is X?",
        context="Some context",
        answer="Yes.",
        slm_available=False,
    )
    assert report.score < 0.7
