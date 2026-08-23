"""Tests for scripts/export_training_datasets.py."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "export_training_datasets.py"

INTENT_LABELS = [
    "greeting",
    "simple_fact",
    "factual",
    "procedural",
    "comparison",
    "summarize",
    "complex",
]


def _write_mock_classifier(tmp_path: Path) -> Path:
    """Create a temporary classifier module that returns deterministic intents."""
    classifier_file = tmp_path / "mock_classifier.py"
    classifier_file.write_text(
        """\
from enum import Enum

class IntentType(Enum):
    GREETING = "greeting"
    SIMPLE_FACT = "simple_fact"
    FACTUAL = "factual"
    PROCEDURAL = "procedural"
    COMPARISON = "comparison"
    SUMMARIZATION = "summarize"
    COMPLEX = "complex"
    UNKNOWN = "unknown"

_LABELS = [
    "greeting", "simple_fact", "factual", "procedural",
    "comparison", "summarize", "complex",
]

def classify_intent(query: str) -> tuple[IntentType, float]:
    idx = hash(query) % len(_LABELS)
    return IntentType(_LABELS[idx]), 0.9
""",
        encoding="utf-8",
    )
    return classifier_file


def _run_script(
    tmp_path: Path,
    args: list[str],
    log_dir: Path | None = None,
    feedback_db: Path | None = None,
    classifier_file: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the export script in a subprocess with isolated log/db paths."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)
    if classifier_file is not None:
        env["PYTHONPATH"] = f"{str(classifier_file.parent)}{os.pathsep}{env['PYTHONPATH']}"
        env["RAG_INTENT_CLASSIFIER"] = f"{classifier_file.stem}:classify_intent"
    if log_dir is not None:
        env["LOG_DIR"] = str(log_dir)
    if feedback_db is not None:
        env["RAG_FEEDBACK_DB"] = str(feedback_db)
    # Avoid leaking the repository's real feedback database.
    elif "RAG_FEEDBACK_DB" not in env:
        env["RAG_FEEDBACK_DB"] = str(tmp_path / "nonexistent_feedback.db")

    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _expected_files(output_dir: Path) -> dict[str, Path]:
    return {
        name: output_dir / name
        for name in (
            "intent_train.json",
            "intent_eval.json",
            "llm_train.json",
            "llm_eval.json",
            "reranker_train.json",
            "reranker_eval.json",
        )
    }


def test_produces_all_files_with_fallback_on_empty_logs(tmp_path: Path) -> None:
    """The script must produce all six dataset files when logs are empty."""
    output_dir = tmp_path / "datasets"
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    result = _run_script(
        tmp_path,
        ["--output-dir", str(output_dir), "--eval-split", "0.2", "--fallback"],
        log_dir=log_dir,
    )

    assert result.returncode == 0, result.stderr
    files = _expected_files(output_dir)
    for path in files.values():
        assert path.exists(), f"Expected file {path} was not created"

    intent_train = json.loads(files["intent_train.json"].read_text())
    intent_eval = json.loads(files["intent_eval.json"].read_text())
    assert all(item.get("intent_label") in INTENT_LABELS for item in intent_train + intent_eval)
    assert all("query" in item for item in intent_train + intent_eval)

    reranker_train = json.loads(files["reranker_train.json"].read_text())
    reranker_eval = json.loads(files["reranker_eval.json"].read_text())
    for triple in reranker_train + reranker_eval:
        assert len(triple) == 3
        assert isinstance(triple[0], str)
        assert isinstance(triple[1], str)
        assert isinstance(triple[2], (int, float))

    llm_train = json.loads(files["llm_train.json"].read_text())
    llm_eval = json.loads(files["llm_eval.json"].read_text())
    for item in llm_train + llm_eval:
        messages = item.get("messages", [])
        assert len(messages) == 3
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert messages[2]["role"] == "assistant"

    assert str(output_dir) in result.stdout


def test_reads_real_interactions_and_feedback(tmp_path: Path) -> None:
    """The script must read JSONL logs and generate real datasets."""
    output_dir = tmp_path / "datasets"
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    interactions = []
    feedback = []
    for i in range(8):
        request_id = f"req-{i}"
        query = f"query number {i} about deployment"
        context = (
            "Docker deployment is started with docker-compose up -d.\n\n"
            "The proxy layer runs on port 8080 by default.\n\n"
            "BGE-M3 embeddings are used for dense retrieval."
        )
        response = "Use docker-compose up -d in the proxy directory."
        interactions.append(
            json.dumps(
                {
                    "request_id": request_id,
                    "timestamp": "2026-01-01T00:00:00Z",
                    "user_query": query,
                    "context": context,
                    "response": response,
                    "metadata": {},
                    "user_feedback": "positive" if i % 2 == 0 else None,
                    "corrected_response": f"Corrected answer {i}" if i % 3 == 0 else None,
                },
                ensure_ascii=False,
            )
        )
        if i % 2 == 0:
            feedback.append(
                json.dumps(
                    {
                        "request_id": request_id,
                        "timestamp": "2026-01-01T00:00:00Z",
                        "feedback_type": "positive",
                        "comment": "good",
                        "corrected_response": None,
                        "expert_id": "expert-1",
                    },
                    ensure_ascii=False,
                )
            )

    (log_dir / "interactions.jsonl").write_text("\n".join(interactions) + "\n", encoding="utf-8")
    (log_dir / "feedback.jsonl").write_text("\n".join(feedback) + "\n", encoding="utf-8")

    classifier_file = _write_mock_classifier(tmp_path)

    result = _run_script(
        tmp_path,
        [
            "--output-dir",
            str(output_dir),
            "--eval-split",
            "0.25",
            "--min-samples",
            "1",
            "--seed",
            "7",
        ],
        log_dir=log_dir,
        classifier_file=classifier_file,
    )

    assert result.returncode == 0, result.stderr
    files = _expected_files(output_dir)
    for path in files.values():
        assert path.exists()

    intent_train = json.loads(files["intent_train.json"].read_text())
    intent_eval = json.loads(files["intent_eval.json"].read_text())
    assert len(intent_train) + len(intent_eval) == 8
    assert len(intent_eval) >= 1

    llm_train = json.loads(files["llm_train.json"].read_text())
    llm_eval = json.loads(files["llm_eval.json"].read_text())
    assert len(llm_train) + len(llm_eval) >= 4  # positive + corrected samples
    for item in llm_train + llm_eval:
        assert item["messages"][2]["content"].startswith(("Corrected answer", "Use docker"))

    reranker_train = json.loads(files["reranker_train.json"].read_text())
    reranker_eval = json.loads(files["reranker_eval.json"].read_text())
    assert len(reranker_train) + len(reranker_eval) == 8 * 3


def test_no_fallback_exits_on_insufficient_data(tmp_path: Path) -> None:
    """Without fallback and insufficient real data the script must fail."""
    output_dir = tmp_path / "datasets"
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    result = _run_script(
        tmp_path,
        ["--output-dir", str(output_dir), "--no-fallback"],
        log_dir=log_dir,
    )

    assert result.returncode != 0
    assert "Insufficient" in result.stderr or "fallback" in result.stderr.lower()


def test_feedback_db_merged_into_interactions(tmp_path: Path) -> None:
    """Corrections from the SQLite feedback database must augment interactions."""
    output_dir = tmp_path / "datasets"
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    feedback_db = tmp_path / "feedback.db"

    interaction = {
        "request_id": "r1",
        "timestamp": "2026-01-01T00:00:00Z",
        "user_query": "How do I deploy?",
        "context": "Deployment docs",
        "response": "Old answer",
        "metadata": {},
    }
    (log_dir / "interactions.jsonl").write_text(
        json.dumps(interaction, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (log_dir / "feedback.jsonl").write_text("", encoding="utf-8")

    import sqlite3

    with sqlite3.connect(str(feedback_db)) as conn:
        conn.execute(
            """CREATE TABLE feedback (
                request_id TEXT,
                feedback_type TEXT,
                comment TEXT,
                corrected_response TEXT,
                expert_id TEXT,
                timestamp TEXT
            )"""
        )
        conn.execute(
            "INSERT INTO feedback VALUES (?, ?, ?, ?, ?, ?)",
            ("r1", "correction", "fix it", "Use docker-compose up -d.", "expert-1", "2026-01-01T00:00:00Z"),
        )
        conn.commit()

    classifier_file = _write_mock_classifier(tmp_path)

    result = _run_script(
        tmp_path,
        ["--output-dir", str(output_dir), "--eval-split", "0.2", "--min-samples", "1"],
        log_dir=log_dir,
        feedback_db=feedback_db,
        classifier_file=classifier_file,
    )

    assert result.returncode == 0, result.stderr
    llm_data = json.loads((output_dir / "llm_train.json").read_text())
    assert any(item["messages"][2]["content"] == "Use docker-compose up -d." for item in llm_data)
