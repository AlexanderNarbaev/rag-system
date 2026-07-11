#!/usr/bin/env python3
# etl/scheduler/run_etl.py
"""
Главный оркестратор ETL-пайплайна для RAG-системы.
Запускает все этапы:
1. Extract: Confluence, Jira, GitLab
2. Chunking: семантическая нарезка документов
3. Graph: извлечение сущностей и отношений (опционально)
4. Index: индексация в Qdrant (гибридная, с версионированием)
5. Neo4j: загрузка графа (опционально)

Использует единый WAL для инкрементальных запусков.
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import yaml

# Добавляем корень проекта в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Импорт модулей ETL
from etl.chunker.hash_versioning import ChunkVersionStore
from etl.chunker.semantic_chunker import MDKeyChunker, MetadataEnricher, SemanticChunker
from etl.extractors.confluence import ConfluenceExtractor
from etl.extractors.gitlab import GitLabExtractor
from etl.extractors.jira import JiraExtractor
from etl.graph_builder.entity_extractor import EntityRelationExtractor
from etl.graph_builder.neo4j_loader import Neo4jLoader
from etl.indexer.live_vector_lake import LiveVectorLake
from etl.indexer.qdrant_hybrid import QdrantHybridIndexer
from etl.indexer.wal_manager import (
    PIPELINE_CONFLUENCE,
    PIPELINE_GITLAB,
    PIPELINE_INDEXING,
    PIPELINE_JIRA,
    WALManager,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("ETL Orchestrator")


def load_config(config_path: Path) -> dict[str, Any]:
    """Загружает YAML-конфигурацию."""
    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config


def run_extract_confluence(config: dict, wal: WALManager) -> Path:
    """Запускает выгрузку Confluence, возвращает директорию с сырыми данными."""
    logger.info("=== Starting Confluence extraction ===")
    confluence_config = config.get("confluence", {})
    # Добавляем WAL параметры
    confluence_config["wal_file"] = str(wal.wal_path)  # используем единый WAL
    confluence_config["incremental"] = True
    extractor = ConfluenceExtractor(confluence_config)
    extractor.run()
    wal.update_last_run(PIPELINE_CONFLUENCE)
    output_dir = Path(confluence_config.get("output_dir", "./raw_data/confluence"))
    logger.info(f"Confluence extraction completed. Data in {output_dir}")
    return output_dir


def run_extract_jira(config: dict, wal: WALManager) -> Path:
    """Запускает выгрузку Jira."""
    logger.info("=== Starting Jira extraction ===")
    jira_config = config.get("jira", {})
    # Инкрементальный режим через WAL
    last_run = wal.get_last_run(PIPELINE_JIRA)
    if last_run and not jira_config.get("since_date"):
        jira_config["since_date"] = last_run
        logger.info(f"Using incremental since_date: {last_run}")
    jira_config["incremental"] = True
    jira_config["wal_file"] = str(wal.wal_path)
    extractor = JiraExtractor(jira_config)
    extractor.run()
    # Обновляем WAL
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
    extractor.run()
    wal.update_last_run(PIPELINE_GITLAB)
    output_dir = Path(gitlab_config.get("output_dir", "./raw_data/gitlab"))
    return output_dir


def collect_all_documents(extract_dirs: list[Path]) -> list[dict]:
    """
    Собирает все извлечённые документы из директорий extractors.
    Ожидает структуру:
      - для Confluence: <page_id>/page.json
      - для Jira: <issue_key>/issue.json
      - для GitLab: <project_id>/commits.json, merge_requests.json, files/*.txt
    Возвращает список документов с полями: id, source_type, title, content (html/markdown), metadata.
    """
    documents = []
    # Confluence
    for conflu_dir in extract_dirs[0].glob("*"):
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
                        "created_at": data.get("created_at", ""),
                        "updated_at": data.get("updated_at", ""),
                        "url": f"{conflu_dir.name}",
                    },
                }
            )
    # Jira
    for jira_dir in extract_dirs[1].glob("*"):
        if not jira_dir.is_dir():
            continue
        issue_file = jira_dir / "issue.json"
        if issue_file.exists():
            with open(issue_file, encoding="utf-8") as f:
                data = json.load(f)
            # Формируем контент из описания и комментариев
            content = data.get("description", "")
            for comment in data.get("comments", []):
                content += f"\n\nComment by {comment['author']}: {comment['body']}"
            documents.append(
                {
                    "id": f"jira_{data['key']}",
                    "source_type": "jira",
                    "title": data.get("summary", ""),
                    "content": content,
                    "content_type": "html",  # Jira description может быть HTML
                    "metadata": {
                        "key": data["key"],
                        "status": data.get("status", ""),
                        "priority": data.get("priority", ""),
                        "assignee": data.get("assignee", ""),
                        "created": data.get("created", ""),
                        "updated": data.get("updated", ""),
                    },
                }
            )
    # GitLab: коммиты, MR, файлы
    for gitlab_dir in extract_dirs[2].glob("*"):
        if not gitlab_dir.is_dir():
            continue
        commits_file = gitlab_dir / "commits.json"
        if commits_file.exists():
            with open(commits_file, encoding="utf-8") as f:
                commits = json.load(f)
            for commit in commits[:100]:  # ограничим для примера
                content = commit.get("message", "")
                # Добавим diff кратко
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
                        },
                    }
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
                        },
                    }
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
                        "metadata": {"path": code_file.stem},
                    }
                )
    return documents


def run_chunking(documents: list[dict], chunker: MDKeyChunker, output_dir: Path):
    """Выполняет семантический чанкинг всех документов и сохраняет чанки в JSON."""
    output_dir.mkdir(parents=True, exist_ok=True)
    all_chunks = []
    for doc in documents:
        source_metadata = {
            "source_type": doc["source_type"],
            "source_id": doc["id"],
            "version": doc["metadata"].get("version", "latest"),
            "doc_title": doc["title"],
        }
        try:
            chunks = chunker.process_document(doc["content"], doc["content_type"], source_metadata)
            # Конвертируем Chunk объекты в словари
            chunk_dicts = [ch.__dict__ for ch in chunks]
            # Сохраняем чанки этого документа в отдельный JSON
            doc_chunk_file = output_dir / f"{doc['id'].replace('/', '_')}.json"
            with open(doc_chunk_file, "w", encoding="utf-8") as f:
                json.dump(chunk_dicts, f, ensure_ascii=False, indent=2)
            all_chunks.extend(chunk_dicts)
            logger.info(f"Chunked {doc['id']} -> {len(chunks)} chunks")
        except Exception as e:
            logger.error(f"Failed to chunk {doc['id']}: {e}")
    # Сохраняем все чанки в один файл (опционально)
    all_chunks_file = output_dir / "all_chunks.json"
    with open(all_chunks_file, "w", encoding="utf-8") as f:
        json.dump(all_chunks, f, ensure_ascii=False, indent=2)
    logger.info(f"Total chunks created: {len(all_chunks)}")
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
            {"text": ch["text"], "source_id": ch.get("source_id", "unknown"), "metadata": ch.get("metadata", {})}
        )
    entities, relations = entity_extractor.extract_batch(chunk_inputs)
    logger.info(f"Extracted {len(entities)} entities and {len(relations)} relations")
    if neo4j_loader and (entities or relations):
        # Конвертируем в формат для загрузчика
        entity_dicts = [e.__dict__ for e in entities]
        relation_dicts = [r.__dict__ for r in relations]
        # Удаляем лишние поля
        for e in entity_dicts:
            e.pop("source_id", None)
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
    for doc_id, doc_chunks_list in doc_chunks.items():
        added, deleted = live_lake.sync_document(doc_id, doc_chunks_list)
        total_added += added
        total_deleted += deleted
    # Обновляем WAL индексации
    wal.update_last_run(PIPELINE_INDEXING)
    wal.set_checkpoint(PIPELINE_INDEXING, {"added": total_added, "deleted": total_deleted})
    logger.info(f"Indexing completed: added {total_added}, deleted {total_deleted}")


def main():
    parser = argparse.ArgumentParser(description="RAG ETL Pipeline Orchestrator")
    parser.add_argument("--config", type=Path, default=Path("etl_config.yaml"), help="Path to YAML config")
    parser.add_argument("--timeout", type=int, default=None, help="Request timeout in seconds (overrides config)")
    parser.add_argument("--test-connection", action="store_true", help="Test connection to all sources and exit")
    parser.add_argument("--skip-extract", action="store_true", help="Skip extraction phase")
    parser.add_argument("--skip-chunk", action="store_true", help="Skip chunking phase")
    parser.add_argument("--skip-graph", action="store_true", help="Skip graph building phase")
    parser.add_argument("--skip-index", action="store_true", help="Skip indexing phase")
    parser.add_argument("--force-reindex", action="store_true", help="Force reindex all documents (ignore WAL)")
    parser.add_argument("--reset-wal", action="store_true", help="Reset all WAL checkpoints before run")
    parser.add_argument(
        "--streaming", action="store_true", help="Start streaming ETL (webhook + consumer) alongside batch"
    )  # noqa: E501
    parser.add_argument("--webhook-only", action="store_true", help="Start only webhook server")
    parser.add_argument("--consumer-only", action="store_true", help="Start only stream consumer")
    args = parser.parse_args()

    # Загрузка конфигурации
    config = load_config(args.config)

    # Override timeout from command line
    if args.timeout is not None:
        for source in ["confluence", "jira", "gitlab"]:
            if source in config:
                config[source]["timeout"] = args.timeout
        logger.info(f"Timeout overridden to {args.timeout}s")

    # Test connection mode
    if args.test_connection:
        logger.info("=== Testing connections ===")
        results = {}

        # Test Confluence
        confluence_config = config.get("confluence", {})
        if confluence_config.get("url"):
            try:
                from etl.extractors.confluence import ConfluenceExtractor
                extractor = ConfluenceExtractor(confluence_config)
                results["confluence"] = extractor.test_connection()
            except Exception as e:
                logger.error(f"Confluence: {e}")
                results["confluence"] = False

        # Test Jira
        jira_config = config.get("jira", {})
        if jira_config.get("url"):
            try:
                from etl.extractors.jira import JiraExtractor
                extractor = JiraExtractor(jira_config)
                logger.info(f"Testing Jira connection to {jira_config['url']}...")
                resp = extractor._request("/rest/api/2/myself")
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
                extractor = GitLabExtractor(gitlab_config)
                logger.info(f"Testing GitLab connection to {gitlab_config['url']}...")
                resp = extractor._request("/api/v4/user")
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

    # 1. Извлечение
    extract_dirs = []
    if not args.skip_extract:
        extract_dirs.append(run_extract_confluence(config, wal))
        extract_dirs.append(run_extract_jira(config, wal))
        extract_dirs.append(run_extract_gitlab(config, wal))
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
        base_chunker = SemanticChunker(
            max_tokens=chunker_config.get("max_tokens", 8000),
            overlap_tokens=chunker_config.get("overlap_tokens", 200),
            min_chunk_tokens=chunker_config.get("min_chunk_tokens", 100),
        )
        enricher = MetadataEnricher(
            use_slm=chunker_config.get("use_slm", False), slm_endpoint=chunker_config.get("slm_endpoint")
        )
        md_chunker = MDKeyChunker(base_chunker, enricher)
        chunks_output_dir = Path(chunker_config.get("output_dir", "./chunks"))
        all_chunks = run_chunking(documents, md_chunker, chunks_output_dir)
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
        qdrant_idx = QdrantHybridIndexer(
            host=index_config.get("qdrant_host", "localhost"),
            port=index_config.get("qdrant_port", 6333),
            collection_name=index_config.get("collection_name", "knowledge_base"),
            embedder_model_name=index_config.get("embedder_model", "BAAI/bge-m3"),
            embedder_device=index_config.get("embedder_device", "cpu"),
            batch_size=index_config.get("batch_size", 100),
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

    # 6. Streaming mode (optional)
    streaming_cfg = config.get("streaming", {})
    streaming_enabled = (
        args.streaming or args.webhook_only or args.consumer_only or streaming_cfg.get("streaming_enabled", False)
    )
    live_upsert_enabled = index_config.get("live_upsert_enabled", False)
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
                "REDIS_CONSUMER_GROUP", streaming_cfg.get("redis_consumer_group", "etl-workers")
            )  # noqa: E501

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

    logger.info("ETL pipeline completed successfully")


if __name__ == "__main__":
    main()
