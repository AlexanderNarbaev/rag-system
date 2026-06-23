# proxy/app/hitl.py
"""
Human-in-the-Loop модуль для сбора обратной связи.
Функции:
- Логирование всех запросов и ответов (с метаданными)
- Сохранение исправлений от экспертов
- Формирование датасета для fine-tuning
- Интеграция с дашбордом (через API или запись в БД)
"""
import os
import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from enum import Enum

from app.config import LOG_REQUESTS, LOG_DIR

logger = logging.getLogger(__name__)


class FeedbackType(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    CORRECTION = "correction"  # пользователь исправил ответ


class InteractionLogger:
    """
    Логирует взаимодействия пользователя с системой.
    Сохраняет: запрос, контекст, ответ, временные метки, метаданные.
    """
    def __init__(self, log_dir: Path = None):
        self.log_dir = Path(log_dir or LOG_DIR or "./logs/hitl")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.interactions_file = self.log_dir / "interactions.jsonl"
        self.feedback_file = self.log_dir / "feedback.jsonl"
    
    def log_interaction(
        self,
        request_id: str,
        user_query: str,
        context: str,
        response: str,
        metadata: Dict[str, Any] = None,
        user_feedback: Optional[FeedbackType] = None,
        corrected_response: Optional[str] = None
    ):
        """
        Записывает одно взаимодействие в JSON Lines файл.
        """
        record = {
            "request_id": request_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user_query": user_query,
            "context": context[:5000],  # ограничим длину
            "response": response,
            "metadata": metadata or {},
        }
        if user_feedback:
            record["user_feedback"] = user_feedback.value
        if corrected_response:
            record["corrected_response"] = corrected_response
        
        try:
            with open(self.interactions_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            logger.debug(f"Logged interaction {request_id}")
        except Exception as e:
            logger.error(f"Failed to log interaction: {e}")
    
    def log_feedback(
        self,
        request_id: str,
        feedback_type: FeedbackType,
        comment: Optional[str] = None,
        corrected_response: Optional[str] = None,
        expert_id: Optional[str] = None
    ):
        """
        Записывает обратную связь от пользователя или эксперта.
        """
        record = {
            "request_id": request_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "feedback_type": feedback_type.value,
            "comment": comment,
            "corrected_response": corrected_response,
            "expert_id": expert_id,
        }
        try:
            with open(self.feedback_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            logger.info(f"Feedback recorded for {request_id}: {feedback_type.value}")
        except Exception as e:
            logger.error(f"Failed to log feedback: {e}")
    
    def get_interactions(self, limit: int = 100) -> List[Dict]:
        """Читает последние взаимодействия (обратный порядок)."""
        interactions = []
        try:
            with open(self.interactions_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
            for line in lines[-limit:]:
                interactions.append(json.loads(line))
        except Exception as e:
            logger.error(f"Failed to read interactions: {e}")
        return interactions[::-1]  # от новых к старым


# Глобальный экземпляр логгера (инициализируется при импорте)
_logger = None

def get_logger() -> InteractionLogger:
    global _logger
    if _logger is None:
        _logger = InteractionLogger()
    return _logger


# Упрощённые функции для вызова из main.py
async def log_interaction(
    request_id: str,
    user_query: str,
    context: str,
    response: str,
    metadata: Dict[str, Any] = None
):
    """
    Асинхронная обёртка для логирования (неблокирующая).
    """
    if not LOG_REQUESTS:
        return
    logger = get_logger()
    # Можно выполнить в отдельном потоке, чтобы не блокировать ответ
    import asyncio
    await asyncio.to_thread(
        logger.log_interaction,
        request_id=request_id,
        user_query=user_query,
        context=context,
        response=response,
        metadata=metadata
    )


def log_feedback_sync(
    request_id: str,
    feedback_type: str,
    comment: str = None,
    corrected_response: str = None,
    expert_id: str = None
):
    """Синхронная запись фидбека (например, из дашборда)."""
    logger = get_logger()
    logger.log_feedback(
        request_id=request_id,
        feedback_type=FeedbackType(feedback_type),
        comment=comment,
        corrected_response=corrected_response,
        expert_id=expert_id
    )


# Функция для экспорта датасета для fine-tuning
def export_training_dataset(output_path: Path, min_length: int = 50):
    """
    Экспортирует пары (вопрос, ответ) из взаимодействий, у которых есть положительная обратная связь
    или исправленные ответы, в формат для fine-tuning.
    """
    interaction_logger = get_logger()
    interactions = interaction_logger.get_interactions(limit=10000)
    
    training_pairs = []
    for item in interactions:
        # Берём только те, где есть исправленный ответ
        if "corrected_response" in item:
            training_pairs.append({
                "prompt": item["user_query"],
                "completion": item["corrected_response"]
            })
        # Или положительный фидбек
        elif item.get("user_feedback") == "positive":
            training_pairs.append({
                "prompt": item["user_query"],
                "completion": item["response"]
            })
    
    with open(output_path, "w", encoding="utf-8") as f:
        for pair in training_pairs:
            f.write(json.dumps(pair, ensure_ascii=False) + "\n")
    logger.info(f"Exported {len(training_pairs)} training pairs to {output_path}")


if __name__ == "__main__":
    # Пример использования
    logger = get_logger()
    logger.log_interaction(
        request_id="test123",
        user_query="Как настроить CI/CD?",
        context="Контекст из документации...",
        response="Для настройки CI/CD создайте файл .gitlab-ci.yml",
        metadata={"model": os.getenv("LLM_MODEL_NAME", "default"), "version": "latest"}
    )
    logger.log_feedback("test123", FeedbackType.POSITIVE, comment="Отличный ответ!")
    export_training_dataset(Path("./training_dataset.jsonl"))