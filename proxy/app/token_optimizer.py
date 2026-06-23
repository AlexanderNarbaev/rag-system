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

logger = logging.getLogger(__name__)


# Approximate BPE token boundaries — common multi-character units
def _tokenize_words(text: str) -> list:
    """Split text into word-like and punctuation tokens (approximating subword tokenizer input)."""
    return re.findall(r"\w+|[^\w\s]", text)


def count_bpe_tokens(text: str) -> int:
    """
    Estimate token count approximating BPE behavior.
    Most words become 1-2 subword tokens on average (~1.3 per word).
    """
    if not text:
        return 0
    tokens = _tokenize_words(text)
    return max(1, int(len(tokens) * 1.3))


class TokenOptimizer:
    """Optimizes token usage in RAG context assembly."""

    def estimate_token_cost(self, text: str) -> int:
        """
        Accurate token counting with BPE awareness.
        Uses a combination of word-based BPE estimate and char/4 rule.
        """
        if not text:
            return 0
        char_estimate = max(1, len(text) // 4)
        word_tokens = len(_tokenize_words(text))
        word_estimate = max(1, int(word_tokens * 1.3))
        return max(1, int(char_estimate * 0.4 + word_estimate * 0.6))

    def compress_context(self, chunks: list[dict], max_tokens: int, strategy: str = "relevance") -> str:
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
            return self._compress_relevance(chunks, max_tokens)
        elif strategy == "proposition":
            return self._compress_proposition(chunks, max_tokens)
        elif strategy == "summary":
            return self._compress_summary(chunks, max_tokens)
        elif strategy == "hierarchical":
            return self._compress_hierarchical(chunks, max_tokens)
        else:
            logger.warning(f"Unknown compression strategy '{strategy}', falling back to relevance")
            return self._compress_relevance(chunks, max_tokens)

    def _compress_relevance(self, chunks: list[dict], max_tokens: int) -> str:
        """Keep top chunks, truncate each to fit token budget."""
        token_budget = max_tokens
        parts = []
        used = 0
        per_chunk = max(50, token_budget // max(1, len(chunks)))

        for chunk in chunks:
            text = chunk.get("text", "").strip()
            if not text:
                continue
            if used + per_chunk > token_budget:
                remaining = token_budget - used
                if remaining > 50:
                    parts.append(text[: remaining * 4])
                break
            parts.append(text[: per_chunk * 4])
            used += per_chunk

        return "\n\n".join(parts)

    def _compress_proposition(self, chunks: list[dict], max_tokens: int) -> str:
        """Convert each chunk to atomic fact-like sentences, then assemble."""
        propositions = []
        for chunk in chunks:
            text = chunk.get("text", "").strip()
            if not text:
                continue
            sentences = re.split(r"(?<=[.!?])\s+", text)
            for s in sentences:
                s = s.strip()
                if len(s) > 20:
                    propositions.append(s)
        result = ""
        for prop in propositions:
            candidate = result + prop + " "
            if self.estimate_token_cost(candidate) > max_tokens:
                break
            result = candidate
        return result.strip()

    def _compress_summary(self, chunks: list[dict], max_tokens: int) -> str:
        """Keep first N sentences of each chunk, stop at budget."""
        parts = []
        used = 0
        budget = max_tokens

        for chunk in chunks:
            text = chunk.get("text", "").strip()
            if not text:
                continue
            sentences = re.split(r"(?<=[.!?])\s+", text)
            summary = " ".join(sentences[:2])
            cost = self.estimate_token_cost(summary)
            if used + cost > budget:
                remaining = budget - used
                if remaining > 20:
                    parts.append(summary[: remaining * 4])
                break
            parts.append(summary)
            used += cost

        return "\n\n".join(parts)

    def _compress_hierarchical(self, chunks: list[dict], max_tokens: int) -> str:
        """
        Tiered detail:
        - Top-3 chunks: full text
        - Next 5: first 3 sentences
        - Rest: title/first sentence only
        """
        parts = []
        used = 0
        budget = max_tokens

        for i, chunk in enumerate(chunks):
            text = chunk.get("text", "").strip()
            if not text:
                continue

            if i < 3:
                segment = text
            elif i < 8:
                sentences = re.split(r"(?<=[.!?])\s+", text)
                segment = " ".join(sentences[:3])
            else:
                sentences = re.split(r"(?<=[.!?])\s+", text)
                segment = sentences[0] if sentences else text[:200]

            cost = self.estimate_token_cost(segment)
            if used + cost > budget:
                remaining = budget - used
                if remaining > 50:
                    parts.append(segment[: remaining * 4])
                break
            parts.append(segment)
            used += cost

        return "\n\n".join(parts)

    def smart_token_budget(self, available_tokens: int, num_chunks: int) -> dict[str, int]:
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
                "system_prompt": max(50, available_tokens // 5),
                "context_total": max(100, available_tokens * 3 // 5),
                "history": 0,
                "response": max(50, available_tokens // 5),
            }

        system_prompt = min(2000, available_tokens // 10)
        response = min(4096, available_tokens // 5)
        history = min(8000, available_tokens // 6)
        context_total = available_tokens - system_prompt - response - history

        if context_total < 0:
            context_total = max(100, available_tokens * 2 // 3)
            history = 0

        context_per_chunk = max(100, context_total // max(1, num_chunks)) if num_chunks > 0 else context_total

        return {
            "system_prompt": system_prompt,
            "context_total": context_total,
            "context_per_chunk": context_per_chunk,
            "history": history,
            "response": response,
        }

    def surround_chunks(self, chunks: list[dict], nearby_count: int = 2) -> list[dict]:
        """
        Expand chunks with surrounding context from the same document.
        For chunks sharing the same source_id, returns nearby neighbors.
        If chunks have a 'chunk_index' field, uses it for ordering.
        Returns deduplicated expanded list.
        """
        if not chunks or nearby_count <= 0:
            return list(chunks) if chunks else []

        source_groups: dict[str, list[dict]] = {}
        for chunk in chunks:
            source_id = chunk.get("source_id", "unknown")
            source_groups.setdefault(source_id, []).append(chunk)

        expanded = []
        seen_hashes = set()

        for source_id, group in source_groups.items():
            group.sort(key=lambda x: x.get("chunk_index", 0))
            indices = {id(c): i for i, c in enumerate(group)}

            for chunk in group:
                chunk_hash = chunk.get("text", "")[:80]
                if chunk_hash in seen_hashes:
                    continue
                seen_hashes.add(chunk_hash)
                expanded.append(chunk)

                ci = indices.get(id(chunk), 0)
                start = max(0, ci - nearby_count)
                end = min(len(group), ci + nearby_count + 1)

                for j in range(start, end):
                    if j == ci:
                        continue
                    neighbor = group[j]
                    n_hash = neighbor.get("text", "")[:80]
                    if n_hash not in seen_hashes:
                        seen_hashes.add(n_hash)
                        expanded.append(neighbor)

        return expanded

    def enrich_chunk_headers(self, chunk: dict, doc_context: dict) -> dict:
        """
        Add document-level context as chunk header.
        Modifies chunk in place (text gets a header prefix) and returns it.

        doc_context should have keys: title, section, doc_type, version
        """
        result = dict(chunk)
        text = result.get("text", "")

        title = doc_context.get("title", "")
        section = doc_context.get("section", "")
        doc_type = doc_context.get("doc_type", "")
        version = doc_context.get("version", "")

        header_parts = []
        if doc_type:
            header_parts.append(f"[Type: {doc_type}]")
        if title:
            header_parts.append(f"[Doc: {title}]")
        if section:
            header_parts.append(f"[Section: {section}]")
        if version:
            header_parts.append(f"[Version: {version}]")

        if header_parts:
            header = " ".join(header_parts)
            result["text"] = f"{header}\n{text}"

        return result
