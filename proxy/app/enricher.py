"""Self-enrichment pipeline: extract Q&A from accepted feedback → chunk → index in Qdrant."""
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from app.config import COLLECTION_NAME, QDRANT_HOST, QDRANT_PORT

logger = logging.getLogger(__name__)


async def enrich_from_feedback(feedback_request: Any) -> bool:
    """Process a feedback request and enrich the knowledge base if applicable."""
    feedback_id = feedback_request.feedback_id

    interaction = _find_interaction(feedback_id)
    if interaction is None:
        logger.warning(f"Interaction {feedback_id} not found for enrichment")
        return False

    qa = extract_qa_pair(feedback_request, interaction)
    if qa is None:
        return False

    chunk = chunk_qa_pair(qa)
    if chunk is None:
        return False

    return await _index_chunk(chunk)


def extract_qa_pair(feedback_request: Any, interaction: dict) -> dict | None:
    """Extract a Q&A pair from feedback + original interaction."""
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


def chunk_qa_pair(qa: dict) -> dict | None:
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
        from app.remote_services import create_embedder
        from qdrant_client import QdrantClient
        from qdrant_client.models import PointStruct

        model = create_embedder()

        client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

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


def _find_interaction(feedback_id: str) -> dict | None:
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
