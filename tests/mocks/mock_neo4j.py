"""In-memory Neo4j mock for testing graph features without a real database.

Provides a minimal ``MockAsyncDriver`` that implements the subset of the
async Neo4j Python driver used by the ETL graph builder and proxy retrieval:

* ``driver.session(database=...)`` returns an async context manager.
* ``session.run(query, **params)`` returns a ``MockResult`` whose
  ``.single()`` is awaitable (real driver returns an awaitable result),
  so existing call sites ``await session.run(...).single()`` work
  without modification.
* ``MockGraphStore.execute()`` dispatches simple Cypher fragments
  (MERGE, MATCH, CREATE, DELETE, RETURN COUNT) used by the ETL
  graph-builder, ``cleanup_stale_entities``, and the proxy's
  ``graph_expand_query``.
"""

from __future__ import annotations

import contextlib
from typing import Any


class MockNode:
    """Lightweight stand-in for a Neo4j node record."""

    def __init__(
        self,
        id: str,
        labels: list[str],
        properties: dict[str, Any],
    ) -> None:
        self.id = id
        self.labels = labels
        self.properties = properties

    def __getitem__(self, key: str) -> Any:
        return self.properties.get(key)

    def get(self, key: str, default: Any = None) -> Any:
        return self.properties.get(key, default)


class MockRelationship:
    """Lightweight stand-in for a Neo4j relationship record."""

    def __init__(
        self,
        id: str,
        type: str,
        start_node: MockNode,
        end_node: MockNode,
        properties: dict[str, Any],
    ) -> None:
        self.id = id
        self.type = type
        self.start_node = start_node
        self.end_node = end_node
        self.properties = properties

    def __getitem__(self, key: str) -> Any:
        return self.properties.get(key)


class MockResult:
    """Result set returned from ``MockSession.run``.

    ``.single()`` is awaitable to match the real async Neo4j driver.
    Iteration yields each record (a dict-like object).
    """

    def __init__(self, records: list[Any]) -> None:
        self.records = records

    async def single(self) -> Any:
        return self.records[0] if self.records else None

    def __iter__(self):
        return iter(self.records)

    def data(self) -> list[dict[str, Any]]:
        return [dict(r) if not isinstance(r, dict) else r for r in self.records]


class MockSession:
    """Async-context-manager session that dispatches to ``MockGraphStore``."""

    def __init__(self, store: MockGraphStore, database: str = "neo4j") -> None:
        self.store = store
        self.database = database

    async def __aenter__(self) -> MockSession:
        return self

    async def __aexit__(self, *_args: Any) -> None:
        return None

    async def run(self, query: str, **params: Any) -> MockResult:
        return MockResult(self.store.execute(query, params))

    async def close(self) -> None:
        return None


class MockGraphStore:
    """Minimal in-memory graph store used by ``MockAsyncDriver``.

    The store understands a tiny subset of Cypher (MERGE / MATCH / CREATE /
    DELETE / RETURN COUNT) sufficient for unit-testing the graph builder,
    retention policy, and graph_expand_query.
    """

    def __init__(self) -> None:
        self.nodes: dict[str, MockNode] = {}
        self.relationships: list[MockRelationship] = []
        self.next_id = 0

    def execute(self, query: str, params: dict[str, Any]) -> list[Any]:
        q = query.strip().upper()
        # Order matters: handle RETURN COUNT before generic MATCH, and
        # DETACH/DELETE-bearing MATCH before plain MATCH, so the
        # retention-policy and graph-stats queries get routed correctly.
        if "RETURN COUNT" in q:
            return self._count(query, params)
        if q.startswith("MERGE"):
            return self._merge(query, params)
        if q.startswith("MATCH") and "DELETE" in q:
            return self._delete(query, params)
        if q.startswith("MATCH"):
            return self._match(query, params)
        if q.startswith("CREATE"):
            return self._create(query, params)
        return []

    def _filter_by_threshold(self, params: dict[str, Any]) -> dict[str, MockNode]:
        """Return a view of ``self.nodes`` filtered by ``updated_at < threshold``.

        Used by the retention-policy queries to compute counts without
        actually mutating the store. Returns the full node map when no
        ``threshold`` parameter is supplied.
        """
        threshold = params.get("threshold", "")
        if not threshold:
            return dict(self.nodes)
        return {nid: node for nid, node in self.nodes.items() if node.get("updated_at", "") < threshold}

    def _count(self, _query: str, params: dict[str, Any]) -> list[dict[str, int]]:
        filtered = self._filter_by_threshold(params)
        return [{"count": len(filtered)}]

    def _merge(self, _query: str, params: dict[str, Any]) -> list[MockNode]:
        # Filter out internal param keys (those starting with ``_``).
        properties = {k: v for k, v in params.items() if not k.startswith("_")}
        node = MockNode(
            id=str(self.next_id),
            labels=["Entity"],
            properties=properties,
        )
        self.next_id += 1
        self.nodes[node.id] = node
        return [node]

    def _match(self, _query: str, params: dict[str, Any]) -> list[MockNode]:
        return list(self._filter_by_threshold(params).values())

    def _create(self, _query: str, _params: dict[str, Any]) -> list[Any]:
        return []

    def _delete(self, _query: str, params: dict[str, Any]) -> list[dict[str, int]]:
        threshold = params.get("threshold", "")
        stale_ids = [nid for nid, node in self.nodes.items() if node.get("updated_at", "") < threshold]
        for nid in stale_ids:
            with contextlib.suppress(KeyError):
                del self.nodes[nid]
        return [{"count": len(stale_ids)}]


class MockAsyncDriver:
    """Async-compatible Neo4j driver mock.

    Drop-in replacement for the real ``neo4j.AsyncGraphDatabase.driver``
    for tests: exposes ``session(database=...)`` returning an async
    context manager and a ``close()`` coroutine.
    """

    def __init__(self) -> None:
        self.store = MockGraphStore()

    def session(self, database: str = "neo4j") -> MockSession:
        return MockSession(self.store, database=database)

    async def close(self) -> None:
        return None


__all__ = [
    "MockAsyncDriver",
    "MockGraphStore",
    "MockNode",
    "MockRelationship",
    "MockResult",
    "MockSession",
]
