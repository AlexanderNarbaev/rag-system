"""Tests for proxy/app/hitl.py - HITL logging and feedback module."""

import json
from unittest.mock import MagicMock, patch

import pytest

from proxy.app.core.hitl import (
    FeedbackType,
    InteractionLogger,
    export_intent_dataset,
    export_training_dataset,
    get_logger,
    log_feedback_sync,
    log_interaction,
)


class TestFeedbackType:
    """Tests for FeedbackType enum."""

    def test_values(self):
        assert FeedbackType.POSITIVE.value == "positive"
        assert FeedbackType.NEGATIVE.value == "negative"
        assert FeedbackType.CORRECTION.value == "correction"

    def test_string_enum(self):
        assert FeedbackType("positive") == FeedbackType.POSITIVE
        assert FeedbackType("negative") == FeedbackType.NEGATIVE


class TestInteractionLogger:
    """Tests for InteractionLogger class."""

    @pytest.fixture
    def log_dir(self, tmp_path):
        return tmp_path / "hitl_logs"

    @pytest.fixture
    def logger(self, log_dir):
        return InteractionLogger(log_dir=log_dir)

    def test_creates_log_directory(self, log_dir):
        assert not log_dir.exists()
        InteractionLogger(log_dir=log_dir)
        assert log_dir.exists()

    def test_log_interaction_writes_file(self, logger, log_dir):
        logger.log_interaction(
            request_id="req-1",
            user_query="How to set up CI?",
            context="Some context",
            response="Use .gitlab-ci.yml",
            metadata={"model": "test-model"},
        )
        assert logger.interactions_file.exists()
        with open(logger.interactions_file) as f:
            records = [json.loads(line) for line in f]
        assert len(records) == 1
        assert records[0]["request_id"] == "req-1"
        assert records[0]["user_query"] == "How to set up CI?"

    def test_log_interaction_with_feedback(self, logger):
        logger.log_interaction(
            request_id="req-2",
            user_query="test",
            context="ctx",
            response="resp",
            user_feedback=FeedbackType.POSITIVE,
            corrected_response="better resp",
        )
        with open(logger.interactions_file) as f:
            record = json.loads(f.readline())
        assert record["user_feedback"] == "positive"
        assert record["corrected_response"] == "better resp"

    def test_context_truncated(self, logger):
        long_context = "x" * 6000
        logger.log_interaction(request_id="req-3", user_query="q", context=long_context, response="r")
        with open(logger.interactions_file) as f:
            record = json.loads(f.readline())
        assert len(record["context"]) <= 5000

    def test_log_feedback_writes_file(self, logger):
        logger.log_feedback(
            request_id="req-1", feedback_type=FeedbackType.POSITIVE, comment="Great answer!", expert_id="expert-42"
        )
        assert logger.feedback_file.exists()
        with open(logger.feedback_file) as f:
            record = json.loads(f.readline())
        assert record["request_id"] == "req-1"
        assert record["feedback_type"] == "positive"
        assert record["comment"] == "Great answer!"
        assert record["expert_id"] == "expert-42"

    def test_log_feedback_with_correction(self, logger):
        logger.log_feedback(
            request_id="req-x", feedback_type=FeedbackType.CORRECTION, corrected_response="The correct answer is..."
        )
        with open(logger.feedback_file) as f:
            record = json.loads(f.readline())
        assert record["corrected_response"] == "The correct answer is..."

    def test_get_interactions_empty(self, logger):
        result = logger.get_interactions()
        assert result == []

    def test_get_interactions_returns_reverse_order(self, logger):
        for i in range(5):
            logger.log_interaction(request_id=f"req-{i}", user_query=f"query {i}", context="ctx", response=f"resp {i}")
        result = logger.get_interactions(limit=3)
        assert len(result) == 3
        assert result[0]["request_id"] == "req-4"  # newest first

    def test_get_interactions_limit(self, logger):
        for i in range(10):
            logger.log_interaction(request_id=f"req-{i}", user_query=f"q{i}", context="c", response=f"r{i}")
        result = logger.get_interactions(limit=5)
        assert len(result) == 5

    def test_log_interaction_error_handling(self, logger):
        with patch("builtins.open", side_effect=OSError("disk full")):
            logger.log_interaction(request_id="req-e", user_query="q", context="c", response="r")

    def test_log_feedback_error_handling(self, logger):
        with patch("builtins.open", side_effect=OSError("disk full")):
            logger.log_feedback(request_id="req-e", feedback_type=FeedbackType.NEGATIVE)


