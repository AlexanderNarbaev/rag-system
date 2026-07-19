# proxy/app/query_enhancer.py
"""Query enhancement for better retrieval quality.

Supports:
- HyDE (Hypothetical Document Embedding): generate a fake answer, use it for search
- Multi-query expansion: generate query variants for fusion retrieval
- Complex query decomposition: break complex queries into sub-queries
- Metadata filter extraction: extract structured filters from natural language
- Multi-query rewriting with RRF fusion (Rewrite-Retrieve-Read pattern)
"""

import logging
import re
from collections.abc import Callable
from typing import Any

from proxy.app.core.retrieval import reciprocal_rank_fusion

logger = logging.getLogger(__name__)


class QueryEnhancer:
    """Enhances queries for better retrieval."""

    QUERY_PREFIXES = [
        "Passage: ",
        "Answer: ",
        "The document states that ",
    ]

    METADATA_PATTERNS = {
        "version": [
            r"version\s*[:=]?\s*(\S+)",
            r"v(?:ersion)?\.?\s*([\d.]+)",
            r"release\s+(\S+)",
        ],
        "date": [
            r"(?:from|since|after|before)\s+(\d{4}-\d{2}-\d{2})",
            r"date\s*[:=]?\s*(\d{4}-\d{2}-\d{2})",
            r"(\d{4}-\d{2}-\d{2})",
        ],
        "author": [
            r"(?:by|from|author)\s+['\"]?([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)['\"]?",
            r"written\s+by\s+['\"]?([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)['\"]?",
        ],
        "type": [
            r"(?:type|kind)\s*[:=]?\s*(\w+)",
            r"(specification|guide|tutorial|reference|manual)",
        ],
        "project": [
            r"project\s*[:=]?\s*['\"]?(\w+)['\"]?",
            r"in\s+(?:the\s+)?['\"]?(\w+)\s+project['\"]?",
        ],
    }

    def hyde_enhance(self, query: str) -> str:
        """Hypothetical Document Embedding: generate fake answer, use it for search."""
        hyde_prefixes = [
            "Here is the answer to the query:",
            "The document that answers this question contains:",
            "According to the documentation,",
        ]
        joined = " ".join(hyde_prefixes)
        return f"{joined} {query}"

    def multi_query_expand(self, query: str, num_variants: int = 3) -> list[str]:
        """Generate multiple query variants for fusion retrieval."""
        variants = [query]
        keywords = [w for w in query.split() if len(w) > 3]
        lower = query.lower()

        if lower.startswith("how") and len(keywords) > 1:
            variants.append(f"steps to {query[4:].strip()}")
            variants.append(f"guide for {query[4:].strip()}")
        elif lower.startswith("what"):
            variants.append(f"definition of {query[5:].strip()}")
            variants.append(f"explain {query[5:].strip()}")
        elif lower.startswith("why"):
            variants.append(f"reason for {query[4:].strip()}")
            variants.append(f"cause of {query[4:].strip()}")
        elif " vs " in lower:
            parts = query.split(" vs ", 1)
            variants.append(f"difference between {parts[0].strip()} and {parts[1].strip()}")
            variants.append(f"comparison of {parts[0].strip()} and {parts[1].strip()}")
        elif len(keywords) >= 2:
            variants.append(" ".join(keywords))
            variants.append(f"{keywords[0]} related to {keywords[1]}")

        return list(dict.fromkeys(variants))[: num_variants + 1]

    def decompose_complex_query(self, query: str) -> list[str]:
        """Break complex query into sub-queries."""
        delimiters = [
            r"\band\b(?! so| then| also)",
            r";",
            r"\.(?=\s*[A-Z])",
            r"\balso\b",
            r"\bplus\b",
        ]
        sub_queries = [query]
        for delim in delimiters:
            new_parts: list[str] = []
            for sq in sub_queries:
                parts = re.split(delim, sq, flags=re.IGNORECASE)
                new_parts.extend(p.strip() for p in parts if p.strip())
            sub_queries = new_parts
        if len(sub_queries) == 1:
            sub_queries = [query]
        return sub_queries

    def extract_metadata_filters(self, query: str) -> dict[str, str]:
        """Extract metadata filters from natural language query."""
        filters: dict[str, str] = {}
        for field, patterns in self.METADATA_PATTERNS.items():
            for pattern in patterns:
                match = re.search(pattern, query, re.IGNORECASE)
                if match:
                    filters[field] = match.group(1).strip()
                    break
        return filters

    def enhance(self, query: str) -> dict[str, Any]:
        """Full enhancement: returns HyDE query, variants, sub-queries, and filters."""
        return {
            "hyde_query": self.hyde_enhance(query),
            "variants": self.multi_query_expand(query),
            "sub_queries": self.decompose_complex_query(query),
            "metadata_filters": self.extract_metadata_filters(query),
        }


def generate_query_variants(query: str, num_variants: int = 3) -> list[str]:
    """Generate multiple query formulations for better retrieval.

    Based on: Rewrite-Retrieve-Read (arxiv:2305.14283)

    Strategies:
    1. Original query
    2. Formal/technical version
    3. Simplified version
    4. Question form (if not already)
    5. Keyword extraction
    """
    variants = [query]  # Always include original

    # Strategy 1: Add context prefix
    if not query.startswith(("what", "how", "why", "when", "where", "who")):
        variants.append(f"explain {query}")

    # Strategy 2: Extract key terms (remove stop words)
    stop_words = {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "can",
        "shall",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "as",
        "into",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "between",
        "out",
        "off",
        "over",
        "under",
        "again",
        "further",
        "then",
        "once",
    }
    words = query.lower().split()
    keywords = [w for w in words if w not in stop_words and len(w) > 2]
    if keywords:
        variants.append(" ".join(keywords))

    # Strategy 3: Question form
    if not query.endswith("?"):
        variants.append(f"{query}?")

    # Strategy 4: Rephrase
    variants.append(f"what is {query}")

    return variants[: num_variants + 1]  # +1 for original


def multi_query_search(
    query: str,
    search_fn: Callable[..., Any],
    num_variants: int = 3,
    top_k: int = 10,
) -> list[dict[str, Any]]:
    """Search with multiple query variants and fuse results with RRF.

    Chains pairwise RRF fusions when more than two result sets are present,
    since ``reciprocal_rank_fusion`` accepts exactly two lists.

    Based on: Multi-Query RAG pattern.
    """
    variants = generate_query_variants(query, num_variants)
    logger.info("Multi-query: generated %d variants: %s", len(variants), variants)

    all_results: list[list[dict[str, Any]]] = []
    for variant in variants:
        try:
            results = search_fn(query=variant, top_k=top_k)
            all_results.append(results)
        except Exception as e:
            logger.warning("Search failed for variant '%s': %s", variant, e)

    if not all_results:
        return []

    if len(all_results) == 1:
        return all_results[0]

    # Chain pairwise RRF: fuse first two, then fuse result with next, etc.
    fused = reciprocal_rank_fusion(all_results[0], all_results[1])
    for result_set in all_results[2:]:
        fused = reciprocal_rank_fusion(fused, result_set)

    return fused[:top_k]
