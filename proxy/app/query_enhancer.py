# proxy/app/query_enhancer.py
"""
Query enhancement for better retrieval quality.

Supports:
- HyDE (Hypothetical Document Embedding): generate a fake answer, use it for search
- Multi-query expansion: generate query variants for fusion retrieval
- Complex query decomposition: break complex queries into sub-queries
- Metadata filter extraction: extract structured filters from natural language
"""

import logging
import re
from typing import Any

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
            new_parts = []
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
