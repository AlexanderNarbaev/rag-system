# etl/indexer/wal_manager.py
"""
Универсальный менеджер Write-Ahead Log (WAL) для ETL-пайплайнов.
Используется для:
- Инкрементальных выгрузок (Confluence, Jira, GitLab)
- Индексации чанков в Qdrant
- Отслеживания последних успешных меток времени и идентификаторов

Формат WAL: JSON-файл с секциями для разных pipeline.
Поддерживает конкурентный доступ через filelock (опционально).
"""
import json
import logging
import os
from pathlib import Path
from typing import Dict, Any, Optional, Union
from datetime import datetime, timezone
import time

try:
    from filelock import FileLock
    FILELOCK_AVAILABLE = True
except ImportError:
    FILELOCK_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class WALManager:
    """
    Менеджер WAL для ETL-процессов.
    Каждый pipeline (например, 'confluence_extractor', 'jira_extractor', 'indexing') имеет свою секцию.
    """
    def __init__(self, wal_path: Path, use_lock: bool = True, lock_timeout: int = 30):
        """
        :param wal_path: путь к JSON-файлу WAL
        :param use_lock: использовать ли файловую блокировку (требуется pip install filelock)
        :param lock_timeout: таймаут ожидания блокировки (секунды)
        """
        self.wal_path = Path(wal_path)
        self.use_lock = use_lock and FILELOCK_AVAILABLE
        self.lock_timeout = lock_timeout
        self.wal_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Инициализация пустого WAL, если файл не существует
        if not self.wal_path.exists():
            self._write_wal({})
    
    def _get_lock(self):
        """Возвращает объект блокировки, если используется."""
        if self.use_lock:
            lock_path = self.wal_path.with_suffix(".lock")
            return FileLock(lock_path, timeout=self.lock_timeout)
        return None

    def _read_wal(self) -> Dict:
        """Читает текущий WAL (без блокировки, только чтение)."""
        try:
            with open(self.wal_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            logger.warning(f"WAL file {self.wal_path} corrupted or missing, reinitializing")
            return {}

    def _write_wal(self, data: Dict):
        """Записывает WAL (без блокировки)."""
        with open(self.wal_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _update_wal(self, update_func):
        """
        Безопасное обновление WAL с блокировкой.
        update_func принимает текущие данные и возвращает обновлённые.
        """
        lock = self._get_lock()
        if lock:
            lock.acquire()
        try:
            data = self._read_wal()
            new_data = update_func(data)
            self._write_wal(new_data)
        finally:
            if lock:
                lock.release()
    
    def get_checkpoint(self, pipeline: str, key: str = None) -> Optional[Union[Dict, Any]]:
        """
        Получает чекпоинт для указанного pipeline.
        Если key указан, возвращает конкретное значение (или None).
        Иначе возвращает весь словарь чекпоинта для этого pipeline.
        """
        data = self._read_wal()
        pipeline_data = data.get(pipeline, {})
        if key:
            return pipeline_data.get(key)
        return pipeline_data
    
    def set_checkpoint(self, pipeline: str, updates: Dict[str, Any]):
        """
        Обновляет чекпоинт для pipeline. Добавляет/перезаписывает переданные ключи.
        Автоматически добавляет метку времени обновления '_updated_at'.
        """
        updates_with_time = updates.copy()
        updates_with_time['_updated_at'] = datetime.now(timezone.utc).isoformat()
        
        def update(data):
            if pipeline not in data:
                data[pipeline] = {}
            data[pipeline].update(updates_with_time)
            return data
        
        self._update_wal(update)
        logger.debug(f"Updated checkpoint for pipeline '{pipeline}': {list(updates.keys())}")
    
    def update_last_run(self, pipeline: str, last_run: Union[str, datetime] = None):
        """
        Удобный метод для обновления временной метки последнего успешного запуска.
        """
        if last_run is None:
            last_run = datetime.now(timezone.utc).isoformat()
        elif isinstance(last_run, datetime):
            last_run = last_run.isoformat()
        self.set_checkpoint(pipeline, {"last_run": last_run})
    
    def get_last_run(self, pipeline: str) -> Optional[str]:
        """Возвращает last_run для pipeline или None."""
        return self.get_checkpoint(pipeline, "last_run")
    
    def update_offset(self, pipeline: str, offset: int):
        """Для пагинируемых выгрузок (например, startAt в Jira)."""
        self.set_checkpoint(pipeline, {"offset": offset})
    
    def get_offset(self, pipeline: str) -> int:
        """Возвращает сохранённый offset (0 по умолчанию)."""
        return self.get_checkpoint(pipeline, "offset") or 0
    
    def update_last_id(self, pipeline: str, last_id: str):
        """Сохраняет последний обработанный ID (например, страницы Confluence или коммита)."""
        self.set_checkpoint(pipeline, {"last_id": last_id})
    
    def get_last_id(self, pipeline: str) -> Optional[str]:
        return self.get_checkpoint(pipeline, "last_id")
    
    def update_hash_state(self, pipeline: str, doc_id: str, chunk_hash: str):
        """
        Для версионирования чанков: сохраняет хеш документа.
        Может использоваться вместе с ChunkVersionStore, но дублирует функциональность.
        """
        # Получаем текущий словарь хешей
        hash_map = self.get_checkpoint(pipeline, "hash_map") or {}
        hash_map[doc_id] = chunk_hash
        self.set_checkpoint(pipeline, {"hash_map": hash_map})
    
    def get_hash_state(self, pipeline: str, doc_id: str) -> Optional[str]:
        hash_map = self.get_checkpoint(pipeline, "hash_map") or {}
        return hash_map.get(doc_id)
    
    def reset_pipeline(self, pipeline: str, keep_last_run: bool = False):
        """
        Сбрасывает чекпоинт для указанного pipeline.
        Если keep_last_run=True, сохраняет только last_run.
        """
        def update(data):
            if keep_last_run:
                last_run = data.get(pipeline, {}).get("last_run")
                data[pipeline] = {"last_run": last_run} if last_run else {}
            else:
                data.pop(pipeline, None)
            return data
        self._update_wal(update)
        logger.info(f"Reset checkpoint for pipeline '{pipeline}' (keep_last_run={keep_last_run})")
    
    def reset_all(self):
        """Полный сброс WAL."""
        self._update_wal(lambda data: {})
        logger.info("Reset all WAL checkpoints")
    
    def get_all_pipelines(self) -> list:
        """Возвращает список всех pipeline, присутствующих в WAL."""
        data = self._read_wal()
        return list(data.keys())
    
    def vacuum(self, max_age_days: int = 30):
        """
        Очищает устаревшие записи (например, старые hash_map, чтобы WAL не разрастался).
        Удаляет hash_map для pipeline, если их возраст больше max_age_days.
        """
        def update(data):
            now = datetime.now(timezone.utc)
            for pipeline, cp in data.items():
                updated_at = cp.get("_updated_at")
                if updated_at:
                    try:
                        updated = datetime.fromisoformat(updated_at)
                        if (now - updated).days > max_age_days:
                            # Удаляем большие поля, оставляя метаданные
                            if "hash_map" in cp:
                                del cp["hash_map"]
                                logger.debug(f"Vacuumed hash_map from {pipeline}")
                            if "processed_ids" in cp:
                                del cp["processed_ids"]
                    except Exception:
                        pass
            return data
        self._update_wal(update)


# Предустановленные константы для имён pipeline
PIPELINE_CONFLUENCE = "confluence_extractor"
PIPELINE_JIRA = "jira_extractor"
PIPELINE_GITLAB = "gitlab_extractor"
PIPELINE_INDEXING = "indexing"
PIPELINE_GRAPH = "graph_builder"


# Пример использования и тестирование
if __name__ == "__main__":
    # Создаём WAL менеджер
    wal = WALManager(Path("./test_wal/etl_wal.json"), use_lock=False)
    
    # Обновляем чекпоинт для Confluence
    wal.set_checkpoint(PIPELINE_CONFLUENCE, {
        "last_run": "2025-06-01T00:00:00",
        "space_keys": ["DEV", "OPS"],
        "total_pages": 1250
    })
    
    # Обновляем last_run для Jira
    wal.update_last_run(PIPELINE_JIRA, "2025-06-02T12:00:00")
    
    # Сохраняем offset для GitLab (пагинация)
    wal.update_offset(PIPELINE_GITLAB, 150)
    
    # Получаем данные
    print(f"Confluence last_run: {wal.get_last_run(PIPELINE_CONFLUENCE)}")
    print(f"Jira last_run: {wal.get_last_run(PIPELINE_JIRA)}")
    print(f"GitLab offset: {wal.get_offset(PIPELINE_GITLAB)}")
    
    # Сохраняем хеш документа для индексации
    wal.update_hash_state(PIPELINE_INDEXING, "confluence_123", "abc123hash")
    print(f"Indexing hash for doc: {wal.get_hash_state(PIPELINE_INDEXING, 'confluence_123')}")
    
    # Сброс одного pipeline
    wal.reset_pipeline(PIPELINE_CONFLUENCE, keep_last_run=True)
    print(f"After reset, Confluence last_run: {wal.get_last_run(PIPELINE_CONFLUENCE)}")
    
    # Очистка старых данных
    wal.vacuum(max_age_days=1)