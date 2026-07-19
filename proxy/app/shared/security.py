# proxy/app/security.py
"""Security utilities for input validation, sanitization, and secrets management."""

import hashlib
import os
import re
import secrets
import time
from typing import Any

import bcrypt


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
        return sanitized if sanitized else None

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
        for d in dangerous:  # noqa: SIM110
            if d in path:
                return False
        return True

    @staticmethod
    def sanitize_headers(headers: dict[str, Any]) -> dict[str, Any]:
        """Sanitize HTTP headers dictionary for safe logging."""
        safe: dict[str, Any] = {}
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
    def mask_in_response(data: dict[str, Any]) -> dict[str, Any]:
        """Mask sensitive fields in response data (deep copy)."""
        if not isinstance(data, dict):
            return data
        sensitive_keys = {"api_key", "password", "secret", "token", "private_key"}
        result: dict[str, Any] = {}
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
        "Content-Security-Policy": (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "connect-src 'self' ws: wss:; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self'"
        ),
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        "Cross-Origin-Opener-Policy": "same-origin",
        "Cross-Origin-Resource-Policy": "same-origin",
        "Cross-Origin-Embedder-Policy": "credentialless",
        "X-Permitted-Cross-Domain-Policies": "none",
        "X-Download-Options": "noopen",
        "X-DNS-Prefetch-Control": "off",
        "Cache-Control": "no-store, no-cache, must-revalidate",
    }

    @classmethod
    def get_headers(cls, extra: dict[str, str] | None = None) -> dict[str, str]:
        """Return security headers, optionally merging extra headers.

        Args:
            extra: Additional headers to merge (override defaults).

        Returns:
            Combined security headers dictionary.

        """
        headers = dict(cls.DEFAULT_HEADERS)
        if extra:
            headers.update(extra)
        return headers


