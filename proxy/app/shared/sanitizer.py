"""Input sanitization module for RAG proxy.

Provides SQL injection prevention, XSS stripping, and length validation
for all user-provided inputs (queries, feedback, corrections).
"""

import re

# ---------------------------------------------------------------------------
# SQL / DQL injection keywords and patterns
# ---------------------------------------------------------------------------

_SQL_KEYWORDS = re.compile(
    r"\b("
    r"SELECT|INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|EXEC|EXECUTE"
    r"|UNION|MERGE|REPLACE|GRANT|REVOKE|DECLARE|FETCH|OPEN"
    r")\b",
    re.IGNORECASE,
)

_SQL_COMMENT_PATTERN = re.compile(r"--[^\n]*")
_SEMICOLON_PATTERN = re.compile(r";")
_DQL_INJECTION = re.compile(r"\{\s*\$where\s*:")
_FUNCTION_INJECTION = re.compile(r"function\s*\(\)")

# ---------------------------------------------------------------------------
# XSS patterns
# ---------------------------------------------------------------------------

_HTML_TAG_RE = re.compile(r"<[^>]*>", re.DOTALL)
_SCRIPT_TAG_RE = re.compile(r"<script[\s>].*?</script>", re.DOTALL | re.IGNORECASE)
_JS_PROTOCOL_RE = re.compile(r"javascript\s*:", re.IGNORECASE)
_VB_PROTOCOL_RE = re.compile(r"vbscript\s*:", re.IGNORECASE)
_DATA_PROTOCOL_RE = re.compile(r"data\s*:.*?base64", re.IGNORECASE)
_EVENT_HANDLER_RE = re.compile(
    r"\bon(click|load|error|focus|blur|change|submit|mouseover|mouseout"
    r"|keydown|keyup|keypress|dblclick|contextmenu|scroll|resize"
    r"|abort|beforeunload|hashchange|popstate|storage|unload)\s*=",
    re.IGNORECASE,
)
_CSS_EXPRESSION_RE = re.compile(r"expression\s*\(", re.IGNORECASE)
_IFRAME_RE = re.compile(r"<iframe[\s>].*?</iframe>", re.DOTALL | re.IGNORECASE)
_ENTITY_ENCODED_RE = re.compile(r"&#x?[0-9a-f]+;", re.IGNORECASE)

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MULTIPLE_SPACES_RE = re.compile(r"\s+")

DEFAULT_MAX_QUERY_LENGTH = 8000
DEFAULT_MAX_FEEDBACK_LENGTH = 32000


def sanitize_query(text: str) -> str:
    """Sanitize a user search query.

    Strips SQL/DQL injection patterns, HTML tags, event handlers,
    control characters, and collapses whitespace.

    Returns the sanitized string, or empty string for None/invalid input.
    """
    if not isinstance(text, str):
        return ""

    text = text[:DEFAULT_MAX_QUERY_LENGTH]

    text = _HTML_TAG_RE.sub("", text)
    text = _SQL_COMMENT_PATTERN.sub("", text)
    text = _SEMICOLON_PATTERN.sub("", text)
    text = _DQL_INJECTION.sub("", text)
    text = _FUNCTION_INJECTION.sub("", text)
    text = _SQL_KEYWORDS.sub("", text)
    text = _JS_PROTOCOL_RE.sub("", text)
    text = _VB_PROTOCOL_RE.sub("", text)
    text = _EVENT_HANDLER_RE.sub("", text)
    text = _CSS_EXPRESSION_RE.sub("", text)
    text = _CONTROL_CHARS_RE.sub("", text)
    text = _MULTIPLE_SPACES_RE.sub(" ", text)

    return text.strip()


def sanitize_feedback(text: str) -> str:
    """Sanitize expert feedback text.

    Strips XSS vectors: HTML tags, script tags, iframes, event handlers,
    javascript/vbscript protocols, CSS expressions, and control characters.

    Returns the sanitized string, or empty string for None/invalid input.
    """
    if not isinstance(text, str):
        return ""

    text = text[:DEFAULT_MAX_FEEDBACK_LENGTH]

    text = _SCRIPT_TAG_RE.sub("", text)
    text = _IFRAME_RE.sub("", text)
    text = _HTML_TAG_RE.sub("", text)
    text = _JS_PROTOCOL_RE.sub("", text)
    text = _VB_PROTOCOL_RE.sub("", text)
    text = _DATA_PROTOCOL_RE.sub("", text)
    text = _EVENT_HANDLER_RE.sub("", text)
    text = _CSS_EXPRESSION_RE.sub("", text)
    text = _ENTITY_ENCODED_RE.sub("", text)
    text = _CONTROL_CHARS_RE.sub("", text)
    text = _MULTIPLE_SPACES_RE.sub(" ", text)

    return text.strip()


def validate_length(text: str, max_len: int = DEFAULT_MAX_QUERY_LENGTH) -> str:
    """Validate and truncate text to maximum length.

    Returns the text truncated to max_len characters, or empty string
    for None/invalid input.
    """
    if not isinstance(text, str):
        return ""
    if max_len <= 0:
        return ""
    if len(text) <= max_len:
        return text
    return text[:max_len]
