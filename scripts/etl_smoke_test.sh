#!/bin/bash
set -e

container_name="test-qdrant"
cleanup() {
  docker stop "$container_name" >/dev/null 2>&1 || true
  docker rm "$container_name" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "=== ETL Smoke Test ==="

echo "Starting mock Qdrant..."
docker run -d --name "$container_name" -p 6333:6333 qdrant/qdrant:latest || echo "Qdrant already running"

sleep 5

echo "Running small ETL job..."
python -c '
from pathlib import Path
from etl.chunker.semantic_chunker import SemanticChunker

source = Path("tests/fixtures/test_doc.txt")
if not source.exists():
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("# ETL Smoke Test\\n\\nRAG smoke test document.", encoding="utf-8")

text = source.read_text(encoding="utf-8")
chunker = SemanticChunker(max_tokens=500, overlap_tokens=0, min_chunk_tokens=1, contextual_enrichment=False)
chunks = chunker.chunk_document(text, "text", {"source_type": "doc", "source_id": str(source), "version": "1"})
print(f"Prepared {len(chunks)} chunks for indexing")
'

echo "Verifying..."
curl -fsS http://localhost:6333/collections | python -m json.tool

echo "Cleanup..."
cleanup
trap - EXIT

echo "=== ETL Smoke Test PASSED ==="
