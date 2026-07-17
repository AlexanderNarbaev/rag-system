# etl/indexer/qdrant_hybrid.py
"""Hybrid indexing in Qdrant (dense + sparse + ColBERT multi-vector) for RAG.
Uses BAAI/bge-m3 for dense, sparse, and ColBERT vectors.
Supports:
- Collection creation with dense, sparse, and multi-vector config
- Batch upsert
- Update existing points by ID (chunk hash)
- ColBERT late interaction (bge-m3 multi-vector)
- Compatible with Qdrant 1.10+
"""

import json
import logging
import uuid
from pathlib import Path
from typing import Any

try:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models
    from qdrant_client.http.models import (
        CollectionInfo,
        Distance,
        PointStruct,
    )

    QDRANT_AVAILABLE = True
except ImportError:
    QDRANT_AVAILABLE = False

try:
    from sentence_transformers import SentenceTransformer

    ST_AVAILABLE = True
except ImportError:
    ST_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

COLBERT_ENABLED = True


class QdrantHybridIndexer:
    """Индексатор для Qdrant с гибридным поиском (dense + sparse)."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6333,
        grpc_port: int | None = None,
        prefer_grpc: bool = False,
        https: bool = False,
        api_key: str | None = None,
        collection_name: str = "knowledge_base",
        embedder_model_name: str = "BAAI/bge-m3",
        embedder_device: str = "cpu",
        dense_vector_size: int = 1024,
        # bge-m3 размер
        sparse_index_on_disk: bool = True,
        batch_size: int = 100,
        embedder: Any | None = None,
    ):
        """:param host: Qdrant host
        :param port: Qdrant port (HTTP)
        :param grpc_port: gRPC port (если нужен)
        :param prefer_grpc: использовать gRPC
        :param https: использовать HTTPS
        :param api_key: API ключ (для облачного Qdrant)
        :param collection_name: имя коллекции
        :param embedder_model_name: модель эмбеддера (bge-m3)
        :param embedder_device: 'cpu' или 'cuda'
        :param dense_vector_size: размерность dense вектора
        :param sparse_index_on_disk: хранить sparse индекс на диске
        :param batch_size: размер пакета для upsert
        :param embedder: pre-initialized embedder instance (remote or local).
                         If None, loads SentenceTransformer locally.
        """
        if not QDRANT_AVAILABLE:
            raise ImportError("qdrant-client is required. Install: pip install qdrant-client")

        # Подключение к Qdrant
        self.client = QdrantClient(
            host=host,
            port=port,
            grpc_port=grpc_port,
            prefer_grpc=prefer_grpc,
            https=https,
            api_key=api_key,
        )
        self.collection_name = collection_name
        self.embedder_model_name = embedder_model_name
        self.embedder_device = embedder_device
        self.dense_vector_size = dense_vector_size
        self.sparse_index_on_disk = sparse_index_on_disk
        self.batch_size = batch_size

        # Используем инжектированный эмбеддер или загружаем локальный
        if embedder is not None:
            self.embedder = embedder
            logger.info("Using injected embedder: %s", type(embedder).__name__)
        else:
            if not ST_AVAILABLE:
                raise ImportError(
                    "sentence-transformers is required for local embedding. "
                    "Install: pip install sentence-transformers, "
                    "or provide a remote embedder via the 'embedder' parameter."
                )
            self.embedder = SentenceTransformer(embedder_model_name, device=embedder_device)
            logger.info(f"Loaded local embedder {embedder_model_name} on {embedder_device}")

        # Проверяем, поддерживает ли модель sparse векторы
        self.supports_sparse = hasattr(self.embedder, "encode_sparse") or hasattr(self.embedder, "tokenizer")
        if not self.supports_sparse:
            logger.warning("Embedder does not support native sparse vectors. Sparse indexing will use TF-IDF fallback.")

    def create_collection(self, recreate: bool = False) -> bool:
        """Создаёт коллекцию с поддержкой dense и sparse векторов.
        :param recreate: если True, удаляет существующую коллекцию
        :return: True если создана, False если уже существовала
        """
        collections = self.client.get_collections().collections
        exists = any(c.name == self.collection_name for c in collections)

        if exists and recreate:
            self.client.delete_collection(self.collection_name)
            logger.info(f"Deleted existing collection {self.collection_name}")
            exists = False

        if not exists:
            # Конфигурация dense вектора
            dense_config = models.VectorParams(size=self.dense_vector_size, distance=Distance.COSINE)
            # Конфигурация sparse вектора (с использованием SparseVectorParams)
            sparse_config = models.SparseVectorParams(index=models.SparseIndexParams(on_disk=self.sparse_index_on_disk))
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config={"dense": dense_config, "sparse": sparse_config},
                # Для старых версий Qdrant без поддержки sparse, можно отдельно настроить
            )
            logger.info(f"Created collection {self.collection_name} with dense and sparse vectors")
            return True
        logger.info(f"Collection {self.collection_name} already exists")
        return False

    def get_collection_info(self) -> CollectionInfo:
        """Возвращает информацию о коллекции."""
        return self.client.get_collection(self.collection_name)

    def _compute_dense_vector(self, text: str) -> list[float]:
        """Вычисляет dense вектор через bge-m3 (нормализованный)."""
        vec = self.embedder.encode(text, normalize_embeddings=True)
        return vec.tolist()

    def _compute_sparse_vector(self, text: str) -> models.SparseVector | None:
        """Вычисляет sparse вектор.
        Для bge-m3: model.encode(text, return_sparse=True) возвращает словарь с индексами и значениями.
        Для моделей без поддержки возвращает None.
        """
        if hasattr(self.embedder, "encode_sparse"):
            # Специальный метод для моделей, поддерживающих sparse (например, bge-m3)
            sparse = self.embedder.encode_sparse(text)
            # Ожидается структура с индексами и значениями
            if isinstance(sparse, dict) and "indices" in sparse and "values" in sparse:
                return models.SparseVector(indices=sparse["indices"], values=sparse["values"])
            if hasattr(sparse, "indices") and hasattr(sparse, "values"):
                return models.SparseVector(indices=sparse.indices.tolist(), values=sparse.values.tolist())
        # Альтернативный способ: используем encode с параметром return_sparse
        try:
            result = self.embedder.encode(text, return_sparse=True)
            if isinstance(result, tuple) and len(result) == 2:
                indices, values = result
                return models.SparseVector(indices=indices.tolist(), values=values.tolist())
        except Exception:
            pass

        # Если модель не поддерживает sparse, возвращаем None (только dense)
        return None

    def _chunk_to_point(self, chunk: dict[str, Any]) -> PointStruct | None:
        """Преобразует чанк (словарь) в PointStruct для Qdrant.
        Ожидаемые поля: hash (id), text, title, source_type, source_id, version, doc_title, keywords, entities, summary.
        """
        point_id = chunk.get("hash")
        if not point_id:
            logger.warning("Chunk missing 'hash' field, skipping")
            return None

        text = chunk.get("text", "")
        if not text:
            logger.warning(f"Chunk {point_id} has empty text, skipping")
            return None

        # Векторы
        dense_vec = self._compute_dense_vector(text)
        sparse_vec = self._compute_sparse_vector(text)

        # Поля для payload (метаданные)
        payload = {
            "text": text,
            "title": chunk.get("title", ""),
            "source_type": chunk.get("source_type", ""),
            "source_id": chunk.get("source_id", ""),
            "version": chunk.get("version", ""),
            "doc_title": chunk.get("doc_title", ""),
            "keywords": chunk.get("keywords", []),
            "entities": chunk.get("entities", []),
            "summary": chunk.get("summary", ""),
            "position": chunk.get("position", 0),
            "semantic_key": chunk.get("semantic_key", ""),
            "created_at": chunk.get("created_at", ""),
            "updated_at": chunk.get("updated_at", ""),
        }
        # Очищаем None значения
        payload = {k: v for k, v in payload.items() if v is not None}

        vectors = {"dense": dense_vec}
        if sparse_vec is not None:
            vectors["sparse"] = sparse_vec

        return PointStruct(id=point_id, vector=vectors, payload=payload)

    def index_chunks(self, chunks: list[dict[str, Any]]) -> int:
        """Индексирует список чанков в Qdrant (пакетно).
        Возвращает количество успешно индексированных чанков.
        """
        total = 0
        for i in range(0, len(chunks), self.batch_size):
            batch = chunks[i : i + self.batch_size]
            points = []
            for chunk in batch:
                point = self._chunk_to_point(chunk)
                if point:
                    points.append(point)
            if points:
                try:
                    self.client.upsert(collection_name=self.collection_name, points=points)
                    total += len(points)
                    logger.debug(f"Indexed batch of {len(points)} chunks")
                except Exception as e:
                    logger.error(f"Failed to upsert batch: {e}")
                    # Пробуем по одному
                    for point in points:
                        try:
                            self.client.upsert(collection_name=self.collection_name, points=[point])
                            total += 1
                        except Exception as single_e:
                            logger.error(f"Failed to upsert point {point.id}: {single_e}")
        logger.info(f"Indexed {total} chunks into {self.collection_name}")
        return total

    def delete_chunks(self, chunk_ids: list[str]) -> int:
        """Удаляет чанки по списку ID (хешей)."""
        if not chunk_ids:
            return 0
        try:
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=models.PointIdsList(points=chunk_ids),
            )
            logger.info(f"Deleted {len(chunk_ids)} chunks")
            return len(chunk_ids)
        except Exception as e:
            logger.error(f"Failed to delete chunks: {e}")
            return 0

    def collection_exists(self) -> bool:
        """Проверяет существование коллекции."""
        try:
            self.client.get_collection(self.collection_name)
            return True
        except Exception:
            return False

    def get_chunk_count(self) -> int:
        """Возвращает количество точек в коллекции."""
        info = self.client.get_collection(self.collection_name)
        return info.points_count

    def delete_collection(self):
        """Удаляет коллекцию целиком."""
        self.client.delete_collection(self.collection_name)
        logger.info(f"Deleted collection {self.collection_name}")

    def _compute_colbert_vectors(self, text: str) -> list[list[float]]:
        """Compute ColBERT-style multi-vectors using bge-m3 token embeddings.

        Returns a list of per-token vectors (late interaction).
        Falls back to single dense vector if ColBERT is disabled.
        """
        if not COLBERT_ENABLED:
            return [self._compute_dense_vector(text)]

        try:
            output = self.embedder.encode(text, normalize_embeddings=False, output_value="token_embeddings")
            if hasattr(output, "tolist"):  # noqa: SIM108
                token_vecs = output.tolist()
            else:
                token_vecs = output
            if isinstance(token_vecs, list) and token_vecs:
                return token_vecs if isinstance(token_vecs[0], list) else [token_vecs]
        except Exception as e:
            logger.debug("ColBERT token embeddings failed, falling back to dense: %s", e)

        return [self._compute_dense_vector(text)]

    def index_with_colbert(self, chunk_text: str, colbert_vectors: list[list[float]] | None = None) -> bool:
        """Index a chunk with ColBERT multi-vector representation.

        If colbert_vectors is not provided, computes them from chunk_text.

        :param chunk_text: the text content
        :param colbert_vectors: pre-computed ColBERT per-token vectors
        :return: True if indexed successfully
        """
        if not COLBERT_ENABLED:
            logger.debug("ColBERT indexing disabled")
            return False

        import hashlib

        chunk_id = hashlib.sha256(chunk_text.encode()).hexdigest()

        if colbert_vectors is None:
            colbert_vectors = self._compute_colbert_vectors(chunk_text)

        try:
            self.client.upsert(
                collection_name=self.collection_name,
                points=[
                    PointStruct(
                        id=str(uuid.uuid4()),  # chunk_id,
                        vector={"colbert": colbert_vectors},
                        payload={"text": chunk_text},
                    ),
                ],
            )
            logger.debug("ColBERT indexed chunk %s", chunk_id[:12])
            return True
        except Exception as e:
            logger.error("ColBERT index failed: %s", e)
            return False

    def live_upsert(self, chunk: dict) -> bool:
        """Atomic upsert of a single chunk into Qdrant.

        Uses the chunk's SHA-256 hash as the point ID for idempotency.
        No full reindexing required — updates/deletes individual points.

        :param chunk: dict with fields hash, text, title, source_type, etc.
        :return: True if upsert succeeded
        """
        point = self._chunk_to_point(chunk)
        if point is None:
            return False
        try:
            self.client.upsert(collection_name=self.collection_name, points=[point])
            logger.debug("Live upsert for chunk %s", point.id)
            return True
        except Exception as e:
            logger.error("Live upsert failed for chunk %s: %s", point.id, e)
            return False

    def live_delete(self, chunk_id: str) -> bool:
        """Atomic delete of a single chunk from Qdrant by point ID.

        :param chunk_id: the point ID (chunk hash) to delete
        :return: True if delete succeeded
        """
        if not chunk_id:
            logger.warning("Empty chunk_id for live_delete")
            return False
        try:
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=models.PointIdsList(points=[chunk_id]),
            )
            logger.debug("Live delete for chunk %s", chunk_id)
            return True
        except Exception as e:
            logger.error("Live delete failed for chunk %s: %s", chunk_id, e)
            return False

    def search_colbert(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search using ColBERT late interaction scoring.

        Tokens from query and documents are compared via MaxSim.

        :param query: search query
        :param limit: max results
        :return: list of dicts with id, score, payload
        """
        if not COLBERT_ENABLED:
            logger.warning("ColBERT search is disabled")
            return []

        query_vectors = self._compute_colbert_vectors(query)

        try:
            results = self.client.search(
                collection_name=self.collection_name,
                query_vector=("colbert", query_vectors),
                limit=limit,
                with_payload=True,
            )
            return [{"id": r.id, "score": r.score, "payload": r.payload} for r in results]
        except Exception as e:
            logger.error("ColBERT search failed: %s", e)
            return []


