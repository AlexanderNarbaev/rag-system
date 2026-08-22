# etl/indexer/live_vector_lake.py
"""LiveVectorLake: two-tier chunk storage for the RAG system.
- Hot tier: Qdrant (vector index for fast search)
- Cold tier: Parquet/Delta Lake (full version history, delta updates)

Implements incremental indexing:
- When new chunks are added (or existing ones change), Qdrant is updated
- Stale chunks are removed from Qdrant
- History is preserved in cold storage with rollback support
"""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import pandas as pd

    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

# Import our modules
from etl.chunker.hash_versioning import ChunkVersionStore
from etl.indexer.qdrant_hybrid import QdrantHybridIndexer

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class LiveVectorLake:
    """Implements the LiveVectorLake pattern for versioning and incremental indexing."""

    def __init__(
        self,
        qdrant_indexer: QdrantHybridIndexer,
        version_store: ChunkVersionStore,
        cold_storage_dir: Path,
        use_delta: bool = False,
    ):
        """:param qdrant_indexer: QdrantHybridIndexer instance for the hot tier
        :param version_store: ChunkVersionStore instance for WAL and hashing
        :param cold_storage_dir: directory for cold storage (Parquet/Delta)
        :param use_delta: whether to use Delta Lake (requires delta-rs), otherwise Parquet
        """
        self.qdrant = qdrant_indexer
        self.version_store = version_store
        self.cold_storage_dir = Path(cold_storage_dir)
        self.cold_storage_dir.mkdir(parents=True, exist_ok=True)
        self.use_delta = use_delta

        if use_delta:
            try:
                import deltalake  # noqa: F401  # availability check

                self.delta_available = True
            except ImportError:
                logger.warning("Delta Lake not installed, falling back to Parquet")
                self.use_delta = False
                self.delta_available = False
        else:
            self.delta_available = False

    def _append_to_cold_storage(self, doc_id: str, chunks: list[dict], operation: str = "upsert"):
        """Adds a chunk version to cold storage.
        Stores a full document snapshot or incremental changes.
        """
        if not PANDAS_AVAILABLE:
            logger.warning("pandas is not available — cold storage disabled")
            return

        timestamp = datetime.now(UTC).isoformat()
        records = []
        for chunk in chunks:
            record = {
                "doc_id": doc_id,
                "timestamp": timestamp,
                "operation": operation,
                "chunk_hash": chunk.get("hash"),
                "text": chunk.get("text"),
                "title": chunk.get("title"),
                "source_type": chunk.get("source_type"),
                "source_id": chunk.get("source_id"),
                "version": chunk.get("version"),
                "doc_title": chunk.get("doc_title"),
                "keywords": json.dumps(chunk.get("keywords", [])),
                "entities": json.dumps(chunk.get("entities", [])),
                "summary": chunk.get("summary", ""),
            }
            records.append(record)

        df = pd.DataFrame(records)
        cold_file = self.cold_storage_dir / f"{doc_id}_history"

        if self.use_delta and self.delta_available:
            from deltalake import write_deltalake

            if cold_file.exists():
                write_deltalake(str(cold_file), df, mode="append")
            else:
                write_deltalake(str(cold_file), df)
        else:
            # Parquet with accumulation
            parquet_file = cold_file.with_suffix(".parquet")
            if parquet_file.exists():
                existing = pd.read_parquet(parquet_file)
                df = pd.concat([existing, df], ignore_index=True)
            df.to_parquet(parquet_file, index=False)

        logger.debug(f"Appended {len(chunks)} chunks to cold storage for doc {doc_id}")

    def sync_document(self, doc_id: str, new_chunks: list[dict], force: bool = False) -> tuple[int, int]:
        """Synchronizes a document: updates the hot tier (Qdrant) and cold storage.
        Returns (added_count, deleted_count).
        """
        # Determine which chunks to add/delete
        added_chunks, deleted_hashes = self.version_store.update_document_chunks(doc_id, new_chunks, force)

        # Update Qdrant
        if added_chunks:  # noqa: SIM108
            # Index new/changed chunks
            added_count = self.qdrant.index_chunks(added_chunks)
        else:
            added_count = 0

        if deleted_hashes:  # noqa: SIM108
            # Remove stale chunks from Qdrant
            deleted_count = self.qdrant.delete_chunks(deleted_hashes)  # type: ignore[arg-type]
        else:
            deleted_count = 0

        # Save the version to cold storage
        if added_chunks:
            self._append_to_cold_storage(doc_id, added_chunks, operation="upsert")
        if deleted_hashes:
            # Log the deletion as a separate operation
            deletion_records = [{"hash": h} for h in deleted_hashes]
            self._append_to_cold_storage(doc_id, deletion_records, operation="delete")

        logger.info(f"Document {doc_id}: added {added_count}, deleted {deleted_count}")
        return added_count, deleted_count

    def bulk_sync(self, documents: dict[str, list[dict]], force: bool = False) -> dict[str, tuple[int, int]]:
        """Synchronizes multiple documents.
        :param documents: {doc_id: [chunks]}
        :return: {doc_id: (added, deleted)}
        """
        results = {}
        for doc_id, chunks in documents.items():
            results[doc_id] = self.sync_document(doc_id, chunks, force)
        return results

    def get_document_history(self, doc_id: str, limit: int = 100):
        """Returns the document change history from cold storage."""
        if not PANDAS_AVAILABLE:
            logger.warning("pandas not available — cannot read cold storage history")
            return []

        cold_file = self.cold_storage_dir / f"{doc_id}_history"
        if self.use_delta and self.delta_available:
            from deltalake import DeltaTable

            if not DeltaTable.is_delta_table(str(cold_file)):
                return pd.DataFrame()
            dt = DeltaTable(str(cold_file))
            df = dt.to_pandas()
        else:
            parquet_file = cold_file.with_suffix(".parquet")
            if not parquet_file.exists():
                return pd.DataFrame()
            df = pd.read_parquet(parquet_file)
        return df.tail(limit)

    def rollback_document(self, doc_id: str, to_timestamp: str) -> int:
        """Rolls back a document to the given timestamp.
        Restores the chunk state from cold storage and reindexes into Qdrant.
        """
        history = self.get_document_history(doc_id)
        is_empty = history.empty if PANDAS_AVAILABLE and hasattr(history, "empty") else not history
        if is_empty:
            logger.warning(f"No history for document {doc_id}")
            return 0

        # Filter records up to the given time
        snapshot = history[history["timestamp"] <= to_timestamp]
        if snapshot.empty:
            logger.warning(f"No snapshot before {to_timestamp} for doc {doc_id}")
            return 0

        # Take the latest version of each chunk at that point
        # (simplified: collect all chunks with an upsert operation, excluding delete)
        chunks_snapshot = []
        seen_hashes = set()
        for _, row in snapshot.iterrows():
            if row["operation"] == "upsert" and row["chunk_hash"] not in seen_hashes:
                chunks_snapshot.append(
                    {
                        "hash": row["chunk_hash"],
                        "text": row["text"],
                        "title": row["title"],
                        "source_type": row["source_type"],
                        "source_id": row["source_id"],
                        "version": row["version"],
                        "doc_title": row["doc_title"],
                        "keywords": json.loads(row["keywords"]) if row["keywords"] else [],
                        "entities": json.loads(row["entities"]) if row["entities"] else [],
                        "summary": row["summary"],
                    },
                )
                seen_hashes.add(row["chunk_hash"])

        # Force-replace the current state
        self.version_store.reset(doc_id)
        added, _ = self.sync_document(doc_id, chunks_snapshot, force=True)
        logger.info(f"Rolled back document {doc_id} to {to_timestamp}, restored {added} chunks")
        return added

    def get_all_current_chunks(self) -> list[dict[str, Any]]:
        """Returns all current chunks from the version store (for a full export)."""
        return self.version_store.get_all_current_chunks()

    def cleanup_old_versions(self, doc_id: str, keep_versions: int = 10):
        """Prunes old versions in cold storage."""
        self.version_store.cleanup_old_versions(doc_id, keep_versions)
        # Old Parquet/Delta files could also be deleted (but we keep the history here)
        logger.info(f"Cleaned up old versions for {doc_id}")


