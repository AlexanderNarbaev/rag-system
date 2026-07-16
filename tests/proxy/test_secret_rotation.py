# ruff: noqa: E501, SIM117, E402, N817
"""Tests for proxy/app/auth/secret_rotation.py — Secrets rotation automation."""

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio

from proxy.app.auth.secret_rotation import (
    DEFAULT_API_KEY_OVERLAP_SECONDS,
    DEFAULT_JWT_GRACE_SECONDS,
    ROTATION_SIGNAL_FILE,
    ROTATION_STATE_DIR,
    EC_CURVE,
    RSA_KEY_SIZE,
    JWTKeyPair,
    RotationRecord,
    RotationStatus,
    SecretRotationManager,
    SecretType,
    get_rotation_manager,
)


# ── Data Model Tests ──────────────────────────────────────────────────────────


class TestRotationStatus:
    def test_enum_values(self):
        assert RotationStatus.PENDING.value == "pending"
        assert RotationStatus.IN_PROGRESS.value == "in_progress"
        assert RotationStatus.COMPLETED.value == "completed"
        assert RotationStatus.FAILED.value == "failed"
        assert RotationStatus.ROLLED_BACK.value == "rolled_back"

    def test_enum_members(self):
        assert len(RotationStatus) == 5


class TestSecretType:
    def test_enum_values(self):
        assert SecretType.JWT_SIGNING_KEY.value == "jwt_signing_key"
        assert SecretType.API_KEY.value == "api_key"
        assert SecretType.DATABASE_PASSWORD.value == "database_password"
        assert SecretType.EMBEDDER_API_KEY.value == "embedder_api_key"
        assert SecretType.RERANKER_API_KEY.value == "reranker_api_key"
        assert SecretType.LLM_API_KEY.value == "llm_api_key"

    def test_enum_members(self):
        assert len(SecretType) == 6


class TestRotationRecord:
    def test_to_dict_basic(self):
        record = RotationRecord(
            rotation_id="rot_123",
            secret_type="jwt_signing_key",
            status="completed",
            started_at="2025-01-01T00:00:00",
        )
        result = record.to_dict()
        assert result["rotation_id"] == "rot_123"
        assert result["secret_type"] == "jwt_signing_key"
        assert result["status"] == "completed"
        assert result["started_at"] == "2025-01-01T00:00:00"
        # None fields should be excluded
        assert "completed_at" not in result
        assert "error" not in result

    def test_to_dict_with_all_fields(self):
        record = RotationRecord(
            rotation_id="rot_456",
            secret_type="api_key",
            status="failed",
            started_at="2025-01-01T00:00:00",
            completed_at="2025-01-01T00:01:00",
            initiated_by="admin",
            details={"users_rotated": 5},
            error="something broke",
            old_key_fingerprint="abc123",
            new_key_fingerprint="def456",
            grace_period_seconds=3600,
            expires_at="2025-01-01T01:00:00",
        )
        result = record.to_dict()
        assert result["rotation_id"] == "rot_456"
        assert result["initiated_by"] == "admin"
        assert result["details"] == {"users_rotated": 5}
        assert result["error"] == "something broke"
        assert result["grace_period_seconds"] == 3600

    def test_to_dict_filters_none_values(self):
        record = RotationRecord(
            rotation_id="rot_789",
            secret_type="jwt_signing_key",
            status="pending",
            started_at="2025-01-01T00:00:00",
        )
        result = record.to_dict()
        for v in result.values():
            assert v is not None


class TestJWTKeyPair:
    def test_fingerprint_auto_generated(self):
        kp = JWTKeyPair(
            key_id="key_1",
            algorithm="RS256",
            private_key_pem="private",
            public_key_pem="public_key_data",
            created_at="2025-01-01T00:00:00",
        )
        assert kp.fingerprint != ""
        assert len(kp.fingerprint) == 16

    def test_fingerprint_is_sha256_prefix(self):
        import hashlib

        pub_key = "my_public_key"
        expected = hashlib.sha256(pub_key.encode()).hexdigest()[:16]
        kp = JWTKeyPair(
            key_id="key_1",
            algorithm="RS256",
            private_key_pem="private",
            public_key_pem=pub_key,
            created_at="2025-01-01T00:00:00",
        )
        assert kp.fingerprint == expected

    def test_fingerprint_preserved_if_provided(self):
        kp = JWTKeyPair(
            key_id="key_1",
            algorithm="RS256",
            private_key_pem="private",
            public_key_pem="public_key_data",
            created_at="2025-01-01T00:00:00",
            fingerprint="custom_fp",
        )
        assert kp.fingerprint == "custom_fp"

    def test_optional_fields(self):
        kp = JWTKeyPair(
            key_id="key_1",
            algorithm="ES256",
            private_key_pem="priv",
            public_key_pem="pub",
            created_at="2025-01-01T00:00:00",
        )
        assert kp.expires_at is None
        assert kp.algorithm == "ES256"


