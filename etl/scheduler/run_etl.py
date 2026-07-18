#!/usr/bin/env python3
# etl/scheduler/run_etl.py
"""Главный оркестратор ETL-пайплайна для RAG-системы.
Запускает все этапы:
1. Extract: Confluence, Jira, GitLab (параллельно, с graceful degradation)
2. Chunking: семантическая нарезка документов
3. Graph: извлечение сущностей и отношений (опционально)
4. Index: индексация в Qdrant (гибридная, с версионированием)
5. Neo4j: загрузка графа (опционально)

Использует единый WAL для инкрементальных запусков.
"""

import argparse
import atexit
import json
import logging
import os
import signal
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

# Глобальное событие для graceful shutdown (потокобезопасное)
_shutdown_event = threading.Event()
# Флаг для обработки двойного Ctrl+C (принудительный выход)
_force_exit = False


def _signal_handler(signum: int, frame: Any) -> None:
    """Обработчик SIGINT/SIGTERM для graceful shutdown."""
    global _force_exit
    if _shutdown_event.is_set():
        # Второй нажатие Ctrl+C — принудительный выход
        _force_exit = True
        logger.warning("Forced shutdown requested — exiting immediately")
        sys.exit(1)
    _shutdown_event.set()
    logger.warning(f"Received signal {signum}, shutting down gracefully...")


# Регистрируем обработчики сигналов
signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)

