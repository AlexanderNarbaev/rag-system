# etl/indexer/chunk_enricher.py
"""SLM-based chunk enrichment for RAG ETL pipeline.

For each chunk, uses a lightweight SLM to generate:
1. Keywords (5-10 relevant terms for search)
2. Entities (people, products, technologies mentioned)
3. Hypothetical questions (2-3 HyDE-style questions this chunk could answer)
4. Summary (1-2 sentence summary)

Falls back to heuristic extraction (spaCy NER, regex, templates) when SLM is
unavailable or disabled. Dramatically improves retrieval quality — the chunk
is found even when the user's query doesn't match the exact text.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import requests

logger = logging.getLogger(__name__)

try:
    import spacy as _spacy

    NLP_AVAILABLE = True
except ImportError:
    _spacy = None  # type: ignore[assignment]
    NLP_AVAILABLE = False

ENRICHMENT_PROMPT_TEMPLATE = """Analyze this technical text and return a JSON object with these fields:
- "keywords": list of 5-10 key terms for search (technical terms, concepts, technologies)
- "entities": list of named entities found (people, products, organizations, technologies)
- "hyde_questions": list of 2-3 questions this text could answer (user would ask these)
- "summary": one-line summary in Russian (1 sentence, under 150 chars)

Return ONLY valid JSON, no other text. Example:
{{
  "keywords": ["RAG", "retrieval", "embedding", "vector database"],
  "entities": ["Qdrant", "BAAI/bge-m3", "Transformer"],
  "hyde_questions": ["Как работает гибридный поиск?", "Какие эмбеддеры использовать с Qdrant?"],
  "summary": "Обзор гибридного поиска в Qdrant с dense и sparse эмбеддерами"
}}

