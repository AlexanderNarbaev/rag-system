#!/usr/bin/env python3
"""
Automated retrieval quality evaluation pipeline.

Computes standard IR metrics from HITL-interaction logs or a JSONL query-document
labeled dataset:

  - MRR (Mean Reciprocal Rank)
  - Recall@k (k = 5, 10, 20)
  - nDCG@k (k = 5, 10)
  - Precision@k (k = 5)

Usage:
    # Evaluate using HITL interaction logs (auto-extracts query->doc pairs)
    python scripts/evaluate_retrieval.py --hitl-dir ./logs/hitl --output report.json

    # Evaluate using a labeled JSONL dataset
    python scripts/evaluate_retrieval.py --dataset ./data/eval_dataset.jsonl

    # Full mode: run retrieval for each query in a labeled dataset
    python scripts/evaluate_retrieval.py --dataset ./data/eval_dataset.jsonl --run-retrieval

Labeled dataset JSONL format (one JSON object per line):
{"query": "How to configure CI/CD?", "relevant_docs": ["doc_id_1", "doc_id_2"]}
"""

import argparse
import json
import logging
import math
import sys
import time
from pathlib import Path
from typing import Any

logging.basicConfig (level = logging.INFO, format = "%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger (__name__)

METRICS = {}


def dcg_at_k (relevance_scores: list [float], k: int) -> float:
  """Compute DCG@k (Discounted Cumulative Gain)."""
  dcg = 0.0
  for i, rel in enumerate (relevance_scores [:k]):
    dcg += rel / math.log2 (i + 2)
  return dcg


def ndcg_at_k (retrieved: list [str], relevant: set [str], k: int) -> float:
  """Compute nDCG@k (Normalized DCG).

  Uses binary relevance: 1.0 if doc is relevant, 0.0 otherwise.
  """
  if not relevant:
    return 1.0
  
  binary_relevance = [1.0 if doc in relevant else 0.0 for doc in retrieved [:k]]
  ideal_relevance = sorted ([1.0] * min (len (relevant), k) + [0.0] * max (0, k - len (relevant)), reverse = True)
  
  dcg = dcg_at_k (binary_relevance, k)
  idcg = dcg_at_k (ideal_relevance, k)
  
  return dcg / idcg if idcg > 0 else 0.0


def recall_at_k (retrieved: list [str], relevant: set [str], k: int) -> float:
  """Compute Recall@k."""
  if not relevant:
    return 1.0
  retrieved_k = set (retrieved [:k])
  hits = len (retrieved_k & relevant)
  return hits / len (relevant)


def precision_at_k (retrieved: list [str], relevant: set [str], k: int) -> float:
  """Compute Precision@k."""
  if not retrieved:
    return 0.0
  retrieved_k = set (retrieved [:k])
  hits = len (retrieved_k & relevant)
  return hits / k


def mrr (retrieved_lists: list [list [str]], relevant_sets: list [set [str]]) -> float:
  """Compute MRR (Mean Reciprocal Rank) over all queries."""
  if not retrieved_lists:
    return 0.0
  
  rr_sum = 0.0
  for retrieved, relevant in zip (retrieved_lists, relevant_sets, strict = False):
    if not relevant:
      continue
    for rank, doc in enumerate (retrieved, start = 1):
      if doc in relevant:
        rr_sum += 1.0 / rank
        break
  
  return rr_sum / len (retrieved_lists) if retrieved_lists else 0.0


def extract_eval_pairs_from_hitl (hitl_dir: str) -> list [dict [str, Any]]:
  """Extract query-document pairs from HITL interaction logs.

  Reads JSONL files from the HITL log directory and extracts
  query + retrieved document IDs from each interaction.
  """
  pairs = []
  log_path = Path (hitl_dir)
  
  if not log_path.exists ():
    logger.error (f"HITL directory not found: {hitl_dir}")
    return pairs
  
  for jsonl_file in log_path.glob ("*.jsonl"):
    with open (jsonl_file, encoding = "utf-8") as f:
      for line in f:
        line = line.strip ()
        if not line:
          continue
        try:
          record = json.loads (line)
        except json.JSONDecodeError:
          continue
        
        query = record.get ("user_query") or record.get ("query", "")
        if not query:
          continue
        
        # Extract relevant doc IDs from chunk metadata or explicit feedback
        relevant_docs = []
        metadata = record.get ("metadata") or {}
        if "relevant_doc_ids" in metadata:
          relevant_docs = metadata ["relevant_doc_ids"]
        elif "chunks" in metadata:
          relevant_docs = [c.get ("source_id", "") for c in metadata ["chunks"] if c.get ("source_id")]
        
        if relevant_docs:
          pairs.append ({"query": query, "relevant_docs": relevant_docs})
  
  logger.info (f"Extracted {len (pairs)} eval pairs from HITL logs")
  return pairs


def load_labeled_dataset (dataset_path: str) -> list [dict [str, Any]]:
  """Load a labeled evaluation dataset from a JSONL file."""
  pairs = []
  path = Path (dataset_path)
  
  if not path.exists ():
    logger.error (f"Dataset not found: {dataset_path}")
    return pairs
  
  with open (path, encoding = "utf-8") as f:
    for line in f:
      line = line.strip ()
      if not line or line.startswith ("#"):
        continue
      try:
        record = json.loads (line)
        if "query" in record and "relevant_docs" in record:
          pairs.append (record)
      except json.JSONDecodeError:
        continue
  
  logger.info (f"Loaded {len (pairs)} labeled eval pairs from {dataset_path}")
  return pairs


def run_retrieval_for_queries (
    eval_pairs: list [dict [str, Any]], top_k: int = 20, ) -> tuple [list [list [str]], list [set [str]]]:
  """Run the RAG retrieval pipeline for each query in the eval set.

  Imports retrieval module lazily to avoid dependency issues when
  running as a standalone script.
  """
  retrieved_lists = []
  relevant_sets = []
  
  try:
    from proxy.app.retrieval import hybrid_search
  except ImportError as e:
    logger.error (f"Cannot import retrieval module: {e}. Use --hitl-dir instead.")
    return retrieved_lists, relevant_sets
  
  for i, pair in enumerate (eval_pairs):
    query = pair ["query"]
    relevant = set (pair.get ("relevant_docs", []))
    
    try:
      results = hybrid_search (query = query, top_k = top_k)
      retrieved_ids = []
      for hit in results:
        source_id = hit.payload.get ("source_id", "")
        if source_id:
          retrieved_ids.append (source_id)
        elif hit.id:
          retrieved_ids.append (str (hit.id))
      
      retrieved_lists.append (retrieved_ids)
      relevant_sets.append (relevant)
    except Exception as e:
      logger.warning (f"Retrieval failed for query '{query [:80]}': {e}")
      retrieved_lists.append ([])
      relevant_sets.append (relevant)
    
    if (i + 1) % 50 == 0:
      logger.info (f"  Processed {i + 1}/{len (eval_pairs)} queries")
  
  return retrieved_lists, relevant_sets


def compute_all_metrics (
    retrieved_lists: list [list [str]], relevant_sets: list [set [str]], ) -> dict [str, float]:
  """Compute all evaluation metrics."""
  metrics: dict [str, float] = {}
  
  metrics ["mrr"] = mrr (retrieved_lists, relevant_sets)
  
  for k in (5, 10, 20):
    recalls = [recall_at_k (r, rel, k) for r, rel in zip (retrieved_lists, relevant_sets, strict = False)]
    metrics [f"recall@{k}"] = sum (recalls) / len (recalls) if recalls else 0.0
  
  for k in (5, 10):
    ndcgs = [ndcg_at_k (r, rel, k) for r, rel in zip (retrieved_lists, relevant_sets, strict = False)]
    metrics [f"ndcg@{k}"] = sum (ndcgs) / len (ndcgs) if ndcgs else 0.0
  
  for k in (5,):
    precisions = [precision_at_k (r, rel, k) for r, rel in zip (retrieved_lists, relevant_sets, strict = False)]
    metrics [f"precision@{k}"] = sum (precisions) / len (precisions) if precisions else 0.0
  
  metrics ["num_queries"] = float (len (retrieved_lists))
  return metrics


def generate_eval_dataset_template (output_path: str, num_examples: int = 10):
  """Generate a template JSONL file for expert annotation."""
  template_entries = []
  for i in range (num_examples):
    template_entries.append ({
        "query": f"<Insert query {i + 1} here>", "relevant_docs": ["<doc_id_1>", "<doc_id_2>"],
        "notes": "<Optional: why these docs are relevant>",
    })
  
  with open (output_path, "w", encoding = "utf-8") as f:
    for entry in template_entries:
      f.write (json.dumps (entry, ensure_ascii = False) + "\n")
  
  logger.info (f"Template dataset written to {output_path} ({num_examples} entries)")


def main ():
  parser = argparse.ArgumentParser (description = "Retrieval Quality Evaluation Pipeline",
      formatter_class = argparse.RawDescriptionHelpFormatter, )
  parser.add_argument ("--dataset", type = str, help = "Path to labeled JSONL evaluation dataset", )
  parser.add_argument ("--hitl-dir", type = str, default = "./logs/hitl",
      help = "Directory with HITL interaction logs (default: ./logs/hitl)", )
  parser.add_argument ("--run-retrieval", action = "store_true",
      help = "Actually run retrieval for each query (requires Qdrant access)", )
  parser.add_argument ("--output", type = str, help = "Path to save JSON metrics report", )
  parser.add_argument ("--top-k", type = int, default = 20,
      help = "Number of chunks to retrieve per query (default: 20)", )
  parser.add_argument ("--gen-template", type = str, help = "Generate a template JSONL file for expert annotation", )
  parser.add_argument ("--threshold-mrr", type = float, default = 0.75,
      help = "Minimum acceptable MRR for CI regression test (default: 0.75)", )
  
  args = parser.parse_args ()
  
  if args.gen_template:
    generate_eval_dataset_template (args.gen_template)
    return
  
  if not args.dataset and not args.run_retrieval:
    parser.error ("Either --dataset or --run-retrieval with --hitl-dir is required")
  
  eval_pairs = []
  if args.dataset:
    eval_pairs = load_labeled_dataset (args.dataset)
  
  if not eval_pairs and args.run_retrieval:
    eval_pairs = extract_eval_pairs_from_hitl (args.hitl_dir)
  
  if not eval_pairs:
    logger.error ("No evaluation pairs found. Provide --dataset or use --gen-template to create one.")
    logger.info ("Tip: Use --gen-template ./data/eval_dataset.jsonl to create a template for annotation.")
    sys.exit (1)
  
  start_time = time.time ()
  
  if args.run_retrieval:
    retrieved_lists, relevant_sets = run_retrieval_for_queries (eval_pairs, top_k = args.top_k)
  else:
    # Use document IDs directly from the labeled dataset
    retrieved_lists = [pair.get ("retrieved_docs", []) for pair in eval_pairs]
    relevant_sets = [set (pair.get ("relevant_docs", [])) for pair in eval_pairs]
    
    if not any (retrieved_lists):
      logger.warning ("No retrieved_docs in dataset. Use --run-retrieval to execute retrieval, "
                      "or add 'retrieved_docs' field to dataset entries.")
      sys.exit (1)
  
  metrics = compute_all_metrics (retrieved_lists, relevant_sets)
  elapsed = time.time () - start_time
  
  # Print report
  print ("\n" + "=" * 60)
  print ("  Retrieval Quality Evaluation Report")
  print ("=" * 60)
  print (f"  Queries evaluated:  {int (metrics ['num_queries'])}")
  print (f"  Time:                {elapsed:.1f}s")
  print ("-" * 60)
  for k, v in sorted (metrics.items ()):
    if k == "num_queries":
      continue
    status = "PASS" if v >= args.threshold_mrr else "FAIL"
    if "mrr" in k:
      print (f"  {k:<20s} {v:.4f}  ({status})")
    else:
      print (f"  {k:<20s} {v:.4f}")
  print ("=" * 60)
  
  # Check CI threshold
  if metrics.get ("mrr", 0.0) < args.threshold_mrr:
    print (f"\n  CI CHECK: MRR {metrics ['mrr']:.4f} < {args.threshold_mrr} threshold — FAIL")
    sys.exit (1)
  else:
    print (f"\n  CI CHECK: MRR {metrics ['mrr']:.4f} >= {args.threshold_mrr} threshold — PASS")
  
  if args.output:
    with open (args.output, "w", encoding = "utf-8") as f:
      json.dump (metrics, f, indent = 2, ensure_ascii = False)
    logger.info (f"Metrics saved to {args.output}")


if __name__ == "__main__":
  main ()
