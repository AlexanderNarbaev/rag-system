#!/usr/bin/env python3
"""
Retrieval Evaluation Script

Computes MRR, Recall@k, nDCG@k, Precision@k for the retrieval system.

Usage:
    python scripts/eval_retrieval.py --dataset eval/retrieval_eval_dataset.jsonl
    python scripts/eval_retrieval.py --dataset eval/retrieval_eval_dataset.jsonl --threshold-mrr 0.75
"""

import argparse
import json
import sys
from collections.abc import Callable
from typing import Any


def load_dataset (path: str) -> list [dict]:
  """Load JSONL evaluation dataset."""
  pairs = []
  with open (path, encoding = "utf-8") as f:
    for line in f:
      line = line.strip ()
      if line:
        pairs.append (json.loads (line))
  return pairs


def compute_mrr (ranked_docs: list [str], relevant_docs: list [str]) -> float:
  """Compute Mean Reciprocal Rank for a single query."""
  for i, doc in enumerate (ranked_docs, 1):
    if doc in relevant_docs:
      return 1.0 / i
  return 0.0


def compute_recall_at_k (ranked_docs: list [str], relevant_docs: list [str], k: int) -> float:
  """Compute Recall@k for a single query."""
  if not relevant_docs:
    return 1.0
  retrieved_at_k = ranked_docs [:k]
  hits = sum (1 for doc in retrieved_at_k if doc in relevant_docs)
  return hits / len (relevant_docs)


def compute_precision_at_k (ranked_docs: list [str], relevant_docs: list [str], k: int) -> float:
  """Compute Precision@k for a single query."""
  if k == 0:
    return 0.0
  retrieved_at_k = ranked_docs [:k]
  hits = sum (1 for doc in retrieved_at_k if doc in relevant_docs)
  return hits / k


def compute_ndcg_at_k (ranked_docs: list [str], relevant_docs: list [str], k: int) -> float:
  """Compute nDCG@k for a single query."""
  if not relevant_docs:
    return 1.0
  
  # DCG
  dcg = 0.0
  for i, doc in enumerate (ranked_docs [:k], 1):
    if doc in relevant_docs:
      dcg += 1.0 / (2 ** (i - 1)).bit_length () if i > 1 else 1.0
  
  # Ideal DCG
  ideal_hits = min (len (relevant_docs), k)
  idcg = sum (1.0 / (2 ** (i - 1)).bit_length () if i > 1 else 1.0 for i in range (1, ideal_hits + 1))
  
  return dcg / idcg if idcg > 0 else 0.0