# ── Constants ─────────────────────────────────────────────────────────────────


class TestConstants:
    def test_default_grace_seconds(self):
        assert DEFAULT_JWT_GRACE_SECONDS == 3600

    def test_default_api_key_overlap(self):
        assert DEFAULT_API_KEY_OVERLAP_SECONDS == 86400

    def test_rsa_key_size(self):
        assert RSA_KEY_SIZE == 2048

    def test_ec_curve(self):
        assert EC_CURVE == "secp256r1"


# ── SecretRotationManager Tests ──────────────────────────────────────────────


@pytest_asyncio.fixture
async def manager(tmp_path):
    """Create a SecretRotationManager with temp state directory."""
    state_dir = tmp_path / "rotation"
    state_dir.mkdir(parents=True, exist_ok=True)

    with patch("proxy.app.auth.secret_rotation.ROTATION_STATE_DIR", state_dir):
        mgr = SecretRotationManager(
            jwt_grace_seconds=60,
            api_key_overlap_seconds=120,
        )
        yield mgr


@pytest_asyncio.fixture
async def initialized_manager(manager):
    """Create an initialized SecretRotationManager."""
    await manager._ensure_initialized()
    return manager


class TestSecretRotationManagerInit:
    def test_default_values(self):
        mgr = SecretRotationManager()
        assert mgr._jwt_grace_seconds == DEFAULT_JWT_GRACE_SECONDS
        assert mgr._api_key_overlap_seconds == DEFAULT_API_KEY_OVERLAP_SECONDS
        assert mgr._active_rotations == {}
        assert mgr._rotation_history == []
        assert mgr._jwt_key_history == []
        assert mgr._last_rotation_time is None
        assert mgr._last_error is None
        assert mgr._total_rotations == 0
        assert mgr._failed_rotations == 0
        assert mgr._initialized is False

    def test_custom_values(self):
        mgr = SecretRotationManager(
            jwt_grace_seconds=120,
            api_key_overlap_seconds=240,
        )
        assert mgr._jwt_grace_seconds == 120
        assert mgr._api_key_overlap_seconds == 240


class TestEnsureInitialized:
    @pytest.mark.asyncio
    async def test_creates_state_directory(self, tmp_path):
        state_dir = tmp_path / "new_rotation"
        with patch("proxy.app.auth.secret_rotation.ROTATION_STATE_DIR", state_dir):
            mgr = SecretRotationManager()
            assert not state_dir.exists()
            await mgr._ensure_initialized()
            assert state_dir.exists()
            assert mgr._initialized is True

    @pytest.mark.asyncio
    async def test_idempotent(self, initialized_manager):
        """Calling _ensure_initialized twice should be a no-op."""
        assert initialized_manager._initialized is True
        await initialized_manager._ensure_initialized()
        assert initialized_manager._initialized is True

    @pytest.mark.asyncio
    async def test_loads_existing_state(self, tmp_path):
        state_dir = tmp_path / "rotation"
        state_dir.mkdir(parents=True, exist_ok=True)
        state_file = state_dir / "rotation_state.json"
        state = {
            "last_rotation_time": "2025-01-01T00:00:00",
            "total_rotations": 5,
            "failed_rotations": 1,
            "last_error": "test error",
        }
        state_file.write_text(json.dumps(state))

        with patch("proxy.app.auth.secret_rotation.ROTATION_STATE_DIR", state_dir):
            mgr = SecretRotationManager()
            await mgr._ensure_initialized()

        assert mgr._last_rotation_time == "2025-01-01T00:00:00"
        assert mgr._total_rotations == 5
        assert mgr._failed_rotations == 1
        assert mgr._last_error == "test error"

    @pytest.mark.asyncio
    async def test_handles_corrupt_state_file(self, tmp_path):
        state_dir = tmp_path / "rotation"
        state_dir.mkdir(parents=True, exist_ok=True)
        state_file = state_dir / "rotation_state.json"
        state_file.write_text("not valid json!!!")

        with patch("proxy.app.auth.secret_rotation.ROTATION_STATE_DIR", state_dir):
            mgr = SecretRotationManager()
            # Should not raise, just warn
            await mgr._ensure_initialized()
            assert mgr._initialized is True

    @pytest.mark.asyncio
    async def test_handles_missing_state_file(self, tmp_path):
        state_dir = tmp_path / "rotation"
        state_dir.mkdir(parents=True, exist_ok=True)

        with patch("proxy.app.auth.secret_rotation.ROTATION_STATE_DIR", state_dir):
            mgr = SecretRotationManager()
            await mgr._ensure_initialized()
            assert mgr._initialized is True
            assert mgr._total_rotations == 0


