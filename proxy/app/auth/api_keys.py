"""API Key management for user separation."""

import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


@dataclass
class ApiKey:
    key_id: str
    key_hash: str
    user_id: str
    roles: list[str]
    created_at: str
    last_used: str | None = None
    is_active: bool = True


class ApiKeyManager:
    """Manages API keys for user separation."""

    def __init__(self) -> None:
        self._keys: dict[str, ApiKey] = {}
        self._key_to_user: dict[str, str] = {}  # key_hash -> user_id

    def generate_key(self, user_id: str, roles: list[str] | None = None) -> str:
        """Generate a new API key for a user."""
        key = f"sk-{secrets.token_urlsafe(32)}"
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        key_id = secrets.token_hex(8)

        self._keys[key_id] = ApiKey(
            key_id=key_id,
            key_hash=key_hash,
            user_id=user_id,
            roles=roles or ["user"],
            created_at=datetime.now(UTC).isoformat(),
        )
        self._key_to_user[key_hash] = user_id

        logger.info(f"Generated API key for user {user_id}")
        return key

    def validate_key(self, key: str) -> ApiKey | None:
        """Validate an API key and return the associated ApiKey."""
        if not key or not key.startswith("sk-"):
            return None

        key_hash = hashlib.sha256(key.encode()).hexdigest()
        user_id = self._key_to_user.get(key_hash)

        if not user_id:
            return None

        for api_key in self._keys.values():
            if api_key.key_hash == key_hash and api_key.is_active:
                api_key.last_used = datetime.now(UTC).isoformat()
                return api_key

        return None

    def revoke_key(self, key_id: str) -> bool:
        """Revoke an API key."""
        if key_id in self._keys:
            self._keys[key_id].is_active = False
            return True
        return False

    def list_keys(self, user_id: str | None = None) -> list[ApiKey]:
        """List all API keys, optionally filtered by user."""
        keys = list(self._keys.values())
        if user_id:
            keys = [k for k in keys if k.user_id == user_id]
        return keys


# Global instance
api_key_manager = ApiKeyManager()
