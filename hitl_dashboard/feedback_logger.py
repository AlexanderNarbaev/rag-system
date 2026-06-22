# hitl_dashboard/feedback_logger.py
"""
Модуль для логирования обратной связи от экспертов и пользователей.
Предоставляет функции для:
- Сохранения фидбека в JSONL файл
- Чтения фидбека
- Агрегации статистики
- Экспорта датасета для дообучения
"""
import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

@dataclass
class FeedbackRecord:
    """Структура записи обратной связи."""
    request_id: str
    feedback_type: str  # positive, negative, correction
    timestamp: str
    comment: Optional[str] = None
    corrected_response: Optional[str] = None
    expert_id: Optional[str] = None
    metadata: Optional[Dict] = None


class FeedbackLogger:
    """
    Логгер обратной связи. Сохраняет записи в JSONL файл.
    """
    def __init__(self, log_dir: Path = None):
        self.log_dir = Path(log_dir or "./logs/hitl")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.feedback_file = self.log_dir / "feedback.jsonl"
    
    def log(self, record: FeedbackRecord):
        """Сохраняет одну запись обратной связи."""
        try:
            with open(self.feedback_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
            logger.info(f"Feedback logged for {record.request_id}: {record.feedback_type}")
        except Exception as e:
            logger.error(f"Failed to log feedback: {e}")
    
    def log_positive(self, request_id: str, comment: str = None, expert_id: str = None):
        """Удобный метод для положительного фидбека."""
        self.log(FeedbackRecord(
            request_id=request_id,
            feedback_type="positive",
            timestamp=datetime.now(timezone.utc).isoformat(),
            comment=comment,
            expert_id=expert_id
        ))
    
    def log_negative(self, request_id: str, comment: str = None, expert_id: str = None):
        """Удобный метод для отрицательного фидбека."""
        self.log(FeedbackRecord(
            request_id=request_id,
            feedback_type="negative",
            timestamp=datetime.now(timezone.utc).isoformat(),
            comment=comment,
            expert_id=expert_id
        ))
    
    def log_correction(self, request_id: str, corrected_response: str, comment: str = None, expert_id: str = None):
        """Удобный метод для исправленного ответа."""
        self.log(FeedbackRecord(
            request_id=request_id,
            feedback_type="correction",
            timestamp=datetime.now(timezone.utc).isoformat(),
            comment=comment,
            corrected_response=corrected_response,
            expert_id=expert_id
        ))
    
    def get_all_feedback(self) -> List[Dict]:
        """Читает все записи фидбека."""
        if not self.feedback_file.exists():
            return []
        records = []
        with open(self.feedback_file, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return records
    
    def get_feedback_for_request(self, request_id: str) -> List[Dict]:
        """Возвращает фидбек для конкретного запроса."""
        all_fb = self.get_all_feedback()
        return [fb for fb in all_fb if fb.get("request_id") == request_id]
    
    def get_statistics(self) -> Dict[str, int]:
        """Возвращает статистику по типам фидбека."""
        fb = self.get_all_feedback()
        stats = {}
        for rec in fb:
            fb_type = rec.get("feedback_type", "unknown")
            stats[fb_type] = stats.get(fb_type, 0) + 1
        return stats
    
    def export_training_dataset(self, output_path: Path, interactions_df=None) -> int:
        """
        Экспортирует датасет для дообучения на основе исправленных ответов.
        Если передан DataFrame с взаимодействиями, использует его (для объединения запросов).
        Иначе пытается прочитать interactions.jsonl.
        """
        from pathlib import Path
        interactions_file = self.log_dir / "interactions.jsonl"
        if interactions_df is None and interactions_file.exists():
            import pandas as pd
            interactions_df = pd.read_json(interactions_file, lines=True)
        
        if interactions_df is None or interactions_df.empty:
            logger.warning("No interactions data for export")
            return 0
        
        training_pairs = []
        feedback_records = self.get_all_feedback()
        # Создаём словарь исправлений по request_id
        corrections = {}
        for rec in feedback_records:
            rid = rec.get("request_id")
            if rec.get("feedback_type") == "correction" and rec.get("corrected_response"):
                corrections[rid] = rec["corrected_response"]
            elif rec.get("feedback_type") == "positive":
                # Если нет исправления, но есть положительный фидбек – используем исходный ответ
                if rid not in corrections:
                    # Нужно будет подставить из interactions
                    pass
        
        # Проходим по interactions
        for _, row in interactions_df.iterrows():
            rid = row.get("request_id")
            if rid in corrections:
                training_pairs.append({
                    "prompt": row.get("user_query"),
                    "completion": corrections[rid]
                })
            elif row.get("feedback_type") == "positive":
                training_pairs.append({
                    "prompt": row.get("user_query"),
                    "completion": row.get("response")
                })
        
        if training_pairs:
            with open(output_path, "w", encoding="utf-8") as f:
                for pair in training_pairs:
                    f.write(json.dumps(pair, ensure_ascii=False) + "\n")
            logger.info(f"Exported {len(training_pairs)} training pairs to {output_path}")
        return len(training_pairs)


# Глобальный экземпляр для удобного импорта
_default_logger = None

def get_logger() -> FeedbackLogger:
    global _default_logger
    if _default_logger is None:
        _default_logger = FeedbackLogger()
    return _default_logger


if __name__ == "__main__":
    # Пример использования
    logger = get_logger()
    logger.log_positive("test123", comment="Отличный ответ!")
    logger.log_correction("test456", "Исправленный ответ", comment="Была ошибка в версии")
    stats = logger.get_statistics()
    print(stats)