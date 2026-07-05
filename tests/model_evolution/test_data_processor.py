"""Tests for proxy/app/model_evolution/data_processor.py."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from proxy.app.model_evolution.data_processor import DataProcessor
from proxy.app.hitl import FeedbackType, InteractionLogger


class TestDataProcessorInit:
    """Tests for DataProcessor initialization."""

    def test_creates_with_log_dir(self, tmp_path):
        log_dir = tmp_path / "hitl_logs"
        dp = DataProcessor(log_dir=log_dir)
        assert dp.log_dir == log_dir
        assert dp.interactions_file == log_dir / "interactions.jsonl"
        assert dp.feedback_file == log_dir / "feedback.jsonl"

    def test_creates_with_logger_instance(self, tmp_path):
        log_dir = tmp_path / "hitl_logs"
        logger = InteractionLogger(log_dir=log_dir)
        dp = DataProcessor(logger_instance=logger)
        assert dp._logger is logger
        assert dp.log_dir == log_dir

    def test_default_log_dir(self, tmp_path):
        custom_dir = tmp_path / "default_hitl"
        dp = DataProcessor(log_dir=custom_dir)
        assert dp.log_dir == custom_dir


class TestExportTrainingDataset:
    """Tests for DataProcessor.export_training_dataset()."""

    def _populate_logs(self, logger: InteractionLogger):
        logger.log_interaction(
            request_id="r1",
            user_query="How to set up CI?",
            context="CI/CD context",
            response="Use .gitlab-ci.yml",
            metadata={"model": "test"},
        )
        logger.log_interaction(
            request_id="r2",
            user_query="What is Docker?",
            context="Docker context",
            response="Docker is a container platform.",
        )
        logger.log_feedback(
            request_id="r1",
            feedback_type=FeedbackType.CORRECTION,
            corrected_response="Create .gitlab-ci.yml with stages",
            expert_id="expert-1",
        )
        logger.log_feedback(
            request_id="r2",
            feedback_type=FeedbackType.POSITIVE,
            comment="Good answer",
        )

    def test_exports_triples_to_file(self, tmp_path):
        log_dir = tmp_path / "logs"
        logger = InteractionLogger(log_dir=log_dir)
        self._populate_logs(logger)
        dp = DataProcessor(logger_instance=logger)

        output = tmp_path / "training.jsonl"
        triples = dp.export_training_dataset(output)

        assert output.exists()
        assert len(triples) == 2

        with open(output) as f:
            lines = [json.loads(line) for line in f]
        assert len(lines) == 2

    def test_triples_contain_corrections(self, tmp_path):
        log_dir = tmp_path / "logs"
        logger = InteractionLogger(log_dir=log_dir)
        self._populate_logs(logger)
        dp = DataProcessor(logger_instance=logger)

        triples = dp.export_training_dataset()
        r1 = next(t for t in triples if t["request_id"] == "r1")
        assert r1["query"] == "How to set up CI?"
        assert r1["answer"] == "Use .gitlab-ci.yml"
        assert r1["correction"] == "Create .gitlab-ci.yml with stages"
        assert r1["feedback_type"] == "correction"
        assert r1["expert_id"] == "expert-1"

    def test_triples_without_feedback_have_null_fields(self, tmp_path):
        log_dir = tmp_path / "logs"
        logger = InteractionLogger(log_dir=log_dir)
        logger.log_interaction(
            request_id="r3",
            user_query="test query",
            context="ctx",
            response="resp",
        )
        dp = DataProcessor(logger_instance=logger)
        triples = dp.export_training_dataset()
        assert len(triples) == 1
        t = triples[0]
        assert t["feedback_type"] is None
        assert t["correction"] is None

    def test_returns_triples_without_writing(self, tmp_path):
        log_dir = tmp_path / "logs"
        logger = InteractionLogger(log_dir=log_dir)
        self._populate_logs(logger)
        dp = DataProcessor(logger_instance=logger)

        triples = dp.export_training_dataset()
        assert len(triples) == 2

    def test_empty_logs(self, tmp_path):
        log_dir = tmp_path / "logs"
        logger = InteractionLogger(log_dir=log_dir)
        dp = DataProcessor(logger_instance=logger)
        triples = dp.export_training_dataset()
        assert triples == []


class TestSplitTrainValTest:
    """Tests for DataProcessor.split_train_val_test()."""

    def _make_dataset(self, n: int = 30) -> list[dict]:
        types = ["positive", "negative", "correction"]
        data = []
        for i in range(n):
            data.append({
                "request_id": f"r{i}",
                "query": f"query {i}",
                "feedback_type": types[i % len(types)],
            })
        return data

    def test_default_ratios(self):
        dp = DataProcessor()
        dataset = self._make_dataset(30)
        train, val, test = dp.split_train_val_test(dataset)
        assert len(train) > 0
        assert len(val) > 0
        assert len(test) > 0
        total = len(train) + len(val) + len(test)
        assert total == 30

    def test_custom_ratios(self):
        dp = DataProcessor()
        dataset = self._make_dataset(100)
        train, val, test = dp.split_train_val_test(
            dataset, train_ratio=0.8, val_ratio=0.1, test_ratio=0.1
        )
        assert abs(len(train) - 80) <= 5
        assert abs(len(val) - 10) <= 5
        assert abs(len(test) - 10) <= 5

    def test_stratification_maintains_distribution(self):
        dp = DataProcessor()
        dataset = self._make_dataset(90)
        train, val, test = dp.split_train_val_test(dataset, seed=42)

        for split_name, split in [("train", train), ("val", val), ("test", test)]:
            types = [item["feedback_type"] for item in split]
            pos = types.count("positive")
            neg = types.count("negative")
            corr = types.count("correction")
            # Each type should be present
            assert pos > 0, f"{split_name}: no positive samples"
            assert neg > 0, f"{split_name}: no negative samples"
            assert corr > 0, f"{split_name}: no correction samples"

    def test_empty_dataset(self):
        dp = DataProcessor()
        train, val, test = dp.split_train_val_test([])
        assert train == []
        assert val == []
        assert test == []

    def test_single_item(self):
        dp = DataProcessor()
        dataset = [{"request_id": "r1", "feedback_type": "positive"}]
        train, val, test = dp.split_train_val_test(dataset)
        assert len(train) == 1
        assert len(val) == 0
        assert len(test) == 0

    def test_reproducible_with_seed(self):
        dp = DataProcessor()
        dataset = self._make_dataset(60)

        train1, val1, test1 = dp.split_train_val_test(dataset, seed=42)
        train2, val2, test2 = dp.split_train_val_test(dataset, seed=42)

        assert [t["request_id"] for t in train1] == [t["request_id"] for t in train2]
        assert [t["request_id"] for t in val1] == [t["request_id"] for t in val2]
        assert [t["request_id"] for t in test1] == [t["request_id"] for t in test2]

    def test_stratify_by_different_key(self):
        dp = DataProcessor()
        dataset = []
        for i in range(30):
            dataset.append({
                "request_id": f"r{i}",
                "category": "A" if i < 15 else "B",
            })
        train, val, test = dp.split_train_val_test(dataset, stratify_by="category")
        assert len(train) > 0
        assert len(val) > 0
        assert len(test) > 0

    def test_no_overlap_between_splits(self):
        dp = DataProcessor()
        dataset = self._make_dataset(60)
        train, val, test = dp.split_train_val_test(dataset, seed=42)

        train_ids = {t["request_id"] for t in train}
        val_ids = {t["request_id"] for t in val}
        test_ids = {t["request_id"] for t in test}

        assert train_ids.isdisjoint(val_ids)
        assert train_ids.isdisjoint(test_ids)
        assert val_ids.isdisjoint(test_ids)


class TestFormatForSLM:
    """Tests for DataProcessor.format_for_slm()."""

    def test_formats_prompt_completion_pairs(self):
        dp = DataProcessor()
        dataset = [
            {"request_id": "r1", "query": "How to configure CI/CD?"},
            {"request_id": "r2", "query": "hello"},
            {"request_id": "r3", "query": ""},
        ]
        result = dp.format_for_slm(dataset)
        assert len(result) == 2  # empty query skipped
        for item in result:
            assert "prompt" in item
            assert "completion" in item
            assert isinstance(item["completion"], str)
            assert len(item["completion"]) > 0

    def test_empty_dataset(self):
        dp = DataProcessor()
        result = dp.format_for_slm([])
        assert result == []

    def test_intent_is_valid_label(self):
        dp = DataProcessor()
        dataset = [{"request_id": "r1", "query": "What is the difference between A and B?"}]
        result = dp.format_for_slm(dataset)
        valid_intents = {
            "greeting", "simple_fact", "factual", "procedural",
            "comparison", "summarize", "complex",
        }
        assert result[0]["completion"] in valid_intents

    def test_heuristic_intent_inference(self):
        dp = DataProcessor()
        test_cases = [
            ("hello there", "greeting"),
            ("how to install nginx", "procedural"),
            ("compare redis and memcached", "comparison"),
            ("summarize the document", "summarize"),
            ("what is", "simple_fact"),
        ]
        for query, expected in test_cases:
            result = dp.format_for_slm([{"request_id": "x", "query": query}])
            assert result[0]["completion"] == expected, f"{query} -> {expected}"


class TestFormatForLLM:
    """Tests for DataProcessor.format_for_llm()."""

    def test_formats_messages_with_correction(self):
        dp = DataProcessor()
        dataset = [
            {
                "request_id": "r1",
                "query": "How to set up CI?",
                "context": "CI/CD docs",
                "answer": "bad answer",
                "feedback_type": "correction",
                "correction": "The correct answer",
            }
        ]
        result = dp.format_for_llm(dataset)
        assert len(result) == 1
        item = result[0]
        assert "messages" in item
        messages = item["messages"]
        assert len(messages) == 3
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert messages[2]["role"] == "assistant"
        assert messages[2]["content"] == "The correct answer"

    def test_formats_messages_with_positive_feedback(self):
        dp = DataProcessor()
        dataset = [
            {
                "request_id": "r2",
                "query": "What is Docker?",
                "context": "Docker docs",
                "answer": "Docker is a container platform.",
                "feedback_type": "positive",
                "correction": None,
            }
        ]
        result = dp.format_for_llm(dataset)
        assert len(result) == 1
        messages = result[0]["messages"]
        assert messages[2]["content"] == "Docker is a container platform."

    def test_skips_negative_without_correction(self):
        dp = DataProcessor()
        dataset = [
            {
                "request_id": "r3",
                "query": "What is Kubernetes?",
                "context": "K8s docs",
                "answer": "bad answer",
                "feedback_type": "negative",
                "correction": None,
            },
            {
                "request_id": "r4",
                "query": "What is CI?",
                "context": "CI docs",
                "answer": "good answer",
                "feedback_type": "positive",
                "correction": None,
            },
        ]
        result = dp.format_for_llm(dataset)
        assert len(result) == 1
        assert result[0]["metadata"]["request_id"] == "r4"

    def test_format_includes_metadata(self):
        dp = DataProcessor()
        dataset = [
            {
                "request_id": "r5",
                "query": "q",
                "context": "ctx",
                "answer": "a",
                "feedback_type": "correction",
                "correction": "c",
            }
        ]
        result = dp.format_for_llm(dataset)
        assert result[0]["metadata"]["request_id"] == "r5"
        assert result[0]["metadata"]["feedback_type"] == "correction"
        assert result[0]["metadata"]["has_correction"] is True

    def test_format_user_message_includes_context(self):
        dp = DataProcessor()
        dataset = [
            {
                "request_id": "r6",
                "query": "How to X?",
                "context": "Documentation about X",
                "answer": "answer",
                "feedback_type": "positive",
                "correction": None,
            }
        ]
        result = dp.format_for_llm(dataset)
        user_msg = result[0]["messages"][1]["content"]
        assert "Documentation about X" in user_msg
        assert "How to X?" in user_msg

    def test_empty_dataset(self):
        dp = DataProcessor()
        result = dp.format_for_llm([])
        assert result == []


class TestInferIntent:
    """Tests for DataProcessor._infer_intent()."""

    def test_greeting(self):
        assert DataProcessor._infer_intent("hello") == "greeting"
        assert DataProcessor._infer_intent("good morning") == "greeting"
        assert DataProcessor._infer_intent("thanks a lot") == "greeting"

    def test_comparison(self):
        assert DataProcessor._infer_intent("compare A and B") == "comparison"
        assert DataProcessor._infer_intent("what is the difference between X and Y") == "comparison"
        assert DataProcessor._infer_intent("which is better A or B") == "comparison"

    def test_summarize(self):
        assert DataProcessor._infer_intent("summarize the meeting notes") == "summarize"
        assert DataProcessor._infer_intent("give me a brief summary") == "summarize"
        assert DataProcessor._infer_intent("tldr of the doc") == "summarize"

    def test_factual(self):
        assert DataProcessor._infer_intent("define machine learning and its applications") == "factual"
        assert DataProcessor._infer_intent("explain the concept of quantum computing") == "factual"

    def test_complex_multi_question(self):
        result = DataProcessor._infer_intent("What is X? And how does it compare to Y?")
        assert result == "complex"


class TestIntegrationWithHITL:
    """Integration tests with the HITL logging module."""

    def test_end_to_end_workflow(self, tmp_path):
        log_dir = tmp_path / "hitl_logs"
        logger = InteractionLogger(log_dir=log_dir)

        logger.log_interaction(
            request_id="w1",
            user_query="How to configure CI/CD pipeline?",
            context="GitLab CI/CD documentation...",
            response="Create a .gitlab-ci.yml file.",
            metadata={"model": "test-model", "version": "v1"},
        )
        logger.log_feedback(
            request_id="w1",
            feedback_type=FeedbackType.CORRECTION,
            corrected_response="Create a .gitlab-ci.yml file with stages: build, test, deploy.",
            comment="Added stage details",
        )

        logger.log_interaction(
            request_id="w2",
            user_query="What is Docker?",
            context="Docker is a platform for developing, shipping, and running applications.",
            response="Docker is a container runtime.",
            metadata={"model": "test-model"},
        )
        logger.log_feedback(
            request_id="w2",
            feedback_type=FeedbackType.POSITIVE,
            comment="Correct and concise",
        )

        dp = DataProcessor(logger_instance=logger)

        triples = dp.export_training_dataset(
            output_path=tmp_path / "training.jsonl"
        )
        assert len(triples) == 2

        train, val, test = dp.split_train_val_test(triples, seed=42)
        assert len(train) + len(val) + len(test) == 2

        slm_data = dp.format_for_slm(train)
        assert len(slm_data) > 0

        llm_data = dp.format_for_llm(triples)
        assert len(llm_data) == 2
        contents = [item["messages"][2]["content"] for item in llm_data]
        assert "Create a .gitlab-ci.yml file with stages: build, test, deploy." in contents
        assert "Docker is a container runtime." in contents
