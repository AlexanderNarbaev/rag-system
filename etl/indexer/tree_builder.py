"""
RAPTOR: Recursive Abstractive Processing for Tree-Organized Retrieval

Builds hierarchical summaries from chunks for multi-level retrieval.
Based on: https://arxiv.org/abs/2401.18059

Architecture:
- Level 0: Original chunks (leaf nodes)
- Level 1: Cluster summaries (groups of 5-10 chunks)
- Level 2: Meta-summaries (groups of 5-10 level-1 summaries)
- Level 3: Root summary (single document/topic summary)
"""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger (__name__)


@dataclass
class TreeNode:
  """A node in the RAPTOR tree."""

  id: str
  level: int
  text: str
  summary: str = ""
  children: list [str] = field (default_factory = list)  # Child node IDs
  parent: str | None = None
  embedding: list [float] = field (default_factory = list)
  metadata: dict [str, Any] = field (default_factory = dict)


class RaptorTreeBuilder:
  """
  Builds hierarchical tree from chunks using recursive clustering + summarization.

  Usage:
      builder = RaptorTreeBuilder(max_cluster_size=5)
      tree = builder.build_tree(chunks)
      summaries = builder.get_summaries_at_level(tree, level=1)
  """

  def __init__ (
      self, max_cluster_size: int = 5, max_levels: int = 3, summary_fn: Callable [..., Any] | None = None,
      embed_fn: Callable [..., Any] | None = None, ):
    self.max_cluster_size = max_cluster_size
    self.max_levels = max_levels
    self.summary_fn = summary_fn or self._default_summary
    self.embed_fn = embed_fn

  def _default_summary (self, texts: list [str]) -> str:
    """Default summary: concatenate with truncation."""
    combined = " ".join (texts)
    if len (combined) > 2000:
      combined = combined [:2000] + "..."
    return combined

  def _cluster_texts (self, texts: list [str], max_size: int = 5) -> list [list [int]]:
    """
    Simple clustering: group consecutive texts into clusters of max_size.
    For production, use proper clustering (KMeans, GMM, etc.)
    """
    clusters = []
    for i in range (0, len (texts), max_size):
      cluster = list (range (i, min (i + max_size, len (texts))))
      clusters.append (cluster)
    return clusters

  def build_tree (self, chunks: list [dict [str, Any]]) -> dict [str, TreeNode]:
    """
    Build RAPTOR tree from chunks.

    Returns dict of node_id -> TreeNode
    """
    tree: dict [str, TreeNode] = {}

    # Level 0: Create leaf nodes from chunks
    for i, chunk in enumerate (chunks):
      node_id = f"L0_{i}"
      tree [node_id] = TreeNode (id = node_id, level = 0, text = chunk.get ("text", ""),
          summary = chunk.get ("text", "") [:500],  # First 500 chars as summary
          metadata = chunk.get ("metadata", {}), )

    # Build upper levels recursively
    current_level_nodes = list (tree.values ())
    level = 1

    while len (current_level_nodes) > 1 and level <= self.max_levels:
      # Get texts for clustering
      texts = [node.summary for node in current_level_nodes]

      # Cluster
      clusters = self._cluster_texts (texts, self.max_cluster_size)

      # Create parent nodes
      new_level_nodes = []
      for cluster_idx, cluster_indices in enumerate (clusters):
        # Get child nodes
        child_nodes = [current_level_nodes [i] for i in cluster_indices]
        child_ids = [node.id for node in child_nodes]

        # Generate summary
        child_texts = [node.summary for node in child_nodes]
        summary = self.summary_fn (child_texts)

        # Create parent node
        node_id = f"L{level}_{cluster_idx}"
        parent_node = TreeNode (id = node_id, level = level, text = summary, summary = summary, children = child_ids,
            metadata = {"num_children": len (child_ids)}, )

        # Update children's parent reference
        for child in child_nodes:
          child.parent = node_id

        tree [node_id] = parent_node
        new_level_nodes.append (parent_node)

      current_level_nodes = new_level_nodes
      level += 1

    logger.info (f"Built RAPTOR tree: {len (tree)} nodes, {level - 1} levels")
    return tree

  def get_summaries_at_level (self, tree: dict [str, TreeNode], level: int) -> list [str]:
    """Get all summaries at a specific level."""
    return [node.summary for node in tree.values () if node.level == level]

  def get_all_summaries (self, tree: dict [str, TreeNode]) -> dict [int, list [str]]:
    """Get all summaries grouped by level."""
    summaries: dict [int, list [str]] = {}
    for node in tree.values ():
      if node.level not in summaries:
        summaries [node.level] = []
      summaries [node.level].append (node.summary)
    return summaries

  def save_tree (self, tree: dict [str, TreeNode], path: Path) -> None:
    """Save tree to JSON file."""
    data = {node_id: {
        "id": node.id, "level": node.level, "text": node.text, "summary": node.summary, "children": node.children,
        "parent": node.parent, "metadata": node.metadata,
    } for node_id, node in tree.items ()}
    path.parent.mkdir (parents = True, exist_ok = True)
    with open (path, "w", encoding = "utf-8") as f:
      json.dump (data, f, ensure_ascii = False, indent = 2)
    logger.info (f"Saved RAPTOR tree to {path}")

  def load_tree (self, path: Path) -> dict [str, TreeNode]:
    """Load tree from JSON file."""
    with open (path, encoding = "utf-8") as f:
      data = json.load (f)

    tree = {}
    for node_id, node_data in data.items ():
      tree [node_id] = TreeNode (id = node_data ["id"], level = node_data ["level"], text = node_data ["text"],
          summary = node_data ["summary"], children = node_data.get ("children", []), parent = node_data.get ("parent"),
          metadata = node_data.get ("metadata", {}), )

    logger.info (f"Loaded RAPTOR tree from {path}: {len (tree)} nodes")
    return tree