class TestGenerateJWTKeyPair:
    def test_generates_hs256_fallback(self):
        """When cryptography is not available, should fall back to HS256."""
        with patch.dict("sys.modules", {"cryptography": None, "cryptography.hazmat": None, "cryptography.hazmat.primitives": None, "cryptography.hazmat.primitives.asymmetric": None}):
            kp = SecretRotationManager._generate_jwt_key_pair("RS256")
            assert kp.algorithm == "HS256"
            assert kp.key_id.startswith("key_")
            assert len(kp.private_key_pem) > 0
            assert kp.public_key_pem == kp.private_key_pem
            assert kp.fingerprint != ""

    def test_generates_rs256_key_pair(self):
        """Test RS256 key generation when cryptography is available, or HS256 fallback."""
        kp = SecretRotationManager._generate_jwt_key_pair("RS256")
        # If cryptography is installed, we get RS256; otherwise HS256 fallback
        try:
            import cryptography  # noqa: F401

            assert kp.algorithm == "RS256"
            assert "BEGIN PRIVATE KEY" in kp.private_key_pem
            assert "BEGIN PUBLIC KEY" in kp.public_key_pem
        except ImportError:
            assert kp.algorithm == "HS256"
        assert kp.key_id.startswith("key_")
        assert len(kp.fingerprint) == 16

    def test_generates_es256_key_pair(self):
        """Test ES256 key generation when cryptography is available, or HS256 fallback."""
        kp = SecretRotationManager._generate_jwt_key_pair("ES256")
        try:
            import cryptography  # noqa: F401

            assert kp.algorithm == "ES256"
            assert "BEGIN PRIVATE KEY" in kp.private_key_pem
            assert "BEGIN PUBLIC KEY" in kp.public_key_pem
        except ImportError:
            assert kp.algorithm == "HS256"

    def test_default_algorithm_is_rs256(self):
        kp = SecretRotationManager._generate_jwt_key_pair()
        try:
            import cryptography  # noqa: F401

            assert kp.algorithm == "RS256"
        except ImportError:
            assert kp.algorithm == "HS256"


