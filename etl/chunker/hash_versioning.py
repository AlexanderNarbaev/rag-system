# etl/chunker/hash_versioning.py
"""Chunk versioning for the RAG system.
Implements:
- SHA-256 hash computation for a chunk (based on text + metadata)
- Comparison with the previous version to detect changes
- Incremental updates: only new/changed chunks
- LiveVectorLake: hot layer (current chunks) and cold layer (history, Delta Lake / Parquet)
- WAL for tracking the latest hashes
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
    """Computes a SHA-256 hash of a chunk based on text and key metadata.
    Ignores fields that may change without a content change (e.g., extracted_at).
    """
    # Keep only meaningful fields
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
    # Serialize to sorted JSON
    hash_str = json.dumps(hashable_fields, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(hash_str.encode("utf-8")).hexdigest()


class ChunkVersionStore:
    """Chunk version store with incremental update support.
    Supports:
    - LiveVectorLake: hot (current chunks) and cold storage (history)
    - WAL (checkpoint) for fast recovery
    """

    def __init__(self, hot_dir: Path, cold_dir: Path, wal_path: Path):
        """:param hot_dir: directory with current chunks (e.g., for fast indexing into Qdrant)
        :param cold_dir: directory with version history (Parquet/JSON logs)
        :param wal_path: path to the WAL file (stores the latest hashes for each document)
        """
        self.hot_dir = Path(hot_dir)
        self.cold_dir = Path(cold_dir)
        self.wal_path = Path(wal_path)
        self.hot_dir.mkdir(parents=True, exist_ok=True)
        self.cold_dir.mkdir(parents=True, exist_ok=True)
        self.wal_path.parent.mkdir(parents=True, exist_ok=True)
        self._wal = self._load_wal()

    def _load_wal(self) -> dict[str, Any]:
        """Loads the WAL: mapping doc_id -> last_hash, last_modified, version_history."""
        if self.wal_path.exists():
            with open(self.wal_path) as f:
                return json.load(f)
        return {"documents": {}}

    def _save_wal(self) -> None:
        with open(self.wal_path, "w") as f:
            json.dump(self._wal, f, indent=2)

    def get_last_hash(self, doc_id: str) -> str | None:
        """Returns the last known hash of a document (or None)."""
        doc_entry = self._wal["documents"].get(doc_id)
        if doc_entry:
            return str(doc_entry.get("last_hash"))
        return None

    def _append_to_cold_storage(self, doc_id: str, chunk: dict[str, Any], old_hash: str | None = None) -> None:
        """Saves a chunk version to cold storage (history)."""
        # Create a record with a timestamp
        version_record = {
            "doc_id": doc_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "old_hash": old_hash,
            "new_hash": chunk["hash"],
            "chunk_data": chunk.copy(),
        }
        # Use Parquet if available, otherwise JSON logs
        if PANDAS_AVAILABLE:
            df = pd.DataFrame([version_record])
            cold_file = self.cold_dir / f"{doc_id}_history.parquet"
            if cold_file.exists():
                existing = pd.read_parquet(cold_file)
                df = pd.concat([existing, df], ignore_index=True)
            df.to_parquet(cold_file, index=False)
        else:
            # JSON Lines format
            cold_file = self.cold_dir / f"{doc_id}_history.jsonl"
            with open(cold_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(version_record, ensure_ascii=False) + "\n")

    def update_document_chunks(
        self,
        doc_id: str,
        new_chunks: list[dict],
        force: bool = False,
    ) -> tuple[list[dict], list[dict]]:
        """Compares new chunks with the last known ones (by hash) and returns:
        - chunks_to_add: list of chunks that are new or have changed
        - chunks_to_delete: list of hashes of chunks that no longer exist (removed from the source)
        With force=True all chunks are treated as changed.
        """
        last_hash = self.get_last_hash(doc_id)
        if force or not last_hash:
            # All chunks are new
            self._save_chunks_to_hot(doc_id, new_chunks)
            self._update_wal(doc_id, new_chunks)
            return new_chunks, []

        # Load previous chunks from the hot directory
        old_chunks = self._load_hot_chunks(doc_id)
        old_map = {ch["hash"]: ch for ch in old_chunks}
        new_map = {ch["hash"]: ch for ch in new_chunks}

        # Chunks present only in the new set (added or changed)
        added = []
        for h, ch in new_map.items():
            if h not in old_map:
                added.append(ch)
            # Hash matches, but metadata not affecting the hash may have changed? Compare texts
            elif old_map[h].get("text") != ch.get("text"):
                added.append(ch)  # text changed -> reindex
                # Save to history
                self._append_to_cold_storage(doc_id, ch, old_hash=h)

        # Chunks that were in the old set but are missing from the new one (deleted)
        deleted = [h for h in old_map if h not in new_map]

        if added or deleted:
            # Save the updated set to hot
            self._save_chunks_to_hot(doc_id, new_chunks)
            # Log the changes
            logger.info(f"Doc {doc_id}: added {len(added)} chunks, deleted {len(deleted)} chunks")
            for ch in added:
                self._append_to_cold_storage(doc_id, ch)
            for dh in deleted:
                self._log_deletion(doc_id, dh)

        # Update the WAL
        self._update_wal(doc_id, new_chunks)
        return added, deleted

    def _save_chunks_to_hot(self, doc_id: str, chunks: list[dict[str, Any]]) -> None:
        """Saves the current chunk version to the hot directory (one JSON file per document)."""
        doc_hot_path = self.hot_dir / f"{doc_id}.json"
        with open(doc_hot_path, "w", encoding="utf-8") as f:
            json.dump(chunks, f, ensure_ascii=False, indent=2)

    def _load_hot_chunks(self, doc_id: str) -> list[dict[str, Any]]:
        """Loads the current chunks of a document from the hot directory."""
        doc_hot_path = self.hot_dir / f"{doc_id}.json"
        if not doc_hot_path.exists():
            return []
        with open(doc_hot_path, encoding="utf-8") as f:
            return json.load(f)

    def _update_wal(self, doc_id: str, chunks: list[dict[str, Any]]) -> None:
        """Updates the WAL entry for a document."""
        # Find the maximum version (if a version field exists) and the latest hash
        last_hash = chunks[-1]["hash"] if chunks else ""
        self._wal["documents"][doc_id] = {
            "last_hash": last_hash,
            "last_modified": datetime.now(UTC).isoformat(),
            "num_chunks": len(chunks),
        }
        self._save_wal()

    def _log_deletion(self, doc_id: str, chunk_hash: str) -> None:
        """Logs a chunk deletion to cold storage."""
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
        """Returns all current chunks from the hot directory (for full indexing)."""
        all_chunks = []
        for hot_file in self.hot_dir.glob("*.json"):
            with open(hot_file, encoding="utf-8") as f:
                chunks = json.load(f)
                all_chunks.extend(chunks)
        return all_chunks

    def get_chunk_history(self, doc_id: str, limit: int = 100) -> list[dict[str, Any]]:
        """Returns the chunk change history for a document (from cold storage)."""
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
        """Prunes old versions in cold storage, keeping only the latest keep_versions."""
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
        """Full reset of the WAL and hot data for a document or all documents.
        Used for reindexing.
        """
        if doc_id:
            # Remove the hot file
            hot_path = self.hot_dir / f"{doc_id}.json"
            if hot_path.exists():
                hot_path.unlink()
            # Remove the WAL entry
            if doc_id in self._wal["documents"]:
                del self._wal["documents"][doc_id]
            # Keep the history (cold) by default to preserve the audit trail
            logger.info(f"Reset version store for doc {doc_id}")
        else:
            # Clear the hot directory
            shutil.rmtree(self.hot_dir)
            self.hot_dir.mkdir()
            self._wal["documents"] = {}
            logger.info("Reset version store for all documents")
        self._save_wal()


# Helper function for incremental indexing into Qdrant
def get_incremental_chunks(
    version_store: ChunkVersionStore,
    doc_id: str,
    new_chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Returns only the chunks that need to be reindexed in Qdrant (add/update)."""
    added, _ = version_store.update_document_chunks(doc_id, new_chunks)
    return added