class TestGetLoggerSingleton:
    """Tests for get_logger singleton."""

    def test_returns_same_instance(self):
        a = get_logger()
        b = get_logger()
        assert a is b

    def test_creates_instance_if_none(self):
        import proxy.app.core.hitl as hitl_mod

        old = hitl_mod._logger
        hitl_mod._logger = None
        inst = get_logger()
        assert isinstance(inst, InteractionLogger)
        hitl_mod._logger = old


class TestLogInteractionAsync:
    """Tests for async log_interaction function."""

    @pytest.mark.asyncio
    async def test_skips_when_logging_disabled(self):
        with patch("proxy.app.core.hitl.LOG_REQUESTS", False), patch("proxy.app.core.hitl.get_logger") as mock_get:
            await log_interaction("rid", "q", "ctx", "resp")
            mock_get.assert_not_called()

    @pytest.mark.asyncio
    async def test_calls_logger_when_enabled(self):
        mock_logger = MagicMock()
        with (
            patch("proxy.app.core.hitl.LOG_REQUESTS", True),
            patch("proxy.app.core.hitl.get_logger", return_value=mock_logger),
            patch("asyncio.to_thread", new_callable=lambda: AsyncMock()) as mock_thread,
        ):
            await log_interaction("rid", "q", "ctx", "resp", metadata={"k": "v"})
            mock_thread.assert_called_once()


class AsyncMock(MagicMock):
    async def __call__(self, *args, **kwargs):
        return super().__call__(*args, **kwargs)


class TestLogFeedbackSync:
    """Tests for log_feedback_sync function."""

    def test_calls_logger_with_correct_args(self):
        mock_logger = MagicMock()
        with patch("proxy.app.core.hitl.get_logger", return_value=mock_logger):
            log_feedback_sync(request_id="r1", feedback_type="positive", comment="good")
            mock_logger.log_feedback.assert_called_once()
            call_args = mock_logger.log_feedback.call_args
            assert call_args[1]["request_id"] == "r1"
            assert call_args[1]["feedback_type"] == FeedbackType.POSITIVE


class TestExportTrainingDataset:
    """Tests for export_training_dataset function."""

    def test_exports_corrected_responses(self, tmp_path):
        logger = InteractionLogger(log_dir=tmp_path)
        # Log interaction with corrected response
        logger.log_interaction(
            request_id="r1",
            user_query="How to X?",
            context="ctx",
            response="bad answer",
            corrected_response="good answer",
        )
        logger.log_interaction(
            request_id="r2",
            user_query="What is Y?",
            context="ctx",
            response="just ok",
            user_feedback=FeedbackType.POSITIVE,
        )
        logger.log_interaction(
            request_id="r3", user_query="What is Z?", context="ctx", response="bad", user_feedback=FeedbackType.NEGATIVE
        )

        output = tmp_path / "training.jsonl"
        with patch("proxy.app.core.hitl.get_logger", return_value=logger):
            export_training_dataset(output)

        with open(output) as f:
            pairs = [json.loads(line) for line in f]
        assert len(pairs) == 2  # r1 (corrected) and r2 (positive)
        # r3 has negative feedback, should not be included
        prompts = [p["prompt"] for p in pairs]
        assert "How to X?" in prompts
        assert "What is Y?" in prompts


