# proxy/app/hitl.py
"""Human-in-the-Loop module for feedback collection.
Features:
- Logging of all requests and responses (with metadata)
- Storing corrections from experts
- Building a dataset for fine-tuning
- Dashboard integration (via API or DB writes)
"""

import json
import logging
import os
import shutil
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from proxy.app.shared.config import LOG_DIR, LOG_REQUESTS

logger = logging.getLogger(__name__)

# JSONL log rotation: rotate when file exceeds this size (bytes)
# Default: 10 MB for interactions, 5 MB for feedback
_DEFAULT_MAX_INTERACTIONS_SIZE = 10 * 1024 * 1024  # 10 MB
_DEFAULT_MAX_FEEDBACK_SIZE = 5 * 1024 * 1024  # 5 MB
_MAX_BACKUP_COUNT = 5  # Keep up to 5 rotated files


def generate_feedback_id() -> str:
    """Generate a unique feedback ID for tracking user feedback on a response."""
    return f"fb_{uuid.uuid4().hex[:12]}"


class FeedbackType(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    CORRECTION = "correction"  # the user corrected the answer


class InteractionLogger:
    """Logs user interactions with the system.
    Stores: query, context, response, timestamps, metadata.
    """

    def __init__(self, log_dir: Path | None = None) -> None:
        self.log_dir = Path(log_dir or LOG_DIR or "./logs/hitl")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.interactions_file = self.log_dir / "interactions.jsonl"
        self.feedback_file = self.log_dir / "feedback.jsonl"

    @staticmethod
    def _rotate_if_needed(filepath: Path, max_size: int, max_backups: int = _MAX_BACKUP_COUNT) -> Path:
        """Rotate JSONL file if it exceeds max_size. Returns the active file path.

        Renames the current file to filepath.1 (shifting older backups to .2, .3, ...)
        and returns a fresh file path. If file is under max_size, returns filepath as-is.

        :param filepath: Path to the JSONL log file.
        :param max_size: Maximum file size in bytes before rotation is triggered.
        :param max_backups: Number of rotated backups to retain (oldest deleted).
        :return: The active (writable) file path.
        """
        if not filepath.exists():
            return filepath
        try:
            if filepath.stat().st_size < max_size:
                return filepath
        except OSError:
            return filepath

        # Shift existing backups: file.N → file.N+1, delete oldest
        for i in range(max_backups, 0, -1):
            old_backup = Path(f"{filepath}.{i}")
            new_backup = Path(f"{filepath}.{i + 1}")
            if i == max_backups and new_backup.exists():
                new_backup.unlink(missing_ok=True)
            if old_backup.exists():
                old_backup.rename(new_backup)

        # Rename current file to .1
        first_backup = Path(f"{filepath}.1")
        shutil.move(str(filepath), str(first_backup))
        return filepath

    def log_interaction(
        self,
        request_id: str,
        user_query: str,
        context: str,
        response: str,
        metadata: dict[str, Any] | None = None,
        user_feedback: FeedbackType | None = None,
        corrected_response: str | None = None,
    ) -> None:
        """Writes a single interaction to a JSON Lines file."""
        record = {
            "request_id": request_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "user_query": user_query,
            "context": context[:5000],  # limit the length
            "response": response,
            "metadata": metadata or {},
        }
        if user_feedback:
            record["user_feedback"] = user_feedback.value
        if corrected_response:
            record["corrected_response"] = corrected_response

        try:
            active_file = self._rotate_if_needed(self.interactions_file, _DEFAULT_MAX_INTERACTIONS_SIZE)
            with open(active_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            logger.debug(f"Logged interaction {request_id}")
        except Exception as e:
            logger.error(f"Failed to log interaction: {e}")

    def log_feedback(
        self,
        request_id: str,
        feedback_type: FeedbackType,
        comment: str | None = None,
        corrected_response: str | None = None,
        expert_id: str | None = None,
    ) -> None:
        """Writes feedback from a user or an expert."""
        record = {
            "request_id": request_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "feedback_type": feedback_type.value,
            "comment": comment,
            "corrected_response": corrected_response,
            "expert_id": expert_id,
        }
        try:
            active_file = self._rotate_if_needed(self.feedback_file, _DEFAULT_MAX_FEEDBACK_SIZE)
            with open(active_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            logger.info(f"Feedback recorded for {request_id}: {feedback_type.value}")
        except Exception as e:
            logger.error(f"Failed to log feedback: {e}")

    def get_interactions(self, limit: int = 100) -> list[dict[str, Any]]:
        """Reads the most recent interactions (reverse order)."""
        interactions = []
        try:
            with open(self.interactions_file, encoding="utf-8") as f:
                lines = f.readlines()
            for line in lines[-limit:]:
                interactions.append(json.loads(line))
        except Exception as e:
            logger.error(f"Failed to read interactions: {e}")
        return interactions[::-1]  # newest to oldest


# Global logger instance (initialized on import)
_logger = None


def get_logger() -> InteractionLogger:
    global _logger
    if _logger is None:
        _logger = InteractionLogger()
    return _logger


# Simplified functions for calling from main.py
async def log_interaction(
    request_id: str,
    user_query: str,
    context: str,
    response: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Async wrapper for logging (non-blocking)."""
    if not LOG_REQUESTS:
        return
    logger = get_logger()
    # Can be run in a separate thread to avoid blocking the response
    import asyncio

    await asyncio.to_thread(
        logger.log_interaction,
        request_id=request_id,
        user_query=user_query,
        context=context,
        response=response,
        metadata=metadata,
    )


def log_feedback_sync(
    request_id: str,
    feedback_type: str,
    comment: str | None = None,
    corrected_response: str | None = None,
    expert_id: str | None = None,
) -> None:
    """Synchronous feedback write (e.g. from the dashboard)."""
    logger = get_logger()
    logger.log_feedback(
        request_id=request_id,
        feedback_type=FeedbackType(feedback_type),
        comment=comment,
        corrected_response=corrected_response,
        expert_id=expert_id,
    )


# Function for exporting the fine-tuning dataset
def export_training_dataset(output_path: Path, min_length: int = 50, use_processor: bool = False) -> None:
    """Exports (question, answer) pairs from interactions that have positive feedback
    or corrected responses, in a fine-tuning format.

    When ``use_processor=True``, delegates to ``DataProcessor.export_training_dataset()``
    for richer query-answer-correction triples with feedback metadata.
    """
    if use_processor:
        from proxy.app.model_evolution.data_processor import DataProcessor

        processor = DataProcessor()
        processor.export_training_dataset(str(output_path))
        return

    interaction_logger = get_logger()
    interactions = interaction_logger.get_interactions(limit=10000)

    training_pairs = []
    for item in interactions:
        if "corrected_response" in item:
            training_pairs.append({"prompt": item["user_query"], "completion": item["corrected_response"]})
        elif item.get("user_feedback") == "positive":
            training_pairs.append({"prompt": item["user_query"], "completion": item["response"]})

    from proxy.app.shared.path_utils import sanitize_path

    safe_output = sanitize_path(output_path)
    with open(safe_output, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(pair, ensure_ascii=False) + "\n" for pair in training_pairs)
    logger.info(f"Exported {len(training_pairs)} training pairs to {safe_output}")


def export_intent_dataset(output_path: Path, limit: int = 10000, use_multilingual: bool = False) -> None:
    """Exports (query, intent) pairs from interaction logs
    in JSONL format for training the intent classifier.

    :param output_path: Path to the output JSONL file.
    :param limit: Maximum number of interactions to process.
    :param use_multilingual: Use classify_intent_multilingual
        (DE/FR/ZH support) instead of classify_intent.
    """
    from proxy.app.llm.slm import classify_intent, classify_intent_multilingual

    classify_fn = classify_intent_multilingual if use_multilingual else classify_intent

    interaction_logger = get_logger()
    interactions = interaction_logger.get_interactions(limit=limit)

    # get_interactions returns newest first; reverse to chronological order
    interactions = list(reversed(interactions))

    intent_pairs = []
    for item in interactions:
        query = (item.get("user_query") or "").strip()
        if not query:
            continue
        intent, _ = classify_fn(query)
        intent_pairs.append({"query": query, "intent": intent.value})

    from proxy.app.shared.path_utils import sanitize_path

    safe_output = sanitize_path(output_path)
    with open(safe_output, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(pair, ensure_ascii=False) + "\n" for pair in intent_pairs)
    logger.info(f"Exported {len(intent_pairs)} intent pairs to {safe_output}")


if __name__ == "__main__":
    # Usage example
    interaction_logger = get_logger()
    interaction_logger.log_interaction(
        request_id="test123",
        user_query="Как настроить CI/CD?",
        context="Контекст из документации...",
        response="Для настройки CI/CD создайте файл .gitlab-ci.yml",
        metadata={"model": os.getenv("LLM_MODEL_NAME", "default"), "version": "latest"},
    )
    interaction_logger.log_feedback("test123", FeedbackType.POSITIVE, comment="Отличный ответ!")
    export_training_dataset(Path("./training_dataset.jsonl"))
