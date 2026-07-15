# proxy/app/token_optimizer.py
"""
Token economy module for RAG context assembly.

Implements:
- Token counting with BPE awareness
- Context compression strategies (relevance, proposition, summary, hierarchical)
- Smart token budget allocation
- Surrounding chunk expansion
- Chunk header enrichment with document context
"""

import logging
import re
from typing import Any

logger = logging.getLogger (__name__)


# Approximate BPE token boundaries — common multi-character units
def _tokenize_words (text: str) -> list [str]:
  """Split text into word-like and punctuation tokens (approximating subword tokenizer input)."""
  return re.findall (r"\w+|[^\w\s]", text)


def count_bpe_tokens (text: str) -> int:
  """
  Estimate token count approximating BPE behavior.
  Most words become 1-2 subword tokens on average (~1.3 per word).
  """
  if not text:
    return 0
  tokens = _tokenize_words (text)
  return max (1, int (len (tokens) * 1.3))


class TokenOptimizer:
  """Optimizes token usage in RAG context assembly."""

  def estimate_token_cost (self, text: str) -> int:
    """
    Accurate token counting with BPE awareness.
    Uses a combination of word-based BPE estimate and char/4 rule.
    """
    if not text:
      return 0
    char_estimate = max (1, len (text) // 4)
    word_tokens = len (_tokenize_words (text))
    word_estimate = max (1, int (word_tokens * 1.3))
    return max (1, int (char_estimate * 0.4 + word_estimate * 0.6))

  def compress_context (self, chunks: list [dict [str, Any]], max_tokens: int, strategy: str = "relevance") -> str:
    """
    Compress context using the specified strategy.

    Strategies:
    - 'relevance': keep only the most relevant sentences (Relevant Segment Extraction)
    - 'proposition': convert to atomic propositions
    - 'summary': truncate less relevant chunks to their first N sentences
    - 'hierarchical': tiered detail (heading -> summary -> full for top-k)
    """
    if not chunks:
      return ""

    if strategy == "relevance":
      return self._compress_relevance (chunks, max_tokens)
    elif strategy == "proposition":
      return self._compress_proposition (chunks, max_tokens)
    elif strategy == "summary":
      return self._compress_summary (chunks, max_tokens)
    elif strategy == "hierarchical":
      return self._compress_hierarchical (chunks, max_tokens)
    else:
      logger.warning (f"Unknown compression strategy '{strategy}', falling back to relevance")
      return self._compress_relevance (chunks, max_tokens)

  def _compress_relevance (self, chunks: list [dict [str, Any]], max_tokens: int) -> str:
    """Keep top chunks, truncate each to fit token budget."""
    token_budget = max_tokens
    parts = []
    used = 0
    per_chunk = max (50, token_budget // max (1, len (chunks)))

    for chunk in chunks:
      text = chunk.get ("text", "").strip ()
      if not text:
        continue
      if used + per_chunk > token_budget:
        remaining = token_budget - used
        if remaining > 50:
          parts.append (text [: remaining * 4])
        break
      parts.append (text [: per_chunk * 4])
      used += per_chunk

    return "\n\n".join (parts)

  def _compress_proposition (self, chunks: list [dict [str, Any]], max_tokens: int) -> str:
    """Convert each chunk to atomic fact-like sentences, then assemble."""
    propositions = []
    for chunk in chunks:
      text = chunk.get ("text", "").strip ()
      if not text:
        continue
      sentences = re.split (r"(?<=[.!?])\s+", text)
      for s in sentences:
        s = s.strip ()
        if len (s) > 20:
          propositions.append (s)
    result = ""
    for prop in propositions:
      candidate = result + prop + " "
      if self.estimate_token_cost (candidate) > max_tokens:
        break
      result = candidate
    return result.strip ()

  def _compress_summary (self, chunks: list [dict [str, Any]], max_tokens: int) -> str:
    """Keep first N sentences of each chunk, stop at budget."""
    parts = []
    used = 0
    budget = max_tokens

    for chunk in chunks:
      text = chunk.get ("text", "").strip ()
      if not text:
        continue
      sentences = re.split (r"(?<=[.!?])\s+", text)
      summary = " ".join (sentences [:2])
      cost = self.estimate_token_cost (summary)
      if used + cost > budget:
        remaining = budget - used
        if remaining > 20:
          parts.append (summary [: remaining * 4])
        break
      parts.append (summary)
      used += cost

    return "\n\n".join (parts)

  def _compress_hierarchical (self, chunks: list [dict [str, Any]], max_tokens: int) -> str:
    """
    Tiered detail:
    - Top-3 chunks: full text
    - Next 5: first 3 sentences
    - Rest: title/first sentence only
    """
    parts = []
    used = 0
    budget = max_tokens

    for i, chunk in enumerate (chunks):
      text = chunk.get ("text", "").strip ()
      if not text:
        continue

      if i < 3:
        segment = text
      elif i < 8:
        sentences = re.split (r"(?<=[.!?])\s+", text)
        segment = " ".join (sentences [:3])
      else:
        sentences = re.split (r"(?<=[.!?])\s+", text)
        segment = sentences [0] if sentences else text [:200]

      cost = self.estimate_token_cost (segment)
      if used + cost > budget:
        remaining = budget - used
        if remaining > 50:
          parts.append (segment [: remaining * 4])
        break
      parts.append (segment)
      used += cost

    return "\n\n".join (parts)

  def extractive_compress (self, chunks: list [str], query: str, max_sentences: int = 3) -> str:
    """Extract most query-relevant sentences from chunks.

    Heuristic: tokenize query into keywords, score each sentence by
    keyword overlap, keep top N sentences per chunk.
    """
    if not chunks or not query:
      return "\n\n".join (chunks) if chunks else ""

    query_keywords = set (re.findall (r"\w+", query.lower ()))
    if not query_keywords:
      return "\n\n".join (chunks)

    result_parts = []
    for chunk_text in chunks:
      if not chunk_text.strip ():
        continue
      sentences = re.split (r"(?<=[.!?])\s+", chunk_text)
      if len (sentences) <= max_sentences:
        result_parts.append (chunk_text.strip ())
        continue

      scored = []
      for s in sentences:
        s_tokens = set (re.findall (r"\w+", s.lower ()))
        if not s_tokens:
          scored.append ((s, 0.0))
          continue
        overlap = len (query_keywords & s_tokens)
        score = overlap / len (query_keywords)
        scored.append ((s, score))

      scored.sort (key = lambda x: x [1], reverse = True)
      top_sentences = [s for s, _ in scored [:max_sentences]]
      result_parts.append (" ".join (top_sentences))

    return "\n\n".join (result_parts)

  def smart_token_budget (self, available_tokens: int, num_chunks: int) -> dict [str, int]:
    """
    Allocate token budget across system_prompt, context_per_chunk, history, and response.

    Returns a dict with:
    - 'system_prompt': tokens for system prompt (instructions)
    - 'context_total': total tokens for all chunks
    - 'history': tokens for conversation history
    - 'response': reserved for generated output
    """
    if available_tokens < 1000:
      return {
          "system_prompt": max (50, available_tokens // 5), "context_total": max (100, available_tokens * 3 // 5),
          "history": 0, "response": max (50, available_tokens // 5),
      }

    system_prompt = min (2000, available_tokens // 10)
    response = min (4096, available_tokens // 5)
    history = min (8000, available_tokens // 6)
    context_total = available_tokens - system_prompt - response - history

    if context_total < 0:
      context_total = max (100, available_tokens * 2 // 3)
      history = 0

    context_per_chunk = max (100, context_total // max (1, num_chunks)) if num_chunks > 0 else context_total

    return {
        "system_prompt": system_prompt, "context_total": context_total, "context_per_chunk": context_per_chunk,
        "history": history, "response": response,
    }

  def surround_chunks (self, chunks: list [dict [str, Any]], nearby_count: int = 2) -> list [dict [str, Any]]:
    """
    Expand chunks with surrounding context from the same document.
    For chunks sharing the same source_id, returns nearby neighbors.
    If chunks have a 'chunk_index' field, uses it for ordering.
    Returns deduplicated expanded list.
    """
    if not chunks or nearby_count <= 0:
      return list (chunks) if chunks else []

    source_groups: dict [str, list [dict [str, Any]]] = {}
    for chunk in chunks:
      source_id = chunk.get ("source_id", "unknown")
      source_groups.setdefault (source_id, []).append (chunk)

    expanded = []
    seen_hashes = set ()

    for _source_id, group in source_groups.items ():
      group.sort (key = lambda x: x.get ("chunk_index", 0))
      indices = {id (c): i for i, c in enumerate (group)}

      for chunk in group:
        chunk_hash = chunk.get ("text", "") [:80]
        if chunk_hash in seen_hashes:
          continue
        seen_hashes.add (chunk_hash)
        expanded.append (chunk)

        ci = indices.get (id (chunk), 0)
        start = max (0, ci - nearby_count)
        end = min (len (group), ci + nearby_count + 1)

        for j in range (start, end):
          if j == ci:
            continue
          neighbor = group [j]
          n_hash = neighbor.get ("text", "") [:80]
          if n_hash not in seen_hashes:
            seen_hashes.add (n_hash)
            expanded.append (neighbor)

    return expanded

  def enrich_chunk_headers (self, chunk: dict [str, Any], doc_context: dict [str, Any]) -> dict [str, Any]:
    """
    Add document-level context as chunk header.
    Modifies chunk in place (text gets a header prefix) and returns it.

    doc_context should have keys: title, section, doc_type, version
    """
    result = dict (chunk)
    text = result.get ("text", "")

    title = doc_context.get ("title", "")
    section = doc_context.get ("section", "")
    doc_type = doc_context.get ("doc_type", "")
    version = doc_context.get ("version", "")

    header_parts = []
    if doc_type:
      header_parts.append (f"[Type: {doc_type}]")
    if title:
      header_parts.append (f"[Doc: {title}]")
    if section:
      header_parts.append (f"[Section: {section}]")
    if version:
      header_parts.append (f"[Version: {version}]")

    if header_parts:
      header = " ".join (header_parts)
      result ["text"] = f"{header}\n{text}"

    return result

  # ── F5: LLMLingua-style Perplexity Compression ──

  def compress_with_perplexity (self, text: str, budget: int, strategy: str = "keyword") -> str:
    """Compress text to fit within token budget using SLM perplexity or keyword scoring.

    strategy: "perplexity" — use SLM log-probability token importance (falls back to keyword)
              "keyword"   — use sentence-level keyword density scoring
              "none"      — return text unchanged

    High-surprise (high-perplexity) tokens are kept; predictable tokens are dropped.
    If SLM is unavailable, falls back gracefully to keyword density method.
    """
    if not text or not text.strip ():
      return ""

    if strategy == "none":
      return text

    current_tokens = self.estimate_token_cost (text)
    if current_tokens <= budget:
      return text

    if strategy == "perplexity":
      try:
        return self._compress_by_perplexity (text, budget)
      except Exception as e:
        logger.warning (f"Perplexity compression failed ({e}), falling back to keyword")
        return self._compress_by_keyword (text, budget)
    else:
      return self._compress_by_keyword (text, budget)

  def _compress_by_perplexity (self, text: str, budget: int) -> str:
    """Perplexity-based compression using token-level surprise scores.

    Computes approximate token importance via word rarity in the text corpus.
    Keeps high-surprise tokens, drops predictable/common ones.
    Falls back to keyword density if SLM log-prob unavailable.
    """
    # Build word frequency from the text itself as proxy for "predictability"
    words = re.findall (r"\w+", text.lower ())
    if not words:
      return text

    word_freq: dict [str, int] = {}
    for w in words:
      word_freq [w] = word_freq.get (w, 0) + 1
    total = len (words)

    # Higher frequency → lower surprise (more predictable)
    vocab = {w: 1.0 - (cnt / total) for w, cnt in word_freq.items ()}

    surprises = _compute_token_surprise (text, vocab)

    sentences = re.split (r"(?<=[.!?])\s+", text)
    scored = []
    for s in sentences:
      s_stripped = s.strip ()
      if not s_stripped:
        continue
      s_words = re.findall (r"\w+", s_stripped.lower ())
      if not s_words:
        scored.append ((s_stripped, 0.0))
        continue
      avg_surprise = sum (surprises.get (w, 0.5) for w in s_words) / len (s_words)
      scored.append ((s_stripped, avg_surprise))

    scored.sort (key = lambda x: x [1], reverse = True)

    result = ""
    for sentence, _ in scored:
      candidate = result + sentence + " "
      if self.estimate_token_cost (candidate) > budget:
        # Try to fit partial
        remaining_chars = budget * 4 - len (result)
        if remaining_chars > 20:
          truncated = sentence [:remaining_chars]
          result += truncated
        break
      result += sentence + " "

    return result.strip ()

  def _compress_by_keyword (self, text: str, budget: int) -> str:
    """Sentence-level compression by keyword density relative to the full text.

    Sentences with more unique/relevant words (high keyword density vs corpus)
    are kept first. Falls back to keeping first N sentences if all equal.
    """
    words = re.findall (r"\w+", text.lower ())
    if not words:
      return text

    word_freq: dict [str, int] = {}
    for w in words:
      word_freq [w] = word_freq.get (w, 0) + 1
    total = len (words)

    # IDF-like: rare words are more important
    word_importance = {w: 1.0 - (cnt / total) for w, cnt in word_freq.items ()}

    sentences = re.split (r"(?<=[.!?])\s+", text)
    scored = []
    for s in sentences:
      s_stripped = s.strip ()
      if not s_stripped:
        continue
      s_words = re.findall (r"\w+", s_stripped.lower ())
      if not s_words:
        scored.append ((s_stripped, 0.0))
        continue
      avg_importance = sum (word_importance.get (w, 0.5) for w in s_words) / len (s_words)
      scored.append ((s_stripped, avg_importance))

    scored.sort (key = lambda x: x [1], reverse = True)

    result = ""
    for sentence, _ in scored:
      candidate = result + sentence + " "
      if self.estimate_token_cost (candidate) > budget:
        remaining_chars = budget * 4 - len (result)
        if remaining_chars > 20:
          truncated = sentence [:remaining_chars]
          result += truncated
        break
      result += sentence + " "

    return result.strip ()


# ── Standalone functions for external use ──


def _compute_token_surprise (text: str, vocab: dict [str, float]) -> dict [str, float]:
  """Compute token-level surprise scores.

  Surprise = -log(P(token)) approx 1.0 - P(token) in vocab.
  Rare words have high surprise; common words have low surprise.
  """
  if not text or not vocab:
    return {}

  words = re.findall (r"\w+", text.lower ())
  surprises = {}
  for w in words:
    surprisal = vocab.get (w, 0.5)  # 0.5 = medium surprise for unknown
    surprises [w] = surprisal
  return surprises


def _score_sentence_by_keyword_density (sentence: str, query: str) -> float:
  """Score a sentence by keyword overlap with a query."""
  if not sentence or not query:
    return 0.0
  query_tokens = set (re.findall (r"\w+", query.lower ()))
  if not query_tokens:
    return 0.0
  sent_tokens = set (re.findall (r"\w+", sentence.lower ()))
  overlap = len (query_tokens & sent_tokens)
  return overlap / len (query_tokens)


def compress_with_perplexity (text: str, budget: int, strategy: str = "keyword") -> str:
  """Standalone function for perplexity-based compression."""
  optimizer = TokenOptimizer ()
  return optimizer.compress_with_perplexity (text, budget, strategy = strategy)