class TestExportIntentDataset:
    """Tests for export_intent_dataset function."""

    def test_exports_query_intent_pairs(self, tmp_path):
        logger = InteractionLogger(log_dir=tmp_path)
        logger.log_interaction(
            request_id="r1",
            user_query="How to set up CI/CD?",
            context="ctx",
            response="Use .gitlab-ci.yml",
        )
        logger.log_interaction(
            request_id="r2",
            user_query="What is Docker?",
            context="ctx",
            response="A container platform",
        )
        logger.log_interaction(
            request_id="r3",
            user_query="Compare Kubernetes vs Nomad",
            context="ctx",
            response="Both are orchestrators",
        )

        output = tmp_path / "intent_dataset.jsonl"

        def mock_classify(query):
            from proxy.app.llm.slm import IntentType

            if "CI/CD" in query:
                return IntentType.PROCEDURAL, 0.8
            elif "Docker" in query:
                return IntentType.FACTUAL, 0.9
            elif "Compare" in query:
                return IntentType.COMPARISON, 0.85
            return IntentType.UNKNOWN, 0.5

        with (
            patch("proxy.app.core.hitl.get_logger", return_value=logger),
            patch("proxy.app.llm.slm.classify_intent", side_effect=mock_classify),
        ):
            export_intent_dataset(output)

        with open(output) as f:
            pairs = [json.loads(line) for line in f]
        assert len(pairs) == 3
        assert pairs[0] == {"query": "How to set up CI/CD?", "intent": "procedural"}
        assert pairs[1] == {"query": "What is Docker?", "intent": "factual"}
        assert pairs[2] == {"query": "Compare Kubernetes vs Nomad", "intent": "comparison"}

    def test_empty_dataset(self, tmp_path):
        logger = InteractionLogger(log_dir=tmp_path)
        output = tmp_path / "intent_dataset.jsonl"

        with (
            patch("proxy.app.core.hitl.get_logger", return_value=logger),
        ):
            export_intent_dataset(output)

        with open(output) as f:
            pairs = [json.loads(line) for line in f]
        assert len(pairs) == 0

    def test_writes_jsonl_format(self, tmp_path):
        logger = InteractionLogger(log_dir=tmp_path)
        logger.log_interaction(
            request_id="r1",
            user_query="Hello",
            context="ctx",
            response="Hi there!",
        )

        output = tmp_path / "intent_dataset.jsonl"

        def mock_classify(query):
            from proxy.app.llm.slm import IntentType

            return IntentType.GREETING, 0.95

        with (
            patch("proxy.app.core.hitl.get_logger", return_value=logger),
            patch("proxy.app.llm.slm.classify_intent", side_effect=mock_classify),
        ):
            export_intent_dataset(output)

        with open(output) as f:
            lines = f.readlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert "query" in record
        assert "intent" in record
        assert record["intent"] in (
            "greeting",
            "simple_fact",
            "factual",
            "procedural",
            "comparison",
            "summarize",
            "complex",
            "unknown",
        )

    def test_skips_interactions_with_empty_query(self, tmp_path):
        logger = InteractionLogger(log_dir=tmp_path)
        logger.log_interaction(
            request_id="r1",
            user_query="",
            context="ctx",
            response="resp",
        )
        logger.log_interaction(
            request_id="r2",
            user_query="Valid query",
            context="ctx",
            response="resp",
        )

        output = tmp_path / "intent_dataset.jsonl"

        def mock_classify(query):
            from proxy.app.llm.slm import IntentType

            return IntentType.FACTUAL, 0.7

        with (
            patch("proxy.app.core.hitl.get_logger", return_value=logger),
            patch("proxy.app.llm.slm.classify_intent", side_effect=mock_classify),
        ):
            export_intent_dataset(output)

        with open(output) as f:
            pairs = [json.loads(line) for line in f]
        assert len(pairs) == 1
        assert pairs[0]["query"] == "Valid query"

    def test_uses_multilingual_classification_when_available(self, tmp_path):
        logger = InteractionLogger(log_dir=tmp_path)
        logger.log_interaction(
            request_id="r1",
            user_query="Bonjour",
            context="ctx",
            response="Bonjour!",
        )

        output = tmp_path / "intent_dataset.jsonl"

        def mock_multilingual(query):
            from proxy.app.llm.slm import IntentType

            return IntentType.GREETING, 0.85

        with (
            patch("proxy.app.core.hitl.get_logger", return_value=logger),
            patch("proxy.app.llm.slm.classify_intent_multilingual", side_effect=mock_multilingual),
        ):
            export_intent_dataset(output, use_multilingual=True)

        with open(output) as f:
            pairs = [json.loads(line) for line in f]
        assert len(pairs) == 1
        assert pairs[0]["query"] == "Bonjour"
        assert pairs[0]["intent"] == "greeting"