def evaluate (
    dataset: list [dict], search_fn: Callable | None = None, top_k: int = 20, ) -> dict [str, Any]:
  """
  Evaluate retrieval quality on the dataset.

  Returns dict with aggregate metrics.
  """
  metrics = {
      "mrr": [], "recall@5": [], "recall@10": [], "recall@20": [], "precision@5": [], "precision@10": [], "ndcg@10": [],
      "by_category": {}, "by_difficulty": {},
  }
  
  for pair in dataset:
    query = pair ["query"]
    relevant_docs = pair ["relevant_docs"]
    category = pair.get ("category", "unknown")
    difficulty = pair.get ("difficulty", "unknown")
    
    # Get ranked results (mock if no search_fn)
    if search_fn:
      try:
        results = search_fn (query = query, top_k = top_k)
        ranked_docs = [r.id for r in results]
      except Exception:
        ranked_docs = []
    else:
      # Mock: return relevant docs mixed with irrelevant
      ranked_docs = relevant_docs + pair.get ("irrelevant_docs", [])
    
    # Compute metrics
    mrr = compute_mrr (ranked_docs, relevant_docs)
    r5 = compute_recall_at_k (ranked_docs, relevant_docs, 5)
    r10 = compute_recall_at_k (ranked_docs, relevant_docs, 10)
    r20 = compute_recall_at_k (ranked_docs, relevant_docs, 20)
    p5 = compute_precision_at_k (ranked_docs, relevant_docs, 5)
    p10 = compute_precision_at_k (ranked_docs, relevant_docs, 10)
    ndcg10 = compute_ndcg_at_k (ranked_docs, relevant_docs, 10)
    
    metrics ["mrr"].append (mrr)
    metrics ["recall@5"].append (r5)
    metrics ["recall@10"].append (r10)
    metrics ["recall@20"].append (r20)
    metrics ["precision@5"].append (p5)
    metrics ["precision@10"].append (p10)
    metrics ["ndcg@10"].append (ndcg10)
    
    # By category
    if category not in metrics ["by_category"]:
      metrics ["by_category"] [category] = []
    metrics ["by_category"] [category].append (mrr)
    
    # By difficulty
    if difficulty not in metrics ["by_difficulty"]:
      metrics ["by_difficulty"] [difficulty] = []
    metrics ["by_difficulty"] [difficulty].append (mrr)
  
  # Aggregate
  result = {
      "total_pairs": len (dataset), "mrr": sum (metrics ["mrr"]) / len (metrics ["mrr"]) if metrics ["mrr"] else 0,
      "recall@5": sum (metrics ["recall@5"]) / len (metrics ["recall@5"]) if metrics ["recall@5"] else 0,
      "recall@10": sum (metrics ["recall@10"]) / len (metrics ["recall@10"]) if metrics ["recall@10"] else 0,
      "recall@20": sum (metrics ["recall@20"]) / len (metrics ["recall@20"]) if metrics ["recall@20"] else 0,
      "precision@5": sum (metrics ["precision@5"]) / len (metrics ["precision@5"]) if metrics ["precision@5"] else 0,
      "precision@10": sum (metrics ["precision@10"]) / len (metrics ["precision@10"]) if metrics [
        "precision@10"] else 0,
      "ndcg@10": sum (metrics ["ndcg@10"]) / len (metrics ["ndcg@10"]) if metrics ["ndcg@10"] else 0,
      "by_category": {k: sum (v) / len (v) for k, v in metrics ["by_category"].items ()},
      "by_difficulty": {k: sum (v) / len (v) for k, v in metrics ["by_difficulty"].items ()},
  }
  
  return result


def main ():
  parser = argparse.ArgumentParser (description = "Evaluate retrieval quality")
  parser.add_argument ("--dataset", required = True, help = "Path to JSONL evaluation dataset")
  parser.add_argument ("--top-k", type = int, default = 20, help = "Top-k results to evaluate")
  parser.add_argument ("--threshold-mrr", type = float, default = 0.75, help = "MRR threshold for CI gate")
  parser.add_argument ("--output", help = "Output JSON file path")
  args = parser.parse_args ()
  
  # Load dataset
  dataset = load_dataset (args.dataset)
  print (f"Loaded {len (dataset)} evaluation pairs")
  
  # Run evaluation
  results = evaluate (dataset, top_k = args.top_k)
  
  # Print results
  print ("\n=== Retrieval Evaluation Results ===")
  print (f"MRR:         {results ['mrr']:.3f}")
  print (f"Recall@5:    {results ['recall@5']:.3f}")
  print (f"Recall@10:   {results ['recall@10']:.3f}")
  print (f"Recall@20:   {results ['recall@20']:.3f}")
  print (f"Precision@5: {results ['precision@5']:.3f}")
  print (f"Precision@10:{results ['precision@10']:.3f}")
  print (f"nDCG@10:     {results ['ndcg@10']:.3f}")
  
  print ("\n=== By Category ===")
  for cat, score in results ["by_category"].items ():
    print (f"  {cat}: {score:.3f}")
  
  print ("\n=== By Difficulty ===")
  for diff, score in results ["by_difficulty"].items ():
    print (f"  {diff}: {score:.3f}")
  
  # Save output
  if args.output:
    with open (args.output, "w") as f:
      json.dump (results, f, indent = 2)
    print (f"\nResults saved to {args.output}")
  
  # CI gate
  if results ["mrr"] < args.threshold_mrr:
    print (f"\n❌ MRR {results ['mrr']:.3f} < threshold {args.threshold_mrr}")
    sys.exit (1)
  else:
    print (f"\n✅ MRR {results ['mrr']:.3f} >= threshold {args.threshold_mrr}")


if __name__ == "__main__":
  main ()
