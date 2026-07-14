# RAGAS Feedback Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:
> executing-plans to implement this plan task-by-task.

**Goal:** Integrate RAGAS evaluation metrics into the feedback loop and every RAG response.

**Architecture:** The existing `proxy/app/core/ragas_eval.py` already implements `compute_faithfulness`,
`compute_answer_relevance`, `compute_context_relevance`, and `evaluate_rag_response`. We need to wire these into the
feedback endpoint and the main RAG pipeline.

**Tech Stack:** Python, FastAPI, pytest, ruff

## Files to Modify

| File                        | Action     | Purpose                                      |
|-----------------------------|------------|----------------------------------------------|
| `tests/proxy/test_ragas.py` | **Create** | Test suite for RAGAS metrics                 |
| `proxy/app/api/feedback.py` | **Modify** | Add RAGAS computation on feedback submission |
| `proxy/app/main.py`         | **Modify** | Add RAGAS scores to every RAG response       |

## Task 1: Create RAGAS Test Suite

**Files:**

- Create: `tests/proxy/test_ragas.py`

**Step 1:** Create the test file with comprehensive tests for all RAGAS functions.

**Step 2:** Run tests to verify they pass against existing `ragas_eval.py`.

Run: `python -m pytest tests/proxy/test_ragas.py -v`
Expected: All PASS

## Task 2: Integrate RAGAS into Feedback Endpoint

**Files:**

- Modify: `proxy/app/api/feedback.py`

**Changes:**

- Add `question`, `answer`, `contexts` fields to `FeedbackRequest`
- Import and call `evaluate_rag_response` after storing feedback
- Store RAGAS scores alongside feedback

## Task 3: Integrate RAGAS into Main RAG Pipeline

**Files:**

- Modify: `proxy/app/main.py`

**Changes:**

- Import `evaluate_rag_response`
- After generating response in `process_rag_query`, compute RAGAS scores
- Add RAGAS scores to response extensions

## Verification

1. `python -m ruff check proxy/app/core/ragas_eval.py proxy/app/main.py --no-fix`
2. `python -m pytest tests/proxy/test_ragas.py -v`