class PasswordStrengthValidator:
    """Validates password strength against corporate security policy."""

    MIN_LENGTH = 10
    MAX_LENGTH = 128
    _UPPER_RE = re.compile(r"[A-Z]")
    _LOWER_RE = re.compile(r"[a-z]")
    _DIGIT_RE = re.compile(r"\d")
    _SPECIAL_RE = re.compile(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>/?`~]")

    @classmethod
    def validate(cls, password: str) -> tuple[bool, str | None]:
        """Validate password strength. Returns (valid, error_message)."""
        if not isinstance(password, str):
            return False, "Password must be a string"
        if len(password) < cls.MIN_LENGTH:
            return False, f"Password must be at least {cls.MIN_LENGTH} characters"
        if len(password) > cls.MAX_LENGTH:
            return False, f"Password must be at most {cls.MAX_LENGTH} characters"
        if not cls._UPPER_RE.search(password):
            return False, "Password must contain at least one uppercase letter"
        if not cls._LOWER_RE.search(password):
            return False, "Password must contain at least one lowercase letter"
        if not cls._DIGIT_RE.search(password):
            return False, "Password must contain at least one digit"
        if not cls._SPECIAL_RE.search(password):
            return False, "Password must contain at least one special character"
        return True, None


class CSRFProtection:
    """CSRF protection for cookie-authenticated endpoints.

    Generates and validates CSRF tokens for state-changing operations.
    Uses the double-submit cookie pattern: a random token is set as a cookie
    and must be submitted in a custom header for state-changing requests.
    """

    HEADER_NAME = "X-CSRF-Token"
    COOKIE_NAME = "csrf_token"
    TOKEN_BYTES = 32

    @staticmethod
    def generate_token() -> str:
        """Generate a cryptographically secure CSRF token."""
        return secrets.token_urlsafe(CSRFProtection.TOKEN_BYTES)

    @staticmethod
    def validate_request(request_headers: dict[str, str], request_cookies: dict[str, str]) -> bool:
        """Validate CSRF token using double-submit cookie pattern.

        The token in the X-CSRF-Token header must match the token in the csrf_token cookie.
        Both must be present for state-changing requests (POST, PUT, PATCH, DELETE).
        """
        header_token = request_headers.get(CSRFProtection.HEADER_NAME, "")
        cookie_token = request_cookies.get(CSRFProtection.COOKIE_NAME, "")

        if not header_token or not cookie_token:
            return False

        return secrets.compare_digest(header_token, cookie_token)

    @staticmethod
    def is_state_changing(method: str) -> bool:
        """Check if the HTTP method requires CSRF protection."""
        return method.upper() in {"POST", "PUT", "PATCH", "DELETE"}


class SQLInjectionDetector:
    """Detects common SQL injection patterns in user input."""

    _SQLI_PATTERNS = [
        re.compile(r"(?i)(\bUNION\b.*\bSELECT\b)"),
        re.compile(r"(?i)(\bSELECT\b.*\bFROM\b)"),
        re.compile(r"(?i)(\bINSERT\b\s+\bINTO\b)"),
        re.compile(r"(?i)(\bUPDATE\b\s+\w+\s+\bSET\b)"),
        re.compile(r"(?i)(\bDELETE\b\s+\bFROM\b)"),
        re.compile(r"(?i)(\bDROP\b\s+\bTABLE\b)"),
        re.compile(r"(?i)(\bALTER\b\s+\bTABLE\b)"),
        re.compile(r"(?i)(\bEXEC\b\s*[\(x])"),
        re.compile(r"(?i)(\bOR\b\s+['\"]?\d?['\"]?\s*=\s*['\"]?\d?['\"]?)"),
        re.compile(r"(?i)(\bAND\b\s+['\"]?\d?['\"]?\s*=\s*['\"]?\d?['\"]?)"),
        re.compile(r"(?i)(\bSLEEP\b\s*\()"),
        re.compile(r"(?i)(\bBENCHMARK\b\s*\()"),
        re.compile(r"(?i)(\bWAITFOR\b\s+\bDELAY\b)"),
        re.compile(r"(?i)(\/\*.*\*\/)"),
        re.compile(r"(--\s*[^\n]*$)"),
        re.compile(r"(;\s*\bDROP\b|\bSELECT\b|\bUPDATE\b|\bDELETE\b)"),
    ]

    _XSS_PATTERNS = [
        re.compile(r"<script[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL),
        re.compile(r"javascript\s*:", re.IGNORECASE),
        re.compile(r"on\w+\s*=\s*[\"'][^\"']*[\"']", re.IGNORECASE),
        re.compile(r"<iframe[^>]*>", re.IGNORECASE),
        re.compile(r"<embed[^>]*>", re.IGNORECASE),
        re.compile(r"<object[^>]*>", re.IGNORECASE),
        re.compile(r"data\s*:\s*text/html", re.IGNORECASE),
        re.compile(r"vbscript\s*:", re.IGNORECASE),
        re.compile(r"expression\s*\(", re.IGNORECASE),
    ]

    @classmethod
    def detect_sqli(cls, text: str) -> list[str]:
        """Detect SQL injection patterns. Returns list of matched pattern descriptions."""
        findings = []
        for i, pattern in enumerate(cls._SQLI_PATTERNS):
            if pattern.search(text):
                findings.append(f"sqli_pattern_{i}")
        return findings

    @classmethod
    def detect_xss(cls, text: str) -> list[str]:
        """Detect XSS patterns in text. Returns list of matched pattern descriptions."""
        findings = []
        for i, pattern in enumerate(cls._XSS_PATTERNS):
            if pattern.search(text):
                findings.append(f"xss_pattern_{i}")
        return findings

    @classmethod
    def is_suspicious(cls, text: str) -> bool:
        """Quick check: does the text contain any SQLi or XSS patterns?"""
        return bool(cls.detect_sqli(text)) or bool(cls.detect_xss(text))


class RequestSigner:
    """HMAC-based request signing for webhook verification.

    Provides generation and verification of HMAC-SHA256 signatures
    for webhook payloads from external systems (Confluence, Jira, GitLab).
    Uses constant-time comparison to prevent timing attacks.
    """

    SIGNATURE_HEADER = "X-Webhook-Signature"
    TIMESTAMP_HEADER = "X-Webhook-Timestamp"
    MAX_AGE_SECONDS = 300

    @staticmethod
    def sign(payload: str, secret: str, timestamp: str | None = None) -> str:
        """Generate HMAC-SHA256 signature for a webhook payload.

        Args:
            payload: The request body to sign.
            secret: Shared secret key.
            timestamp: Optional Unix timestamp (generated if not provided).

        Returns:
            Hex-encoded HMAC-SHA256 signature.
        """
        import hmac

        ts = timestamp or str(int(time.time()))
        message = f"{ts}.{payload}"
        mac = hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256)
        return mac.hexdigest()

    @staticmethod
    def verify(payload: str, signature: str, secret: str, timestamp: str) -> bool:
        """Verify an HMAC-SHA256 webhook signature.

        Args:
            payload: The raw request body.
            signature: The hex-encoded signature from the webhook header.
            secret: Shared secret key.
            timestamp: Unix timestamp from the webhook header.

        Returns:
            True if the signature is valid and not expired.
        """

        if not signature or not timestamp:
            return False

        try:
            ts_int = int(timestamp)
        except (ValueError, TypeError):
            return False

        if abs(int(time.time()) - ts_int) > RequestSigner.MAX_AGE_SECONDS:
            return False

        expected = RequestSigner.sign(payload, secret, timestamp)
        return secrets.compare_digest(expected, signature)

    @staticmethod
    def generate_secret(length: int = 32) -> str:
        """Generate a cryptographically secure webhook secret."""
        return secrets.token_hex(length)

    @staticmethod
    def extract_from_request(headers: dict[str, str], body: str) -> tuple[str, str]:
        """Extract signature and timestamp from request headers.

        Returns:
            Tuple of (signature, timestamp) or ("", "") if missing.
        """
        sig = headers.get(RequestSigner.SIGNATURE_HEADER, "")
        ts = headers.get(RequestSigner.TIMESTAMP_HEADER, "")
        return sig, ts


class IPAllowlist:
    """IP-based access control for admin and sensitive endpoints.

    Supports IPv4/IPv6 addresses, CIDR notation, and both
    allowlist and denylist modes.
    """

    def __init__(
        self,
        allowlist: list[str] | None = None,
        denylist: list[str] | None = None,
    ):
        import ipaddress

        self._allowlist: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
        self._denylist: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
        self._single_allow_ips: set[str] = set()
        self._single_deny_ips: set[str] = set()

        for entry in allowlist or []:
            entry = entry.strip()
            if not entry:
                continue
            try:
                if "/" in entry:
                    self._allowlist.append(ipaddress.ip_network(entry, strict=False))
                else:
                    self._single_allow_ips.add(entry)
            except ValueError:
                continue

        for entry in denylist or []:
            entry = entry.strip()
            if not entry:
                continue
            try:
                if "/" in entry:
                    self._denylist.append(ipaddress.ip_network(entry, strict=False))
                else:
                    self._single_deny_ips.add(entry)
            except ValueError:
                continue

    def is_allowed(self, ip: str) -> bool:
        """Check if an IP address is allowed.

        Returns True if:
        - No allowlist is configured (allow all), or
        - The IP matches an allowlist entry and is not denied.
        """
        import ipaddress

        if self._single_deny_ips and ip in self._single_deny_ips:
            return False

        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return False

        for network in self._denylist:
            if addr in network:
                return False

        if not self._allowlist and not self._single_allow_ips:
            return True

        if ip in self._single_allow_ips:
            return True

        return any(addr in network for network in self._allowlist)

    def is_denied(self, ip: str) -> bool:
        """Check if an IP address is explicitly denied."""
        import ipaddress

        if ip in self._single_deny_ips:
            return True

        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return True

        return any(addr in network for network in self._denylist)

    def add_to_allowlist(self, entry: str) -> bool:
        """Add an IP or CIDR range to the allowlist. Returns True on success."""
        import ipaddress

        entry = entry.strip()
        if not entry:
            return False
        try:
            if "/" in entry:
                self._allowlist.append(ipaddress.ip_network(entry, strict=False))
            else:
                self._single_allow_ips.add(entry)
            return True
        except ValueError:
            return False

    def add_to_denylist(self, entry: str) -> bool:
        """Add an IP or CIDR range to the denylist. Returns True on success."""
        import ipaddress

        entry = entry.strip()
        if not entry:
            return False
        try:
            if "/" in entry:
                self._denylist.append(ipaddress.ip_network(entry, strict=False))
            else:
                self._single_deny_ips.add(entry)
            return True
        except ValueError:
            return False

    def remove_from_allowlist(self, entry: str) -> bool:
        """Remove an entry from the allowlist. Returns True if removed."""
        import ipaddress

        entry = entry.strip()
        if entry in self._single_allow_ips:
            self._single_allow_ips.discard(entry)
            return True
        try:
            network = ipaddress.ip_network(entry, strict=False)
            if network in self._allowlist:
                self._allowlist.remove(network)
                return True
        except ValueError:
            pass
        return False

    @property
    def allowlist_entries(self) -> list[str]:
        """Return current allowlist entries as strings."""
        entries = list(self._single_allow_ips)
        entries.extend(str(n) for n in self._allowlist)
        return entries

    @property
    def denylist_entries(self) -> list[str]:
        """Return current denylist entries as strings."""
        entries = list(self._single_deny_ips)
        entries.extend(str(n) for n in self._denylist)
        return entries


class PasswordHistoryManager:
    """Tracks password history to prevent reuse.

    Maintains a configurable number of previous password hashes
    and rejects passwords that match any in the history window.
    """

    DEFAULT_MAX_HISTORY = 5

    def __init__(self, max_history: int = DEFAULT_MAX_HISTORY):
        self._max_history = max(max_history, 1)

    def is_previously_used(self, new_password: str, history_hashes: list[str]) -> bool:
        """Check if a new password matches any in the history.

        Args:
            new_password: The new password to check.
            history_hashes: List of bcrypt hashes of previous passwords.

        Returns:
            True if the password has been used before within the history window.
        """
        for old_hash in history_hashes[-self._max_history :]:
            if bcrypt.checkpw(new_password.encode("utf-8"), old_hash.encode("utf-8")):
                return True
        return False

    @staticmethod
    def hash_password(password: str) -> str:
        """Bcrypt-hash a password for history storage."""
        return bcrypt.hashpw(
            password.encode("utf-8"),
            bcrypt.gensalt(rounds=12),
        ).decode("utf-8")

    @staticmethod
    def trim_history(history: list[str], max_entries: int) -> list[str]:
        """Keep only the most recent entries in password history."""
        if len(history) <= max_entries:
            return history
        return history[-max_entries:]

    @property
    def max_history(self) -> int:
        return self._max_history


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
    def parse_requirements_line(line: str) -> tuple[str, str] | None:
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
    def scan_requirements(cls, req_file: str) -> list[dict[str, Any]]:
        """Check requirements.txt against known vulnerabilities.

        Args:
            req_file: Path to requirements.txt file.

        Returns:
            List of vulnerability findings (empty if none found).

        """

        from proxy.app.shared.path_utils import sanitize_path

        findings = []
        safe_path = sanitize_path(req_file)
        if not os.path.exists(safe_path):
            return [{"error": f"File not found: {req_file}"}]

        try:
            with open(safe_path, encoding="utf-8") as f:
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
                                },
                            )

        return findings


__all__ = [
    "CSRFProtection",
    "DependencyScanner",
    "IPAllowlist",
    "InputValidator",
    "PasswordHistoryManager",
    "PasswordStrengthValidator",
    "RequestSigner",
    "SecretsManager",
    "SecurityHeaders",
    "SQLInjectionDetector",
]
