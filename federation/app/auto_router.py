import logging
import re

from .config import FEDERATION_AUTO_SLM_ENABLED
from .silo_registry import SiloRegistry

logger = logging.getLogger("federation")

_KEYWORD_MAP: dict[str, list[str]] = {
    "hr": [
        "sick leave", "больничный", "vacation", "отпуск", "hiring",
        "onboarding", "payroll", "salary", "benefits", "hr policy",
    ],
    "engineering": [
        "deploy", "production", "kubernetes", "docker", "pipeline",
        "code review", "merge request", "pull request", "git", "jira",
        "confluence", "architecture", "microservice", "api",
    ],
    "finance": [
        "budget", "expense", "invoice", "reimbursement", "report",
        "quarterly", "annual", "fiscal", "tax",
    ],
}

_regex_cache: dict[str, re.Pattern] = {}


def _get_regex(silo_id: str) -> re.Pattern:
    if silo_id not in _regex_cache:
        keywords = _KEYWORD_MAP.get(silo_id, [])
        pattern = "|".join(re.escape(kw) for kw in keywords)
        _regex_cache[silo_id] = re.compile(pattern, re.IGNORECASE)
    return _regex_cache[silo_id]


async def classify_query(query: str, registry: SiloRegistry) -> list[str]:
    if not FEDERATION_AUTO_SLM_ENABLED:
        return [s.id for s in registry.list_all()]

    query_lower = query.lower()
    matched: list[tuple[str, int]] = []
    all_silos = [s.id for s in registry.list_all()]

    for silo_id in all_silos:
        pattern = _get_regex(silo_id)
        matches = len(pattern.findall(query_lower))
        if matches > 0:
            matched.append((silo_id, matches))

    if not matched:
        return all_silos

    matched.sort(key=lambda x: x[1], reverse=True)
    return [m[0] for m in matched]