if __name__ == "__main__":
    # Usage example
    store = ChunkVersionStore(
        hot_dir=Path("./test_hot"),
        cold_dir=Path("./test_cold"),
        wal_path=Path("./test_wal/wal.json"),
    )

    # Dummy chunks
    doc_id = "confluence_123"
    chunks_v1 = [
        {"hash": "aaa", "text": "Version 1 content", "source_id": doc_id, "version": "1.0"},
        {"hash": "bbb", "text": "Another chunk", "source_id": doc_id},
    ]
    # Add for the first time
    added, _ = store.update_document_chunks(doc_id, chunks_v1)
    print(f"Added: {len(added)}")

    # New document version (text changed)
    chunks_v2 = [
        {"hash": "ccc", "text": "Version 2 content (updated)", "source_id": doc_id, "version": "2.0"},
        {"hash": "bbb", "text": "Another chunk (unchanged)", "source_id": doc_id},
    ]
    added2, deleted = store.update_document_chunks(doc_id, chunks_v2)
    print(f"Added in v2: {len(added2)}, Deleted: {len(deleted)}")

    # View history
    history = store.get_chunk_history(doc_id)
    print(f"History records: {len(history)}")

    # Get all current chunks for indexing
    all_current = store.get_all_current_chunks()
    print(f"Total current chunks: {len(all_current)}")
