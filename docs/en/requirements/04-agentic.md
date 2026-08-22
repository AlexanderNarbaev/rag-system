# Block D. Agentic Orchestration — LangGraph (FR-26 — FR-31)

---

## FR-26. LangGraph 10-node graph

**Description:**
The system optionally uses LangGraph for agentic orchestration. A graph of 10 nodes:

1. `rewrite` — query rephrasing
2. `retrieve` — hybrid search
3. `check_sufficiency` — context sufficiency check
4. `graph_expand` — expansion via the knowledge graph
5. `rerank` — ranking
6. `build_context` — context assembly
7. `generate` — LLM answer generation
8. `check_confidence` — confidence check
9. `call_tools` — tool invocation (if requested by the LLM)
10. `finalize` — response finalization

**Acceptance criteria:**

1. `USE_LANGGRAPH=true` — the graph compiles without errors
2. A request passes through all nodes in order
3. The log contains entries for each node

**Status:** ✅ Confirmed (with mock LangGraph)
**Priority:** HIGH (opt-in)
**Reference:** ADR-006

---

## FR-27. Query rewriting (SLM/LLM)

**Description:**
Before search, the system rephrases the user query to improve relevance:

- Fixes typos
- Expands abbreviations
- Adds context from previous messages (for multi-turn)

**Acceptance criteria:**

1. A query with a typo — rewrite fixes it
2. The rewritten query differs from the original
3. Search results for the rewritten query are more relevant

**Status:** ✅ Confirmed (with mock LangGraph)
**Priority:** HIGH (opt-in)
**Reference:** ADR-006

---

## FR-28. Retrieval sufficiency loop (max 3)

**Description:**
After search, the system checks context sufficiency (score ≥ 0.6). If insufficient,
it returns to the `rewrite` node for another attempt. Maximum 3 loops.
After 3 failed attempts — the best context found is used.

**Acceptance criteria:**

1. Insufficient context — the system rewrites the query and searches again
2. Maximum 3 loops (not an infinite loop)
3. After 3 loops — the best found context is used

**Status:** ✅ Confirmed (with mock LangGraph)
**Priority:** HIGH (opt-in)
**Reference:** ADR-006

---

## FR-29. Fallback to linear pipeline

**Description:**
With `USE_LANGGRAPH=false` the system uses a simple linear pipeline:
search → rerank → context → generate. No loops, no agentic behavior.

**Acceptance criteria:**

1. `USE_LANGGRAPH=false` — the request is processed linearly
2. The response is generated successfully
3. The log contains no mention of LangGraph

**Status:** ✅ Confirmed (with mock LangGraph)
**Priority:** CRITICAL
**Reference:** ADR-006, ADR-011

---

## FR-30. Tool/function calling

**Description:**
The LLM can request tool calls. The system supports:

- Built-in tools (live Confluence, Jira, GitLab API)
- Custom tools (via SDK or declarative YAML)
- OpenAPI auto-discovery (automatic tool creation from OpenAPI specs)

**Acceptance criteria:**

1. The LLM requests a tool call — the system executes it and returns the result
2. The tool call result is passed back to the LLM to generate the final answer
3. Tools are filtered by user role

**Status:** ✅ Confirmed (with mock LangGraph)
**Priority:** HIGH
**Reference:** ADR-009

---

## FR-31. Parallel tool execution

**Description:**
If the LLM requests multiple tool calls at once, the system executes them
in parallel via `asyncio.gather`. Dependencies between tools are resolved
through topological sorting.

**Acceptance criteria:**

1. Two independent tool calls — executed in parallel (time ≈ max(a, b), not a+b)
2. Dependent tool calls — executed sequentially
3. A failure of one tool does not interrupt the others

**Status:** ✅ Confirmed (with mock LangGraph)
**Priority:** HIGH
**Reference:** ADR-009 4.2-4.3