Text to analyze:
{chunk_text}
"""


class ChunkEnricher:
    """Enriches chunks with SLM-generated metadata.

    Uses an OpenAI-compatible chat completions API to generate keywords,
    entities, HyDE questions, and a summary. Falls back to heuristic
    extraction when SLM is unavailable or disabled.

    Usage:
        enricher = ChunkEnricher(
            slm_endpoint="http://rag-proxy:8080/v1",
            model="qwen2.5-3b",
        )
        enriched = enricher.enrich("chunk text", {"doc_title": "My Doc"})
        print(enriched["keywords"], enriched["summary"])
    """

    def __init__(
        self,
        slm_endpoint: str = "",
        model: str = "qwen2.5-3b",
        api_key: str = "",
        max_concurrent: int = 5,
        fallback_to_heuristic: bool = True,
        timeout: int = 30,
    ):
        self._endpoint = slm_endpoint.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._max_concurrent = max_concurrent
        self._fallback_to_heuristic = fallback_to_heuristic
        self._timeout = timeout
        self._semaphore: asyncio.Semaphore | None = None
        self._headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"

        self._nlp: Any = None
        if NLP_AVAILABLE and fallback_to_heuristic:
            self._init_spacy()

    def _init_spacy(self) -> None:
        if _spacy is None:
            return
        try:
            self._nlp = _spacy.load("ru_core_news_sm")
        except Exception:
            try:
                self._nlp = _spacy.load("en_core_web_sm")
            except Exception:
                logger.warning("spaCy model not found. Heuristic fallback will use regex only.")

    def _get_semaphore(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self._max_concurrent)
        return self._semaphore

    @property
    def is_enabled(self) -> bool:
        return bool(self._endpoint and self._model)

    def enrich(self, chunk_text: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        """Enrich a single chunk with SLM-generated metadata.

        :param chunk_text: The chunk text to analyze (truncated to 2000 chars for SLM).
        :param metadata: Optional metadata dict (doc_title, source_type, etc.) for context.
        :return: dict with keys: keywords, entities, hyde_questions, summary.
        """
        if metadata is None:
            metadata = {}

        if not chunk_text or not chunk_text.strip():
            return self._empty_result()

        if self.is_enabled:
            try:
                result = self._call_slm(chunk_text[:2000])
                return self._validate_result(result, chunk_text, metadata)
            except Exception as e:
                logger.warning("SLM enrichment failed: %s. Falling back to heuristic.", e)
                if self._fallback_to_heuristic:
                    return self._heuristic_fallback(chunk_text, metadata)

        if self._fallback_to_heuristic:
            return self._heuristic_fallback(chunk_text, metadata)

        return self._empty_result()

    def _call_slm(self, chunk_text: str) -> dict[str, Any]:
        """Call SLM via OpenAI-compatible /v1/chat/completions API.

        Uses chat format with a system prompt for structured JSON output.
        """
        prompt = ENRICHMENT_PROMPT_TEMPLATE.format(chunk_text=chunk_text)
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a text analyzer that returns ONLY valid JSON. No other output.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 512,
        }

        url = f"{self._endpoint}/chat/completions"
        resp = requests.post(
            url,
            json=payload,
            headers=self._headers,
            timeout=self._timeout,
        )
        resp.raise_for_status()

        body = resp.json()
        content = body.get("choices", [{}])[0].get("message", {}).get("content", "")

        if not content:
            raise ValueError("SLM returned empty response")

        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)

        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
            else:
                raise ValueError(
                    f"Failed to parse SLM response as JSON: {content[:200]}"
                ) from None

        return data

    def _validate_result(
        self,
        result: dict[str, Any],
        chunk_text: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """Validate and normalize SLM result, filling gaps with heuristic fallback."""
        normalized: dict[str, Any] = {
            "keywords": [],
            "entities": [],
            "hyde_questions": [],
            "summary": "",
        }

        if isinstance(result.get("keywords"), list):
            normalized["keywords"] = [
                str(k) for k in result["keywords"] if isinstance(k, str) and len(k) > 1
            ][:10]

        if isinstance(result.get("entities"), list):
            normalized["entities"] = [
                str(e) for e in result["entities"] if isinstance(e, str) and len(e) > 1
            ][:10]

        if isinstance(result.get("hyde_questions"), list):
            normalized["hyde_questions"] = [
                str(q).rstrip("?") + "?"
                for q in result["hyde_questions"]
                if isinstance(q, str) and len(q) > 5
            ][:5]

        if isinstance(result.get("summary"), str) and result["summary"].strip():
            normalized["summary"] = result["summary"].strip()

        if not normalized["keywords"]:
            normalized["keywords"] = self._heuristic_keywords(chunk_text)
        if not normalized["entities"]:
            normalized["entities"] = self._heuristic_entities(chunk_text)
        if not normalized["hyde_questions"]:
            normalized["hyde_questions"] = self._heuristic_hyde_questions(chunk_text, metadata)
        if not normalized["summary"]:
            normalized["summary"] = self._heuristic_summary(chunk_text)

        return normalized

    def _heuristic_fallback(
        self,
        chunk_text: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """Heuristic extraction when SLM is unavailable."""
        return {
            "keywords": self._heuristic_keywords(chunk_text),
            "entities": self._heuristic_entities(chunk_text),
            "hyde_questions": self._heuristic_hyde_questions(chunk_text, metadata),
            "summary": self._heuristic_summary(chunk_text),
        }

    @staticmethod
    def _heuristic_keywords(text: str, top_n: int = 8) -> list[str]:
        """Extract keywords via TF-like frequency analysis with stopword filtering."""
        if not text or not text.strip():
            return []

        stopwords = {
            "и", "в", "на", "с", "к", "у", "по", "для", "из", "о", "не", "быть",
            "что", "как", "это", "то", "от", "за", "но", "же", "все", "она",
            "они", "мы", "вы", "он", "его", "ее", "их", "the", "a", "an", "is",
            "are", "was", "were", "be", "been", "being", "have", "has", "had",
            "do", "does", "did", "will", "would", "could", "should", "may",
            "might", "can", "shall", "to", "of", "in", "for", "on", "with",
            "at", "by", "from", "as", "into", "through", "during", "before",
            "after", "above", "below", "between", "under", "and", "but", "or",
            "nor", "not", "so", "yet", "both", "either", "neither", "each",
            "every", "all", "any", "few", "more", "most", "other", "some",
            "such", "only", "own", "same", "than", "too", "very", "just",
            "because", "about", "while", "which", "who", "whom", "when",
            "where", "also", "then", "there", "here", "этом", "этой", "этого",
            "если", "или", "уже", "еще", "бы", "ли", "без", "под", "над",
            "около", "при", "про", "этот", "эти", "эта", "эту",
        }

        words = re.findall(r"\b[A-Za-zА-Яа-я][A-Za-zА-Яа-я0-9_\-+#.]{2,}\b", text.lower())
        freq: dict[str, int] = {}
        for w in words:
            if w not in stopwords:
                freq[w] = freq.get(w, 0) + 1

        sorted_words = sorted(freq.items(), key=lambda x: (-x[1], x[0]))
        return [w for w, _ in sorted_words[:top_n]]

    def _heuristic_entities(self, text: str) -> list[str]:
        """Extract entities via spaCy NER or regex-based patterns."""
        entities: list[str] = []

        if self._nlp is not None:
            try:
                doc = self._nlp(text[:100000])
                for ent in doc.ents:
                    if ent.label_ in ("PERSON", "ORG", "PRODUCT", "GPE", "LOC", "FAC"):
                        entity_text = ent.text.strip()
                        if len(entity_text) > 1 and entity_text not in entities:
                            entities.append(entity_text)
                return entities[:10]
            except Exception as e:
                logger.debug("spaCy NER failed: %s", e)

        uppercase_pattern = re.compile(
            r"\b[A-ZА-Я][A-Za-zА-Яа-я0-9_\-+]{2,}"
            r"(?:\s+[A-ZА-Я][A-Za-zА-Яа-я0-9_\-+]{2,}){0,3}\b"
        )
        matches = uppercase_pattern.findall(text)
        for m in matches:
            stripped = m.strip()
            if stripped not in entities and not re.match(r"^[A-ZА-Я]{2,}$", stripped):
                entities.append(stripped)

        version_pattern = re.compile(r"\b(v?\d+\.\d+(?:\.\d+)?)\b")
        for m in version_pattern.findall(text):
            if m not in entities:
                entities.append(m)

        return entities[:10]

    @staticmethod
    def _heuristic_hyde_questions(
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> list[str]:
        """Generate hypothetical questions using template-based approach."""
        questions: list[str] = []

        ru_patterns = [
            (r"([Кк]ак\s[^.!?]+[.!?])", "question"),
            (r"([Чч]то такое\s[^.!?]+[.!?])", "question"),
            (r"([Пп]очему\s[^.!?]+[.!?])", "question"),
            (r"([Гг]де\s[^.!?]+[.!?])", "question"),
            (r"([Зз]ачем\s[^.!?]+[.!?])", "question"),
            (r"([Кк]огда\s[^.!?]+[.!?])", "question"),
            (r"([Кк]то\s[^.!?]+[.!?])", "question"),
        ]
        en_patterns = [
            (r"([Hh]ow\s[^.!?]+\?)", "question"),
            (r"([Ww]hat\s[^.!?]+\?)", "question"),
            (r"([Ww]hy\s[^.!?]+\?)", "question"),
            (r"([Ww]here\s[^.!?]+\?)", "question"),
            (r"([Ww]hen\s[^.!?]+\?)", "question"),
            (r"([Ww]ho\s[^.!?]+\?)", "question"),
            (r"([Cc]an\s[^.!?]+\?)", "question"),
        ]

        for patterns in (ru_patterns, en_patterns):
            for pattern, _ptype in patterns:
                for match in re.finditer(pattern, text):
                    q = match.group(1).strip()
                    if len(q) < 200 and len(q) > 10:
                        questions.append(q)
                    if len(questions) >= 3:
                        break
                if len(questions) >= 3:
                    break
            if questions:
                break

        if not questions and metadata:
            title = metadata.get("doc_title", "")
            sec_title = metadata.get("section_title", "")
            source_type = metadata.get("source_type", "")

            if title:
                questions.append(f"Что такое {title}?")
            if sec_title and sec_title != title:
                questions.append(f"Как работает {sec_title}?")
            if source_type == "jira":
                questions.append("Как решить эту задачу?")
            elif source_type == "confluence":
                questions.append("О чём этот документ?")
            elif source_type and len(questions) < 2:
                questions.append("Что содержится в этом документе?")

        if not questions:
            sentences = re.split(r"(?<=[.!?])\s+", text)
            if sentences:
                first = sentences[0].strip()[:100]
                questions.append(f"Что такое {first}?")

        return questions[:3]

    @staticmethod
    def _heuristic_summary(text: str, max_chars: int = 150) -> str:
        """Generate summary by taking first 1-2 sentences."""
        if not text or not text.strip():
            return ""

        clean = re.sub(r"^\[.*?\]\s*", "", text)
        clean = re.sub(r"^#{1,6}\s+", "", clean, flags=re.MULTILINE)
        sentences = re.split(r"(?<=[.!?])\s+", clean)

        result = ""
        for s in sentences[:2]:
            result += s.strip() + " "
            if len(result) >= max_chars:
                break

        result = result.strip()
        if len(text) > len(result) and not result.endswith("...") and len(result) >= max_chars - 3:
            result = result[:max_chars - 3].rstrip() + "..."

        return result

    @staticmethod
    def _empty_result() -> dict[str, Any]:
        return {
            "keywords": [],
            "entities": [],
            "hyde_questions": [],
            "summary": "",
        }

    async def enrich_async(
        self,
        chunk_text: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Async version of enrich() with semaphore-based backpressure."""
        sem = self._get_semaphore()
        async with sem:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, self.enrich, chunk_text, metadata)

    async def enrich_batch_async(
        self,
        chunks: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Enrich multiple chunks with concurrent SLM calls.

        Each chunk dict should have "text" and optionally "metadata" keys.
        Returns list of enrichment result dicts in the same order.
        """
        tasks = [
            self.enrich_async(ch.get("text", ""), ch.get("metadata"))
            for ch in chunks
        ]
        return list(await asyncio.gather(*tasks, return_exceptions=False))

    def enrich_chunks_sync(
        self,
        chunks: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Synchronous batch enrichment for use in batch pipelines."""
        results: list[dict[str, Any]] = []
        for ch in chunks:
            result = self.enrich(ch.get("text", ""), ch.get("metadata"))
            results.append(result)
        return results


def build_chunk_enricher_from_config(config: dict[str, Any]) -> ChunkEnricher | None:
    """Build a ChunkEnricher from the ETL config.

    Reads the enrichment section. Returns None if enrichment is disabled
    or no SLM endpoint is configured.
    """
    enrich_cfg = config.get("enrichment", {})

    enabled = enrich_cfg.get("enabled", False)
    if not enabled:
        logger.info("Chunk enrichment is disabled in config")
        return None

    slm_endpoint = enrich_cfg.get("slm_endpoint", "")
    slm_model = enrich_cfg.get("slm_model", "qwen2.5-3b")

    if not slm_endpoint:
        logger.info("No SLM endpoint configured for enrichment")
        if not enrich_cfg.get("fallback_to_heuristic", True):
            return None

    return ChunkEnricher(
        slm_endpoint=slm_endpoint,
        model=slm_model,
        api_key=enrich_cfg.get("slm_api_key", ""),
        max_concurrent=enrich_cfg.get("max_concurrent", 5),
        fallback_to_heuristic=enrich_cfg.get("fallback_to_heuristic", True),
        timeout=enrich_cfg.get("timeout", 30),
    )
