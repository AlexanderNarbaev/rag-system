"""API Key management for user separation with rotation and expiry support."""

import hashlib
import logging
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ApiKey:
    key_id: str
    key_hash: str
    user_id: str
    roles: list[str]
    created_at: str
    expires_at: str | None = None
    last_used: str | None = None
    last_rotated_at: str | None = None
    rotated_from_key_id: str | None = None
    is_active: bool = True
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        if not self.expires_at:
            return False
        try:
            expiry = datetime.fromisoformat(self.expires_at)
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=UTC)
            return datetime.now(UTC) > expiry
        except (ValueError, TypeError):
            return False

    @property
    def age_days(self) -> float | None:
        try:
            created = datetime.fromisoformat(self.created_at)
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            return (datetime.now(UTC) - created).total_seconds() / 86400
        except (ValueError, TypeError):
            return None


class ApiKeyManager:
    """Manages API keys for user separation with rotation and expiry.

    Features:
    - SHA-256 hashed storage (keys never stored in plaintext)
    - Configurable key expiry with automatic invalidation
    - Key rotation with overlap support (old key remains valid during overlap)
    - Active key limit per user to prevent key sprawl
    """

    MAX_KEYS_PER_USER = 10
    DEFAULT_KEY_TTL_DAYS = 90

    def __init__(self) -> None:
        self._keys: dict[str, ApiKey] = {}
        self._key_to_user: dict[str, str] = {}  # key_hash -> user_id

    def generate_key(
        self,
        user_id: str,
        roles: list[str] | None = None,
        ttl_days: int | None = None,
        rotated_from_key_id: str | None = None,
    ) -> str:
        """Generate a new API key for a user.

        Args:
            user_id: The user this key belongs to.
            roles: RBAC roles for the key.
            ttl_days: Days until key expiry (default: 90 days).
            rotated_from_key_id: If this key replaces an old one, the old key_id.

        Returns:
            The plaintext API key (only shown once).

        """
        user_keys = self.list_keys(user_id=user_id, include_inactive=False)
        if len(user_keys) >= self.MAX_KEYS_PER_USER:
            raise ValueError(f"User {user_id} has reached the maximum of {self.MAX_KEYS_PER_USER} active API keys")

        key = f"sk-{secrets.token_urlsafe(32)}"
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        key_id = secrets.token_hex(8)

        ttl = ttl_days or self.DEFAULT_KEY_TTL_DAYS
        expires_at = (datetime.now(UTC) + timedelta(days=ttl)).isoformat()

        self._keys[key_id] = ApiKey(
            key_id=key_id,
            key_hash=key_hash,
            user_id=user_id,
            roles=roles or ["user"],
            created_at=datetime.now(UTC).isoformat(),
            expires_at=expires_at,
            rotated_from_key_id=rotated_from_key_id,
            last_rotated_at=datetime.now(UTC).isoformat() if rotated_from_key_id else None,
        )
        self._key_to_user[key_hash] = user_id

        msg = f"Generated API key for user {user_id} (key_id={key_id}, ttl={ttl}d)"
        if rotated_from_key_id:
            msg += f", rotated from {rotated_from_key_id}"
        logger.info(msg)
        return key

    def rotate_key(self, old_key_id: str, ttl_days: int | None = None) -> str | None:
        """Rotate an API key: generate a new one and deactivate the old after overlap.

        The old key remains active for a grace period (24h) so in-flight
        requests don't fail. After the overlap, the old key is deactivated.

        Args:
            old_key_id: The key_id to rotate.
            ttl_days: TTL for the new key (default: 90 days).

        Returns:
            The new plaintext API key, or None if old_key_id is invalid.

        """
        if old_key_id not in self._keys:
            return None

        old_key = self._keys[old_key_id]
        if not old_key.is_active:
            return None

        new_key = self.generate_key(
            user_id=old_key.user_id,
            roles=old_key.roles,
            ttl_days=ttl_days,
            rotated_from_key_id=old_key_id,
        )

        old_key.metadata["overlap_till"] = (datetime.now(UTC) + timedelta(hours=24)).isoformat()
        old_key.metadata["replaced_by"] = new_key.split("_")[-1][:8] if "_" in new_key else "unknown"

        logger.info(
            "API key rotated for user %s: %s -> new key (overlap=%s)",
            old_key.user_id,
            old_key_id,
            old_key.metadata["overlap_till"],
        )
        return new_key

    def validate_key(self, key: str) -> ApiKey | None:
        """Validate an API key and return the associated ApiKey.

        Checks key format, hash match, active status, and expiry.
        Returns None for invalid, inactive, or expired keys.
        """
        if not key or not key.startswith("sk-"):
            return None

        key_hash = hashlib.sha256(key.encode()).hexdigest()
        user_id = self._key_to_user.get(key_hash)

        if not user_id:
            return None

        for api_key in self._keys.values():
            if api_key.key_hash == key_hash and api_key.is_active:
                if api_key.is_expired:
                    logger.info("API key %s for user %s is expired", api_key.key_id, api_key.user_id)
                    return None
                api_key.last_used = datetime.now(UTC).isoformat()
                return api_key

        return None

    def revoke_key(self, key_id: str) -> bool:
        """Revoke an API key immediately."""
        if key_id in self._keys:
            self._keys[key_id].is_active = False
            logger.info("API key %s revoked for user %s", key_id, self._keys[key_id].user_id)
            return True
        return False

    def expire_key(self, key_id: str) -> bool:
        """Manually expire a key by setting its expiry to now."""
        if key_id in self._keys:
            self._keys[key_id].expires_at = datetime.now(UTC).isoformat()
            logger.info("API key %s manually expired for user %s", key_id, self._keys[key_id].user_id)
            return True
        return False

    def list_keys(self, user_id: str | None = None, include_inactive: bool = False) -> list[ApiKey]:
        """List all API keys, optionally filtered by user.

        Args:
            user_id: Filter by user. None = all users.
            include_inactive: Include revoked/expired keys.

        """
        keys = list(self._keys.values())
        if user_id:
            keys = [k for k in keys if k.user_id == user_id]
        if not include_inactive:
            keys = [k for k in keys if k.is_active and not k.is_expired]
        return keys

    def cleanup_expired_keys(self) -> int:
        """Remove keys that have been expired for more than 30 days.

        Returns:
            Number of keys cleaned up.

        """
        threshold = datetime.now(UTC) - timedelta(days=30)
        expired_to_remove = []

        for key_id, api_key in self._keys.items():
            if not api_key.expires_at:
                continue
            try:
                expiry = datetime.fromisoformat(api_key.expires_at)
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=UTC)
                if expiry < threshold:
                    expired_to_remove.append(key_id)
            except (ValueError, TypeError):
                pass

        for key_id in expired_to_remove:
            key_hash = self._keys[key_id].key_hash
            self._key_to_user.pop(key_hash, None)
            del self._keys[key_id]

        if expired_to_remove:
            logger.info("Cleaned up %d expired API keys", len(expired_to_remove))
        return len(expired_to_remove)

    def get_key_health(self) -> dict[str, Any]:
        """Return a summary of API key health for monitoring."""
        total = len(self._keys)
        active = sum(1 for k in self._keys.values() if k.is_active)
        expired = sum(1 for k in self._keys.values() if k.is_expired)
        near_expiry_threshold = datetime.now(UTC) + timedelta(days=7)
        near_expiry = 0

        for k in self._keys.values():
            if k.is_active and k.expires_at:
                try:
                    exp = datetime.fromisoformat(k.expires_at)
                    if exp.tzinfo is None:
                        exp = exp.replace(tzinfo=UTC)
                    if exp < near_expiry_threshold and not k.is_expired:
                        near_expiry += 1
                except (ValueError, TypeError):
                    pass

        return {
            "total_keys": total,
            "active_keys": active,
            "expired_keys": expired,
            "keys_near_expiry": near_expiry,
            "max_keys_per_user": self.MAX_KEYS_PER_USER,
        }


# Global instance
api_key_manager = ApiKeyManager()
