# proxy/app/hitl.py
"""
Human-in-the-Loop модуль для сбора обратной связи.
Функции:
- Логирование всех запросов и ответов (с метаданными)
- Сохранение исправлений от экспертов
- Формирование датасета для fine-tuning
- Интеграция с дашбордом (через API или запись в БД)
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

logger = logging.getLogger (__name__)

# JSONL log rotation: rotate when file exceeds this size (bytes)
# Default: 10 MB for interactions, 5 MB for feedback
_DEFAULT_MAX_INTERACTIONS_SIZE = 10 * 1024 * 1024  # 10 MB
_DEFAULT_MAX_FEEDBACK_SIZE = 5 * 1024 * 1024  # 5 MB
_MAX_BACKUP_COUNT = 5  # Keep up to 5 rotated files


def generate_feedback_id () -> str:
  """Generate a unique feedback ID for tracking user feedback on a response."""
  return f"fb_{uuid.uuid4 ().hex [:12]}"


class FeedbackType (StrEnum):
  POSITIVE = "positive"
  NEGATIVE = "negative"
  CORRECTION = "correction"  # пользователь исправил ответ


class InteractionLogger:
  """
  Логирует взаимодействия пользователя с системой.
  Сохраняет: запрос, контекст, ответ, временные метки, метаданные.
  """
  
  def __init__ (self, log_dir: Path | None = None) -> None:
    self.log_dir = Path (log_dir or LOG_DIR or "./logs/hitl")
    self.log_dir.mkdir (parents = True, exist_ok = True)
    self.interactions_file = self.log_dir / "interactions.jsonl"
    self.feedback_file = self.log_dir / "feedback.jsonl"
  
  @staticmethod
  def _rotate_if_needed (filepath: Path, max_size: int, max_backups: int = _MAX_BACKUP_COUNT) -> Path:
    """Rotate JSONL file if it exceeds max_size. Returns the active file path.

    Renames the current file to filepath.1 (shifting older backups to .2, .3, ...)
    and returns a fresh file path. If file is under max_size, returns filepath as-is.

    :param filepath: Path to the JSONL log file.
    :param max_size: Maximum file size in bytes before rotation is triggered.
    :param max_backups: Number of rotated backups to retain (oldest deleted).
    :return: The active (writable) file path.
    """
    if not filepath.exists ():
      return filepath
    try:
      if filepath.stat ().st_size < max_size:
        return filepath
    except OSError:
      return filepath
    
    # Shift existing backups: file.N → file.N+1, delete oldest
    for i in range (max_backups, 0, -1):
      old_backup = Path (f"{filepath}.{i}")
      new_backup = Path (f"{filepath}.{i + 1}")
      if i == max_backups and new_backup.exists ():
        new_backup.unlink (missing_ok = True)
      if old_backup.exists ():
        old_backup.rename (new_backup)
    
    # Rename current file to .1
    first_backup = Path (f"{filepath}.1")
    shutil.move (str (filepath), str (first_backup))
    return filepath
  
  def log_interaction (
      self, request_id: str, user_query: str, context: str, response: str, metadata: dict [str, Any] | None = None,
      user_feedback: FeedbackType | None = None, corrected_response: str | None = None, ) -> None:
    """
    Записывает одно взаимодействие в JSON Lines файл.
    """
    record = {
        "request_id": request_id, "timestamp": datetime.now (UTC).isoformat (), "user_query": user_query,
        "context": context [:5000],  # ограничим длину
        "response": response, "metadata": metadata or {},
    }
    if user_feedback:
      record ["user_feedback"] = user_feedback.value
    if corrected_response:
      record ["corrected_response"] = corrected_response
    
    try:
      active_file = self._rotate_if_needed (self.interactions_file, _DEFAULT_MAX_INTERACTIONS_SIZE)
      with open (active_file, "a", encoding = "utf-8") as f:
        f.write (json.dumps (record, ensure_ascii = False) + "\n")
      logger.debug (f"Logged interaction {request_id}")
    except Exception as e:
      logger.error (f"Failed to log interaction: {e}")
  
  def log_feedback (
      self, request_id: str, feedback_type: FeedbackType, comment: str | None = None,
      corrected_response: str | None = None, expert_id: str | None = None, ) -> None:
    """
    Записывает обратную связь от пользователя или эксперта.
    """
    record = {
        "request_id": request_id, "timestamp": datetime.now (UTC).isoformat (), "feedback_type": feedback_type.value,
        "comment": comment, "corrected_response": corrected_response, "expert_id": expert_id,
    }
    try:
      active_file = self._rotate_if_needed (self.feedback_file, _DEFAULT_MAX_FEEDBACK_SIZE)
      with open (active_file, "a", encoding = "utf-8") as f:
        f.write (json.dumps (record, ensure_ascii = False) + "\n")
      logger.info (f"Feedback recorded for {request_id}: {feedback_type.value}")
    except Exception as e:
      logger.error (f"Failed to log feedback: {e}")
  
  def get_interactions (self, limit: int = 100) -> list [dict [str, Any]]:
    """Читает последние взаимодействия (обратный порядок)."""
    interactions = []
    try:
      with open (self.interactions_file, encoding = "utf-8") as f:
        lines = f.readlines ()
      for line in lines [-limit:]:
        interactions.append (json.loads (line))
    except Exception as e:
      logger.error (f"Failed to read interactions: {e}")
    return interactions [::-1]  # от новых к старым


# Глобальный экземпляр логгера (инициализируется при импорте)
_logger = None


def get_logger () -> InteractionLogger:
  global _logger
  if _logger is None:
    _logger = InteractionLogger ()
  return _logger


# Упрощённые функции для вызова из main.py
async def log_interaction (
    request_id: str, user_query: str, context: str, response: str, metadata: dict [str, Any] | None = None, ) -> None:
  """
  Асинхронная обёртка для логирования (неблокирующая).
  """
  if not LOG_REQUESTS:
    return
  logger = get_logger ()
  # Можно выполнить в отдельном потоке, чтобы не блокировать ответ
  import asyncio
  
  await asyncio.to_thread (logger.log_interaction, request_id = request_id, user_query = user_query, context = context,
      response = response, metadata = metadata, )


def log_feedback_sync (
    request_id: str, feedback_type: str, comment: str | None = None, corrected_response: str | None = None,
    expert_id: str | None = None, ) -> None:
  """Синхронная запись фидбека (например, из дашборда)."""
  logger = get_logger ()
  logger.log_feedback (request_id = request_id, feedback_type = FeedbackType (feedback_type), comment = comment,
      corrected_response = corrected_response, expert_id = expert_id, )


# Функция для экспорта датасета для fine-tuning
def export_training_dataset (output_path: Path, min_length: int = 50, use_processor: bool = False) -> None:
  """
  Экспортирует пары (вопрос, ответ) из взаимодействий, у которых есть положительная обратная связь
  или исправленные ответы, в формат для fine-tuning.

  When ``use_processor=True``, delegates to ``DataProcessor.export_training_dataset()``
  for richer query-answer-correction triples with feedback metadata.
  """
  if use_processor:
    from proxy.app.model_evolution.data_processor import DataProcessor
    
    processor = DataProcessor ()
    processor.export_training_dataset (str (output_path))
    return
  
  interaction_logger = get_logger ()
  interactions = interaction_logger.get_interactions (limit = 10000)
  
  training_pairs = []
  for item in interactions:
    if "corrected_response" in item:
      training_pairs.append ({"prompt": item ["user_query"], "completion": item ["corrected_response"]})
    elif item.get ("user_feedback") == "positive":
      training_pairs.append ({"prompt": item ["user_query"], "completion": item ["response"]})
  
  with open (output_path, "w", encoding = "utf-8") as f:
    for pair in training_pairs:
      f.write (json.dumps (pair, ensure_ascii = False) + "\n")
  logger.info (f"Exported {len (training_pairs)} training pairs to {output_path}")


def export_intent_dataset (output_path: Path, limit: int = 10000, use_multilingual: bool = False) -> None:
  """
  Экспортирует пары (query, intent) из логов взаимодействий
  в формат JSONL для обучения классификатора интентов.

  :param output_path: Путь к выходному JSONL-файлу.
  :param limit: Максимальное количество взаимодействий для обработки.
  :param use_multilingual: Использовать classify_intent_multilingual
      (поддержка DE/FR/ZH) вместо classify_intent.
  """
  from proxy.app.llm.slm import classify_intent, classify_intent_multilingual
  
  classify_fn = classify_intent_multilingual if use_multilingual else classify_intent
  
  interaction_logger = get_logger ()
  interactions = interaction_logger.get_interactions (limit = limit)
  
  # get_interactions returns newest first; reverse to chronological order
  interactions = list (reversed (interactions))
  
  intent_pairs = []
  for item in interactions:
    query = (item.get ("user_query") or "").strip ()
    if not query:
      continue
    intent, _ = classify_fn (query)
    intent_pairs.append ({"query": query, "intent": intent.value})
  
  with open (output_path, "w", encoding = "utf-8") as f:
    for pair in intent_pairs:
      f.write (json.dumps (pair, ensure_ascii = False) + "\n")
  logger.info (f"Exported {len (intent_pairs)} intent pairs to {output_path}")


if __name__ == "__main__":
  # Пример использования
  interaction_logger = get_logger ()
  interaction_logger.log_interaction (request_id = "test123", user_query = "Как настроить CI/CD?",
      context = "Контекст из документации...", response = "Для настройки CI/CD создайте файл .gitlab-ci.yml",
      metadata = {"model": os.getenv ("LLM_MODEL_NAME", "default"), "version": "latest"}, )
  interaction_logger.log_feedback ("test123", FeedbackType.POSITIVE, comment = "Отличный ответ!")
  export_training_dataset (Path ("./training_dataset.jsonl"))
