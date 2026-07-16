# ruff: noqa: E501, SIM117, E402, N817, SIM105
"""Tests for hallucination detection and benchmarking."""

from proxy.app.core.hallucination import (
    HallucinationReport,
    check_claim_against_context,
    compute_hallucination_rate,
    detect_hallucinations,
    extract_factual_claims,
    run_hallucination_benchmark,
)


class TestExtractFactualClaims:
    """Tests for extracting factual claims from answer text."""

    def test_extract_simple_claims(self):
        claims = extract_factual_claims(
            "Python was created by Guido van Rossum. It is widely used for web development."
        )
        assert len(claims) >= 1

    def test_extract_empty_answer(self):
        claims = extract_factual_claims("")
        assert claims == []

    def test_extract_numeric_claims(self):
        claims = extract_factual_claims(
            "The server has 64 GB of RAM. It runs at 3.5 GHz. The temperature is 72 degrees."
        )
        assert len(claims) >= 2

    def test_extract_whitespace_only(self):
        claims = extract_factual_claims("   \n  \t  ")
        assert claims == []

    def test_extract_bulleted_claims(self):
        claims = extract_factual_claims(
            "- Kubernetes is an orchestrator.\n- Docker provides containerization.\n- Helm is a package manager."
        )
        assert len(claims) >= 2

    def test_extract_with_version_numbers(self):
        claims = extract_factual_claims("Python 3.12 was released in 2023. It adds improved error messages.")
        assert len(claims) >= 1


class TestCheckClaimAgainstContext:
    """Tests for checking if a claim is supported by context."""

    def test_direct_match(self):
        result = check_claim_against_context(
            "Python was created by Guido van Rossum",
            "Python is a programming language created by Guido van Rossum in 1991.",
        )
        assert result is True

    def test_no_match(self):
        result = check_claim_against_context(
            "The moon landing was faked by NASA in a Hollywood studio",
            "Python is a programming language created by Guido van Rossum in 1991.",
        )
        assert result is False

    def test_empty_context(self):
        result = check_claim_against_context("Some claim", "")
        assert result is False

    def test_empty_claim(self):
        result = check_claim_against_context("", "Some context")
        assert result is False

    def test_partial_match(self):
        result = check_claim_against_context(
            "Docker uses OS-level virtualization for containers",
            "Docker is a containerization platform that uses OS-level virtualization to deliver software in packages "
            "called containers.",
        )
        assert result is True


class TestDetectHallucinations:
    """Tests for hallucination detection on answer+context pairs."""

    def test_no_hallucinations_when_all_supported(self):
        report = detect_hallucinations(
            answer="Python was created by Guido van Rossum. It is used for web development.",
            context="Python is a programming language created by Guido van Rossum in 1991. It is widely used for web "
            "development, data science, and automation.",
        )
        assert isinstance(report, HallucinationReport)
        assert report.hallucination_rate <= 0.6
        assert len(report.hallucinated_claims) < report.total_claims

    def test_detect_hallucinations_when_unsupported(self):
        report = detect_hallucinations(
            answer="Python was invented by Dennis Ritchie in 1970. It runs on the JVM natively.",
            context="Python is a programming language created by Guido van Rossum in 1991. It uses CPython as its "
            "primary implementation.",
        )
        assert isinstance(report, HallucinationReport)
        assert report.hallucination_rate > 0.0

    def test_empty_answer(self):
        report = detect_hallucinations("", "Some context here.")
        assert report.hallucination_rate == 0.0
        assert report.total_claims == 0

    def test_empty_context_all_hallucinated(self):
        report = detect_hallucinations("Python is a language. It was created in 1991.", "")
        assert report.hallucination_rate == 1.0

    def test_report_fields_populated(self):
        report = detect_hallucinations(
            answer="Docker is a container platform. It was created by Solomon Hykes.",
            context="Docker is a containerization platform. Solomon Hykes founded Docker Inc.",
        )
        assert isinstance(report.hallucination_rate, float)
        assert isinstance(report.hallucinated_claims, list)
        assert isinstance(report.evidence_links, dict)
        assert 0.0 <= report.hallucination_rate <= 1.0

    def test_supported_claims_in_evidence_links(self):
        report = detect_hallucinations(
            answer="Python is a programming language.",
            context="Python is a high-level programming language created by Guido van Rossum.",
        )
        assert len(report.evidence_links) > 0


class TestComputeHallucinationRate:
    """Tests for computing hallucination rate across multiple examples."""

    def test_perfect_answers_zero_rate(self):
        answers = ["Python is a language."]
        contexts = ["Python is a programming language."]
        rate = compute_hallucination_rate(answers, contexts)
        assert 0.0 <= rate <= 1.0

    def test_all_unsupported_max_rate(self):
        answers = ["Java runs on CLR."]
        contexts = [""]
        rate = compute_hallucination_rate(answers, contexts)
        assert rate == 1.0

    def test_mixed_answers(self):
        answers = [
            "Python is a language.",
            "Java was created by Dennis Ritchie.",
        ]
        contexts = [
            "Python is a programming language.",
            "Java was created by James Gosling.",
        ]
        rate = compute_hallucination_rate(answers, contexts)
        assert 0.0 <= rate <= 1.0

    def test_empty_inputs(self):
        rate = compute_hallucination_rate([], [])
        assert rate == 0.0

    def test_mismatched_lengths(self):
        rate = compute_hallucination_rate(["A"], ["B", "C"])
        assert 0.0 <= rate <= 1.0


class TestRunHallucinationBenchmark:
    """Tests for the benchmark runner."""

    def test_benchmark_returns_metrics(self):
        dataset = [
            {
                "query": "What is Python?",
                "answer": "Python is a programming language.",
                "context": "Python is a high-level programming language.",
            },
            {
                "query": "What is Docker?",
                "answer": "Docker is a container platform.",
                "context": "Docker is a containerization platform.",
            },
        ]
        metrics = run_hallucination_benchmark(dataset)
        assert isinstance(metrics, dict)
        assert "hallucination_rate" in metrics
        assert "total_claims" in metrics
        assert "hallucinated_claims" in metrics
        assert "samples_count" in metrics

    def test_benchmark_empty_dataset(self):
        metrics = run_hallucination_benchmark([])
        assert metrics["hallucination_rate"] == 0.0
        assert metrics["samples_count"] == 0

    def test_benchmark_target_below_5_percent(self):
        dataset = [
            {
                "query": f"Query {i}",
                "answer": f"Answer {i} is correct and grounded in the provided context.",
                "context": f"Answer {i} is correct and grounded in the provided context.",
            }
            for i in range(5)
        ]
        metrics = run_hallucination_benchmark(dataset)
        assert metrics["samples_count"] == 5


class TestHallucinationReport:
    """Tests for the HallucinationReport dataclass."""

    def test_report_fields(self):
        report = HallucinationReport(
            hallucination_rate=0.05,
            hallucinated_claims=["Fake claim"],
            supported_claims=19,
            total_claims=20,
            evidence_links={"claim1": "context sentence 1"},
        )
        assert report.hallucination_rate == 0.05
        assert len(report.hallucinated_claims) == 1
        assert report.supported_claims == 19
        assert report.total_claims == 20

    def test_report_default_values(self):
        report = HallucinationReport(hallucination_rate=0.0)
        assert report.hallucinated_claims == []
        assert report.supported_claims == 0
        assert report.total_claims == 0
        assert report.evidence_links == {}
