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
