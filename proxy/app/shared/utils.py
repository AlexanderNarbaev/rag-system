# proxy/app/utils.py
"""Auxiliary utilities for the RAG proxy.
- Hashing strings and objects
- Token count estimation (tiktoken or approximation)
- Safe text truncation
- Metadata formatting
- Request ID generation
- Date handling
"""

import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
import uuid
from datetime import UTC, datetime
from typing import Any

# Try importing tiktoken for precise tokenization
try:
    import tiktoken

    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False


def compute_hash(data: Any) -> str:
    """Computes the SHA-256 hash of any object (JSON-serializable)."""
    if isinstance(data, str):  # noqa: SIM108
        content = data
    else:
        content = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def estimate_tokens(text: str, model: str = "gpt-3.5-turbo") -> int:
    """Estimates the number of tokens in the text.
    Uses tiktoken if available, otherwise an approximate rule (4 characters ~ 1 token).
    """
    if not text:
        return 0
    if TIKTOKEN_AVAILABLE:
        try:
            encoding = tiktoken.encoding_for_model(model)
            return len(encoding.encode(text))
        except Exception:
            # fallback
            pass
    # Fallback: length / 4 (rough)
    return len(text) // 4


def truncate_by_tokens(text: str, max_tokens: int, model: str = "gpt-3.5-turbo") -> str:
    """Truncates text to the given number of tokens."""
    if estimate_tokens(text, model) <= max_tokens:
        return text
    # Rough approximation: truncate characters
    max_chars = max_tokens * 4
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "..." if max_chars > 3 else "..."


def generate_request_id() -> str:
    """Generates a unique ID for a request.
    Format: rag_<timestamp>_<uuid_short>
    """
    timestamp = int(time.time() * 1000)
    short_uuid = uuid.uuid4().hex[:8]
    return f"rag_{timestamp}_{short_uuid}"


def format_metadata(metadata: dict[str, Any]) -> str:
    """Formats metadata for inclusion in the context."""
    if not metadata:
        return ""
    parts = []
    for key, value in metadata.items():
        if value is not None:
            parts.append(f"{key}: {value}")
    return " | ".join(parts)


def now_iso() -> str:
    """Returns the current time in ISO format."""
    return datetime.now(UTC).isoformat()


def safe_json_loads(s: str, default: Any = None) -> Any:
    """Safely parses JSON, returning default on error."""
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return default


def extract_issue_keys(text: str) -> list[str]:
    """Extracts Jira-like issue keys from text (e.g. PROJ-123)."""
    pattern = r"\b[A-Z][A-Z0-9]+-\d+\b"
    return re.findall(pattern, text)


def extract_urls(text: str) -> list[str]:
    """Extracts URLs from text."""
    pattern = r'https?://[^\s<>"\']+'
    return re.findall(pattern, text)


def mask_sensitive_data(text: str, secrets: list[str] | None = None) -> str:
    """Masks sensitive data (tokens, passwords) in logs.
    By default masks strings that look like tokens (40+ characters).
    """
    if not text:
        return text
    # Mask sequences of 40+ alphanumeric characters (presumably tokens)
    masked = re.sub(r"\b[A-Za-z0-9]{40,}\b", "[REDACTED_TOKEN]", text)
    if secrets:
        for secret in secrets:
            if secret and secret in masked:
                masked = masked.replace(secret, "[REDACTED]")
    return masked


def chunk_list(lst: list[Any], chunk_size: int) -> list[list[Any]]:
    """Splits a list into chunks of the given size."""
    return [lst[i : i + chunk_size] for i in range(0, len(lst), chunk_size)]


def safe_divide(a: float, b: float, default: float = 0.0) -> float:
    """Safe division (protects against division by zero)."""
    return a / b if b != 0 else default


_ALLOWED_URL_SCHEMES = frozenset({"https", "http"})


def safe_urlopen(
    url: str,
    timeout: float = 10.0,
    data: bytes | None = None,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    allow_localhost: bool = True,
) -> Any:
    """Open *url* safely — validates scheme (https-only in production, localhost
    allowed for development) and always sets a timeout.

    Values ``None`` for *data*, *method*, or *headers* default to no body,
    ``"GET"``, and no extra headers respectively.

    Raises :exc:`ValueError` when the URL scheme is disallowed and
    re-raises :exc:`OSError` / :exc:`urllib.error.URLError` on network errors.
    """
    parsed = urllib.parse.urlparse(url)
    scheme = parsed.scheme.lower()

    if scheme not in _ALLOWED_URL_SCHEMES:
        raise ValueError(f"URL scheme '{scheme}' is not allowed")

    hostname = parsed.hostname or ""
    is_local = hostname in ("127.0.0.1", "::1", "localhost")

    if not allow_localhost and is_local:
        raise ValueError(f"URL hostname '{hostname}' is not allowed (localhost rejected)")

    req = urllib.request.Request(url, data=data or None, method=method)
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    return urllib.request.urlopen(req, timeout=timeout)


if __name__ == "__main__":
    # Usage examples
    print(f"Hash: {compute_hash({'key': 'value'})}")
    print(f"Tokens estimate: {estimate_tokens('Пример текста для оценки токенов.')}")
    print(f"Truncated: {truncate_by_tokens('Длинный текст ' * 100, 50)}")
    print(f"Request ID: {generate_request_id()}")
    print(f"Issue keys: {extract_issue_keys('Связано с PROJ-123 и TEST-456')}")
    print(f"Masked: {mask_sensitive_data('My token: abcdef1234567890abcdef1234567890abcdef12')}")
