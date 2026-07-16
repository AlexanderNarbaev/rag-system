# ruff: noqa: E501, SIM117, E402, N817, SIM105
"""Tests for proxy/app/model_evolution/model_registry.py — model registry."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from proxy.app.model_evolution.model_registry import ModelRegistry, ModelVersion


class TestModelVersion:
    """Tests for ModelVersion dataclass."""

    def test_defaults(self):
        mv = ModelVersion(name="m1", version="1.0", artifact_path="/path")
        assert mv.status == "staging"
        assert mv.metrics == {}
        assert mv.created_at  # auto-set

    def test_to_dict_roundtrip(self):
        mv = ModelVersion(name="m1", version="1.0", artifact_path="/path", metrics={"acc": 0.9})
        d = mv.to_dict()
        mv2 = ModelVersion.from_dict(d)
        assert mv2.name == mv.name
        assert mv2.version == mv.version
        assert mv2.metrics == mv.metrics


class TestModelRegistry:
    """Tests for ModelRegistry class."""

    @pytest.fixture
    def registry(self, tmp_path):
        """Create a registry with temp storage."""
        return ModelRegistry(store_path=str(tmp_path / "registry.json"))

    def test_init_creates_empty(self, registry):
        """Registry starts empty."""
        assert registry.list_models() == []

    def test_register_model(self, registry):
        """Register a new model version."""
        mv = registry.register(name="test-model", artifact_path="/path/to/model", metrics={"accuracy": 0.9})
        assert mv.name == "test-model"
        assert mv.status == "staging"

    def test_register_with_version(self, registry):
        """Register with explicit version."""
        mv = registry.register(name="m1", artifact_path="/p", version="2.0")
        assert mv.version == "2.0"

    def test_register_auto_version(self, registry):
        """Auto-increments version."""
        v1 = registry.register(name="m1", artifact_path="/p1")
        v2 = registry.register(name="m1", artifact_path="/p2")
        assert v2.version != v1.version

    def test_register_duplicate_raises(self, registry):
        """Duplicate version raises ValueError."""
        registry.register(name="m1", artifact_path="/p", version="1.0")
        with pytest.raises(ValueError, match="already exists"):
            registry.register(name="m1", artifact_path="/p2", version="1.0")

    def test_register_empty_name_raises(self, registry):
        """Empty name raises ValueError."""
        with pytest.raises(ValueError, match="name"):
            registry.register(name="", artifact_path="/p")

    def test_register_empty_path_raises(self, registry):
        """Empty artifact_path raises ValueError."""
        with pytest.raises(ValueError, match="artifact_path"):
            registry.register(name="m1", artifact_path="")

    def test_list_models(self, registry):
        """List all registered models."""
        registry.register(name="model-a", artifact_path="/a")
        registry.register(name="model-b", artifact_path="/b")
        models = registry.list_models()
        assert "model-a" in models
        assert "model-b" in models

    def test_get_model(self, registry):
        """Get a specific model version."""
        registry.register(name="m1", artifact_path="/m", version="1.0")
        mv = registry.get("m1", "1.0")
        assert mv.name == "m1"

    def test_get_not_found_raises(self, registry):
        """Getting non-existent model raises KeyError."""
        with pytest.raises(KeyError):
            registry.get("nonexistent", "1.0")

    def test_get_latest_production(self, registry):
        """Get production version."""
        registry.register(name="m1", artifact_path="/p1")
        registry.register(name="m1", artifact_path="/p2")
        # Get the actual version numbers
        versions = registry.list_versions("m1")
        v1 = versions[0].version
        registry.promote("m1", v1)  # staging -> canary
        registry.promote("m1", v1)  # canary -> production
        mv = registry.get_latest_production("m1")
        assert mv is not None
        assert mv.version == v1

    def test_get_latest_production_none(self, registry):
        """Returns None when no production version."""
        registry.register(name="m1", artifact_path="/p")
        assert registry.get_latest_production("m1") is None

    def test_get_latest_production_nonexistent(self, registry):
        """Returns None for non-existent model."""
        assert registry.get_latest_production("no-model") is None

    def test_get_latest(self, registry):
        """Get latest registered version."""
        registry.register(name="m1", artifact_path="/p1")
        registry.register(name="m1", artifact_path="/p2")
        mv = registry.get_latest("m1")
        assert mv is not None

    def test_get_latest_none(self, registry):
        """Returns None for non-existent model."""
        assert registry.get_latest("no-model") is None

    def test_list_versions(self, registry):
        """List versions for a specific model."""
        registry.register(name="m1", artifact_path="/a")
        registry.register(name="m1", artifact_path="/b")
        versions = registry.list_versions("m1")
        assert len(versions) == 2

    def test_list_versions_empty(self, registry):
        """Empty list for non-existent model."""
        assert registry.list_versions("no-model") == []

    def test_list_by_status(self, registry):
        """List versions by status."""
        registry.register(name="m1", artifact_path="/p1")
        registry.register(name="m1", artifact_path="/p2")
        staging = registry.list_by_status("m1", "staging")
        assert len(staging) == 2

    def test_promote_staging_to_canary(self, registry):
        """Promote from staging to canary."""
        mv = registry.register(name="m1", artifact_path="/p")
        mv2 = registry.promote("m1", mv.version)
        assert mv2.status == "canary"

    def test_promote_canary_to_production(self, registry):
        """Promote from canary to production."""
        mv = registry.register(name="m1", artifact_path="/p")
        registry.promote("m1", mv.version)  # staging -> canary
        mv2 = registry.promote("m1", mv.version)  # canary -> production
        assert mv2.status == "production"

    def test_promote_archives_previous(self, registry):
        """Promoting new version archives old production."""
        v1 = registry.register(name="m1", artifact_path="/p1")
        v2 = registry.register(name="m1", artifact_path="/p2")
        # Promote v1 to production
        registry.promote("m1", v1.version)
        registry.promote("m1", v1.version)
        # Promote v2 to production
        registry.promote("m1", v2.version)
        registry.promote("m1", v2.version)
        old = registry.get("m1", v1.version)
        assert old.status == "archived"

    def test_promote_production_noop(self, registry):
        """Promoting production version is a no-op."""
        mv = registry.register(name="m1", artifact_path="/p")
        registry.promote("m1", mv.version)
        registry.promote("m1", mv.version)
        mv2 = registry.promote("m1", mv.version)
        assert mv2.status == "production"

    def test_promote_nonexistent_raises(self, registry):
        """Promoting non-existent model raises KeyError."""
        with pytest.raises(KeyError):
            registry.promote("no-model", "1.0")

    def test_rollback(self, registry):
        """Rollback to previous production version."""
        v1 = registry.register(name="m1", artifact_path="/p1")
        v2 = registry.register(name="m1", artifact_path="/p2")
        # v1 -> production
        registry.promote("m1", v1.version)
        registry.promote("m1", v1.version)
        # v2 -> production (archives v1)
        registry.promote("m1", v2.version)
        registry.promote("m1", v2.version)
        # Rollback
        prev = registry.rollback("m1")
        assert prev.version == v1.version
        assert prev.status == "production"

    def test_rollback_no_production_raises(self, registry):
        """Rollback with no production raises ValueError."""
        registry.register(name="m1", artifact_path="/p")
        with pytest.raises(ValueError, match="No current production"):
            registry.rollback("m1")

    def test_rollback_no_previous_raises(self, registry):
        """Rollback with no previous production raises ValueError."""
        mv = registry.register(name="m1", artifact_path="/p")
        registry.promote("m1", mv.version)
        registry.promote("m1", mv.version)
        with pytest.raises(ValueError, match="No previous production"):
            registry.rollback("m1")

    def test_rollback_nonexistent_raises(self, registry):
        """Rollback for non-existent model raises KeyError."""
        with pytest.raises(KeyError):
            registry.rollback("no-model")

    def test_update_metrics(self, registry):
        """Update metrics for a model version."""
        mv = registry.register(name="m1", artifact_path="/p")
        registry.update_metrics("m1", mv.version, {"accuracy": 0.95})
        result = registry.get("m1", mv.version)
        assert result.metrics["accuracy"] == 0.95

    def test_delete_model(self, registry):
        """Delete a model version."""
        mv = registry.register(name="m1", artifact_path="/p")
        registry.delete("m1", mv.version)
        assert registry.list_models() == []

    def test_delete_nonexistent_raises(self, registry):
        """Deleting non-existent model raises KeyError."""
        with pytest.raises(KeyError):
            registry.delete("no-model", "1.0")

    def test_persistence(self, tmp_path):
        """Registry persists across instances."""
        path = str(tmp_path / "reg.json")
        reg1 = ModelRegistry(store_path=path)
        reg1.register(name="m1", artifact_path="/p", version="1.0")

        reg2 = ModelRegistry(store_path=path)
        mv = reg2.get("m1", "1.0")
        assert mv.name == "m1"

    def test_load_corrupted_json(self, tmp_path):
        """Registry handles corrupted JSON gracefully."""
        path = tmp_path / "reg.json"
        path.write_text("not json!", encoding="utf-8")
        reg = ModelRegistry(store_path=str(path))
        assert reg.list_models() == []

    def test_load_missing_file(self, tmp_path):
        """Registry handles missing file gracefully."""
        reg = ModelRegistry(store_path=str(tmp_path / "nonexistent.json"))
        assert reg.list_models() == []