# Добавляем корень проекта в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Импорт модулей ETL — E402 suppressed: sys.path must be set before imports
from etl.chunker.hash_versioning import ChunkVersionStore  # noqa: E402
from etl.chunker.semantic_chunker import MDKeyChunker, MetadataEnricher, SemanticChunker  # noqa: E402
from etl.extractors.confluence import ConfluenceExtractor  # noqa: E402
from etl.extractors.gitlab import GitLabExtractor  # noqa: E402
from etl.extractors.jira import JiraExtractor  # noqa: E402
from etl.graph_builder.entity_extractor import EntityRelationExtractor  # noqa: E402
from etl.graph_builder.neo4j_loader import Neo4jLoader  # noqa: E402
from etl.indexer.chunk_enricher import build_chunk_enricher_from_config  # noqa: E402
from etl.indexer.chunk_quality import build_chunk_quality_filter_from_config  # noqa: E402
from etl.indexer.live_vector_lake import LiveVectorLake  # noqa: E402
from etl.indexer.qdrant_hybrid import QdrantHybridIndexer  # noqa: E402
from etl.indexer.remote_embedder import _resolve_max_tokens, build_remote_embedder_from_config  # noqa: E402
from etl.indexer.wal_manager import (  # noqa: E402
    PIPELINE_CONFLUENCE,
    PIPELINE_GITLAB,
    PIPELINE_INDEXING,
    PIPELINE_JIRA,
    WALManager,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("ETL Orchestrator")


def load_config(config_path: Path) -> dict[str, Any]:
    """Загружает YAML-конфигурацию с подстановкой переменных окружения.

    Поддерживает синтаксис ${VAR:-default} в строковых значениях.
    """
    with open(config_path, encoding="utf-8") as f:
        raw = f.read()

    import re

    def _expand_env(match: re.Match) -> str:
        var_name = match.group(1)
        default = match.group(2) if match.group(2) is not None else ""
        return os.environ.get(var_name, default)

    expanded = re.sub(r"\$\{(\w+):-([^}]*)\}", _expand_env, raw)
    expanded = re.sub(r"\$\{(\w+)\}", lambda m: os.environ.get(m.group(1), ""), expanded)

    return yaml.safe_load(expanded)


def _resolve_chunk_max_tokens(chunker_config: dict, full_config: dict) -> int:
    """Resolve chunking max_tokens, supporting 'auto' detection from embedder model.

    When chunking.max_tokens is "auto", looks up the embedder model name from
    remote_services.embedder.model and resolves its known context window.
    Falls back to 1500 if no model info is available.
    """
    raw_value = chunker_config.get("max_tokens", 1500)
    if raw_value != "auto":
        return int(raw_value)

    model = full_config.get("remote_services", {}).get("embedder", {}).get("model", "")
    if model:
        resolved = _resolve_max_tokens(model)
        logger.info(
            "Auto-detected chunk max_tokens=%d from embedder model '%s'",
            resolved,
            model,
        )
        return resolved

    logger.warning("chunking.max_tokens='auto' but no embedder model configured. Defaulting to 1500 tokens.")
    return 1500


def run_extract_confluence(config: dict, wal: WALManager) -> Path:
    """Запускает выгрузку Confluence, возвращает директорию с сырыми данными."""
    logger.info("=== Starting Confluence extraction ===")
    confluence_config = config.get("confluence", {})
    last_run = wal.get_last_run(PIPELINE_CONFLUENCE)
    if last_run and not confluence_config.get("since_date"):
        confluence_config["since_date"] = last_run
        logger.info(f"Using incremental since_date: {last_run}")
    confluence_config["wal_file"] = str(wal.wal_path)
    confluence_config["incremental"] = True
    extractor = ConfluenceExtractor(confluence_config)
    extractor._shutdown_event = _shutdown_event  # inject graceful shutdown
    extractor.run()
    wal.update_last_run(PIPELINE_CONFLUENCE)
    output_dir = Path(confluence_config.get("output_dir", "./raw_data/confluence"))
    logger.info(f"Confluence extraction completed. Data in {output_dir}")
    return output_dir


def run_extract_jira(config: dict, wal: WALManager) -> Path:
    """Запускает выгрузку Jira."""
    logger.info("=== Starting Jira extraction ===")
    jira_config = config.get("jira", {})
    last_run = wal.get_last_run(PIPELINE_JIRA)
    if last_run and not jira_config.get("since_date"):
        jira_config["since_date"] = last_run
        logger.info(f"Using incremental since_date: {last_run}")
    jira_config["incremental"] = True
    jira_config["wal_file"] = str(wal.wal_path)
    extractor = JiraExtractor(jira_config)
    extractor._shutdown_event = _shutdown_event  # inject graceful shutdown
    extractor.run()
    wal.update_last_run(PIPELINE_JIRA)
    output_dir = Path(jira_config.get("output_dir", "./raw_data/jira"))
    return output_dir


def run_extract_gitlab(config: dict, wal: WALManager) -> Path:
    """Запускает выгрузку GitLab."""
    logger.info("=== Starting GitLab extraction ===")
    gitlab_config = config.get("gitlab", {})
    last_run = wal.get_last_run(PIPELINE_GITLAB)
    if last_run and not gitlab_config.get("since_date"):
        gitlab_config["since_date"] = last_run
        logger.info(f"Using incremental since_date: {last_run}")
    gitlab_config["incremental"] = True
    gitlab_config["wal_file"] = str(wal.wal_path)
    extractor = GitLabExtractor(gitlab_config)
    extractor._shutdown_event = _shutdown_event  # inject graceful shutdown
    extractor.run()
    wal.update_last_run(PIPELINE_GITLAB)
    output_dir = Path(gitlab_config.get("output_dir", "./raw_data/gitlab"))
    return output_dir


def _run_extractor_safe(name: str, extract_fn, config: dict, wal: WALManager) -> tuple[str, Path | None, str | None]:
    """Запускает экстрактор с обработкой ошибок. Возвращает (name, output_dir, error)."""
    try:
        output_dir = extract_fn(config, wal)
        return (name, output_dir, None)
    except Exception as e:
        logger.error(f"Extractor '{name}' failed: {e}", exc_info=True)
        return (name, None, str(e))


def collect_all_documents(extract_dirs: list[Path]) -> list[dict[str, Any]]:
    """Собирает все извлечённые документы из директорий extractors.
    Обрабатывает отсутствующие директории gracefully (Extractor мог не запуститься).
    """
    documents = []
    source_names = ["confluence", "jira", "gitlab"]

    for source_dir, source_name in zip(extract_dirs, source_names, strict=False):
        if not source_dir.exists():
            logger.warning(f"Directory for {source_name} does not exist: {source_dir} — skipping")
            continue
        logger.info(f"Collecting documents from {source_name}: {source_dir}")

        if source_name == "confluence":
            for conflu_dir in source_dir.glob("*"):
                if not conflu_dir.is_dir():
                    continue
                page_file = conflu_dir / "page.json"
                if page_file.exists():
                    with open(page_file, encoding="utf-8") as f:
                        data = json.load(f)
                    documents.append(
                        {
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
                        },
                    )

        elif source_name == "jira":
            for jira_dir in source_dir.glob("*"):
                if not jira_dir.is_dir():
                    continue
                issue_file = jira_dir / "issue.json"
                if issue_file.exists():
                    with open(issue_file, encoding="utf-8") as f:
                        data = json.load(f)
                    content = data.get("description", "")
                    for comment in data.get("comments", []):
                        content += f"\n\nComment by {comment['author']}: {comment['body']}"
                    documents.append(
                        {
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
                        },
                    )

        elif source_name == "gitlab":
            for gitlab_dir in source_dir.glob("*"):
                if not gitlab_dir.is_dir():
                    continue
                # Load project-level RBAC metadata if available
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
                        documents.append(
                            {
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
                            },
                        )
                mr_file = gitlab_dir / "merge_requests.json"
                if mr_file.exists():
                    with open(mr_file, encoding="utf-8") as f:
                        mrs = json.load(f)
                    for mr in mrs:
                        content = mr.get("title", "") + "\n" + mr.get("description", "")
                        for disc in mr.get("discussions", []):
                            for note in disc.get("notes", []):
                                content += f"\n{note['author']}: {note['body']}"
                        documents.append(
                            {
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
                            },
                        )
                files_dir = gitlab_dir / "files"
                if files_dir.exists():
                    for code_file in files_dir.glob("*.txt"):
                        content = code_file.read_text(encoding="utf-8")
                        documents.append(
                            {
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
                            },
                        )

    return documents


def run_chunking(
    documents: list[dict],
    chunker: MDKeyChunker,
    output_dir: Path,
    quality_filter: Any = None,
):
    """Выполняет семантический чанкинг всех документов и сохраняет чанки в JSON.
    Также создаёт heading-level и document-level чанки для Confluence-страниц.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    all_chunks = []
    heading_chunks = []
    document_chunks = []
    total_filtered_out = 0
    for i, doc in enumerate(documents):
        if _shutdown_event.is_set():
            logger.warning(f"Shutdown requested, stopping chunking at document {i}/{len(documents)}")
            break
        source_metadata = {
            "source_type": doc["source_type"],
            "source_id": doc["id"],
            "version": doc["metadata"].get("version", "latest"),
            "doc_title": doc["title"],
        }
        try:
            chunks = chunker.process_document(doc["content"], doc["content_type"], source_metadata)
            chunk_dicts = [ch.__dict__ for ch in chunks]

            # Apply quality filter after chunking, before saving
            if quality_filter and chunk_dicts:
                original_count = len(chunk_dicts)
                chunk_dicts, _stats = quality_filter.filter(
                    doc_title=doc.get("title", ""),
                    chunks=chunk_dicts,
                )
                filtered_out = original_count - len(chunk_dicts)
                total_filtered_out += filtered_out
                if filtered_out:
                    logger.info(
                        "Quality filter: %d/%d chunks kept for '%s' (%d filtered out)",
                        len(chunk_dicts),
                        original_count,
                        doc["title"][:80],
                        filtered_out,
                    )

            doc_chunk_file = output_dir / f"{doc['id'].replace('/', '_')}.json"
            with open(doc_chunk_file, "w", encoding="utf-8") as f:
                json.dump(chunk_dicts, f, ensure_ascii=False, indent=2)
            all_chunks.extend(chunk_dicts)
            logger.info(f"Chunked {doc['id']} -> {len(chunks)} chunks")

            # Heading-level and document-level indexing for Confluence pages
            if doc["source_type"] == "confluence" and doc["content_type"] == "html":
                html_content = doc["content"]
                # Convert to markdown for document chunk
                try:
                    md_text = chunker.base._html_to_markdown(html_content)
                except Exception:
                    md_text = doc["content"]
                # Heading chunks
                try:
                    h_chunks = chunker.base.create_heading_chunks(html_content, source_metadata)
                    h_dicts = [h.__dict__ for h in h_chunks]
                    heading_chunks.extend(h_dicts)
                    logger.info(f"  -> {len(h_chunks)} heading chunks for {doc['id']}")
                except Exception as e:
                    logger.warning(f"  Failed to create heading chunks for {doc['id']}: {e}")
                # Document chunk
                try:
                    doc_chunk = chunker.base.create_document_chunk(md_text, source_metadata)
                    if doc_chunk:
                        document_chunks.append(doc_chunk.__dict__)
                        logger.info(f"  -> document chunk for {doc['id']}")
                except Exception as e:
                    logger.warning(f"  Failed to create document chunk for {doc['id']}: {e}")

        except Exception as e:
            logger.error(f"Failed to chunk {doc['id']}: {e}")

    # Сохраняем все чанки
    all_chunks_file = output_dir / "all_chunks.json"
    with open(all_chunks_file, "w", encoding="utf-8") as f:
        json.dump(all_chunks, f, ensure_ascii=False, indent=2)
    if heading_chunks:
        heading_file = output_dir / "heading_chunks.json"
        with open(heading_file, "w", encoding="utf-8") as f:
            json.dump(heading_chunks, f, ensure_ascii=False, indent=2)
        all_chunks.extend(heading_chunks)
    if document_chunks:
        doc_file = output_dir / "document_chunks.json"
        with open(doc_file, "w", encoding="utf-8") as f:
            json.dump(document_chunks, f, ensure_ascii=False, indent=2)
        all_chunks.extend(document_chunks)

    logger.info(
        "Total chunks: %d (content=%d, heading=%d, document=%d)",
        len(all_chunks),
        len(all_chunks) - len(heading_chunks) - len(document_chunks),
        len(heading_chunks),
        len(document_chunks),
    )
    return all_chunks


def run_enrichment(all_chunks: list[dict], config: dict) -> list[dict]:
    """Обогащает чанки через SLM: keywords, entities, hyde_questions, summary.

    Enrichment is non-blocking — if SLM is unavailable, falls back to heuristics.
    Each chunk dict gets enriched fields merged in-place.
    """
    enricher = build_chunk_enricher_from_config(config)
    if enricher is None:
        logger.info("Chunk enrichment is disabled — skipping")
        return all_chunks

    enrich_cfg = config.get("enrichment", {})
    max_concurrent = enrich_cfg.get("max_concurrent", 5)
    logger.info(
        "Starting chunk enrichment: %d chunks, %d concurrent, SLM=%s",
        len(all_chunks),
        max_concurrent,
        enricher._model if enricher.is_enabled else "heuristic-only",
    )

    enriched_count = 0
    for i, ch in enumerate(all_chunks):
        if _shutdown_event.is_set():
            logger.warning(f"Shutdown requested, stopping enrichment at chunk {i}/{len(all_chunks)}")
            break

        try:
            result = enricher.enrich(ch.get("text", ""), ch.get("metadata", {}))
            ch["keywords"] = result.get("keywords", [])
            ch["entities"] = result.get("entities", [])
            ch["hypothetical_questions"] = result.get("hyde_questions", [])
            if result.get("summary"):
                ch["summary"] = result["summary"]
            enriched_count += 1
        except Exception as e:
            logger.warning("Enrichment failed for chunk %s: %s", ch.get("hash", "?"), e)

        if (i + 1) % 100 == 0:
            logger.info("Enrichment progress: %d/%d chunks", i + 1, len(all_chunks))

    logger.info("Chunk enrichment complete: %d/%d chunks enriched", enriched_count, len(all_chunks))
    return all_chunks


def run_graph_extraction(
    chunks: list[dict],
    entity_extractor: EntityRelationExtractor,
    neo4j_loader: Neo4jLoader | None,
):
    """Извлекает сущности и отношения из чанков, загружает в Neo4j."""
    logger.info("=== Starting graph extraction ===")
    # Преобразуем чанки в формат для batch extractor
    chunk_inputs = []
    for ch in chunks:
        chunk_inputs.append(
            {"text": ch["text"], "source_id": ch.get("source_id", "unknown"), "metadata": ch.get("metadata", {})},
        )
    entities, relations = entity_extractor.extract_batch(chunk_inputs)
    logger.info(f"Extracted {len(entities)} entities and {len(relations)} relations")
    if neo4j_loader and (entities or relations):
        # Создаём индексы и ограничения (один раз)
        neo4j_loader.create_constraints_and_indexes()
        # Конвертируем в формат для загрузчика (НЕ удаляем source_id — он нужен для MERGE)
        entity_dicts = [e.__dict__ for e in entities]
        relation_dicts = [r.__dict__ for r in relations]
        neo4j_loader.load_entities(entity_dicts)
        neo4j_loader.load_relations(relation_dicts)
        logger.info("Loaded graph into Neo4j")
    return entities, relations


def run_indexing(chunks: list[dict], live_lake: LiveVectorLake, wal: WALManager):
    """Инкрементально индексирует чанки в Qdrant через LiveVectorLake."""
    logger.info("=== Starting indexing ===")
    # Группируем чанки по source_id (документ)
    doc_chunks = {}
    for ch in chunks:
        doc_id = ch.get("source_id", "unknown")
        if doc_id not in doc_chunks:
            doc_chunks[doc_id] = []
        doc_chunks[doc_id].append(ch)
    total_added = 0
    total_deleted = 0
    for i, (doc_id, doc_chunks_list) in enumerate(doc_chunks.items()):
        if _shutdown_event.is_set():
            logger.warning(f"Shutdown requested, stopping indexing at document {i}/{len(doc_chunks)}")
            break
        added, deleted = live_lake.sync_document(doc_id, doc_chunks_list)
        total_added += added
        total_deleted += deleted
    # Обновляем WAL индексации
    wal.update_last_run(PIPELINE_INDEXING)
    wal.set_checkpoint(PIPELINE_INDEXING, {"added": total_added, "deleted": total_deleted})
    logger.info(f"Indexing completed: added {total_added}, deleted {total_deleted}")


def _cleanup_path(path: Path, dry_run: bool) -> bool:
    """Remove a directory if it exists. Returns True if action was taken."""
    if not path.exists():
        logger.info(f"[cleanup] {path} does not exist — skipping")
        return False
    if dry_run:
        logger.info(f"[dry-run] Would remove: {path}")
        return True
    import shutil

    shutil.rmtree(path)
    logger.info(f"[cleanup] Removed: {path}")
    return True


def _strip_chunk_full_text(hot_dir: Path, dry_run: bool) -> tuple[int, int]:
    """Strip full text from hot_chunks JSON files, keeping only hashes and metadata.

    Returns (files_processed, bytes_freed).
    """
    if not hot_dir.exists():
        return (0, 0)
    files_processed = 0
    bytes_freed = 0
    for json_file in hot_dir.glob("*.json"):
        try:
            original_text = json_file.read_text(encoding="utf-8")
            original_size = len(original_text.encode("utf-8"))
            chunks = json.loads(original_text)
            stripped: list[dict[str, Any]] = []
            for ch in chunks:
                keep_fields = {
                    "hash": ch.get("hash", ""),
                    "source_id": ch.get("source_id", "unknown"),
                    "version": ch.get("version", "latest"),
                    "doc_title": ch.get("doc_title", ""),
                    "source_type": ch.get("source_type", ""),
                }
                stripped.append(keep_fields)
            if dry_run:
                logger.info(f"[dry-run] Would strip {json_file.name}: {len(chunks)} chunks")
            else:
                json.dump(stripped, json_file.open("w", encoding="utf-8"), ensure_ascii=False, indent=2)
                bytes_freed += original_size - len(json.dumps(stripped, ensure_ascii=False, indent=2).encode("utf-8"))
            files_processed += 1
        except Exception as e:
            logger.warning(f"Failed to strip {json_file}: {e}")
    return (files_processed, bytes_freed)


def run_cleanup(
    config: dict[str, Any],
    cleanup_after_index: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Clean up raw data and chunk files after successful indexing.

    Respects config settings:
      etl.data_retention.raw_data_days: auto-delete raw extracts after N days (0 = keep forever)
      etl.data_retention.cleanup_after_run: clean immediately after indexing
      etl.data_retention.keep_cold_storage: preserve cold storage for versioning

    Returns dict with cleanup summary.
    """
    retention_cfg = config.get("etl", {}).get("data_retention", {})

    if not cleanup_after_index and not retention_cfg.get("cleanup_after_run"):
        logger.info("Cleanup not requested — skipping")
        return {"ran": False, "reason": "not requested"}

    logger.info(f"=== Starting post-indexing cleanup {'(dry-run)' if dry_run else ''} ===")
    summary: dict[str, Any] = {
        "ran": True,
        "dry_run": dry_run,
        "directories_removed": [],
        "hot_chunks_stripped": 0,
        "bytes_freed": 0,
    }

    raw_data_dirs = [
        Path(config.get("confluence", {}).get("output_dir", "./raw_data/confluence")),
        Path(config.get("jira", {}).get("output_dir", "./raw_data/jira")),
        Path(config.get("gitlab", {}).get("output_dir", "./raw_data/gitlab")),
    ]
    for d in raw_data_dirs:
        if _cleanup_path(d, dry_run=dry_run):
            summary["directories_removed"].append(str(d))

    chunks_dir = Path(config.get("chunking", {}).get("output_dir", "./chunks"))
    if _cleanup_path(chunks_dir, dry_run=dry_run):
        summary["directories_removed"].append(str(chunks_dir))

    keep_cold = retention_cfg.get("keep_cold_storage", True)
    if keep_cold:
        logger.info("Keeping cold storage (keep_cold_storage=true)")
    else:
        cold_dir = Path(config.get("indexing", {}).get("cold_dir", "./cold_chunks"))
        if _cleanup_path(cold_dir, dry_run=dry_run):
            summary["directories_removed"].append(str(cold_dir))
        lake_dir = Path(config.get("indexing", {}).get("lake_dir", "./cold_lake"))
        if _cleanup_path(lake_dir, dry_run=dry_run):
            summary["directories_removed"].append(str(lake_dir))

    hot_dir = Path(config.get("indexing", {}).get("hot_dir", "./hot_chunks"))
    files_stripped, bytes_freed = _strip_chunk_full_text(hot_dir, dry_run=dry_run)
    summary["hot_chunks_stripped"] = files_stripped
    summary["bytes_freed"] = bytes_freed

    logger.info(f"Cleanup complete: {summary}")
    return summary


def main():
    parser = argparse.ArgumentParser(description="RAG ETL Pipeline Orchestrator")
    parser.add_argument("--config", type=Path, default=Path("etl_config.yaml"), help="Path to YAML config")
    parser.add_argument(
        "--mode",
        choices=["streaming", "batch"],
        default=None,
        help="Pipeline mode (default: from config pipeline.mode, falls back to streaming)",
    )
    parser.add_argument("--timeout", type=int, default=None, help="Request timeout in seconds (overrides config)")
    parser.add_argument("--test-connection", action="store_true", help="Test connection to all sources and exit")
    parser.add_argument("--skip-extract", action="store_true", help="Skip extraction phase (batch mode only)")
    parser.add_argument("--skip-chunk", action="store_true", help="Skip chunking phase (batch mode only)")
    parser.add_argument("--skip-graph", action="store_true", help="Skip graph building phase")
    parser.add_argument("--skip-index", action="store_true", help="Skip indexing phase (batch mode only)")
    parser.add_argument("--force-reindex", action="store_true", help="Force reindex all documents (ignore WAL)")
    parser.add_argument("--reset-wal", action="store_true", help="Reset all WAL checkpoints before run")
    parser.add_argument(
        "--cleanup-after-index",
        action="store_true",
        help="Clean up raw data and chunk files after indexing",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be cleaned (use with --cleanup-after-index)",
    )
    parser.add_argument(
        "--streaming",
        action="store_true",
        help="Start streaming ETL (webhook + consumer) alongside batch (deprecated: use --mode streaming)",
    )
    parser.add_argument("--webhook-only", action="store_true", help="Start only webhook server")
    parser.add_argument("--consumer-only", action="store_true", help="Start only stream consumer")
    parser.add_argument(
        "--quality-report",
        type=Path,
        default=None,
        help="Generate extraction quality report (JSON) and save to path",
    )
    args = parser.parse_args()

    # Загрузка конфигурации
    config = load_config(args.config)

    # Override timeout from command line
    if args.timeout is not None:
        for source in ["confluence", "jira", "gitlab"]:
            if source in config:
                config[source]["timeout"] = args.timeout
        logger.info(f"Timeout overridden to {args.timeout}s")

    # Determine pipeline mode: CLI > config > default
    pipeline_cfg = config.get("pipeline", {})
    mode = args.mode or pipeline_cfg.get("mode", "streaming")
    logger.info("Pipeline mode: %s (config: %s, CLI: %s)", mode, pipeline_cfg.get("mode"), args.mode)

    # Test connection mode
    if args.test_connection:
        logger.info("=== Testing connections ===")
        results = {}

        # Test Confluence
        confluence_config = config.get("confluence", {})
        if confluence_config.get("url"):
            try:
                from etl.extractors.confluence import ConfluenceExtractor

                conflu_extractor = ConfluenceExtractor(confluence_config)
                results["confluence"] = conflu_extractor.test_connection()
            except Exception as e:
                logger.error(f"Confluence: {e}")
                results["confluence"] = False

        # Test Jira
        jira_config = config.get("jira", {})
        if jira_config.get("url"):
            try:
                from etl.extractors.jira import JiraExtractor

                jira_extractor = JiraExtractor(jira_config)
                logger.info(f"Testing Jira connection to {jira_config['url']}...")
                resp = jira_extractor._request("/rest/api/2/myself")
                logger.info(f"✅ Jira: {resp.get('displayName', 'OK')}")
                results["jira"] = True
            except Exception as e:
                logger.error(f"❌ Jira: {e}")
                results["jira"] = False

        # Test GitLab
        gitlab_config = config.get("gitlab", {})
        if gitlab_config.get("url"):
            try:
                from etl.extractors.gitlab import GitLabExtractor

                gitlab_extractor = GitLabExtractor(gitlab_config)
                logger.info(f"Testing GitLab connection to {gitlab_config['url']}...")
                resp = gitlab_extractor._request("/api/v4/user")
                logger.info(f"✅ GitLab: {resp.get('name', 'OK')}")
                results["gitlab"] = True
            except Exception as e:
                logger.error(f"❌ GitLab: {e}")
                results["gitlab"] = False

        # Summary
        logger.info("=== Connection Test Results ===")
        for source, ok in results.items():
            status = "✅ OK" if ok else "❌ FAILED"
            logger.info(f"  {source}: {status}")

        if all(results.values()):
            logger.info("All connections OK!")
        else:
            logger.error("Some connections failed. Check logs above.")
        return

    # Инициализация WAL
    wal_path = Path(config.get("wal", {}).get("wal_file", "./wal/etl_wal.json"))
    wal = WALManager(wal_path, use_lock=True)
    if args.reset_wal:
        wal.reset_all()
        logger.info("WAL has been reset")

    # --- Streaming mode: use StreamingPipeline (extract->chunk->embed->index in one pass) ---
    if mode == "streaming":
        logger.info("=== Starting streaming pipeline ===")
        from etl.scheduler.streaming_pipeline import StreamingPipeline

        pipeline = StreamingPipeline(config, wal, shutdown_event=_shutdown_event)
        pipeline.run_sync()
        logger.info("Streaming pipeline completed successfully")
        return

    # --- Batch mode: traditional extract -> collect -> chunk -> index ---
    def _save_wal_on_exit() -> None:
        """Сохраняет WAL checkpoint при завершении процесса."""
        try:
            wal.set_checkpoint(
                "pipeline",
                {
                    "shutdown": True,
                    "shutdown_at": datetime.now(UTC).isoformat(),
                    "forced": _force_exit,
                },
            )
            # Use print() instead of logger — logging stream may already be closed during shutdown
            print("WAL checkpoint saved on exit", file=sys.stderr)
        except Exception as e:
            logger.error(f"Failed to save WAL on exit: {e}")

    atexit.register(_save_wal_on_exit)

    # 1. Извлечение (параллельно с graceful degradation)
    extract_dirs = []
    if not args.skip_extract:
        # Определяем какие экстракторы запускать
        extractors_to_run = []
        if config.get("confluence", {}).get("url"):
            extractors_to_run.append(("confluence", run_extract_confluence))
        if config.get("jira", {}).get("url"):
            extractors_to_run.append(("jira", run_extract_jira))
        if config.get("gitlab", {}).get("url"):
            extractors_to_run.append(("gitlab", run_extract_gitlab))

        if not extractors_to_run:
            logger.warning("No extractors configured (confluence/jira/gitlab URLs missing)")
        else:
            names = [e[0] for e in extractors_to_run]
            logger.info(f"Starting {len(extractors_to_run)} extractors in parallel: {names}")
            failed_extractors = []
            default_dirs = {
                "confluence": Path(config.get("confluence", {}).get("output_dir", "./raw_data/confluence")),
                "jira": Path(config.get("jira", {}).get("output_dir", "./raw_data/jira")),
                "gitlab": Path(config.get("gitlab", {}).get("output_dir", "./raw_data/gitlab")),
            }

            with ThreadPoolExecutor(max_workers=len(extractors_to_run), thread_name_prefix="etl") as pool:
                futures = {
                    pool.submit(_run_extractor_safe, name, fn, config, wal): name for name, fn in extractors_to_run
                }
                for future in as_completed(futures):
                    if _shutdown_event.is_set():
                        logger.warning("Shutdown requested, cancelling remaining extractors...")
                        pool.shutdown(wait=False, cancel_futures=True)
                        break
                    name, output_dir, error = future.result()
                    if error:
                        failed_extractors.append((name, error))
                        logger.warning(f"Extractor '{name}' failed — continuing with other extractors")
                        extract_dirs.append(default_dirs[name])
                    elif output_dir is not None:
                        extract_dirs.append(output_dir)

            if failed_extractors:
                failed_names = [f[0] for f in failed_extractors]
                logger.warning(f"=== {len(failed_extractors)} extractor(s) failed: {failed_names} ===")
                for name, err in failed_extractors:
                    logger.warning(f"  {name}: {err}")
            if len(failed_extractors) == len(extractors_to_run):
                logger.error("All extractors failed — pipeline cannot continue")
                sys.exit(1)
            succeeded = len(extractors_to_run) - len(failed_extractors)
            logger.info(f"Extraction completed: {succeeded}/{len(extractors_to_run)} succeeded")
    else:
        # Используем уже существующие директории из конфига
        extract_dirs = [
            Path(config.get("confluence", {}).get("output_dir", "./raw_data/confluence")),
            Path(config.get("jira", {}).get("output_dir", "./raw_data/jira")),
            Path(config.get("gitlab", {}).get("output_dir", "./raw_data/gitlab")),
        ]

    # 2. Сбор документов
    documents = collect_all_documents(extract_dirs)
    logger.info(f"Collected {len(documents)} documents from extractors")

    # 3. Чанкинг (если нужен)
    if not args.skip_chunk:
        chunker_config = config.get("chunking", {})
        max_tokens = _resolve_chunk_max_tokens(chunker_config, config)
        base_chunker = SemanticChunker(
            max_tokens=max_tokens,
            overlap_tokens=chunker_config.get("overlap_tokens", 200),
            min_chunk_tokens=chunker_config.get("min_chunk_tokens", 100),
        )
        enricher = MetadataEnricher(
            use_slm=chunker_config.get("use_slm", False),
            slm_endpoint=chunker_config.get("slm_endpoint"),
        )
        md_chunker = MDKeyChunker(base_chunker, enricher)
        chunks_output_dir = Path(chunker_config.get("output_dir", "./chunks"))
        quality_filter = build_chunk_quality_filter_from_config(config)
        all_chunks = run_chunking(documents, md_chunker, chunks_output_dir, quality_filter=quality_filter)
    else:
        # Загружаем уже существующие чанки
        chunks_output_dir = Path(config.get("chunking", {}).get("output_dir", "./chunks"))
        all_chunks_file = chunks_output_dir / "all_chunks.json"
        if all_chunks_file.exists():
            with open(all_chunks_file, encoding="utf-8") as f:
                all_chunks = json.load(f)
        else:
            logger.error("No chunks found and --skip-chunk is set. Exiting.")
            sys.exit(1)

    # 3.5. SLM-обогащение чанков (keywords, entities, hyde_questions, summary)
    enrichment_cfg = config.get("enrichment", {})
    if enrichment_cfg.get("enabled", False):
        all_chunks = run_enrichment(all_chunks, config)

    # 4. Граф знаний (опционально)
    if not args.skip_graph and config.get("graph", {}).get("enabled", False):
        graph_config = config.get("graph", {})
        entity_extractor = EntityRelationExtractor(
            use_spacy=graph_config.get("use_spacy", True),
            spacy_model=graph_config.get("spacy_model", "ru_core_news_sm"),
            use_slm=graph_config.get("use_slm", False),
            slm_endpoint=graph_config.get("slm_endpoint"),
            cache_dir=Path(graph_config.get("cache_dir", "./entity_cache")),
        )
        neo4j_config = graph_config.get("neo4j", {})
        if neo4j_config.get("enabled", False):
            neo4j_loader = Neo4jLoader(
                uri=neo4j_config["uri"],
                user=neo4j_config["user"],
                password=neo4j_config["password"],
                database=neo4j_config.get("database", "neo4j"),
            )
            neo4j_loader.connect()
        else:
            neo4j_loader = None
        run_graph_extraction(all_chunks, entity_extractor, neo4j_loader)
        if neo4j_loader:
            neo4j_loader.close()

    # 5. Индексация в Qdrant
    if not args.skip_index:
        index_config = config.get("indexing", {})

        embedder = build_remote_embedder_from_config(config)
        if embedder:
            logger.info("Using remote embedder: %s", embedder._embedding_url)

        qdrant_idx = QdrantHybridIndexer(
            host=index_config.get("qdrant_host", "localhost"),
            port=index_config.get("qdrant_port", 6333),
            collection_name=index_config.get("collection_name", "knowledge_base"),
            embedder_model_name=index_config.get("embedder_model", "BAAI/bge-m3"),
            embedder_device=index_config.get("embedder_device", "cpu"),
            batch_size=index_config.get("batch_size", 100),
            embedder=embedder,
        )
        qdrant_idx.create_collection(recreate=args.force_reindex)

        version_store = ChunkVersionStore(
            hot_dir=Path(index_config.get("hot_dir", "./hot_chunks")),
            cold_dir=Path(index_config.get("cold_dir", "./cold_chunks")),
            wal_path=Path(index_config.get("version_wal", "./wal/version_wal.json")),
        )
        live_lake = LiveVectorLake(
            qdrant_indexer=qdrant_idx,
            version_store=version_store,
            cold_storage_dir=Path(index_config.get("lake_dir", "./cold_lake")),
            use_delta=index_config.get("use_delta", False),
        )
        run_indexing(all_chunks, live_lake, wal)

    # 6. Post-indexing cleanup (FR-07)
    if args.cleanup_after_index:
        cleanup_result = run_cleanup(
            config,
            cleanup_after_index=True,
            dry_run=args.dry_run,
        )
        logger.info(f"Cleanup result: {cleanup_result}")

    # 7. Streaming mode (optional)
    streaming_cfg = config.get("streaming", {})
    streaming_enabled = (
        args.streaming or args.webhook_only or args.consumer_only or streaming_cfg.get("streaming_enabled", False)
    )
    live_upsert_enabled = config.get("indexing", {}).get("live_upsert_enabled", False)
    if live_upsert_enabled:
        logger.info("Live upsert enabled: atomic chunk-level updates in Qdrant")

    if streaming_enabled:
        logger.info("=== Starting streaming ETL ===")
        try:
            import redis
        except ImportError:
            logger.error("redis package not installed, streaming disabled")
            streaming_enabled = False

        if streaming_enabled:
            redis_host = os.environ.get("REDIS_HOST", streaming_cfg.get("redis_host", "localhost"))
            redis_port = int(os.environ.get("REDIS_PORT", streaming_cfg.get("redis_port", 6379)))
            stream_key = os.environ.get("REDIS_STREAM_KEY", streaming_cfg.get("redis_stream_key", "etl:events"))
            consumer_group = os.environ.get(
                "REDIS_CONSUMER_GROUP",
                streaming_cfg.get("redis_consumer_group", "etl-workers"),
            )

            try:
                rclient = redis.Redis(host=redis_host, port=redis_port, socket_connect_timeout=2)
                rclient.ping()
                logger.info("Redis connected at %s:%d", redis_host, redis_port)
            except Exception as e:
                logger.warning("Redis unavailable: %s. Falling back to batch mode.", e)
                rclient = None

            if args.webhook_only or (args.streaming and not args.consumer_only):
                from etl.scheduler.webhook_server import create_app as create_webhook_app

                webhook_secret = os.environ.get("WEBHOOK_SECRET", streaming_cfg.get("webhook_secret", ""))
                webhook_host = os.environ.get("WEBHOOK_HOST", streaming_cfg.get("webhook_host", "0.0.0.0"))
                webhook_port = int(os.environ.get("WEBHOOK_PORT", streaming_cfg.get("webhook_port", 9000)))

                webhook_app = create_webhook_app(
                    redis_client=rclient,
                    webhook_secret=webhook_secret,
                    stream_key=stream_key,
                    webhook_enabled=streaming_cfg.get("webhook_enabled", True),
                )
                logger.info("Webhook server configured on %s:%d", webhook_host, webhook_port)

                if args.webhook_only:
                    import uvicorn

                    logger.info("Starting webhook-only mode")
                    uvicorn.run(webhook_app, host=webhook_host, port=webhook_port)
                    return

            if args.consumer_only or (args.streaming and not args.webhook_only):
                from etl.scheduler.stream_consumer import StreamConsumer

                consumer = StreamConsumer(
                    redis_client=rclient,
                    stream_key=stream_key,
                    consumer_group=consumer_group,
                )
                logger.info("Starting stream consumer on stream %s", stream_key)
                if args.consumer_only:
                    consumer.run_forever()
                    return

    # 7. Quality report generation (FR-12/FR-60)
    if args.quality_report:
        logger.info("=== Generating quality report ===")
        _generate_quality_report(documents, all_chunks, config, args.quality_report)

    logger.info("ETL pipeline completed successfully")


def _generate_quality_report(
    documents: list[dict],
    all_chunks: list[dict],
    config: dict,
    output_path: Path,
) -> None:
    """Generate a structured JSON quality report with per-source breakdown.

    Aggregates:
      - OCR confidence (from quality_metrics)
      - Chunk coherence (avg/min/max tokens, chunk counts)
      - Embedding quality (model info, dimension, endpoint)
      - Per-source document and chunk counts
    """
    report: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "pipeline_summary": {},
        "per_source": {},
        "chunk_coherence": {},
        "embedding_quality": {},
    }

    # --- Per-source document counts ---
    source_doc_counts: dict[str, int] = {}
    source_chunk_counts: dict[str, int] = {}
    for doc in documents:
        st = doc.get("source_type", "unknown")
        source_doc_counts[st] = source_doc_counts.get(st, 0) + 1
    for ch in all_chunks:
        st = ch.get("source_type", ch.get("metadata", {}).get("source_type", "unknown"))
        source_chunk_counts[st] = source_chunk_counts.get(st, 0) + 1

    report["pipeline_summary"] = {
        "total_documents": len(documents),
        "total_chunks": len(all_chunks),
        "sources": sorted(source_doc_counts.keys()),
    }

    for st in sorted(set(source_doc_counts) | set(source_chunk_counts)):
        report["per_source"][st] = {
            "documents": source_doc_counts.get(st, 0),
            "chunks": source_chunk_counts.get(st, 0),
        }

    # --- Chunk coherence stats ---
    chunk_token_lengths: list[int] = []
    for ch in all_chunks:
        text = ch.get("text", "")
        if text:
            chunk_token_lengths.append(len(text.split()))
    if chunk_token_lengths:
        report["chunk_coherence"] = {
            "avg_tokens": round(sum(chunk_token_lengths) / len(chunk_token_lengths), 1),
            "min_tokens": min(chunk_token_lengths),
            "max_tokens": max(chunk_token_lengths),
            "total_chunks_with_text": len(chunk_token_lengths),
            "empty_chunks": len(all_chunks) - len(chunk_token_lengths),
        }

    # --- Embedding quality info ---
    embedder_cfg = config.get("remote_services", {}).get("embedder", {})
    if embedder_cfg:
        report["embedding_quality"] = {
            "model": embedder_cfg.get("model", "unknown"),
            "endpoint": embedder_cfg.get("endpoint", "local"),
            "dimensions": embedder_cfg.get("dimensions", 1024),
        }
    else:
        report["embedding_quality"] = {
            "model": config.get("indexing", {}).get("embedder_model", "BAAI/bge-m3"),
            "endpoint": "local",
            "dimensions": 1024,
        }

    # --- OCR and table quality (from quality_metrics module) ---
    try:
        from etl.extractors.quality_metrics import (
            compute_ocr_quality,
            compute_table_quality,
        )

        ocr_per_source: dict[str, dict] = {}
        table_per_source: dict[str, dict] = {}
        for doc in documents:
            st = doc.get("source_type", "unknown")
            tables = doc.get("metadata", {}).get("tables", [])
            ocr_results = doc.get("metadata", {}).get("ocr_results", [])

            if tables or ocr_results:
                ocr = compute_ocr_quality(ocr_results if isinstance(ocr_results, list) else [])
                tbl = compute_table_quality(tables if isinstance(tables, list) else [])

                if st not in ocr_per_source:
                    ocr_per_source[st] = {"page_count": 0, "total_chars": 0, "confidences": []}
                if st not in table_per_source:
                    table_per_source[st] = {"total_tables": 0, "tables_with_rows": 0, "accuracy": []}

                if ocr.page_count > 0:
                    ocr_per_source[st]["page_count"] += ocr.page_count
                    ocr_per_source[st]["total_chars"] += ocr.total_chars
                    ocr_per_source[st]["confidences"].append(ocr.avg_confidence)
                if tbl.total_tables > 0:
                    table_per_source[st]["total_tables"] += tbl.total_tables
                    table_per_source[st]["tables_with_rows"] += tbl.tables_with_rows
                    table_per_source[st]["accuracy"].append(tbl.estimated_accuracy)

        if ocr_per_source:
            report["ocr_quality"] = {}
            for st, data in ocr_per_source.items():
                confs = data["confidences"]
                report["ocr_quality"][st] = {
                    "pages": data["page_count"],
                    "avg_confidence": round(sum(confs) / len(confs), 2) if confs else 0.0,
                    "total_chars": data["total_chars"],
                }

        if table_per_source:
            report["table_quality"] = {}
            for st, data in table_per_source.items():
                accs = data["accuracy"]
                report["table_quality"][st] = {
                    "total_tables": data["total_tables"],
                    "tables_with_rows": data["tables_with_rows"],
                    "avg_accuracy": round(sum(accs) / len(accs), 2) if accs else 0.0,
                }
    except ImportError:
        logger.debug("quality_metrics module not available, skipping OCR/table quality in report")

    # --- Write the report ---
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    logger.info("Quality report saved: %s", output_path)


if __name__ == "__main__":
    main()