class TestRotateJWTKeys:
    @pytest.mark.asyncio
    async def test_successful_rotation(self, initialized_manager, monkeypatch):
        monkeypatch.setattr(
            "proxy.app.auth.secret_rotation.ROTATION_SIGNAL_FILE",
            "/tmp/test_rag_signal_" + os.urandom(4).hex(),
        )
        with patch("proxy.app.shared.config.JWT_SECRET", "old_secret_value"):
            record = await initialized_manager.rotate_jwt_keys(
                algorithm="RS256",
                initiated_by="test_admin",
                grace_seconds=30,
            )

        assert record.status == RotationStatus.COMPLETED.value
        assert record.initiated_by == "test_admin"
        assert record.grace_period_seconds == 30
        assert record.old_key_fingerprint is not None
        assert record.new_key_fingerprint is not None
        assert record.completed_at is not None
        assert record.expires_at is not None
        assert record.details["algorithm"] == "RS256"
        assert "key_id" in record.details

        # Manager state should be updated
        assert initialized_manager._total_rotations == 1
        assert initialized_manager._failed_rotations == 0
        assert initialized_manager._last_rotation_time is not None
        assert len(initialized_manager._rotation_history) == 1
        assert len(initialized_manager._jwt_key_history) == 1
        assert record.rotation_id not in initialized_manager._active_rotations

    @pytest.mark.asyncio
    async def test_failed_rotation(self, initialized_manager, monkeypatch):
        monkeypatch.setattr(
            "proxy.app.auth.secret_rotation.ROTATION_SIGNAL_FILE",
            "/tmp/test_rag_signal_" + os.urandom(4).hex(),
        )
        with (
            patch("proxy.app.shared.config.JWT_SECRET", "old_secret"),
            patch.object(initialized_manager, "_generate_jwt_key_pair", side_effect=RuntimeError("key gen failed")),
        ):
            record = await initialized_manager.rotate_jwt_keys(
                algorithm="RS256",
                initiated_by="test_admin",
            )

        assert record.status == RotationStatus.FAILED.value
        assert record.error == "key gen failed"
        assert record.completed_at is not None
        assert initialized_manager._failed_rotations == 1
        assert initialized_manager._last_error == "key gen failed"
        assert len(initialized_manager._rotation_history) == 1

    @pytest.mark.asyncio
    async def test_rotation_with_es256(self, initialized_manager, monkeypatch):
        monkeypatch.setattr(
            "proxy.app.auth.secret_rotation.ROTATION_SIGNAL_FILE",
            "/tmp/test_rag_signal_" + os.urandom(4).hex(),
        )
        with patch("proxy.app.shared.config.JWT_SECRET", "old_secret"):
            record = await initialized_manager.rotate_jwt_keys(algorithm="ES256")

        assert record.status == RotationStatus.COMPLETED.value
        assert record.details["algorithm"] == "ES256"
        # ES256 doesn't set JWT_PUBLIC_KEY
        assert os.environ.get("JWT_ALGORITHM") == "ES256"

    @pytest.mark.asyncio
    async def test_rotation_sets_environment_variables(self, initialized_manager, monkeypatch):
        signal_file = "/tmp/test_rag_signal_" + os.urandom(4).hex()
        monkeypatch.setattr(
            "proxy.app.auth.secret_rotation.ROTATION_SIGNAL_FILE",
            signal_file,
        )
        with patch("proxy.app.shared.config.JWT_SECRET", "old_secret"):
            await initialized_manager.rotate_jwt_keys(algorithm="RS256")

        assert "JWT_SECRET" in os.environ
        assert "JWT_ALGORITHM" in os.environ
        assert os.environ["JWT_ALGORITHM"] == "RS256"

    @pytest.mark.asyncio
    async def test_rotation_with_default_grace(self, initialized_manager, monkeypatch):
        monkeypatch.setattr(
            "proxy.app.auth.secret_rotation.ROTATION_SIGNAL_FILE",
            "/tmp/test_rag_signal_" + os.urandom(4).hex(),
        )
        with patch("proxy.app.shared.config.JWT_SECRET", "old_secret"):
            record = await initialized_manager.rotate_jwt_keys()

        assert record.grace_period_seconds == 60  # custom fixture value

    @pytest.mark.asyncio
    async def test_rotation_cleared_from_active(self, initialized_manager, monkeypatch):
        monkeypatch.setattr(
            "proxy.app.auth.secret_rotation.ROTATION_SIGNAL_FILE",
            "/tmp/test_rag_signal_" + os.urandom(4).hex(),
        )
        with patch("proxy.app.shared.config.JWT_SECRET", "old_secret"):
            record = await initialized_manager.rotate_jwt_keys()

        assert record.rotation_id not in initialized_manager._active_rotations


