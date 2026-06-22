# Self-Improving RAG v0.4 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add confidence scoring, active feedback, VERIFY_CASCADE routing, and self-enrichment to the RAG proxy.

**Architecture:** Four new/modified modules in `proxy/app/` — `confidence.py` (scoring), `enricher.py` (knowledge ingestion), plus modifications to `main.py` (feedback endpoint + response metadata) and `orchestrator.py` (verify-cascade loop). All new components gracefully degrade when optional services unavailable.

**Tech Stack:** Python 3.11+, FastAPI, LangGraph, Qdrant, existing sentence-transformers/reranker stack.

## Global Constraints
- Air-gapped first — no external API calls at runtime
- Graceful degradation — every component optional, never crash on dependency failure
- Token economy — every token counts
- All config via environment variables
- English for code/comments, Russian for discussions
- TDD: test first, then implementation

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `proxy/app/confidence.py` | CREATE | Confidence scoring with heuristics + optional SLM verification |
| `proxy/app/enricher.py` | CREATE | Self-enrichment: extract Q&A from feedback → chunk → Qdrant |
| `proxy/app/main.py` | MODIFY | New `/v1/feedback` endpoint, `rag_feedback_id` in response, VERIFY_CASCADE in orchestrator flow |
| `proxy/app/orchestrator.py` | MODIFY | Add `check_confidence` node, VERIFY_CASCADE loop |
| `proxy/app/config.py` | MODIFY | New env vars: `CONFIDENCE_THRESHOLD`, `ENRICHMENT_ENABLED`, `ADMIN_ALERT_ENABLED` |
| `proxy/app/hitl.py` | MODIFY | Add `feedback_id` generation, `get_feedback_stats()` |
| `tests/proxy/test_confidence.py` | CREATE | Tests for confidence scorer |
| `tests/proxy/test_enricher.py` | CREATE | Tests for enricher |
| `tests/proxy/test_main.py` | MODIFY | Tests for new `/v1/feedback` endpoint |
| `tests/proxy/test_orchestrator.py` | CREATE | Tests for VERIFY_CASCADE routing |

---

### Task 1: Config — New Environment Variables

**Files:**
- Modify: `proxy/app/config.py:122` (append new vars)

**Interfaces:**
- Produces: `CONFIDENCE_THRESHOLD`, `ENRICHMENT_ENABLED`, `ADMIN_ALERT_ENABLED`, `ADMIN_ALERT_ENDPOINT`, `MAX_VERIFY_LOOPS`

- [x] **Step 1: Add new config vars**

```python
# ============ Confidence Scoring ============
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.5"))
MAX_VERIFY_LOOPS = int(os.getenv("MAX_VERIFY_LOOPS", "2"))

# ============ Self-Enrichment ============
ENRICHMENT_ENABLED = os.getenv("ENRICHMENT_ENABLED", "false").lower() == "true"

# ============ Admin Alerts ============
ADMIN_ALERT_ENABLED = os.getenv("ADMIN_ALERT_ENABLED", "false").lower() == "true"
ADMIN_ALERT_ENDPOINT = os.getenv("ADMIN_ALERT_ENDPOINT", "")  # webhook URL or email
```

- [x] **Step 2: Run existing tests to verify no regression**

Run: `pytest tests/proxy/test_config.py -v`
Expected: PASS

- [x] **Step 3: Commit**

```bash
git add proxy/app/config.py
git commit -m "feat: add confidence, enrichment, admin alert config vars"
```

---

### Task 2: Confidence Scorer

**Files:**
- Create: `proxy/app/confidence.py`
- Test: `tests/proxy/test_confidence.py`

**Interfaces:**
- Produces: `ConfidenceReport` dataclass, `compute_confidence(query, context, answer, slm_available) -> ConfidenceReport`

- [x] **Step 1: Write the failing test**

