# etl/scheduler/streaming_pipeline.py
"""Streaming-first ETL pipeline: extract -> chunk -> embed -> index, one doc at a time.

Each source is extracted as a generator, each document is chunked immediately,
each chunk is embedded via remote API, and each chunk is indexed to Qdrant immediately.
No disk storage — everything flows through memory.

Uses:
- RemoteEmbedder (with retry, connection pooling) for embedding
- QdrantHybridIndexer.live_upsert() for atomic chunk-level indexing
- asyncio.Semaphore for backpressure on concurrent API calls
- SHA-256 content-addressable chunks for idempotent indexing
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


@dataclass
class StreamingResult:
    """Result of processing one document through the streaming pipeline."""

    source: str
    doc_id: str
    chunks_count: int = 0
    chunks_indexed: int = 0
    errors: list[str] = field(default_factory=list)
    duration_ms: float = 0.0
    embedded_at: str = ""


@dataclass
class PipelineProgress:
    total_docs: int = 0
    processed_docs: int = 0
    total_chunks: int = 0
    indexed_chunks: int = 0
    errors: int = 0
    started_at: str = ""

    @property
    def progress_pct(self) -> float:
        if self.total_docs == 0:
            return 0.0
        return (self.processed_docs / self.total_docs) * 100


class StreamingPipeline:
    """Streaming-first ETL pipeline.

    Process flow per document:
      1. Chunk document (semantic_chunker)
      2. Embed chunks (remote API, parallel with semaphore)
      3. Index to Qdrant (hybrid indexer, live_upsert)
      4. Yield StreamingResult

    Supports:
    - Graceful shutdown via shutdown_event
    - Progress logging every N documents
    - Backpressure via semaphore for concurrent API calls
    """

    def __init__(
        self,
        config: dict[str, Any],
        wal: Any,
        shutdown_event: threading.Event | None = None,
    ):
        self._config = config
        self._wal = wal
        self._shutdown_event = shutdown_event
        self._progress = PipelineProgress(started_at=datetime.now(UTC).isoformat())

        self._embedder: Any = None
        self._indexer: Any = None
        self._chunker: Any = None
        self._semaphore: asyncio.Semaphore | None = None
        self._progress_interval: int = config.get("streaming", {}).get("progress_interval", 50)
        self._max_concurrent: int = config.get("streaming", {}).get("max_concurrent_api_calls", 10)

    async def _init_components(self) -> None:
        """Lazy initialization of embedder, indexer, chunker."""
        if self._embedder is None:
            self._embedder = self._create_embedder()
        if self._indexer is None:
            self._indexer = self._create_indexer()
        if self._chunker is None:
            self._chunker = self._create_chunker()
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self._max_concurrent)

    def _create_embedder(self) -> Any:
        remote_cfg = self._config.get("remote_services", {})
        embedder_cfg = remote_cfg.get("embedder", {})

        from etl.indexer.remote_embedder import RemoteEmbedder, RetryConfig

        retry_cfg = RetryConfig(
            max_attempts=embedder_cfg.get("max_retries", 5),
            base_delay=embedder_cfg.get("retry_delay", 2.0),
            max_delay=embedder_cfg.get("retry_max_delay", 30.0),
            retryable_http_statuses=(429, 500, 502, 503, 504),
        )

        endpoint = embedder_cfg.get("endpoint", embedder_cfg.get("url", ""))
        return RemoteEmbedder(
            endpoint=endpoint,
            model=embedder_cfg.get("model", ""),
            api_key=embedder_cfg.get("api_key", remote_cfg.get("api_key", "")),
            timeout=embedder_cfg.get("timeout", 60),
            max_batch_size=embedder_cfg.get("batch_size", 64),
            retry_config=retry_cfg,
            connection_pool_size=embedder_cfg.get("connection_pool_size", 16),
        )

    def _create_indexer(self) -> Any:
        index_cfg = self._config.get("indexing", {})

        from etl.indexer.qdrant_hybrid import QdrantHybridIndexer

        return QdrantHybridIndexer(
            host=index_cfg.get("qdrant_host", "localhost"),
            port=index_cfg.get("qdrant_port", 6333),
            collection_name=index_cfg.get("collection_name", "knowledge_base"),
            embedder_model_name=index_cfg.get("embedder_model", "BAAI/bge-m3"),
            embedder_device=index_cfg.get("embedder_device", "cpu"),
            batch_size=index_cfg.get("batch_size", 100),
            embedder=self._embedder,
        )

    def _create_chunker(self) -> Any:
        chunker_cfg = self._config.get("chunking", {})

        from etl.chunker.semantic_chunker import MDKeyChunker, MetadataEnricher, SemanticChunker

        base_chunker = SemanticChunker(
            max_tokens=chunker_cfg.get("max_tokens", 1500),
            overlap_tokens=chunker_cfg.get("overlap_tokens", 200),
            min_chunk_tokens=chunker_cfg.get("min_chunk_tokens", 100),
        )
        enricher = MetadataEnricher(
            use_slm=chunker_cfg.get("use_slm", False),
            slm_endpoint=chunker_cfg.get("slm_endpoint"),
        )
        return MDKeyChunker(base_chunker, enricher)

    async def _process_chunk(self, chunk_dict: dict[str, Any]) -> bool:
        """Embed a single chunk and index to Qdrant.

        Uses semaphore for backpressure on concurrent API calls.
        Returns True on success.
        """
        sem = self._semaphore
        if sem is None:
            raise RuntimeError("Semaphore not initialized — call _init_components() first")
        async with sem:
            try:
                loop = asyncio.get_running_loop()
                dense_vec = await loop.run_in_executor(
                    None,
                    lambda: self._embedder.encode(chunk_dict["text"], normalize_embeddings=True),
                )
                chunk_dict["_dense_vec"] = dense_vec.tolist()
            except Exception as e:
                logger.error("Failed to embed chunk %s: %s", chunk_dict.get("hash", "?"), e)
                return False

        return True

    async def _index_chunk(self, chunk_dict: dict[str, Any]) -> bool:
        """Index a single embedded chunk to Qdrant via live_upsert."""
        try:
            dense_vec = chunk_dict.pop("_dense_vec", None)
            if dense_vec is None:
                return False
            result = self._indexer.live_upsert(chunk_dict)
            if not result:
                point = self._indexer._chunk_to_point(chunk_dict)
                if point is not None:
                    self._indexer.client.upsert(
                        collection_name=self._indexer.collection_name,
                        points=[point],
                    )
                    return True
                return False
            return True
        except Exception as e:
            logger.error("Failed to index chunk %s: %s", chunk_dict.get("hash", "?"), e)
            return False

    async def process_document(self, doc: dict[str, Any]) -> StreamingResult:
        """Process a single document: chunk -> embed -> index -> yield result.

        :param doc: Document dict with id, source_type, title, content, content_type, metadata.
        :return: StreamingResult with processing summary.
        """
        started = datetime.now(UTC)
        result = StreamingResult(
            source=doc.get("source_type", "unknown"),
            doc_id=doc.get("id", "unknown"),
        )
        errors: list[str] = []

        source_metadata = {
            "source_type": doc.get("source_type", ""),
            "source_id": doc.get("id", ""),
            "version": doc.get("metadata", {}).get("version", "latest"),
            "doc_title": doc.get("title", ""),
        }

        try:
            chunks = self._chunker.process_document(
                doc["content"],
                doc.get("content_type", "html"),
                source_metadata,
            )
        except Exception as e:
            error_msg = f"Chunking failed for {doc['id']}: {e}"
            logger.error(error_msg)
            errors.append(error_msg)
            result.errors = errors
            result.duration_ms = (datetime.now(UTC) - started).total_seconds() * 1000
            return result

        chunk_dicts = [ch.__dict__ for ch in chunks]
        result.chunks_count = len(chunk_dicts)

        # Embed chunks in parallel (with semaphore backpressure)
        embed_tasks = [self._process_chunk(ch) for ch in chunk_dicts]
        embed_results = await asyncio.gather(*embed_tasks, return_exceptions=True)

        for ch, embed_result in zip(chunk_dicts, embed_results, strict=True):
            if isinstance(embed_result, Exception):
                errors.append(f"Embedding failed for chunk {ch.get('hash', '?')}: {embed_result}")
                continue
            if embed_result is False:
                errors.append(f"Embedding returned False for chunk {ch.get('hash', '?')}")
                continue

        # Index chunks (must be sequential for live_upsert due to Qdrant client)
        for ch in chunk_dicts:
            if "_dense_vec" not in ch:
                continue
            indexed = await asyncio.get_running_loop().run_in_executor(None, self._index_chunk_sync, ch)
            if indexed:
                result.chunks_indexed += 1
            else:
                errors.append(f"Indexing failed for chunk {ch.get('hash', '?')}")

        if result.chunks_indexed > 0:
            self._wal.update_last_run("streaming_index")

        result.errors = errors
        self._progress.processed_docs += 1
        self._progress.total_chunks += result.chunks_count
        self._progress.indexed_chunks += result.chunks_indexed
        if errors:
            self._progress.errors += 1
        result.duration_ms = (datetime.now(UTC) - started).total_seconds() * 1000
        result.embedded_at = datetime.now(UTC).isoformat()

        if self._progress.processed_docs % self._progress_interval == 0:
            logger.info(
                "Progress: %d/%d docs, %d chunks, %d indexed, %d errors (%.1f%%)",
                self._progress.processed_docs,
                self._progress.total_docs,
                self._progress.total_chunks,
                self._progress.indexed_chunks,
                self._progress.errors,
                self._progress.progress_pct,
            )

        return result

    def _index_chunk_sync(self, chunk_dict: dict[str, Any]) -> bool:
        """Synchronous wrapper for chunk indexing (called via run_in_executor)."""
        dense_vec = chunk_dict.get("_dense_vec")
        if dense_vec is None:
            return False
        try:
            point = self._indexer._chunk_to_point(chunk_dict)
            if point is not None:
                self._indexer.client.upsert(
                    collection_name=self._indexer.collection_name,
                    points=[point],
                )
                return True
        except Exception as e:
            logger.error("Failed to index chunk %s: %s", chunk_dict.get("hash", "?"), e)
        return False

    def _extract_documents_generator(self) -> Any:
        """Generate documents from raw data directories (streaming, not batching).

        Returns a generator that yields document dicts one at a time.
        This is the streaming equivalent of collect_all_documents().
        """
        source_names = ["confluence", "jira", "gitlab"]
        default_dirs = {
            "confluence": Path(self._config.get("confluence", {}).get("output_dir", "./raw_data/confluence")),
            "jira": Path(self._config.get("jira", {}).get("output_dir", "./raw_data/jira")),
            "gitlab": Path(self._config.get("gitlab", {}).get("output_dir", "./raw_data/gitlab")),
        }

        for source_name in source_names:
            source_dir = default_dirs[source_name]
            if not source_dir.exists():
                logger.warning("Directory for %s does not exist: %s — skipping", source_name, source_dir)
                continue

            logger.info("Streaming documents from %s: %s", source_name, source_dir)

            if source_name == "confluence":
                yield from self._extract_confluence_docs(source_dir)
            elif source_name == "jira":
                yield from self._extract_jira_docs(source_dir)
            elif source_name == "gitlab":
                yield from self._extract_gitlab_docs(source_dir)

    @staticmethod
    def _extract_confluence_docs(source_dir: Path) -> Any:
        for conflu_dir in source_dir.glob("*"):
            if not conflu_dir.is_dir():
                continue
            page_file = conflu_dir / "page.json"
            if not page_file.exists():
                continue
            with open(page_file, encoding="utf-8") as f:
                data = json.load(f)
            yield {
                "id": f"confluence_{data['id']}",
                "source_type": "confluence",
                "title": data.get("title", ""),
                "content": data.get("body_view_html", "") or data.get("body_storage_raw", ""),
                "content_type": "html",
                "metadata": {
                    "version": str(data.get("version", "")),
                    "space": data.get("space", ""),
                    "space_key": data.get("space_key", ""),
                    "page_id": data.get("id", ""),
                    "author": data.get("author", ""),
                    "contributors": data.get("contributors", []),
                    "labels": data.get("labels", []),
                    "restrictions": data.get("restrictions", {}),
                    "created_at": data.get("created_at", ""),
                    "updated_at": data.get("updated_at", ""),
                    "url": f"{conflu_dir.name}",
                },
            }

    @staticmethod
    def _extract_jira_docs(source_dir: Path) -> Any:
        for jira_dir in source_dir.glob("*"):
            if not jira_dir.is_dir():
                continue
            issue_file = jira_dir / "issue.json"
            if not issue_file.exists():
                continue
            with open(issue_file, encoding="utf-8") as f:
                data = json.load(f)
            content = data.get("description", "")
            for comment in data.get("comments", []):
                content += f"\n\nComment by {comment['author']}: {comment['body']}"
            yield {
                "id": f"jira_{data['key']}",
                "source_type": "jira",
                "title": data.get("summary", ""),
                "content": content,
                "content_type": "html",
                "metadata": {
                    "key": data["key"],
                    "status": data.get("status", ""),
                    "priority": data.get("priority", ""),
                    "assignee": data.get("assignee", ""),
                    "reporter": data.get("reporter", ""),
                    "project_key": data.get("project_key", ""),
                    "issue_type": data.get("issue_type", ""),
                    "labels": data.get("labels", []),
                    "components": data.get("components", []),
                    "created": data.get("created", ""),
                    "updated": data.get("updated", ""),
                },
            }

    @staticmethod
    def _extract_gitlab_docs(source_dir: Path) -> Any:
        for gitlab_dir in source_dir.glob("*"):
            if not gitlab_dir.is_dir():
                continue

            project_info: dict[str, Any] = {}
            project_file = gitlab_dir / "project.json"
            if project_file.exists():
                with open(project_file, encoding="utf-8") as f:
                    project_info = json.load(f)
            project_id = project_info.get("id", gitlab_dir.name)
            namespace = project_info.get("namespace", {}).get("full_path", "")
            visibility = project_info.get("visibility", "")

            commits_file = gitlab_dir / "commits.json"
            if commits_file.exists():
                with open(commits_file, encoding="utf-8") as f:
                    commits = json.load(f)
                for commit in commits[:100]:
                    content = commit.get("message", "")
                    for diff in commit.get("diff", [])[:5]:
                        content += f"\n{diff.get('new_path', '')}: {diff.get('diff', '')[:200]}"
                    yield {
                        "id": f"gitlab_commit_{commit['id']}",
                        "source_type": "gitlab_commit",
                        "title": commit.get("title", commit["id"][:8]),
                        "content": content,
                        "content_type": "markdown",
                        "metadata": {
                            "sha": commit["id"],
                            "author": commit.get("author_name", ""),
                            "date": commit.get("created_at", ""),
                            "project_id": project_id,
                            "namespace": namespace,
                            "visibility": visibility,
                        },
                    }

            mr_file = gitlab_dir / "merge_requests.json"
            if mr_file.exists():
                with open(mr_file, encoding="utf-8") as f:
                    mrs = json.load(f)
                for mr in mrs:
                    content = mr.get("title", "") + "\n" + mr.get("description", "")
                    for disc in mr.get("discussions", []):
                        for note in disc.get("notes", []):
                            content += f"\n{note['author']}: {note['body']}"
                    yield {
                        "id": f"gitlab_mr_{mr['iid']}",
                        "source_type": "gitlab_merge_request",
                        "title": mr.get("title", ""),
                        "content": content,
                        "content_type": "markdown",
                        "metadata": {
                            "iid": mr["iid"],
                            "state": mr.get("state", ""),
                            "author": mr.get("author", {}).get("username", ""),
                            "project_id": project_id,
                            "namespace": namespace,
                            "visibility": visibility,
                        },
                    }

            files_dir = gitlab_dir / "files"
            if files_dir.exists():
                for code_file in files_dir.glob("*.txt"):
                    content = code_file.read_text(encoding="utf-8")
                    yield {
                        "id": f"gitlab_file_{code_file.stem}",
                        "source_type": "gitlab_code",
                        "title": code_file.stem,
                        "content": content,
                        "content_type": "plaintext",
                        "metadata": {
                            "path": code_file.stem,
                            "project_id": project_id,
                            "namespace": namespace,
                            "visibility": visibility,
                        },
                    }

    def _count_docs(self) -> int:
        """Count total documents for progress tracking."""
        count = 0
        for _ in self._extract_documents_generator():
            count += 1
        return count

    async def run(self) -> AsyncIterator[StreamingResult]:
        """Execute the full streaming pipeline.

        Yields StreamingResult for each processed document.
        """
        await self._init_components()

        self._indexer.create_collection(recreate=False)

        docs = list(self._extract_documents_generator())
        self._progress.total_docs = len(docs)
        logger.info(
            "Streaming pipeline starting: %d documents, %d concurrent API calls",
            self._progress.total_docs,
            self._max_concurrent,
        )

        self._progress.processed_docs = 0

        for doc in docs:
            if self._shutdown_event and self._shutdown_event.is_set():
                logger.warning(
                    "Shutdown requested, stopping at doc %d/%d",
                    self._progress.processed_docs,
                    self._progress.total_docs,
                )
                break

            result = await self.process_document(doc)
            yield result

        logger.info(
            "Streaming pipeline complete: %d docs, %d chunks, %d indexed, %d errors",
            self._progress.processed_docs,
            self._progress.total_chunks,
            self._progress.indexed_chunks,
            self._progress.errors,
        )

    def run_sync(self) -> list[StreamingResult]:
        """Synchronous wrapper for the streaming pipeline.

        Returns list of all StreamingResults.
        """
        return asyncio.run(self._run_collect())

    async def _run_collect(self) -> list[StreamingResult]:
        results: list[StreamingResult] = []
        async for result in self.run():
            results.append(result)
        return results


def load_config(config_path: Path) -> dict[str, Any]:
    import os
    import re

    with open(config_path, encoding="utf-8") as f:
        raw = f.read()

    def _expand(m: re.Match) -> str:
        var_name = m.group(1)
        default = m.group(2) if m.group(2) is not None else ""
        return os.environ.get(var_name, default)

    expanded = re.sub(r"\$\{(\w+):-([^}]*)\}", _expand, raw)
    expanded = re.sub(r"\$\{(\w+)\}", lambda m: os.environ.get(m.group(1), ""), expanded)

    return yaml.safe_load(expanded)


async def main_streaming(config: dict[str, Any], wal: Any) -> None:
    """Entry point for streaming pipeline from run_etl.py.

    :param config: Full ETL YAML config as dict.
    :param wal: WALManager instance for checkpoint tracking.
    """
    pipeline = StreamingPipeline(config, wal)

    async for result in pipeline.run():
        level = logging.WARNING if result.errors else logging.INFO
        logger.log(
            level,
            "Processed: %s doc %s — %d chunks, %d indexed, %d errors (%.0fms)",
            result.source,
            result.doc_id,
            result.chunks_count,
            result.chunks_indexed,
            len(result.errors),
            result.duration_ms,
        )