class TestRotateAPIKeys:
    @pytest.mark.asyncio
    async def test_successful_rotation_with_users(self, initialized_manager):
        mock_key_manager = MagicMock()
        mock_key1 = MagicMock()
        mock_key1.user_id = "user1"
        mock_key1.is_active = True
        mock_key1.key_id = "key1"
        mock_key1.roles = ["user"]

        mock_key2 = MagicMock()
        mock_key2.user_id = "user2"
        mock_key2.is_active = True
        mock_key2.key_id = "key2"
        mock_key2.roles = ["admin"]

        mock_key_manager.list_keys.return_value = [mock_key1, mock_key2]
        mock_key_manager.generate_key.return_value = "sk-new-key-123"

        with patch("proxy.app.auth.api_keys.api_key_manager", mock_key_manager):
            record = await initialized_manager.rotate_api_keys(
                user_ids=["user1", "user2"],
                initiated_by="cron",
                overlap_seconds=60,
            )

        assert record.status == RotationStatus.COMPLETED.value
        assert record.initiated_by == "cron"
        assert record.details["users_rotated"] == 2
        assert record.details["keys_generated"] == 2
        assert record.details["overlap_seconds"] == 60
        assert initialized_manager._total_rotations == 1

    @pytest.mark.asyncio
    async def test_rotation_all_users(self, initialized_manager):
        mock_key_manager = MagicMock()
        mock_key = MagicMock()
        mock_key.user_id = "user1"
        mock_key.is_active = True
        mock_key.key_id = "key1"
        mock_key.roles = ["user"]

        mock_key_manager.list_keys.return_value = [mock_key]
        mock_key_manager.generate_key.return_value = "sk-new-key"

        with patch("proxy.app.auth.api_keys.api_key_manager", mock_key_manager):
            record = await initialized_manager.rotate_api_keys(initiated_by="system")

        assert record.status == RotationStatus.COMPLETED.value
        mock_key_manager.list_keys.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_rotation_no_active_keys(self, initialized_manager):
        mock_key_manager = MagicMock()
        mock_inactive = MagicMock()
        mock_inactive.is_active = False
        mock_key_manager.list_keys.return_value = [mock_inactive]

        with patch("proxy.app.auth.api_keys.api_key_manager", mock_key_manager):
            record = await initialized_manager.rotate_api_keys()

        assert record.status == RotationStatus.COMPLETED.value
        assert record.details["users_rotated"] == 0
        assert record.details["keys_generated"] == 0

    @pytest.mark.asyncio
    async def test_rotation_failure(self, initialized_manager):
        mock_key_manager = MagicMock()
        mock_key_manager.list_keys.side_effect = RuntimeError("DB connection lost")

        with patch("proxy.app.auth.api_keys.api_key_manager", mock_key_manager):
            record = await initialized_manager.rotate_api_keys()

        assert record.status == RotationStatus.FAILED.value
        assert record.error == "DB connection lost"
        assert initialized_manager._failed_rotations == 1
        assert initialized_manager._last_error == "DB connection lost"

    @pytest.mark.asyncio
    async def test_rotation_deduplicates_users(self, initialized_manager):
        """Each user should only get one new key per rotation."""
        mock_key_manager = MagicMock()
        mock_key1 = MagicMock()
        mock_key1.user_id = "user1"
        mock_key1.is_active = True
        mock_key1.key_id = "key1"
        mock_key1.roles = ["user"]

        mock_key2 = MagicMock()
        mock_key2.user_id = "user1"  # same user
        mock_key2.is_active = True
        mock_key2.key_id = "key2"
        mock_key2.roles = ["user"]

        mock_key_manager.list_keys.return_value = [mock_key1, mock_key2]
        mock_key_manager.generate_key.return_value = "sk-new-key"

        with patch("proxy.app.auth.api_keys.api_key_manager", mock_key_manager):
            record = await initialized_manager.rotate_api_keys(user_ids=["user1"])

        assert record.details["users_rotated"] == 1
        assert record.details["keys_generated"] == 1

    @pytest.mark.asyncio
    async def test_rotation_with_default_overlap(self, initialized_manager):
        mock_key_manager = MagicMock()
        mock_key_manager.list_keys.return_value = []

        with patch("proxy.app.auth.api_keys.api_key_manager", mock_key_manager):
            record = await initialized_manager.rotate_api_keys()

        assert record.details["overlap_seconds"] == 120  # custom fixture value


class TestNotifyServices:
    @pytest.mark.asyncio
    async def test_notify_services(self, initialized_manager, monkeypatch):
        signal_file = "/tmp/test_rag_signal_" + os.urandom(4).hex()
        monkeypatch.setattr(
            "proxy.app.auth.secret_rotation.ROTATION_SIGNAL_FILE",
            signal_file,
        )
        result = await initialized_manager.notify_services()
        assert result is True
        assert Path(signal_file).exists()

        # Verify content is valid JSON
        content = json.loads(Path(signal_file).read_text())
        assert "rotated_at" in content
        assert "pid" in content