```python
# tests/proxy/test_confidence.py
import pytest
from proxy.app.confidence import ConfidenceReport, compute_confidence

def test_compute_confidence_high():
    report = compute_confidence(
        query="What is Python?",
        context="Python is a programming language created by Guido van Rossum in 1991.",
        answer="Python is a programming language created in 1991.",
        slm_available=False,
    )
    assert report.score > 0.5
    assert report.needs_review is False
    assert isinstance(report.uncertainties, list)

def test_compute_confidence_low_empty_context():
    report = compute_confidence(
        query="What is XYZ?",
        context="",
        answer="I don't know about XYZ.",
        slm_available=False,
    )
    assert report.score < 0.5
    assert report.needs_review is True

def test_confidence_report_fields():
    report = ConfidenceReport(score=0.8, needs_review=False, uncertainties=[])
    assert report.score == 0.8
    assert report.needs_review is False
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/proxy/test_confidence.py -v`
Expected: FAIL — module not found

- [x] **Step 3: Write minimal implementation**

```python
# proxy/app/confidence.py
"""Confidence scoring for RAG answers. Uses heuristics + optional SLM verification."""
import logging
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ConfidenceReport:
    score: float  # 0.0–1.0
    needs_review: bool
    uncertainties: List[str] = field(default_factory=list)
    low_relevance_sources: List[str] = field(default_factory=list)
    recommendation: str = ""


def compute_confidence(
    query: str,
    context: str,
    answer: str,
    slm_available: bool = False,
) -> ConfidenceReport:
    """Compute confidence score for a RAG answer using heuristics.
    
    Heuristics:
    - Empty context → low confidence
    - Short context relative to answer → low confidence
    - Answer contains uncertainty phrases → low confidence
    - Answer length is very short → low confidence
    - Otherwise → moderate-to-high confidence
    """
    uncertainties: List[str] = []
    score = 0.7  # Base score
    
    # Empty or very short context
    if not context or len(context.strip()) < 20:
        uncertainties.append("Retrieved context is empty or very short")
        score -= 0.4
    
    # Context-to-answer ratio
    if context and len(context) < len(answer) * 0.5:
        uncertainties.append("Context is much shorter than answer — possible hallucination")
        score -= 0.2
    
    # Uncertainty phrases in answer
    uncertainty_phrases = [
        "I don't know", "I'm not sure", "I cannot", "no information",
        "не знаю", "не уверен", "нет информации", "не могу",
        "unclear", "uncertain", "possibly", "maybe",
        "возможно", "вероятно", "неясно",
    ]
    answer_lower = answer.lower()
    found_phrases = [p for p in uncertainty_phrases if p in answer_lower]
    if found_phrases:
        uncertainties.append(f"Answer contains uncertainty phrases: {', '.join(found_phrases)}")
        score -= 0.2
    
    # Very short answer
    if len(answer.strip()) < 20:
        uncertainties.append("Answer is very short — insufficient information")
        score -= 0.15
    
    # Clamp score
    score = max(0.0, min(1.0, score))
    
    needs_review = score < 0.5
    recommendation = ""
    if needs_review:
        recommendation = "Consider rewording query, expanding retrieved context, or flagging for human review."
    
    return ConfidenceReport(
        score=round(score, 2),
        needs_review=needs_review,
        uncertainties=uncertainties,
        recommendation=recommendation,
    )
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/proxy/test_confidence.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add proxy/app/confidence.py tests/proxy/test_confidence.py
git commit -m "feat: confidence scorer with heuristics for RAG answer quality"
```

---

### Task 3: Active Feedback — Response Metadata + Feedback Endpoint

**Files:**
- Modify: `proxy/app/main.py` (add `rag_feedback_id` to response, add `POST /v1/feedback`)
- Modify: `proxy/app/hitl.py` (add `generate_feedback_id()`)

**Interfaces:**
- Consumes: `ConfidenceReport` from Task 2
- Produces: `POST /v1/feedback` endpoint, `rag_feedback_id` in chat completion responses

- [x] **Step 1: Add `generate_feedback_id()` to hitl.py**

