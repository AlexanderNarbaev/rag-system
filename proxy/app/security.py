# proxy/app/security.py
"""Security utilities for input validation, sanitization, and secrets management."""

import hashlib
import os
import re
import secrets


class InputValidator:
    """Validates and sanitizes all user inputs."""

    MAX_QUERY_LENGTH = 8000
    MAX_MESSAGE_CONTENT = 32000

    _HTML_TAG_RE = re.compile(r"<[^>]*>")
    _CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
    _MULTIPLE_SPACES_RE = re.compile(r"\s+")

    @staticmethod
    def validate_query(query: str) -> str:
        """Sanitize user query. Max length: 8000 chars. Strip HTML/special chars."""
        if not isinstance(query, str):
            return ""

        query = query[: InputValidator.MAX_QUERY_LENGTH]
        query = InputValidator._HTML_TAG_RE.sub("", query)
        query = InputValidator._CONTROL_CHARS_RE.sub("", query)
        query = InputValidator._MULTIPLE_SPACES_RE.sub(" ", query)
        return query.strip()

    @staticmethod
    def validate_non_empty(s: str, max_len: int = 4096) -> str | None:
        """Validate string is non-empty and within length. Returns sanitized or None."""
        if not isinstance(s, str) or not s.strip():
            return None
        sanitized = InputValidator._HTML_TAG_RE.sub("", s.strip())
        sanitized = InputValidator._CONTROL_CHARS_RE.sub("", sanitized)
        if len(sanitized) > max_len:
            sanitized = sanitized[:max_len]
        return sanitized

    @staticmethod
    def sanitize_for_log(text: str) -> str:
        """Remove PII and secrets from text for safe logging."""
        if not isinstance(text, str):
            return ""
        # Mask email addresses
        text = re.sub(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", "[EMAIL]", text)
        # Mask IP addresses
        text = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "[IP]", text)
        # Mask potential API keys / tokens (long alphanumeric sequences)
        text = re.sub(r"\b[A-Za-z0-9_-]{32,}\b", "[REDACTED]", text)
        return text

    @staticmethod
    def validate_model_name(name: str) -> bool:
        """Validate model name contains only safe characters."""
        if not isinstance(name, str):
            return False
        return bool(re.match(r"^[a-zA-Z0-9_.\-/:]+$", name))

    @staticmethod
    def validate_path_traversal(path: str) -> bool:
        """Check for path traversal attempts."""
        if not isinstance(path, str):
            return False
        dangerous = ["..", "~", "\x00"]
        for d in dangerous:
            if d in path:
                return False
        return True

    @staticmethod
    def sanitize_headers(headers: dict) -> dict:
        """Sanitize HTTP headers dictionary for safe logging."""
        safe = {}
        sensitive_header_keys = {"authorization", "cookie", "x-api-key", "x-auth-token", "set-cookie"}
        for key, value in headers.items():
            if key.lower() in sensitive_header_keys:
                safe[key] = "[REDACTED]"
            else:
                safe[key] = value
        return safe

    @staticmethod
    def escape_shell_arg(arg: str) -> str:
        """Escape a string safe for shell command arguments."""
        if not isinstance(arg, str):
            return ""
        return re.sub(r"[^a-zA-Z0-9._\- ]", "", arg)


class SecretsManager:
    """Manages secrets rotation and access."""

    @staticmethod
    def generate_api_key(prefix: str = "rag") -> str:
        """Generate a cryptographically secure API key."""
        random_part = secrets.token_urlsafe(32)
        return f"{prefix}_{random_part}"

    @staticmethod
    def hash_secret(secret: str) -> str:
        """SHA-256 hash a secret for storage."""
        return hashlib.sha256(secret.encode("utf-8")).hexdigest()

    @staticmethod
    def verify_secret(secret: str, hashed: str) -> bool:
        """Verify a secret against its hash."""
        return SecretsManager.hash_secret(secret) == hashed

    @staticmethod
    def mask_in_response(data: dict) -> dict:
        """Mask sensitive fields in response data (deep copy)."""
        if not isinstance(data, dict):
            return data
        sensitive_keys = {"api_key", "password", "secret", "token", "private_key"}
        result = {}
        for key, value in data.items():
            key_lower = key.lower()
            if isinstance(value, dict):
                result[key] = SecretsManager.mask_in_response(value)
            elif isinstance(value, list):
                result[key] = [SecretsManager.mask_in_response(v) if isinstance(v, dict) else v for v in value]
            elif any(sk in key_lower for sk in sensitive_keys):
                result[key] = "***"
            else:
                result[key] = value
        return result

    @staticmethod
    def generate_token(length: int = 32) -> str:
        """Generate a random URL-safe token."""
        return secrets.token_urlsafe(length)

    @staticmethod
    def constant_time_compare(a: str, b: str) -> bool:
        """Compare two strings in constant time to prevent timing attacks."""
        return secrets.compare_digest(a.encode() if isinstance(a, str) else a, b.encode() if isinstance(b, str) else b)


class SecurityHeaders:
    """Security headers for FastAPI responses."""

    DEFAULT_HEADERS = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "X-XSS-Protection": "1; mode=block",
        "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
        "Content-Security-Policy": "default-src 'self'",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        "Cache-Control": "no-store, no-cache, must-revalidate",
    }

    @classmethod
    def get_headers(cls, extra: dict | None = None) -> dict[str, str]:
        headers = dict(cls.DEFAULT_HEADERS)
        if extra:
            headers.update(extra)
        return headers


class DependencyScanner:
    """Simple dependency vulnerability scanner using known CVEs data."""

    KNOWN_VULNERABILITIES = {
        "requests": {
            "2.25.0": ["CVE-2023-32681 - Proxy-Authorization header leak"],
        },
        "urllib3": {
            "1.26.0": ["CVE-2023-45803 - Request body not stripped on redirect"],
        },
        "certifi": {
            "2021.0.0": ["CVE-2022-23491 - Weak root certificates"],
        },
    }

    @staticmethod
    def parse_requirements_line(line: str) -> tuple | None:
        """Parse a requirements.txt line into (package, version)."""
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            return None
        match = re.match(r"^([a-zA-Z0-9_.-]+)([<>=!~]+)([a-zA-Z0-9_.*-]+)", line)
        if match:
            return match.group(1), match.group(3)
        match = re.match(r"^([a-zA-Z0-9_.-]+)$", line)
        if match:
            return match.group(1), "any"
        return None

    @classmethod
    def scan_requirements(cls, req_file: str) -> list[dict]:
        """Check requirements.txt against known vulnerabilities."""
        findings = []
        if not os.path.exists(req_file):
            return [{"error": f"File not found: {req_file}"}]

        try:
            with open(req_file, encoding="utf-8") as f:
                lines = f.readlines()
        except Exception as e:
            return [{"error": str(e)}]

        for line in lines:
            parsed = cls.parse_requirements_line(line)
            if parsed is None:
                continue
            pkg, version = parsed
            if pkg in cls.KNOWN_VULNERABILITIES:
                for known_version, vulns in cls.KNOWN_VULNERABILITIES[pkg].items():
                    if version == known_version or version == "any":
                        for vuln in vulns:
                            findings.append(
                                {
                                    "package": pkg,
                                    "version": version,
                                    "vulnerability": vuln,
                                    "severity": "MEDIUM",
                                }
                            )

        return findings


__all__ = ["InputValidator", "SecretsManager", "SecurityHeaders", "DependencyScanner"]