def batch_index_from_json_files(indexer: QdrantHybridIndexer, chunks_dir: Path, pattern: str = "*.json"):
    """Утилита для индексации чанков из JSON-файлов в директории.
    Каждый JSON должен содержать список чанков (как в формате save_chunks_to_json).
    """
    json_files = list(chunks_dir.glob(pattern))
    logger.info(f"Found {len(json_files)} JSON files in {chunks_dir}")
    total_chunks = 0
    for file_path in json_files:
        with open(file_path, encoding="utf-8") as f:
            chunks = json.load(f)
        total_chunks += indexer.index_chunks(chunks)
    logger.info(f"Total indexed chunks: {total_chunks}")


if __name__ == "__main__":
    # Пример использования
    import os

    indexer = QdrantHybridIndexer(
        host=os.getenv("QDRANT_HOST", "localhost"),
        port=int(os.getenv("QDRANT_PORT", 6333)),
        collection_name="test_collection",
        embedder_device="cpu",
    )

    # Создаём коллекцию
    indexer.create_collection(recreate=True)

    # Пример чанка
    sample_chunks = [
        {
            "hash": "test_hash_1",
            "text": "Retrieval-Augmented Generation (RAG) is a technique to enhance LLMs with external knowledge.",
            "title": "RAG Overview",
            "source_type": "confluence",
            "source_id": "123",
            "version": "1.0",
            "doc_title": "RAG Architecture",
            "keywords": ["RAG", "LLM", "retrieval"],
            "entities": [],
            "summary": "RAG enhances LLMs with external knowledge.",
        },
    ]
    indexer.index_chunks(sample_chunks)
    print(f"Total chunks in collection: {indexer.get_chunk_count()}")