In `proxy/app/hitl.py`, add function after the imports:

```python
import uuid

def generate_feedback_id() -> str:
    """Generate a unique feedback ID for tracking user feedback on a response."""
    return f"fb_{uuid.uuid4().hex[:12]}"
```

- [x] **Step 2: Modify main.py — inject feedback_id into response**

In `proxy/app/main.py`, in `process_rag_query()` function, after answer is generated but before returning, add feedback_id to the response message. Find the section where `rag_version` is added and add `rag_feedback_id`:

```python
# In process_rag_query(), after retrieving chunks and generating answer:
from app.hitl import generate_feedback_id
feedback_id = generate_feedback_id()

# Add to the response message metadata
if not request.stream:
    # For non-streaming, add to choices[0].message
    response_data["choices"][0]["message"]["rag_feedback_id"] = feedback_id
```

- [x] **Step 3: Add `POST /v1/feedback` endpoint to main.py**

```python
from pydantic import BaseModel, Field

class FeedbackRequest(BaseModel):
    feedback_id: str = Field(..., description="rag_feedback_id from the response")
    rating: str = Field(..., pattern="^(positive|negative)$")
    correction: Optional[str] = Field(None, description="Corrected answer text")
    comment: Optional[str] = Field(None, description="Expert comment")


class FeedbackResponse(BaseModel):
    status: str
    message: str


@app.post("/v1/feedback", response_model=FeedbackResponse)
async def submit_feedback(request: FeedbackRequest, raw_request: Request):
    """Submit feedback on a RAG response. Supports positive/negative rating
    and optional correction text for knowledge base enrichment."""
    from app.hitl import get_logger, FeedbackType
    from app.config import ENRICHMENT_ENABLED
    
    logger = get_logger()
    
    feedback_type = FeedbackType.POSITIVE if request.rating == "positive" else FeedbackType.NEGATIVE
    
    try:
        logger.log_feedback(
            request_id=request.feedback_id,
            feedback_type=feedback_type,
            comment=request.comment or "",
            correction=request.correction,
        )
        
        # Trigger enrichment if positive feedback or correction provided
        if ENRICHMENT_ENABLED and (request.rating == "positive" or request.correction):
            try:
                from app.enricher import enrich_from_feedback
                await enrich_from_feedback(request)
            except Exception as e:
                logger.error(f"Enrichment failed (non-blocking): {e}")
        
        return FeedbackResponse(status="ok", message="Feedback recorded")
    except Exception as e:
        logger.error(f"Failed to record feedback: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to record feedback: {e}")
```

- [x] **Step 4: Add test for feedback endpoint**

```python
# tests/proxy/test_main.py — add test
def test_feedback_endpoint(client):
    response = client.post("/v1/feedback", json={
        "feedback_id": "fb_test123",
        "rating": "positive",
        "comment": "Great answer!",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
```

- [x] **Step 5: Run tests**

Run: `pytest tests/proxy/test_main.py::test_feedback_endpoint -v`
Expected: PASS

- [x] **Step 6: Commit**

```bash
git add proxy/app/main.py proxy/app/hitl.py tests/proxy/test_main.py
git commit -m "feat: active feedback — feedback_id in response + POST /v1/feedback endpoint"
```

---

### Task 4: VERIFY_CASCADE in Orchestrator

**Files:**
- Modify: `proxy/app/orchestrator.py`
- Test: `tests/proxy/test_orchestrator.py`

**Interfaces:**
- Consumes: `ConfidenceReport`, `compute_confidence` from Task 2
- Produces: Extended orchestrator state with `confidence`, `needs_escalation`, `escalation_reason`

- [x] **Step 1: Add `check_confidence` node to orchestrator**

In `proxy/app/orchestrator.py`, add a new node function:

```python
def check_confidence(state: dict) -> dict:
    """Check confidence of generated answer and decide if escalation needed."""
    from app.confidence import compute_confidence
    from app.config import CONFIDENCE_THRESHOLD, MAX_VERIFY_LOOPS, ADMIN_ALERT_ENABLED
    
    answer = state.get("answer", "")
    context = state.get("context", "")
    query = state.get("query", "")
    rewrite_count = state.get("rewrite_count", 0)
    
    if not answer:
        return {"confidence": None, "needs_escalation": False}
    
    report = compute_confidence(query=query, context=context, answer=answer)
    
    needs_escalation = report.score < CONFIDENCE_THRESHOLD and rewrite_count < MAX_VERIFY_LOOPS
    needs_admin_alert = report.score < CONFIDENCE_THRESHOLD and rewrite_count >= MAX_VERIFY_LOOPS and ADMIN_ALERT_ENABLED
    
    if needs_admin_alert:
        logger.warning(f"Low confidence answer — admin alert: query='{query[:80]}...', score={report.score}")
        # Admin alert is non-blocking — logged for webhook/email integration
    
    return {
        "confidence": report.score,
        "needs_escalation": needs_escalation,
        "escalation_reason": "; ".join(report.uncertainties) if needs_escalation else "",
    }
```

- [x] **Step 2: Wire `check_confidence` into the graph builder**

In `build_rag_graph()`, add the node and conditional edge after `generate`:

```python
builder.add_node("check_confidence", check_confidence)
builder.add_edge("generate", "check_confidence")
builder.add_conditional_edges(
    "check_confidence",
    lambda s: "escalate" if s.get("needs_escalation") else "done",
    {
        "escalate": "rewrite",
        "done": END,
    },
)
```

- [x] **Step 3: Write tests for VERIFY_CASCADE**

```python
# tests/proxy/test_orchestrator.py
import pytest
from unittest.mock import patch, MagicMock

def test_check_confidence_high_score_does_not_escalate():
    from proxy.app.orchestrator import check_confidence
    state = {
        "query": "What is Python?",
        "context": "Python is a programming language created in 1991 by Guido van Rossum.",
        "answer": "Python is a programming language created in 1991 by Guido van Rossum.",
        "rewrite_count": 0,
    }
    result = check_confidence(state)
    assert result["confidence"] is not None
    assert result["confidence"] > 0.5
    assert result["needs_escalation"] is False

def test_check_confidence_low_score_triggers_escalation_within_loop_limit():
    from proxy.app.orchestrator import check_confidence
    state = {
        "query": "What is XYZ?",
        "context": "",
        "answer": "I don't know.",
        "rewrite_count": 0,
    }
    result = check_confidence(state)
    assert result["confidence"] < 0.5
    assert result["needs_escalation"] is True
```

- [x] **Step 4: Run tests**

Run: `pytest tests/proxy/test_orchestrator.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add proxy/app/orchestrator.py tests/proxy/test_orchestrator.py
git commit -m "feat: VERIFY_CASCADE routing — check confidence → escalate or finish"
```

---

### Task 5: Self-Enrichment Pipeline

**Files:**
- Create: `proxy/app/enricher.py`
- Test: `tests/proxy/test_enricher.py`

**Interfaces:**
- Consumes: `FeedbackRequest` from Task 3
- Produces: `enrich_from_feedback(feedback_request) -> None`

- [x] **Step 1: Write tests**

