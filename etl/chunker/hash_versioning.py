# etl/chunker/hash_versioning.py
"""
Версионирование чанков для RAG-системы.
Реализует:
- Вычисление SHA-256 хеша для чанка (на основе текста + метаданных)
- Сравнение с предыдущей версией для детекции изменений
- Инкрементальное обновление: только новые/изменённые чанки
- LiveVectorLake: горячий слой (текущие чанки) и холодный слой (история, Delta Lake / Parquet)
- WAL для отслеживания последних хешей
"""

import hashlib
import json
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import pandas as pd

    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def compute_chunk_hash(chunk: dict[str, Any]) -> str:
    """
    Вычисляет SHA-256 хеш чанка на основе текста и ключевых метаданных.
    Игнорирует поля, которые могут меняться без изменения содержимого (например, extracted_at).
    """
    # Берём только значимые поля
    hashable_fields = {
        "text": chunk.get("text", ""),
        "title": chunk.get("title", ""),
        "source_type": chunk.get("source_type", ""),
        "source_id": chunk.get("source_id", ""),
        "version": chunk.get("version", ""),
        "doc_title": chunk.get("doc_title", ""),
        "keywords": sorted(chunk.get("keywords", [])),
        "entities": sorted(chunk.get("entities", [])),
        "summary": chunk.get("summary", ""),
    }
    # Сериализуем в упорядоченный JSON
    hash_str = json.dumps(hashable_fields, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(hash_str.encode("utf-8")).hexdigest()


class ChunkVersionStore:
    """
    Хранилище версий чанков с поддержкой инкрементальных обновлений.
    Поддерживает:
    - LiveVectorLake: hot (текущие чанки) и cold storage (история)
    - WAL (checkpoint) для быстрого восстановления
    """

    def __init__(self, hot_dir: Path, cold_dir: Path, wal_path: Path):
        """
        :param hot_dir: директория с текущими чанками (например, для быстрой индексации в Qdrant)
        :param cold_dir: директория с историей версий (Parquet/JSON-логи)
        :param wal_path: путь к WAL-файлу (сохраняет последние хеши для каждого документа)
        """
        self.hot_dir = Path(hot_dir)
        self.cold_dir = Path(cold_dir)
        self.wal_path = Path(wal_path)
        self.hot_dir.mkdir(parents=True, exist_ok=True)
        self.cold_dir.mkdir(parents=True, exist_ok=True)
        self.wal_path.parent.mkdir(parents=True, exist_ok=True)
        self._wal = self._load_wal()

    def _load_wal(self) -> dict[str, Any]:
        """Загружает WAL: mapping doc_id -> last_hash, last_modified, version_history."""
        if self.wal_path.exists():
            with open(self.wal_path) as f:
                return json.load(f)
        return {"documents": {}}

    def _save_wal(self) -> None:
        with open(self.wal_path, "w") as f:
            json.dump(self._wal, f, indent=2)

    def get_last_hash(self, doc_id: str) -> str | None:
        """Возвращает последний известный хеш документа (или None)."""
        doc_entry = self._wal["documents"].get(doc_id)
        if doc_entry:
            return str(doc_entry.get("last_hash"))
        return None

    def _append_to_cold_storage(self, doc_id: str, chunk: dict[str, Any], old_hash: str | None = None) -> None:
        """Сохраняет версию чанка в холодное хранилище (историю)."""
        # Создаём запись с временной меткой
        version_record = {
            "doc_id": doc_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "old_hash": old_hash,
            "new_hash": chunk["hash"],
            "chunk_data": chunk.copy(),
        }
        # Используем Parquet, если доступен, иначе JSON-логи
        if PANDAS_AVAILABLE:
            df = pd.DataFrame([version_record])
            cold_file = self.cold_dir / f"{doc_id}_history.parquet"
            if cold_file.exists():
                existing = pd.read_parquet(cold_file)
                df = pd.concat([existing, df], ignore_index=True)
            df.to_parquet(cold_file, index=False)
        else:
            # JSON Lines формат
            cold_file = self.cold_dir / f"{doc_id}_history.jsonl"
            with open(cold_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(version_record, ensure_ascii=False) + "\n")

    def update_document_chunks(
        self,
        doc_id: str,
        new_chunks: list[dict],
        force: bool = False,
    ) -> tuple[list[dict], list[dict]]:
        """
        Сравнивает новые чанки с последними известными (по хешу) и возвращает:
        - chunks_to_add: список чанков, которые новые или изменились
        - chunks_to_delete: список хешей чанков, которые больше не существуют (удалены из источника)
        При force=True все чанки считаются изменившимися.
        """
        last_hash = self.get_last_hash(doc_id)
        if force or not last_hash:
            # Все чанки новые
            self._save_chunks_to_hot(doc_id, new_chunks)
            self._update_wal(doc_id, new_chunks)
            return new_chunks, []

        # Получаем предыдущие чанки из hot-директории
        old_chunks = self._load_hot_chunks(doc_id)
        old_map = {ch["hash"]: ch for ch in old_chunks}
        new_map = {ch["hash"]: ch for ch in new_chunks}

        # Чанки, которые есть только в новом (добавленные или изменённые)
        added = []
        for h, ch in new_map.items():
            if h not in old_map:
                added.append(ch)
            else:
                # Хеш совпадает, но возможно изменились метаданные, не влияющие на хеш? Сравниваем тексты
                if old_map[h].get("text") != ch.get("text"):
                    added.append(ch)  # текст изменился -> переиндексируем
                    # Сохраняем в историю
                    self._append_to_cold_storage(doc_id, ch, old_hash=h)

        # Чанки, которые были в старом, но отсутствуют в новом (удалены)
        deleted = [h for h in old_map if h not in new_map]

        if added or deleted:
            # Сохраняем обновлённый набор в hot
            self._save_chunks_to_hot(doc_id, new_chunks)
            # Логируем изменения
            logger.info(f"Doc {doc_id}: added {len(added)} chunks, deleted {len(deleted)} chunks")
            for ch in added:
                self._append_to_cold_storage(doc_id, ch)
            for dh in deleted:
                self._log_deletion(doc_id, dh)

        # Обновляем WAL
        self._update_wal(doc_id, new_chunks)
        return added, deleted

    def _save_chunks_to_hot(self, doc_id: str, chunks: list[dict[str, Any]]) -> None:
        """Сохраняет текущую версию чанков в hot-директорию (один JSON-файл на документ)."""
        doc_hot_path = self.hot_dir / f"{doc_id}.json"
        with open(doc_hot_path, "w", encoding="utf-8") as f:
            json.dump(chunks, f, ensure_ascii=False, indent=2)

    def _load_hot_chunks(self, doc_id: str) -> list[dict[str, Any]]:
        """Загружает текущие чанки документа из hot-директории."""
        doc_hot_path = self.hot_dir / f"{doc_id}.json"
        if not doc_hot_path.exists():
            return []
        with open(doc_hot_path, encoding="utf-8") as f:
            return json.load(f)

    def _update_wal(self, doc_id: str, chunks: list[dict[str, Any]]) -> None:
        """Обновляет запись в WAL для документа."""
        # Находим максимальную версию (если есть поле version) и последний хеш
        last_hash = chunks[-1]["hash"] if chunks else ""
        self._wal["documents"][doc_id] = {
            "last_hash": last_hash,
            "last_modified": datetime.now(UTC).isoformat(),
            "num_chunks": len(chunks),
        }
        self._save_wal()

    def _log_deletion(self, doc_id: str, chunk_hash: str) -> None:
        """Логирует удаление чанка в холодное хранилище."""
        deletion_record = {
            "doc_id": doc_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "action": "deleted",
            "hash": chunk_hash,
        }
        if PANDAS_AVAILABLE:
            df = pd.DataFrame([deletion_record])
            cold_file = self.cold_dir / f"{doc_id}_history.parquet"
            if cold_file.exists():
                existing = pd.read_parquet(cold_file)
                df = pd.concat([existing, df], ignore_index=True)
            df.to_parquet(cold_file, index=False)
        else:
            cold_file = self.cold_dir / f"{doc_id}_history.jsonl"
            with open(cold_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(deletion_record, ensure_ascii=False) + "\n")

    def get_all_current_chunks(self) -> list[dict[str, Any]]:
        """Возвращает все актуальные чанки из hot-директории (для полной индексации)."""
        all_chunks = []
        for hot_file in self.hot_dir.glob("*.json"):
            with open(hot_file, encoding="utf-8") as f:
                chunks = json.load(f)
                all_chunks.extend(chunks)
        return all_chunks

    def get_chunk_history(self, doc_id: str, limit: int = 100) -> list[dict[str, Any]]:
        """Возвращает историю изменений чанков для документа (из cold storage)."""
        history = []
        if PANDAS_AVAILABLE:
            cold_file = self.cold_dir / f"{doc_id}_history.parquet"
            if cold_file.exists():
                df = pd.read_parquet(cold_file)
                history = df.tail(limit).to_dict(orient="records")
        else:
            cold_file = self.cold_dir / f"{doc_id}_history.jsonl"
            if cold_file.exists():
                with open(cold_file, encoding="utf-8") as f:
                    for line in f:
                        record = json.loads(line)
                        history.append(record)
                        if len(history) >= limit:
                            break
        return history

    def cleanup_old_versions(self, doc_id: str, keep_versions: int = 10) -> None:
        """Очищает старые версии в cold storage, оставляя только последние keep_versions."""
        if PANDAS_AVAILABLE:
            cold_file = self.cold_dir / f"{doc_id}_history.parquet"
            if cold_file.exists():
                df = pd.read_parquet(cold_file)
                if len(df) > keep_versions:
                    df = df.tail(keep_versions)
                    df.to_parquet(cold_file, index=False)
        else:
            cold_file = self.cold_dir / f"{doc_id}_history.jsonl"
            if cold_file.exists():
                with open(cold_file, encoding="utf-8") as f:
                    lines = f.readlines()
                if len(lines) > keep_versions:
                    with open(cold_file, "w", encoding="utf-8") as f:
                        f.writelines(lines[-keep_versions:])

    def reset(self, doc_id: str | None = None) -> None:
        """
        Полный сброс WAL и hot-данных для документа или всех.
        Используется для переиндексации.
        """
        if doc_id:
            # Удаляем hot-файл
            hot_path = self.hot_dir / f"{doc_id}.json"
            if hot_path.exists():
                hot_path.unlink()
            # Удаляем запись из WAL
            if doc_id in self._wal["documents"]:
                del self._wal["documents"][doc_id]
            # Не удаляем историю (cold) по умолчанию, чтобы сохранить audit
            logger.info(f"Reset version store for doc {doc_id}")
        else:
            # Очищаем hot-директорию
            shutil.rmtree(self.hot_dir)
            self.hot_dir.mkdir()
            self._wal["documents"] = {}
            logger.info("Reset version store for all documents")
        self._save_wal()


# Вспомогательная функция для инкрементальной индексации в Qdrant
def get_incremental_chunks(
    version_store: ChunkVersionStore, doc_id: str, new_chunks: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """
    Возвращает только те чанки, которые нужно переиндексировать в Qdrant (добавить/обновить).
    """
    added, _ = version_store.update_document_chunks(doc_id, new_chunks)
    return added


if __name__ == "__main__":
    # Пример использования
    store = ChunkVersionStore(
        hot_dir=Path("./test_hot"), cold_dir=Path("./test_cold"), wal_path=Path("./test_wal/wal.json")
    )

    # Фиктивные чанки
    doc_id = "confluence_123"
    chunks_v1 = [
        {"hash": "aaa", "text": "Version 1 content", "source_id": doc_id, "version": "1.0"},
        {"hash": "bbb", "text": "Another chunk", "source_id": doc_id},
    ]
    # Добавляем в первый раз
    added, _ = store.update_document_chunks(doc_id, chunks_v1)
    print(f"Added: {len(added)}")

    # Новая версия документа (изменился текст)
    chunks_v2 = [
        {"hash": "ccc", "text": "Version 2 content (updated)", "source_id": doc_id, "version": "2.0"},
        {"hash": "bbb", "text": "Another chunk (unchanged)", "source_id": doc_id},
    ]
    added2, deleted = store.update_document_chunks(doc_id, chunks_v2)
    print(f"Added in v2: {len(added2)}, Deleted: {len(deleted)}")

    # Просмотр истории
    history = store.get_chunk_history(doc_id)
    print(f"History records: {len(history)}")

    # Получение всех актуальных чанков для индексации
    all_current = store.get_all_current_chunks()
    print(f"Total current chunks: {len(all_current)}")
