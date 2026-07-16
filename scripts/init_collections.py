#!/usr/bin/env python3
# scripts/init_collections.py
"""Скрипт для инициализации коллекций в Qdrant и Neo4j.
Создаёт коллекцию с поддержкой dense и sparse векторов,
а также индексы и ограничения в графовой базе (опционально).
"""

import argparse
import logging
import sys
from pathlib import Path

# Добавляем путь к корню проекта для импорта модулей
sys.path.insert(0, str(Path(__file__).parent.parent))

from proxy.app.config import (
    COLLECTION_NAME,
    GRAPH_ENABLED,
    NEO4J_PASSWORD,
    NEO4J_URI,
    NEO4J_USER,
    QDRANT_HOST,
    QDRANT_PORT,
)

from etl.graph_builder.neo4j_loader import NEO4J_AVAILABLE, Neo4jLoader
from etl.indexer.qdrant_hybrid import QdrantHybridIndexer

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def init_qdrant(recreate: bool = False):
    """Инициализирует коллекцию Qdrant."""
    logger.info(f"Initializing Qdrant collection '{COLLECTION_NAME}' (recreate={recreate})")
    indexer = QdrantHybridIndexer(host=QDRANT_HOST, port=QDRANT_PORT, collection_name=COLLECTION_NAME)
    # Проверяем, существует ли коллекция
    exists = indexer.collection_exists()
    if exists and recreate:
        logger.info(f"Deleting existing collection {COLLECTION_NAME}")
        indexer.delete_collection()
        exists = False
    if not exists:
        indexer.create_collection()
        logger.info(f"Collection {COLLECTION_NAME} created")
    else:
        logger.info(f"Collection {COLLECTION_NAME} already exists")
    # Выводим информацию о коллекции
    info = indexer.get_collection_info()
    logger.info(f"Collection info: points_count={info.points_count}, status={info.status}")


def init_neo4j():
    """Инициализирует ограничения и индексы в Neo4j (если граф включён)."""
    if not GRAPH_ENABLED:
        logger.info("Graph disabled, skipping Neo4j initialization")
        return
    if not NEO4J_AVAILABLE:
        logger.warning("Neo4j driver not installed, skipping")
        return
    logger.info("Initializing Neo4j constraints and indexes")
    loader = Neo4jLoader(uri=NEO4J_URI, user=NEO4J_USER, password=NEO4J_PASSWORD)
    loader.connect()
    try:
        loader.create_constraints_and_indexes()
        logger.info("Neo4j constraints and indexes created")
        # Дополнительно можно создать ограничения уникальности для конкретных меток
        with loader.driver.session(database=loader.database) as session:
            # Проверяем существование ограничений
            result = session.run("SHOW CONSTRAINTS")
            constraints = list(result)
            logger.info(f"Existing constraints: {len(constraints)}")
    except Exception as e:
        logger.error(f"Failed to initialize Neo4j: {e}")
    finally:
        loader.close()


def main():
    parser = argparse.ArgumentParser(description="Initialize RAG system collections")
    parser.add_argument("--qdrant-recreate", action="store_true", help="Recreate Qdrant collection (delete existing)")
    parser.add_argument("--skip-qdrant", action="store_true", help="Skip Qdrant initialization")
    parser.add_argument("--skip-neo4j", action="store_true", help="Skip Neo4j initialization")
    args = parser.parse_args()

    if not args.skip_qdrant:
        init_qdrant(recreate=args.qdrant_recreate)
    if not args.skip_neo4j:
        init_neo4j()

    logger.info("Initialization complete")


if __name__ == "__main__":
    main()
