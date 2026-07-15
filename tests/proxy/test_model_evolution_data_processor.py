"""Tests for proxy/app/model_evolution/data_processor.py — DataProcessor, TrainingDataset.

Covers: HITL feedback ingestion, JSONL export, train/val/test split, SLM/LLM formatting.
"""

import json
import os
import tempfile

from proxy.app.model_evolution.data_processor import (
  DataProcessor,
  TrainingDataset,
)

# ---------------------------------------------------------------------------
# TrainingDataset dataclass
# ---------------------------------------------------------------------------


class TestTrainingDataset:
  def test_creates_with_empty_lists (self):
    ds = TrainingDataset ()
    assert ds.slm_data == []
    assert ds.llm_data == []
    assert ds.reranker_data == []

  def test_creates_with_prefilled_data (self):
    ds = TrainingDataset (slm_data = [{"query": "q", "intent": "i"}],
        llm_data = [{"instruction": "q", "input": "", "output": "a"}],
        reranker_data = [{"query": "q", "chunk": "c", "relevance": 0.9}], )
    assert len (ds.slm_data) == 1
    assert len (ds.llm_data) == 1
    assert len (ds.reranker_data) == 1


# ---------------------------------------------------------------------------
# DataProcessor — export_training_dataset
# ---------------------------------------------------------------------------


