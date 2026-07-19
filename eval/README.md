# Retrieval Evaluation Dataset

## Purpose

Labeled query-document pairs for automated retrieval quality regression testing.

## Format

Each line is a JSON object with:

- `query`: The search query
- `relevant_docs`: List of document IDs that should be retrieved
- `irrelevant_docs`: List of document IDs that should NOT be retrieved
- `category`: Query category (factual, analytical, comparative, procedural)
- `difficulty`: Query difficulty (easy, medium, hard)

## Dataset Statistics

**Total pairs**: 452

### Distribution by Category

| Category    | Count | Percentage |
|-------------|-------|------------|
| factual     | 113   | 25.0%      |
| analytical  | 114   | 25.2%      |
| comparative | 112   | 24.8%      |
| procedural  | 113   | 25.0%      |

### Distribution by Difficulty

| Difficulty | Count | Percentage |
|------------|-------|------------|
| easy       | 70    | 15.5%      |
| medium     | 208   | 46.0%      |
| hard       | 174   | 38.5%      |

### Query Types Covered

- **Technical documentation queries** - RAG concepts, embeddings, reranking, evaluation metrics
- **Code-related queries** - API endpoints, configuration parameters, middleware
- **Architecture/design queries** - System design, patterns, scalability
- **Configuration queries** - Environment variables, Docker, Kubernetes
- **Troubleshooting queries** - Error handling, debugging, performance issues

## Usage

```bash
python scripts/eval_retrieval.py --dataset eval/retrieval_eval_dataset.jsonl
```

## Expected Metrics

- MRR ≥ 0.75
- Recall@20 ≥ 0.85
- nDCG@10 ≥ 0.80

## Adding New Pairs

1. Identify a query from production logs
2. Find relevant documents in the knowledge base
3. Add to the JSONL file with appropriate category/difficulty
4. Run evaluation to verify quality

## Maintenance

- **Sprint**: S4-2026 Wave 2, Task P1-1 (EVAL-01)
- **Last expanded**: 2026-07-16
- **Previous count**: 20 pairs
- **Current count**: 452 pairs
- **Growth**: +432 pairs (2160% increase)