```python
# tests/proxy/test_enricher.py
import pytest
from unittest.mock import patch, MagicMock
from proxy.app.enricher import extract_qa_pair, chunk_qa_pair

def test_extract_qa_pair_from_feedback():
    feedback = MagicMock()
    feedback.feedback_id = "fb_test"
    feedback.rating = "positive"
    feedback.correction = None
    feedback.comment = ""
    
    interaction = {
        "query": "What is Docker?",
        "response": "Docker is a containerization platform.",
        "context": "Docker enables containerization of applications.",
    }
    
    qa = extract_qa_pair(feedback, interaction)
    assert qa is not None
    assert "Docker" in qa["question"]
    assert "containerization" in qa["answer"]

def test_extract_qa_pair_with_correction():
    feedback = MagicMock()
    feedback.feedback_id = "fb_test2"
    feedback.rating = "negative"
    feedback.correction = "Docker is a platform for developing, shipping, and running applications in containers."
    feedback.comment = ""
    
    interaction = {
        "query": "What is Docker?",
        "response": "Docker is a tool.",
        "context": "",
    }
    
    qa = extract_qa_pair(feedback, interaction)
    assert qa is not None
    assert qa["answer"] == feedback.correction

def test_chunk_qa_pair():
    qa = {
        "question": "What is Docker?",
        "answer": "Docker is a containerization platform for developing, shipping, and running applications.",
    }
    chunk = chunk_qa_pair(qa)
    assert chunk is not None
    assert "What is Docker?" in chunk["text"]
    assert chunk["metadata"]["source"] == "user_feedback"
```

- [x] **Step 2: Run tests to verify they fail**

Run: `pytest tests/proxy/test_enricher.py -v`
Expected: FAIL

- [x] **Step 3: Implement enricher**

```python
# proxy/app/enricher.py
"""Self-enrichment pipeline: extract Q&A from accepted feedback → chunk → index in Qdrant."""
import json
import hashlib
import logging
from pathlib import Path
from typing import Any, Optional

from app.config import COLLECTION_NAME, QDRANT_HOST, QDRANT_PORT

logger = logging.getLogger(__name__)


async def enrich_from_feedback(feedback_request: Any) -> bool:
    """Process a feedback request and enrich the knowledge base if applicable.
    
    Returns True if enrichment was performed, False otherwise.
    """
    feedback_id = feedback_request.feedback_id
    
    # Find the original interaction in the interaction log
    interaction = _find_interaction(feedback_id)
    if interaction is None:
        logger.warning(f"Interaction {feedback_id} not found for enrichment")
        return False
    
    # Extract Q&A pair
    qa = extract_qa_pair(feedback_request, interaction)
    if qa is None:
        return False
    
    # Chunk it
    chunk = chunk_qa_pair(qa)
    if chunk is None:
        return False
    
    # Index in Qdrant
    return await _index_chunk(chunk)


def extract_qa_pair(feedback_request: Any, interaction: dict) -> Optional[dict]:
    """Extract a Q&A pair from feedback + original interaction.
    
    Uses correction if provided (negative feedback with fix),
    otherwise uses the original response (positive feedback).
    """
    query = interaction.get("query", "")
    response = interaction.get("response", "")
    
    answer = feedback_request.correction if feedback_request.correction else response
    
    if not query or not answer:
        return None
    
    return {
        "question": query.strip(),
        "answer": answer.strip(),
        "feedback_id": feedback_request.feedback_id,
        "rating": feedback_request.rating,
        "context": interaction.get("context", ""),
    }


def chunk_qa_pair(qa: dict) -> Optional[dict]:
    """Convert a Q&A pair into a chunk for indexing."""
    text = f"Q: {qa['question']}\nA: {qa['answer']}"
    chunk_id = hashlib.sha256(text.encode()).hexdigest()
    
    return {
        "id": chunk_id,
        "text": text,
        "metadata": {
            "source": "user_feedback",
            "feedback_id": qa.get("feedback_id", ""),
            "rating": qa.get("rating", ""),
            "question": qa["question"],
            "type": "qa_pair",
        },
    }


async def _index_chunk(chunk: dict) -> bool:
    """Index a chunk in Qdrant. Returns True on success."""
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import PointStruct
        from sentence_transformers import SentenceTransformer
        from app.config import EMBEDDER_MODEL, EMBEDDER_DEVICE
        
        if not EMBEDDER_MODEL:
            logger.warning("EMBEDDER_MODEL not configured — skipping enrichment index")
            return False
        
        client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        model = SentenceTransformer(EMBEDDER_MODEL, device=EMBEDDER_DEVICE)
        
        embedding = model.encode(chunk["text"]).tolist()
        
        point = PointStruct(
            id=chunk["id"],
            vector=embedding,
            payload={
                "text": chunk["text"],
                **chunk["metadata"],
            },
        )
        
        client.upsert(collection_name=COLLECTION_NAME, points=[point])
        logger.info(f"Enrichment: indexed chunk {chunk['id'][:12]} from feedback {chunk['metadata']['feedback_id']}")
        return True
    except Exception as e:
        logger.error(f"Failed to index enrichment chunk: {e}")
        return False


def _find_interaction(feedback_id: str) -> Optional[dict]:
    """Find the original interaction by feedback_id in the interaction log."""
    log_path = Path("logs/interactions.jsonl")
    if not log_path.exists():
        return None
    
    try:
        for line in log_path.read_text().strip().split("\n"):
            if not line.strip():
                continue
            entry = json.loads(line)
            if entry.get("feedback_id") == feedback_id or entry.get("request_id") == feedback_id:
                return entry
    except Exception as e:
        logger.error(f"Error reading interaction log: {e}")
    
    return None
```