def incremental_index_pipeline(
    live_lake: LiveVectorLake,
    doc_id: str,
    new_chunks: list[dict],
    force_reindex: bool = False,
) -> bool:
    """Ready-to-use function for incremental indexing: compares hashes, updates Qdrant and cold storage.
    Returns True if there were changes.
    """
    added, deleted = live_lake.sync_document(doc_id, new_chunks, force=force_reindex)
    return (added + deleted) > 0


if __name__ == "__main__":
    # Usage example
    from etl.chunker.hash_versioning import ChunkVersionStore
    from etl.indexer.qdrant_hybrid import QdrantHybridIndexer

    # Component initialization
    qdrant_idx = QdrantHybridIndexer(host="localhost", port=6333, collection_name="test_live_lake")
    qdrant_idx.create_collection(recreate=True)

    version_store = ChunkVersionStore(
        hot_dir=Path("./test_hot"),
        cold_dir=Path("./test_cold_version_store"),
        wal_path=Path("./test_wal/wal.json"),
    )

    live_lake = LiveVectorLake(
        qdrant_indexer=qdrant_idx,
        version_store=version_store,
        cold_storage_dir=Path("./test_cold_lake"),
        use_delta=False,
    )

    # Test document
    doc_id = "confluence_123"
    chunks_v1 = [
        {
            "hash": "aaa",
            "text": "Version 1 content",
            "title": "Doc Title",
            "source_type": "confluence",
            "source_id": doc_id,
            "version": "1.0",
            "doc_title": "Test Doc",
            "keywords": ["test"],
            "entities": [],
            "summary": "Test summary",
        },
    ]
    live_lake.sync_document(doc_id, chunks_v1)

    # New version
    chunks_v2 = [
        {
            "hash": "bbb",
            "text": "Version 2 updated content",
            "title": "Doc Title",
            "source_type": "confluence",
            "source_id": doc_id,
            "version": "2.0",
            "doc_title": "Test Doc",
            "keywords": ["test", "updated"],
            "entities": [],
            "summary": "Updated summary",
        },
    ]
    live_lake.sync_document(doc_id, chunks_v2)

    # History
    history = live_lake.get_document_history(doc_id)
    print("History:")
    print(history[["timestamp", "operation", "chunk_hash"]])

    # Rollback  # live_lake.rollback_document(doc_id, "2025-01-01T00:00:00")