class TestGetRotationStatus:
    def test_initial_status(self, initialized_manager):
        status = initialized_manager.get_rotation_status()
        assert status["status"] == "ok"
        assert status["last_rotation"] is None
        assert status["total_rotations"] == 0
        assert status["failed_rotations"] == 0
        assert status["active_rotations"] == 0
        assert status["jwt_key_age_seconds"] is None
        assert status["last_error"] is None
        assert status["grace_period_seconds"] == 60

    @pytest.mark.asyncio
    async def test_status_after_successful_rotation(self, initialized_manager, monkeypatch):
        monkeypatch.setattr(
            "proxy.app.auth.secret_rotation.ROTATION_SIGNAL_FILE",
            "/tmp/test_rag_signal_" + os.urandom(4).hex(),
        )
        with patch("proxy.app.shared.config.JWT_SECRET", "old_secret"):
            await initialized_manager.rotate_jwt_keys()

        status = initialized_manager.get_rotation_status()
        assert status["status"] == "ok"
        assert status["total_rotations"] == 1
        assert status["failed_rotations"] == 0
        assert status["last_rotation"] is not None
        assert status["jwt_key_age_seconds"] is not None
        assert status["jwt_key_age_seconds"] >= 0

    @pytest.mark.asyncio
    async def test_status_degraded_after_failure(self, initialized_manager):
        mock_key_manager = MagicMock()
        mock_key_manager.list_keys.side_effect = RuntimeError("boom")

        with patch("proxy.app.auth.api_keys.api_key_manager", mock_key_manager):
            await initialized_manager.rotate_api_keys()

        status = initialized_manager.get_rotation_status()
        assert status["status"] == "degraded"
        assert status["failed_rotations"] == 1
        assert status["last_error"] == "boom"

    def test_status_with_active_rotation(self, initialized_manager):
        """Active rotations should set status to 'rotating'."""
        initialized_manager._active_rotations["test"] = RotationRecord(
            rotation_id="test",
            secret_type="jwt_signing_key",
            status="in_progress",
            started_at="2025-01-01T00:00:00",
        )
        status = initialized_manager.get_rotation_status()
        assert status["status"] == "rotating"
        assert status["active_rotations"] == 1

    @pytest.mark.asyncio
    async def test_status_stale_key(self, initialized_manager, monkeypatch):
        """Keys older than 30 days should show stale_key status."""
        monkeypatch.setattr(
            "proxy.app.auth.secret_rotation.ROTATION_SIGNAL_FILE",
            "/tmp/test_rag_signal_" + os.urandom(4).hex(),
        )
        with patch("proxy.app.shared.config.JWT_SECRET", "old_secret"):
            await initialized_manager.rotate_jwt_keys()

        # Manually set the key creation to 31 days ago
        old_key = initialized_manager._jwt_key_history[-1]
        old_time = (datetime.now(UTC) - timedelta(days=31)).isoformat()
        old_key.created_at = old_time

        status = initialized_manager.get_rotation_status()
        assert status["status"] == "stale_key"

    def test_status_with_invalid_key_timestamp(self, initialized_manager):
        """Invalid timestamp in key history should not crash."""
        bad_key = JWTKeyPair(
            key_id="bad",
            algorithm="HS256",
            private_key_pem="secret",
            public_key_pem="secret",
            created_at="not-a-valid-date",
        )
        initialized_manager._jwt_key_history.append(bad_key)
        status = initialized_manager.get_rotation_status()
        # Should fall back to None for key age
        assert status["jwt_key_age_seconds"] is None

    def test_status_with_naive_timestamp(self, initialized_manager):
        """Naive timestamp (no timezone) should be handled gracefully."""
        naive_key = JWTKeyPair(
            key_id="naive",
            algorithm="HS256",
            private_key_pem="secret",
            public_key_pem="secret",
            created_at="2025-01-01T00:00:00",  # no timezone
        )
        initialized_manager._jwt_key_history.append(naive_key)
        status = initialized_manager.get_rotation_status()
        assert status["jwt_key_age_seconds"] is not None
        assert status["jwt_key_age_seconds"] > 0