class TestExportTrainingDataset:
  def _write_hitl_log (self, tmpdir: str, entries: list [dict]) -> str:
    log_path = os.path.join (tmpdir, "hitl.jsonl")
    with open (log_path, "w") as f:
      for entry in entries:
        f.write (json.dumps (entry) + "\n")
    return log_path

  def test_empty_log_returns_empty_dataset (self):
    with tempfile.TemporaryDirectory () as tmpdir:
      log_path = os.path.join (tmpdir, "nonexistent.jsonl")
      output_dir = os.path.join (tmpdir, "output")
      processor = DataProcessor (hitl_log_path = log_path)
      ds = processor.export_training_dataset (output_dir = output_dir)
      assert ds.slm_data == []
      assert ds.llm_data == []
      assert ds.reranker_data == []

  def test_generates_slm_data_from_intent (self):
    with tempfile.TemporaryDirectory () as tmpdir:
      entries = [
          {"query": "How to deploy?", "intent": "deployment", "answer": "Use k8s."},
          {"query": "What is RAG?", "intent": "definition", "answer": "Retrieval Augmented Generation."},
      ]
      log_path = self._write_hitl_log (tmpdir, entries)
      output_dir = os.path.join (tmpdir, "output")
      processor = DataProcessor (hitl_log_path = log_path)
      ds = processor.export_training_dataset (output_dir = output_dir)

      assert len (ds.slm_data) == 2
      assert ds.slm_data [0] == {"query": "How to deploy?", "intent": "deployment"}

  def test_generates_llm_data_from_correction (self):
    with tempfile.TemporaryDirectory () as tmpdir:
      entries = [
          {
              "query": "What is X?", "answer": "Wrong answer", "correction": "Correct answer about X",
          },
      ]
      log_path = self._write_hitl_log (tmpdir, entries)
      output_dir = os.path.join (tmpdir, "output")
      processor = DataProcessor (hitl_log_path = log_path)
      ds = processor.export_training_dataset (output_dir = output_dir)

      assert len (ds.llm_data) == 1
      assert ds.llm_data [0] ["instruction"] == "What is X?"
      assert ds.llm_data [0] ["input"] == "Wrong answer"
      assert ds.llm_data [0] ["output"] == "Correct answer about X"

  def test_generates_reranker_data_from_chunks (self):
    with tempfile.TemporaryDirectory () as tmpdir:
      entries = [
          {
              "query": "How to deploy?", "chunks": [{"text": "Use k8s for deployment."}, "Plain text chunk"],
              "relevance": 0.95,
          },
      ]
      log_path = self._write_hitl_log (tmpdir, entries)
      output_dir = os.path.join (tmpdir, "output")
      processor = DataProcessor (hitl_log_path = log_path)
      ds = processor.export_training_dataset (output_dir = output_dir)

      assert len (ds.reranker_data) == 2
      assert ds.reranker_data [0] ["query"] == "How to deploy?"
      assert ds.reranker_data [0] ["chunk"] == "Use k8s for deployment."
      assert ds.reranker_data [0] ["relevance"] == 0.95
      assert ds.reranker_data [1] ["chunk"] == "Plain text chunk"

  def test_skips_entries_without_query_or_intent_for_slm (self):
    with tempfile.TemporaryDirectory () as tmpdir:
      entries = [
          {"query": "valid", "intent": "deployment"},  # valid
          {"query": "no_intent"},  # missing intent
          {"intent": "no_query"},  # missing query
          {},  # empty
      ]
      log_path = self._write_hitl_log (tmpdir, entries)
      output_dir = os.path.join (tmpdir, "output")
      processor = DataProcessor (hitl_log_path = log_path)
      ds = processor.export_training_dataset (output_dir = output_dir)

      assert len (ds.slm_data) == 1

  def test_skips_entries_without_correction_for_llm (self):
    with tempfile.TemporaryDirectory () as tmpdir:
      entries = [
          {"query": "valid", "correction": "corrected answer"},  # valid
          {"query": "no_correction", "answer": "some answer"},  # no correction
      ]
      log_path = self._write_hitl_log (tmpdir, entries)
      output_dir = os.path.join (tmpdir, "output")
      processor = DataProcessor (hitl_log_path = log_path)
      ds = processor.export_training_dataset (output_dir = output_dir)

      assert len (ds.llm_data) == 1

  def test_skips_malformed_json_lines (self):
    with tempfile.TemporaryDirectory () as tmpdir:
      log_path = os.path.join (tmpdir, "hitl.jsonl")
      with open (log_path, "w") as f:
        f.write ('{"query": "valid", "intent": "test"}\n')
        f.write ("not json at all\n")
        f.write ('{"query": "also valid", "intent": "test2"}\n')
        f.write ("\n")  # empty line
      output_dir = os.path.join (tmpdir, "output")
      processor = DataProcessor (hitl_log_path = log_path)
      ds = processor.export_training_dataset (output_dir = output_dir)

      assert len (ds.slm_data) == 2

  def test_writes_jsonl_files_to_output_dir (self):
    with tempfile.TemporaryDirectory () as tmpdir:
      entries = [
          {
              "query": "Q1", "intent": "test", "answer": "A1", "correction": "C1", "chunks": [{"text": "chunk1"}],
              "relevance": 0.8,
          },
      ]
      log_path = self._write_hitl_log (tmpdir, entries)
      output_dir = os.path.join (tmpdir, "output")
      processor = DataProcessor (hitl_log_path = log_path)
      processor.export_training_dataset (output_dir = output_dir)

      assert os.path.exists (os.path.join (output_dir, "slm_intent.jsonl"))
      assert os.path.exists (os.path.join (output_dir, "llm_instruction.jsonl"))
      assert os.path.exists (os.path.join (output_dir, "reranker_pairs.jsonl"))

      # Verify content
      with open (os.path.join (output_dir, "slm_intent.jsonl")) as f:
        lines = f.readlines ()
      assert len (lines) == 1
      parsed = json.loads (lines [0])
      assert parsed ["query"] == "Q1"

  def test_uses_response_as_fallback_for_answer (self):
    with tempfile.TemporaryDirectory () as tmpdir:
      entries = [
          {
              "query": "What?", "response": "Response text", "correction": "Correction text",
          },
      ]
      log_path = self._write_hitl_log (tmpdir, entries)
      output_dir = os.path.join (tmpdir, "output")
      processor = DataProcessor (hitl_log_path = log_path)
      ds = processor.export_training_dataset (output_dir = output_dir)

      assert ds.llm_data [0] ["input"] == "Response text"

  def test_uses_predicted_intent_as_fallback (self):
    with tempfile.TemporaryDirectory () as tmpdir:
      entries = [
          {"query": "How?", "predicted_intent": "how_to"},
      ]
      log_path = self._write_hitl_log (tmpdir, entries)
      output_dir = os.path.join (tmpdir, "output")
      processor = DataProcessor (hitl_log_path = log_path)
      ds = processor.export_training_dataset (output_dir = output_dir)

      assert len (ds.slm_data) == 1
      assert ds.slm_data [0] ["intent"] == "how_to"

  def test_uses_sources_as_fallback_for_chunks (self):
    with tempfile.TemporaryDirectory () as tmpdir:
      entries = [
          {
              "query": "Q", "sources": [{"text": "src1"}, {"text": "src2"}], "score": 0.75,
          },
      ]
      log_path = self._write_hitl_log (tmpdir, entries)
      output_dir = os.path.join (tmpdir, "output")
      processor = DataProcessor (hitl_log_path = log_path)
      ds = processor.export_training_dataset (output_dir = output_dir)

      assert len (ds.reranker_data) == 2
      assert ds.reranker_data [0] ["relevance"] == 0.75


