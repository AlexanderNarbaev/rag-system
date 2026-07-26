# tests/mocks/mock_langgraph.py
"""In-memory mock for LangGraph StateGraph.

Provides ``MockStateGraph`` and ``MockCompiledGraph`` classes that mimic the
public surface of the real ``langgraph.graph.StateGraph`` and its compiled
output, allowing unit and integration tests to exercise the RAG orchestrator's
agentic pipeline without requiring a real LangGraph installation.

The mock supports:
- Node registration via ``add_node(name, func)``
- Direct edges via ``add_edge(from_node, to_node)``
- Conditional edges via ``add_conditional_edges(from_node, condition, mapping)``
- Entry point via ``set_entry_point(name)``
- Asynchronous execution via the compiled graph's ``ainvoke(state, config)``

Notes
-----
* Node functions may be either sync or async; the runtime awaits coroutines
  and returns plain values directly.
* Conditional routing functions are expected to return a key whose value is
  looked up in the ``mapping`` dict. The sentinel value ``"END"`` (or its
  equivalent falsy result) terminates execution.
* The loop is bounded by ``max_steps`` to prevent infinite cycles caused by
  buggy graphs during tests.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any


class MockStateGraph:
    """In-memory stand-in for ``langgraph.graph.StateGraph``.

    Records all node/edge/entry-point registrations and produces a
    :class:`MockCompiledGraph` when :meth:`compile` is invoked.
    """

    def __init__(self, state_schema: Any = None) -> None:
        # ``state_schema`` mirrors the real LangGraph API which accepts a
        # TypedDict (or callable) describing the graph state shape. The
        # mock does not enforce types but records the value for completeness.
        self.state_schema = state_schema
        self.nodes: dict[str, Callable] = {}
        self.edges: dict[str, list[str]] = {}
        self.entry_point: str | None = None
        self.conditional_edges: dict[str, Any] = {}

    def add_node(self, name: str, func: Callable) -> None:
        """Register a node by name with the callable that implements it."""
        self.nodes[name] = func

    def add_edge(self, from_node: str, to_node: str) -> None:
        """Add a direct edge between two nodes."""
        self.edges.setdefault(from_node, []).append(to_node)

    def add_conditional_edges(
        self,
        from_node: str,
        condition: Callable,
        mapping: dict[str, str],
    ) -> None:
        """Add a conditional routing rule at ``from_node``.

        The condition callable receives the current state and must return a
        key that is looked up in ``mapping`` to determine the next node.
        """
        self.conditional_edges[from_node] = (condition, mapping)

    def set_entry_point(self, name: str) -> None:
        """Set the node where graph execution begins."""
        self.entry_point = name

    def compile(self) -> MockCompiledGraph:
        """Return a :class:`MockCompiledGraph` ready for execution."""
        return MockCompiledGraph(
            nodes=self.nodes,
            edges=self.edges,
            conditional_edges=self.conditional_edges,
            entry_point=self.entry_point,
        )


class MockCompiledGraph:
    """Compiled, runnable form of a :class:`MockStateGraph`.

    Provides an async ``ainvoke`` method that walks the graph deterministically
    using the configured edges and conditional routing rules.
    """

    def __init__(
        self,
        nodes: dict[str, Callable],
        edges: dict[str, list[str]],
        conditional_edges: dict[str, Any],
        entry_point: str | None,
    ) -> None:
        self.nodes = nodes
        self.edges = edges
        self.conditional_edges = conditional_edges
        self.entry_point = entry_point
        self.execution_log: list[str] = []

    async def ainvoke(
        self,
        state: dict[str, Any],
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute the graph asynchronously against the given initial state.

        Walks the graph by following the configured edges and conditional
        routing rules. The state object is passed through every node
        function, which may return a partial update that is merged into the
        state. Execution stops when there is no outgoing edge, a conditional
        edge routes to ``END`` (or any unmapped key), or ``max_steps`` is
        reached.
        """
        current = self.entry_point
        max_steps = 20
        steps = 0

        while current and steps < max_steps:
            self.execution_log.append(current)

            if current in self.nodes:
                node = self.nodes[current]
                result = await self._call_node(node, state)
                if result is not None:
                    state = {**state, **result} if isinstance(result, dict) else state

            # Determine next node
            if current in self.conditional_edges:
                condition, mapping = self.conditional_edges[current]
                next_node = await self._call_condition(condition, state, mapping)
                if next_node is None or next_node == "END" or next_node not in self.nodes:
                    break
                current = next_node
            elif current in self.edges and self.edges[current]:
                current = self.edges[current][0]
            else:
                break
            steps += 1

        return state

    async def _call_node(self, node: Callable, state: dict[str, Any]) -> Any:
        """Invoke a node function, awaiting coroutines and returning sync results directly."""
        if inspect.iscoroutinefunction(node):
            return await node(state)
        return node(state)

    async def _call_condition(
        self,
        condition: Callable,
        state: dict[str, Any],
        mapping: dict[str, str],
    ) -> str | None:
        """Evaluate a conditional routing function and resolve the next node name."""
        if inspect.iscoroutinefunction(condition):
            result = await condition(state)
        else:
            result = condition(state)

        if isinstance(result, str):
            return mapping.get(result, result)
        return mapping.get(str(result), str(result))