class TestGetRotationHistory:
    @pytest.mark.asyncio
    async def test_empty_history(self, initialized_manager):
        assert initialized_manager.get_rotation_history() == []

    @pytest.mark.asyncio
    async def test_history_after_rotations(self, initialized_manager, monkeypatch):
        monkeypatch.setattr(
            "proxy.app.auth.secret_rotation.ROTATION_SIGNAL_FILE",
            "/tmp/test_rag_signal_" + os.urandom(4).hex(),
        )
        with patch("proxy.app.shared.config.JWT_SECRET", "old_secret"):
            await initialized_manager.rotate_jwt_keys()
            await initialized_manager.rotate_jwt_keys()

        history = initialized_manager.get_rotation_history()
        assert len(history) == 2
        assert all("rotation_id" in r for r in history)

    @pytest.mark.asyncio
    async def test_history_limit(self, initialized_manager, monkeypatch):
        monkeypatch.setattr(
            "proxy.app.auth.secret_rotation.ROTATION_SIGNAL_FILE",
            "/tmp/test_rag_signal_" + os.urandom(4).hex(),
        )
        with patch("proxy.app.shared.config.JWT_SECRET", "old_secret"):
            for _ in range(5):
                await initialized_manager.rotate_jwt_keys()

        history = initialized_manager.get_rotation_history(limit=3)
        assert len(history) == 3


class TestPersistAndLoad:
    @pytest.mark.asyncio
    async def test_persist_state(self, initialized_manager, tmp_path):
        initialized_manager._last_rotation_time = "2025-01-01T00:00:00"
        initialized_manager._total_rotations = 10
        initialized_manager._failed_rotations = 2
        initialized_manager._last_error = "test error"
        await initialized_manager._persist_state()

        # Verify file was created under the patched state dir
        state_dir = tmp_path / "rotation"
        state_file = state_dir / "rotation_state.json"
        assert state_file.exists()
        data = json.loads(state_file.read_text())
        assert data["total_rotations"] == 10
        assert data["failed_rotations"] == 2
        assert data["last_error"] == "test error"
        assert data["last_rotation_time"] == "2025-01-01T00:00:00"

    @pytest.mark.asyncio
    async def test_persist_key_pair(self, initialized_manager, tmp_path):
        kp = JWTKeyPair(
            key_id="key_test",
            algorithm="RS256",
            private_key_pem="private",
            public_key_pem="public",
            created_at="2025-01-01T00:00:00",
            fingerprint="abc123",
        )
        await initialized_manager._persist_key_pair(kp)

        # Verify by checking that no exception was raised and state dir exists
        assert initialized_manager._initialized is True

    @pytest.mark.asyncio
    async def test_persist_key_pair_handles_error(self, initialized_manager):
        """Write to an invalid path should not raise."""
        kp = JWTKeyPair(
            key_id="key_err",
            algorithm="HS256",
            private_key_pem="private",
            public_key_pem="public",
            created_at="2025-01-01T00:00:00",
            fingerprint="err123",
        )
        with patch("builtins.open", side_effect=OSError("disk full")):
            # Should not raise
            await initialized_manager._persist_key_pair(kp)


class TestSignalReload:
    @pytest.mark.asyncio
    async def test_signal_reload_success(self, monkeypatch):
        signal_file = "/tmp/test_rag_signal_" + os.urandom(4).hex()
        monkeypatch.setattr(
            "proxy.app.auth.secret_rotation.ROTATION_SIGNAL_FILE",
            signal_file,
        )
        result = await SecretRotationManager._signal_reload()
        assert result is True
        assert Path(signal_file).exists()

        content = json.loads(Path(signal_file).read_text())
        assert "rotated_at" in content
        assert "pid" in content

    @pytest.mark.asyncio
    async def test_signal_reload_failure(self, monkeypatch):
        monkeypatch.setattr(
            "proxy.app.auth.secret_rotation.ROTATION_SIGNAL_FILE",
            "/nonexistent/dir/signal.json",
        )
        result = await SecretRotationManager._signal_reload()
        assert result is False


