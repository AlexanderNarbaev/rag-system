# proxy/app/core/context/compression.py
"""Context compression and multi-modal assembly for RAG proxy."""

import logging
import re
from typing import Any

from proxy.app.core.context.builder import KnowledgeStrip, estimate_tokens

logger = logging.getLogger (__name__)

MULTI_MODAL_ENABLED = True


def decompose_to_strips (
    chunks_with_scores: list [tuple [dict [str, Any], float]], relevance_threshold: float = 0.0, ) -> list [
  KnowledgeStrip]:
  """Split each chunk into sentence-level knowledge strips.

  Each strip inherits the parent chunk's score, source_type, and doc_title.
  Strips below relevance_threshold are filtered out.
  """
  if not chunks_with_scores:
    return []
  
  strips = []
  for chunk_idx, (chunk, score) in enumerate (chunks_with_scores):
    text = chunk.get ("text", "").strip ()
    if not text:
      continue
    
    source_type = chunk.get ("source_type", "unknown")
    doc_title = chunk.get ("doc_title", "")
    
    sentences = re.split (r"(?<=[.!?])\s+", text)
    for sent_idx, sentence in enumerate (sentences):
      sentence = sentence.strip ()
      if len (sentence) < 10:
        continue
      
      strip = KnowledgeStrip (text = sentence, score = score, source_type = source_type, doc_title = doc_title,
          chunk_index = chunk_idx, sentence_index = sent_idx, )
      strips.append (strip)
  
  if relevance_threshold > 0:
    strips = [s for s in strips if s.score >= relevance_threshold]
  
  logger.debug (f"CRAG decomposition: {len (chunks_with_scores)} chunks -> {len (strips)} strips")
  return strips


def assemble_multimodal_context (
    chunks: list [str], images: list [str] | None = None, tables: list [str] | None = None,
    code_blocks: list [str] | None = None, max_tokens: int = 120000, ) -> str:
  """Assemble multi-modal context: interleave text, tables, code, image captions.

  Token-aware: allocates budget proportionally across modalities.
  Graceful degradation: all modal inputs are optional.

  :param chunks: list of text chunk strings
  :param images: list of image caption strings
  :param tables: list of Markdown table strings
  :param code_blocks: list of code block strings
  :param max_tokens: maximum total tokens
  :return: assembled multi-modal context string
  """
  if not MULTI_MODAL_ENABLED:
    return "\n\n".join (chunks)
  
  images = images or []
  tables = tables or []
  code_blocks = code_blocks or []
  
  total_items = len (chunks) + len (images) + len (tables) + len (code_blocks)
  if total_items == 0:
    return ""
  
  sections = []
  
  text_budget = int (max_tokens * 0.5)
  table_budget = int (max_tokens * 0.2)
  code_budget = int (max_tokens * 0.2)
  
  current_tokens = 0
  
  for chunk in chunks:
    tokens = estimate_tokens (chunk)
    if current_tokens + tokens > text_budget:
      if text_budget - current_tokens > 50:
        sections.append (chunk [: (text_budget - current_tokens) * 4] + "...")
      break
    sections.append (chunk)
    current_tokens += tokens
  
  table_start = 0
  for table in tables:
    tokens = estimate_tokens (table)
    if table_start + tokens > table_budget:
      break
    sections.append (table)
    table_start += tokens
  
  code_start = 0
  for code in code_blocks:
    tokens = estimate_tokens (code)
    if code_start + tokens > code_budget:
      break
    framed = f"```\n{code}\n```"
    sections.append (framed)
    code_start += tokens
  
  for img in images:
    tokens = estimate_tokens (img)
    if tokens < 20:
      sections.append (img)
  
  return "\n\n".join (sections)