# ---------------------------------------------------------------------------
# DataProcessor — split_train_val_test
# ---------------------------------------------------------------------------


class TestSplitTrainValTest:
  def test_default_split_ratios (self):
    processor = DataProcessor ()
    data = [{"id": i} for i in range (100)]
    train, val, test = processor.split_train_val_test (data)

    assert len (train) == 80
    assert len (val) == 10
    assert len (test) == 10

  def test_custom_split_ratios (self):
    processor = DataProcessor ()
    data = [{"id": i} for i in range (100)]
    train, val, test = processor.split_train_val_test (data, train_ratio = 0.7, val_ratio = 0.2, test_ratio = 0.1)

    assert len (train) == 70
    assert len (val) == 20
    assert len (test) == 10

  def test_deterministic_with_seed (self):
    processor = DataProcessor ()
    data = [{"id": i} for i in range (50)]

    train1, val1, test1 = processor.split_train_val_test (data, seed = 42)
    train2, val2, test2 = processor.split_train_val_test (data, seed = 42)

    assert train1 == train2
    assert val1 == val2
    assert test1 == test2

  def test_different_seeds_give_different_splits (self):
    processor = DataProcessor ()
    data = [{"id": i} for i in range (50)]

    train1, _, _ = processor.split_train_val_test (data, seed = 1)
    train2, _, _ = processor.split_train_val_test (data, seed = 2)

    assert train1 != train2

  def test_empty_data (self):
    processor = DataProcessor ()
    train, val, test = processor.split_train_val_test ([])

    assert train == []
    assert val == []
    assert test == []

  def test_small_dataset (self):
    processor = DataProcessor ()
    data = [{"id": i} for i in range (3)]
    train, val, test = processor.split_train_val_test (data)

    # With 3 items: train=2, val=0, test=1
    assert len (train) + len (val) + len (test) == 3

  def test_all_items_preserved (self):
    processor = DataProcessor ()
    data = [{"id": i} for i in range (100)]
    train, val, test = processor.split_train_val_test (data)

    all_items = train + val + test
    assert len (all_items) == 100
    ids = sorted (item ["id"] for item in all_items)
    assert ids == list (range (100))


# ---------------------------------------------------------------------------
# DataProcessor — format_for_slm / format_for_llm
# ---------------------------------------------------------------------------


class TestFormatForSLM:
  def test_formats_query_and_intent (self):
    processor = DataProcessor ()
    data = [
        {"query": "How to deploy?", "intent": "deployment"}, {"query": "What is RAG?", "intent": "definition"},
    ]
    result = processor.format_for_slm (data)

    assert len (result) == 2
    assert result [0] == {"text": "How to deploy?", "label": "deployment"}
    assert result [1] == {"text": "What is RAG?", "label": "definition"}

  def test_missing_intent_defaults_to_empty (self):
    processor = DataProcessor ()
    data = [{"query": "Test query"}]
    result = processor.format_for_slm (data)

    assert result [0] ["label"] == ""

  def test_empty_data (self):
    processor = DataProcessor ()
    assert processor.format_for_slm ([]) == []


class TestFormatForLLM:
  def test_formats_instruction_output (self):
    processor = DataProcessor ()
    data = [
        {"instruction": "What is X?", "output": "X is a thing."},
    ]
    result = processor.format_for_llm (data)

    assert len (result) == 1
    messages = result [0] ["messages"]
    assert messages [0] == {"role": "user", "content": "What is X?"}
    assert messages [1] == {"role": "assistant", "content": "X is a thing."}

  def test_uses_query_as_fallback_for_instruction (self):
    processor = DataProcessor ()
    data = [{"query": "Fallback query", "correction": "Corrected answer"}]
    result = processor.format_for_llm (data)

    messages = result [0] ["messages"]
    assert messages [0] ["content"] == "Fallback query"
    assert messages [1] ["content"] == "Corrected answer"

  def test_empty_data (self):
    processor = DataProcessor ()
    assert processor.format_for_llm ([]) == []

  def test_multiple_entries (self):
    processor = DataProcessor ()
    data = [
        {"instruction": "Q1", "output": "A1"}, {"instruction": "Q2", "output": "A2"},
        {"instruction": "Q3", "output": "A3"},
    ]
    result = processor.format_for_llm (data)
    assert len (result) == 3
