"""Clarifying question generation for low-confidence RAG scenarios.

When the RAG system has "partial", "insufficient", or "absent" status, this module
generates 1-2 clarifying questions to help the user refine their query.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from proxy.app.core.knowledge_status import normalize_knowledge_status

logger = logging.getLogger(__name__)


@dataclass
class ClarificationResult:
    questions: list[str] = field(default_factory=list)
    clarification_needed: bool = False
    generated_by: str = "heuristic"


def generate_clarifying_questions(
    query: str,
    status: str,
    sources: list[dict[str, Any]] | None = None,
    context: str = "",
    use_slm: bool = True,
    lang: str | None = None,
) -> ClarificationResult:
    """Generate clarifying questions when knowledge is insufficient.

    Args:
        query: The user's original query.
        status: Knowledge status ("sufficient", "partial", "insufficient", "absent").
        Old names ("grounded", "no_knowledge") are accepted via backward compat.
        sources: Retrieved sources (used to understand what was found).
        context: Retrieved context text.
        use_slm: Whether to attempt SLM-based generation.
        lang: ISO 639-1 language code to generate questions in. Defaults to auto-detect.

    Returns:
        ClarificationResult with questions and metadata.
    """
    status = normalize_knowledge_status(status)

    if status == "sufficient":
        return ClarificationResult(questions=[], clarification_needed=False)

    if use_slm:
        try:
            slm_result = _generate_with_slm(query, status, sources, context, lang)
            if slm_result.questions:
                return slm_result
        except Exception:
            logger.debug("SLM clarification generation failed, falling back to heuristic")

    return _generate_heuristic(query, status, sources or [])


def _is_slm_available() -> bool:
    """Check if SLM is configured and available."""
    from proxy.app.shared.config import SLM_ENDPOINT, SLM_LOCAL_ENABLED

    return bool(SLM_LOCAL_ENABLED or SLM_ENDPOINT)


def _generate_with_slm(
    query: str,
    status: str,
    sources: list[dict[str, Any]] | None,
    context: str,
    lang: str | None = None,
) -> ClarificationResult:
    """Use SLM to generate clarifying questions."""
    if not _is_slm_available():
        return ClarificationResult()

    sources_preview = ""
    if sources:
        titles = [s.get("title", "") for s in sources[:3] if s.get("title")]
        if titles:
            sources_preview = f"Found documents: {', '.join(titles)}."

    target_lang = lang or "the same language as the query"

    prompt = (
        f'The user asked: "{query}"\n'
        f"Knowledge base status: {status}\n"
        f"{sources_preview}\n"
        f"Generate 1-2 short clarifying questions in {target_lang} "
        "that would help refine the search to find better information. "
        "Output ONLY the questions, one per line, starting with '- '."
    )

    try:
        from proxy.app.llm.slm import _call_slm_sync

        response = _call_slm_sync(prompt, max_tokens=150, temperature=0.3)
        if not response:
            return ClarificationResult()

        questions = []
        for line in response.split("\n"):
            line = line.strip()
            if line.startswith("- ") and len(line) > 3:
                questions.append(line[2:].strip())
            elif line and "?" in line and len(line) > 5:
                questions.append(line.strip())

        questions = questions[:2]
        if questions:
            return ClarificationResult(
                questions=questions,
                clarification_needed=True,
                generated_by="slm",
            )
    except Exception as e:
        logger.debug(f"SLM clarification failed: {e}")

    return ClarificationResult()


def _generate_heuristic(
    query: str,
    status: str,
    sources: list[dict[str, Any]],
) -> ClarificationResult:
    """Heuristic-based clarifying question generation."""
    questions = []

    status = normalize_knowledge_status(status)

    if status == "absent":
        questions.append(
            "Could you rephrase your question with more specific technical terms or product names?",
        )
        if len(query.split()) > 10:
            questions.append(
                "Would you like to break this down into smaller, more focused questions?",
            )
    elif status in ("partial", "insufficient"):
        if sources:
            titles = [s.get("title", "") for s in sources[:2] if s.get("title")]
            if titles:
                questions.append(
                    f"I found some information about '{titles[0]}' — "
                    "could you clarify what specific aspect you are interested in?",
                )
            else:
                questions.append(
                    "Could you clarify what specific aspect of this topic you are interested in?",
                )
        else:
            questions.append(
                "Could you provide more specific details about what you are looking for?",
            )

    return ClarificationResult(
        questions=questions[:2],
        clarification_needed=True,
        generated_by="heuristic",
    )


def build_uncertainty_response(
    query: str,
    status: str,
    sources: list[dict[str, Any]],
    clarification: ClarificationResult | None = None,
) -> str:
    """Build a structured uncertainty response when knowledge is insufficient.

    Generates a response that includes:
    - What was searched for
    - What was found
    - What's missing
    - Suggested ways to refine the query
    """
    if normalize_knowledge_status(status) == "sufficient":
        return ""

    parts = []

    parts.append(f'I wasn\'t able to find fully reliable information about: "{query}"')

    if sources:
        found_titles = []
        for s in sources[:3]:
            title = s.get("title", "") or s.get("source", "unknown source")
            relevance = s.get("relevance", s.get("score", 0.0))
            found_titles.append(f"- {title} (relevance: {relevance:.2f})")
        parts.append("\nWhat was found (partial matches):\n" + "\n".join(found_titles))
    else:
        parts.append("\nWhat was found: No matching documents in the knowledge base.")

    parts.append("\nWhat's missing: Sufficiently relevant content to provide a confident answer.")

    suggestions = []
    if len(query.split()) < 4:
        suggestions.append("Try adding more specific details or technical terms to your query.")
    else:
        suggestions.append("Try using different keywords or more precise terminology.")
    suggestions.append("Consider breaking your question into smaller, more focused parts.")

    parts.append("\nSuggestions to refine your query:")
    for i, suggestion in enumerate(suggestions, 1):
        parts.append(f"{i}. {suggestion}")

    if clarification and clarification.questions:
        parts.append("\nClarifying questions:")
        for i, q in enumerate(clarification.questions, 1):
            parts.append(f"{i}. {q}")

    return "\n".join(parts)