class TestLogRotationAudit:
    def test_audit_success(self, tmp_path):
        record = RotationRecord(
            rotation_id="rot_test",
            secret_type="jwt_signing_key",
            status="completed",
            started_at="2025-01-01T00:00:00",
            initiated_by="admin",
            old_key_fingerprint="old_fp",
            new_key_fingerprint="new_fp",
        )
        with patch("proxy.app.shared.audit.AuditLogger") as mock_audit_cls:
            mock_audit = MagicMock()
            mock_audit_cls.return_value = mock_audit
            SecretRotationManager._log_rotation_audit(record)
            mock_audit.log_config_change.assert_called_once_with(
                user_id="admin",
                key="secret_rotation.jwt_signing_key",
                old_value="old_fp",
                new_value="new_fp",
            )

    def test_audit_failure_does_not_raise(self):
        """Audit failure should be logged but not raise."""
        record = RotationRecord(
            rotation_id="rot_test",
            secret_type="jwt_signing_key",
            status="completed",
            started_at="2025-01-01T00:00:00",
            initiated_by="admin",
        )
        with patch("proxy.app.shared.audit.AuditLogger", side_effect=ImportError("no audit module")):
            # Should not raise
            SecretRotationManager._log_rotation_audit(record)

    def test_audit_with_missing_fingerprints(self):
        record = RotationRecord(
            rotation_id="rot_test",
            secret_type="api_key",
            status="completed",
            started_at="2025-01-01T00:00:00",
            initiated_by="system",
        )
        with patch("proxy.app.shared.audit.AuditLogger") as mock_audit_cls:
            mock_audit = MagicMock()
            mock_audit_cls.return_value = mock_audit
            SecretRotationManager._log_rotation_audit(record)
            mock_audit.log_config_change.assert_called_once_with(
                user_id="system",
                key="secret_rotation.api_key",
                old_value="unknown",
                new_value="unknown",
            )


class TestGetRotationManager:
    def test_singleton_creation(self):
        import proxy.app.auth.secret_rotation as mod

        # Reset the global singleton
        old = mod._rotation_manager
        mod._rotation_manager = None
        try:
            mgr = get_rotation_manager()
            assert isinstance(mgr, SecretRotationManager)
            # Should return same instance
            assert get_rotation_manager() is mgr
        finally:
            mod._rotation_manager = old


class TestRotationLifecycleIntegration:
    """Integration tests for the full rotation lifecycle."""

    @pytest.mark.asyncio
    async def test_full_jwt_rotation_lifecycle(self, tmp_path, monkeypatch):
        state_dir = tmp_path / "rotation"
        signal_file = str(tmp_path / "signal.json")
        monkeypatch.setattr("proxy.app.auth.secret_rotation.ROTATION_STATE_DIR", state_dir)
        monkeypatch.setattr("proxy.app.auth.secret_rotation.ROTATION_SIGNAL_FILE", signal_file)

        with patch("proxy.app.shared.config.JWT_SECRET", "initial_secret"):
            mgr = SecretRotationManager(jwt_grace_seconds=300)
            await mgr._ensure_initialized()

            # First rotation
            record1 = await mgr.rotate_jwt_keys(algorithm="RS256", initiated_by="admin")
            assert record1.status == RotationStatus.COMPLETED.value
            assert mgr._total_rotations == 1

            # Check status
            status = mgr.get_rotation_status()
            assert status["status"] == "ok"
            assert status["total_rotations"] == 1

            # Second rotation
            record2 = await mgr.rotate_jwt_keys(algorithm="ES256", initiated_by="cron")
            assert record2.status == RotationStatus.COMPLETED.value
            assert mgr._total_rotations == 2

            # History should have both
            history = mgr.get_rotation_history()
            assert len(history) == 2

            # State file should exist
            state_file = state_dir / "rotation_state.json"
            assert state_file.exists()

    @pytest.mark.asyncio
    async def test_rotation_with_mixed_success_failure(self, tmp_path, monkeypatch):
        state_dir = tmp_path / "rotation"
        signal_file = str(tmp_path / "signal.json")
        monkeypatch.setattr("proxy.app.auth.secret_rotation.ROTATION_STATE_DIR", state_dir)
        monkeypatch.setattr("proxy.app.auth.secret_rotation.ROTATION_SIGNAL_FILE", signal_file)

        with patch("proxy.app.shared.config.JWT_SECRET", "initial_secret"):
            mgr = SecretRotationManager()
            await mgr._ensure_initialized()

            # Successful rotation
            await mgr.rotate_jwt_keys()

            # Failed API key rotation
            mock_key_manager = MagicMock()
            mock_key_manager.list_keys.side_effect = RuntimeError("connection lost")
            with patch("proxy.app.auth.api_keys.api_key_manager", mock_key_manager):
                await mgr.rotate_api_keys()

            status = mgr.get_rotation_status()
            assert status["total_rotations"] == 1  # only successful ones counted
            assert status["failed_rotations"] == 1
            assert status["status"] == "degraded"
            assert status["last_error"] == "connection lost"
