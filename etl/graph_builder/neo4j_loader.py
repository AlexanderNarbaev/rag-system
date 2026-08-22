# etl/graph_builder/neo4j_loader.py
"""Knowledge graph loading into Neo4j.
Uses the official Neo4j driver.
Supports:
- Batch loading of nodes and edges
- Incremental updates (MERGE)
- Index and uniqueness constraint creation
- Stale relationship cleanup
"""

import contextlib
import logging
import time
from typing import Any

try:
    from neo4j import Driver, GraphDatabase

    NEO4J_AVAILABLE = True
except ImportError:
    NEO4J_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class Neo4jLoader:
    """Knowledge graph loader for Neo4j."""

    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        database: str = "neo4j",
        batch_size: int = 500,
        max_retries: int = 3,
    ):
        """:param uri: Neo4j URI (bolt://localhost:7687)
        :param user: username
        :param password: password
        :param database: database name
        :param batch_size: batch size for transactions
        :param max_retries: number of retry attempts on failure
        """
        if not NEO4J_AVAILABLE:
            raise ImportError("neo4j driver is required. Install: pip install neo4j")

        self.uri = uri
        self.user = user
        self.password = password
        self.database = database
        self.batch_size = batch_size
        self.max_retries = max_retries
        self.driver: Driver | None = None

    def connect(self):
        """Establishes a connection to Neo4j with retry logic and exponential backoff."""
        base_delay = 2
        for attempt in range(self.max_retries):
            try:
                self.driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
                self.driver.verify_connectivity()
                logger.info(f"Connected to Neo4j at {self.uri}")
                return
            except Exception as e:
                logger.warning(f"Neo4j connection attempt {attempt + 1}/{self.max_retries} failed: {e}")
                if self.driver:
                    with contextlib.suppress(Exception):
                        self.driver.close()
                    self.driver = None
                if attempt < self.max_retries - 1:
                    delay = base_delay * (2**attempt)
                    logger.info(f"Retrying Neo4j connection in {delay}s...")
                    time.sleep(delay)
                else:
                    logger.error(f"Failed to connect to Neo4j at {self.uri} after {self.max_retries} attempts")
                    raise

    def close(self):
        """Closes the connection."""
        if self.driver:
            self.driver.close()
            logger.info("Neo4j connection closed")

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _execute_with_retry(self, query: str, parameters: dict[str, Any] | None = None) -> bool:
        """Executes a query with retries on transient errors (with exponential backoff)."""
        if not self.driver:
            raise RuntimeError("Not connected to Neo4j")

        base_delay = 1
        for attempt in range(self.max_retries):
            try:
                with self.driver.session(database=self.database) as session:
                    logger.warning(f"Query: {query}\n Parameters: {parameters}")
                    result = session.run(query, parameters or {})
                    summary = result.consume()
                    return summary.counters.contains_updates
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1}/{self.max_retries} failed: {e}")
                if attempt < self.max_retries - 1:
                    delay = base_delay * (2**attempt)
                    logger.info(f"Retrying in {delay}s...")
                    time.sleep(delay)
                else:
                    raise
        return False

    def create_constraints_and_indexes(self):
        """Creates the necessary constraints and indexes for optimal performance.
        Runs once at initialization.
        """
        constraints = [
            "CREATE CONSTRAINT IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (p:Person) REQUIRE p.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (o:Organization) REQUIRE o.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (t:Technology) REQUIRE t.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (prod:Product) REQUIRE prod.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (loc:Location) REQUIRE loc.id IS UNIQUE",
        ]
        indexes = [
            "CREATE INDEX IF NOT EXISTS FOR (e:Entity) ON (e.name)",
            "CREATE INDEX IF NOT EXISTS FOR (e:Entity) ON (e.source_id)",
            "CREATE INDEX IF NOT EXISTS FOR (e:Entity) ON (e.type)",
            "CREATE INDEX IF NOT EXISTS FOR ()-[r:RELATES_TO]-() ON (r.type)",
        ]
        for query in constraints + indexes:
            try:
                self._execute_with_retry(query)
                logger.debug(f"Executed: {query[:60]}...")
            except Exception as e:
                logger.warning(f"Failed to create constraint/index: {e}")

    def load_entities(self, entities: list[dict]) -> int:
        """Loads a batch of entities into Neo4j.
        Each entity must have the fields: id, name, type, source_id, properties (dict)
        Returns the number of processed nodes.
        """
        if not entities:
            return 0

        # Split into batches
        total = 0
        for i in range(0, len(entities), self.batch_size):
            batch = entities[i : i + self.batch_size]
            query = """
            UNWIND $batch AS entity
            MERGE (n:Entity {id: entity.id})
            SET n.name = entity.name,
                n.type = entity.type,
                n.source_id = entity.source_id,
                n.properties = entity.properties,
                n.updated_at = datetime()
            // Add an extra label for the specific type (to speed up lookups)
            FOREACH(ignoreMe IN CASE WHEN entity.type = 'PERSON' THEN [1] ELSE [] END |
                SET n:Person
            )
            FOREACH(ignoreMe IN CASE WHEN entity.type = 'ORGANIZATION' THEN [1] ELSE [] END |
                SET n:Organization
            )
            FOREACH(ignoreMe IN CASE WHEN entity.type = 'TECHNOLOGY' THEN [1] ELSE [] END |
                SET n:Technology
            )
            FOREACH(ignoreMe IN CASE WHEN entity.type = 'PRODUCT' THEN [1] ELSE [] END |
                SET n:Product
            )
            FOREACH(ignoreMe IN CASE WHEN entity.type = 'LOCATION' THEN [1] ELSE [] END |
                SET n:Location
            )
            RETURN count(n) as created
            """
            params = {"batch": batch}
            try:
                self._execute_with_retry(query, params)
                total += len(batch)
                logger.debug(f"Loaded {len(batch)} entities")
            except Exception as e:
                logger.error(f"Failed to load entity batch: {e}")
                raise
        return total

    def load_relations(self, relations: list[dict]) -> int:
        """Loads a batch of relations.
        Each relation must contain: source, target, type, properties (dict)
        Returns the number of processed edges.
        """
        if not relations:
            return 0

        total = 0
        for i in range(0, len(relations), self.batch_size):
            batch = relations[i : i + self.batch_size]
            query = """
            UNWIND $batch AS rel
            MATCH (a {id: rel.source})
            MATCH (b {id: rel.target})
            CALL apoc.merge.relationship(a, rel.type, {}, rel.properties, b) YIELD rel as r
            RETURN count(r) as created
            """
            # If APOC is not installed, use MERGE
            fallback_query = """
            UNWIND $batch AS rel
            MATCH (a {id: rel.source})
            MATCH (b {id: rel.target})
            MERGE (a)-[r:RELATES_TO {type: rel.type}]->(b)
            SET r += rel.properties,
                r.updated_at = datetime()
            RETURN count(r) as created
            """
            params = {"batch": batch}
            try:
                # Try APOC first
                self._execute_with_retry(query, params)
            except Exception:
                # Use standard MERGE
                try:
                    self._execute_with_retry(fallback_query, params)
                except Exception as e:
                    logger.error(f"Failed to load relation batch: {e}")
                    raise
            total += len(batch)
            logger.debug(f"Loaded {len(batch)} relations")
        return total

    def delete_outdated_entities(self, valid_source_ids: list[str]):
        """Deletes entities that no longer appear in current sources.
        source_id - identifiers of documents/partial sources that were processed.
        All nodes whose source_id is not in valid_source_ids are deleted.
        """
        if not valid_source_ids:
            logger.warning("No valid source ids provided, skipping deletion")
            return 0

        if not self.driver:
            raise RuntimeError("Not connected to Neo4j")

        query = """
        MATCH (n:Entity)
        WHERE n.source_id IS NOT NULL AND NOT n.source_id IN $valid_ids
        DETACH DELETE n
        RETURN count(n) as deleted
        """
        params = {"valid_ids": valid_source_ids}
        base_delay = 1
        for attempt in range(self.max_retries):
            try:
                with self.driver.session(database=self.database) as session:
                    record = session.run(query, params).single()
                    deleted_count = record["deleted"] if record else 0
                logger.info(f"Deleted {deleted_count} outdated entities")
                return deleted_count
            except Exception as e:
                logger.warning(f"delete_outdated_entities attempt {attempt + 1}/{self.max_retries} failed: {e}")
                if attempt < self.max_retries - 1:
                    delay = base_delay * (2**attempt)
                    logger.info(f"Retrying in {delay}s...")
                    time.sleep(delay)
                else:
                    raise
        return 0

    def delete_outdated_relations(self, max_age_days: int = 30):
        """Deletes relations that have not been updated for more than max_age_days (optional)."""
        if not self.driver:
            raise RuntimeError("Not connected to Neo4j")

        query = """
        MATCH ()-[r:RELATES_TO]->()
        WHERE r.updated_at IS NULL OR r.updated_at < datetime() - duration({days: $max_age_days})
        DELETE r
        RETURN count(r) as deleted
        """
        params = {"max_age_days": max_age_days}
        base_delay = 1
        for attempt in range(self.max_retries):
            try:
                with self.driver.session(database=self.database) as session:
                    result = session.run(query, params)
                    deleted_count = result.single()["deleted"]
                logger.info(f"Deleted {deleted_count} outdated relations")
                return deleted_count
            except Exception as e:
                logger.warning(f"delete_outdated_relations attempt {attempt + 1}/{self.max_retries} failed: {e}")
                if attempt < self.max_retries - 1:
                    delay = base_delay * (2**attempt)
                    logger.info(f"Retrying in {delay}s...")
                    time.sleep(delay)
                else:
                    raise
        return 0

    def get_graph_statistics(self) -> dict[str, int]:
        """Returns graph statistics: node, edge, and entity type counts."""
        if not self.driver:
            raise RuntimeError("Not connected to Neo4j")

        query = """
        MATCH (n:Entity)
        WITH labels(n) as labels, count(n) as nodes
        RETURN sum(nodes) as total_nodes,
               [l in collect(DISTINCT labels) | l] as labels
        """
        base_delay = 1
        for attempt in range(self.max_retries):
            try:
                with self.driver.session(database=self.database) as session:
                    result = session.run(query).single()
                    total_nodes = result["total_nodes"] if result else 0

                query_rels = "MATCH ()-[r]->() RETURN count(r) as total_rels"
                with self.driver.session(database=self.database) as session:
                    result = session.run(query_rels).single()
                    total_rels = result["total_rels"] if result else 0

                return {"nodes": total_nodes, "relations": total_rels}
            except Exception as e:
                logger.warning(f"get_graph_statistics attempt {attempt + 1}/{self.max_retries} failed: {e}")
                if attempt < self.max_retries - 1:
                    delay = base_delay * (2**attempt)
                    logger.info(f"Retrying in {delay}s...")
                    time.sleep(delay)
                else:
                    raise
        return {"nodes": 0, "relations": 0}