- [x] **Step 4: Run tests**

Run: `pytest tests/proxy/test_enricher.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add proxy/app/enricher.py tests/proxy/test_enricher.py
git commit -m "feat: self-enrichment pipeline — feedback → Q&A chunk → Qdrant"
```

---

### Task 6: Integration — Wire Everything Together

**Files:**
- Modify: `proxy/app/main.py` (wire confidence into process_rag_query, feedback_id into response)
- Modify: `proxy/app/config.py` (add new vars to print_config)

- [x] **Step 1: Inject rag_feedback_id into non-streaming and streaming responses**

In `process_rag_query()`, generate feedback_id and add to response:

```python
# After answer is generated, before building response:
from app.hitl import generate_feedback_id
from app.confidence import compute_confidence

feedback_id = generate_feedback_id()
confidence_report = compute_confidence(
    query=user_query,
    context=context,
    answer=answer_text,
    slm_available=bool(SLM_ENDPOINT),
)

# Log interaction with confidence
if LOG_REQUESTS:
    interaction_logger.log_interaction(
        request_id=feedback_id,
        user_query=user_query,
        context=context,
        response=answer_text,
        metadata={
            "model": LLM_MODEL_NAME,
            "confidence": confidence_report.score,
            "version": version,
        }
    )
```

- [x] **Step 2: Add confidence and feedback_id to response format**

For non-streaming responses, add to the message object:
```python
response_data["choices"][0]["message"]["rag_feedback_id"] = feedback_id
response_data["choices"][0]["message"]["rag_confidence"] = confidence_report.score
```

For streaming responses, send the metadata as a final chunk:
```python
yield {
    "choices": [{"delta": {}, "finish_reason": "stop"}],
    "rag_feedback_id": feedback_id,
    "rag_confidence": confidence_report.score,
}
```

- [x] **Step 3: Update print_config()**

Add new config vars to the output:
```python
# In print_config(), the automatic globals listing will catch them
```

- [x] **Step 4: Run full test suite**

Run: `pytest tests/ -x --tb=short -q`
Expected: All 880+ tests pass + new tests

- [x] **Step 5: Commit**

```bash
git add proxy/app/main.py proxy/app/config.py
git commit -m "feat: integrate confidence scoring + feedback_id into response pipeline"
```

---

### Task 7: Documentation

**Files:**
- Modify: `docs/api_reference.md` (add `/v1/feedback` endpoint docs)
- Modify: `AGENTS.md` (update Current State to v0.4)
- Modify: `README.md` (add self-improving RAG features)

- [x] **Step 1: Add /v1/feedback to api_reference.md**

- [x] **Step 2: Update AGENTS.md version**

- [x] **Step 3: Update README.md features**

- [x] **Step 4: Commit**

```bash
git add docs/api_reference.md AGENTS.md README.md
git commit -m "docs: v0.4 self-improving RAG features in API ref, AGENTS, README"
```