def batch_load_from_extractor(
    loader: Neo4jLoader,
    entities: list[dict],
    relations: list[dict],
    clear_old: bool = False,
    valid_source_ids: list[str] = None,
):
    """Convenience function for loading entities and relations from the extractor.
    :param loader: Neo4jLoader instance
    :param entities: list of dicts with fields id, name, type, source_id, properties
    :param relations: list of dicts with fields source, target, type, properties
    :param clear_old: whether to delete stale entities (not in valid_source_ids)
    :param valid_source_ids: list of current source_id values for cleanup
    """
    # Create indexes and constraints (once)
    loader.create_constraints_and_indexes()

    # Load entities
    entities_loaded = loader.load_entities(entities)
    logger.info(f"Loaded {entities_loaded} entities")

    # Load relations
    relations_loaded = loader.load_relations(relations)
    logger.info(f"Loaded {relations_loaded} relations")

    # Optional cleanup
    if clear_old and valid_source_ids:
        loader.delete_outdated_entities(valid_source_ids)

    # Print statistics
    stats = loader.get_graph_statistics()
    logger.info(f"Graph stats: {stats['nodes']} nodes, {stats['relations']} relations")


if __name__ == "__main__":
    # Usage example
    config = {"uri": "bolt://localhost:7687", "user": "neo4j", "password": "password", "database": "neo4j"}
    # Example entities and relations (from entity_extractor)
    sample_entities = [
        {
            "id": "abc123",
            "name": "Иван Иванов",
            "type": "PERSON",
            "source_id": "confluence_123",
            "properties": {"role": "developer"},
        },
        {
            "id": "def456",
            "name": "PROJ-123",
            "type": "PRODUCT",
            "source_id": "jira_456",
            "properties": {"status": "active"},
        },
    ]
    sample_relations = [
        {"source": "abc123", "target": "def456", "type": "WORKS_ON", "properties": {"since": "2025-01-01"}},
    ]

    with Neo4jLoader(**config) as loader:  # type: ignore[arg-type]
        batch_load_from_extractor(loader, sample_entities, sample_relations, clear_old=False)
        stats = loader.get_graph_statistics()
        print("Final stats:", stats)
