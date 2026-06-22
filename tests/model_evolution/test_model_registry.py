"""Tests for proxy/app/model_evolution/model_registry.py — ModelRegistry with JSON persistence."""

import json
import tempfile
from pathlib import Path

import pytest

from proxy.app.model_evolution.model_registry import ModelRegistry, ModelVersion


class TestModelVersion:
    def test_create_minimal(self):
        mv = ModelVersion(
            name="slm-intent-classifier",
            version="1",
            artifact_path="models/slm/v1",
            metrics={"accuracy": 0.93},
            status="staging",
        )
        assert mv.name == "slm-intent-classifier"
        assert mv.version == "1"
        assert mv.artifact_path == "models/slm/v1"
        assert mv.metrics == {"accuracy": 0.93}
        assert mv.status == "staging"
        assert mv.created_at is not None

    def test_create_full(self):
        mv = ModelVersion(
            name="llm-domain-generator",
            version="2",
            artifact_path="s3://bucket/models/llm/v2",
            metrics={"bertscore_f1": 0.78, "rouge_l": 0.42},
            status="production",
            created_at="2026-07-05T10:00:00",
        )
        assert mv.name == "llm-domain-generator"
        assert mv.version == "2"
        assert mv.artifact_path == "s3://bucket/models/llm/v2"
        assert mv.metrics == {"bertscore_f1": 0.78, "rouge_l": 0.42}
        assert mv.status == "production"
        assert mv.created_at == "2026-07-05T10:00:00"

    def test_to_dict(self):
        mv = ModelVersion(
            name="reranker-domain",
            version="3",
            artifact_path="models/reranker/v3",
            metrics={"mrr": 0.82},
            status="canary",
        )
        d = mv.to_dict()
        assert d["name"] == "reranker-domain"
        assert d["version"] == "3"
        assert d["artifact_path"] == "models/reranker/v3"
        assert d["metrics"] == {"mrr": 0.82}
        assert d["status"] == "canary"
        assert d["created_at"] == mv.created_at

    def test_from_dict(self):
        d = {
            "name": "slm-intent-classifier",
            "version": "1",
            "artifact_path": "models/slm/v1",
            "metrics": {"accuracy": 0.93},
            "status": "production",
            "created_at": "2026-07-05T10:00:00",
        }
        mv = ModelVersion.from_dict(d)
        assert mv.name == "slm-intent-classifier"
        assert mv.version == "1"
        assert mv.artifact_path == "models/slm/v1"
        assert mv.metrics == {"accuracy": 0.93}
        assert mv.status == "production"
        assert mv.created_at == "2026-07-05T10:00:00"

    def test_from_dict_defaults(self):
        mv = ModelVersion.from_dict({
            "name": "test",
            "version": "1",
            "artifact_path": "path",
            "metrics": {},
            "status": "staging",
        })
        assert mv.created_at is not None


class TestModelRegistryRegister:
    @pytest.fixture
    def tmp_store(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / "registry.json"

    def test_register_first_version(self, tmp_store):
        registry = ModelRegistry(store_path=str(tmp_store))
        mv = registry.register(
            name="slm-intent-classifier",
            version="1",
            artifact_path="models/slm/v1",
            metrics={"accuracy": 0.93},
        )
        assert mv.name == "slm-intent-classifier"
        assert mv.version == "1"
        assert mv.status == "staging"
        assert tmp_store.exists()

    def test_register_increments_version_if_not_specified(self, tmp_store):
        registry = ModelRegistry(store_path=str(tmp_store))
        registry.register(name="test-model", artifact_path="models/test/v1", metrics={})
        mv2 = registry.register(name="test-model", artifact_path="models/test/v2", metrics={})
        assert mv2.version == "2"

    def test_register_duplicate_version_raises(self, tmp_store):
        registry = ModelRegistry(store_path=str(tmp_store))
        registry.register(name="test-model", version="1", artifact_path="p1", metrics={})
        with pytest.raises(ValueError, match="already exists"):
            registry.register(name="test-model", version="1", artifact_path="p2", metrics={})

    def test_register_persists_and_reloads(self, tmp_store):
        registry = ModelRegistry(store_path=str(tmp_store))
        registry.register(name="slm", version="1", artifact_path="path/v1", metrics={"f1": 0.85})

        registry2 = ModelRegistry(store_path=str(tmp_store))
        mv = registry2.get("slm", "1")
        assert mv.name == "slm"
        assert mv.artifact_path == "path/v1"
        assert mv.status == "staging"

    def test_register_with_empty_metrics(self, tmp_store):
        registry = ModelRegistry(store_path=str(tmp_store))
        mv = registry.register(name="test", version="1", artifact_path="p")
        assert mv.metrics == {}


class TestModelRegistryGet:
    @pytest.fixture
    def registry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = Path(tmpdir) / "registry.json"
            r = ModelRegistry(store_path=str(store))
            r.register(name="slm", version="1", artifact_path="p1", metrics={"a": 1})
            r.register(name="slm", version="2", artifact_path="p2", metrics={"a": 2})
            r.register(name="llm", version="1", artifact_path="p3", metrics={"b": 3})
            yield r

    def test_get_existing_version(self, registry):
        mv = registry.get("slm", "1")
        assert mv.name == "slm"
        assert mv.version == "1"
        assert mv.metrics == {"a": 1}

    def test_get_nonexistent_model(self, registry):
        with pytest.raises(KeyError, match="Model 'nonexistent'"):
            registry.get("nonexistent", "1")

    def test_get_nonexistent_version(self, registry):
        with pytest.raises(KeyError, match="Version '99'"):
            registry.get("slm", "99")

    def test_get_latest_production(self, registry):
        registry.promote("slm", "2")  # staging → canary
        registry.promote("slm", "2")  # canary → production
        mv = registry.get_latest_production("slm")
        assert mv.version == "2"
        assert mv.status == "production"

    def test_get_latest_production_none(self, registry):
        mv = registry.get_latest_production("slm")
        assert mv is None


class TestModelRegistryList:
    @pytest.fixture
    def registry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = Path(tmpdir) / "registry.json"
            r = ModelRegistry(store_path=str(store))
            r.register(name="slm", version="1", artifact_path="p1", metrics={})
            r.register(name="slm", version="2", artifact_path="p2", metrics={})
            r.register(name="llm", version="1", artifact_path="p3", metrics={})
            yield r

    def test_list_all_models(self, registry):
        models = registry.list_models()
        assert set(models) == {"slm", "llm"}

    def test_list_versions_for_model(self, registry):
        versions = registry.list_versions("slm")
        assert len(versions) == 2
        assert {v.version for v in versions} == {"1", "2"}

    def test_list_versions_nonexistent_model(self, registry):
        versions = registry.list_versions("nonexistent")
        assert versions == []

    def test_list_by_status(self, registry):
        registry.promote("slm", "2")  # staging → canary
        registry.promote("slm", "2")  # canary → production
        production = registry.list_by_status("slm", "production")
        assert len(production) == 1
        assert production[0].version == "2"


class TestModelRegistryPromote:
    @pytest.fixture
    def registry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = Path(tmpdir) / "registry.json"
            r = ModelRegistry(store_path=str(store))
            r.register(name="slm", version="1", artifact_path="p1", metrics={"f1": 0.85})
            r.register(name="slm", version="2", artifact_path="p2", metrics={"f1": 0.93})
            r.register(name="llm", version="1", artifact_path="p3", metrics={"bs": 0.72})
            yield r

    def test_promote_staging_to_canary(self, registry):
        mv = registry.get("slm", "1")
        assert mv.status == "staging"

        promoted = registry.promote("slm", "1")
        assert promoted.status == "canary"

    def test_promote_canary_to_production(self, registry):
        registry.promote("slm", "1")  # staging → canary
        promoted = registry.promote("slm", "1")  # canary → production
        assert promoted.status == "production"

    def test_previous_production_archived_on_promote(self, registry):
        registry.promote("slm", "1")  # staging → canary
        registry.promote("slm", "1")  # canary → production
        assert registry.get("slm", "1").status == "production"

        registry.register(name="slm", version="3", artifact_path="p3", metrics={"f1": 0.95})
        registry.promote("slm", "3")  # staging → canary
        registry.promote("slm", "3")  # canary → production

        assert registry.get("slm", "3").status == "production"
        assert registry.get("slm", "1").status == "archived"

    def test_different_models_can_both_be_production(self, registry):
        registry.promote("slm", "1")
        registry.promote("slm", "1")
        registry.promote("llm", "1")
        registry.promote("llm", "1")

        assert registry.get("slm", "1").status == "production"
        assert registry.get("llm", "1").status == "production"

    def test_promote_from_archived_is_noop(self, registry):
        registry.promote("slm", "1")
        registry.promote("slm", "1")
        registry.promote("slm", "2")
        registry.promote("slm", "2")

        assert registry.get("slm", "1").status == "archived"
        promoted = registry.promote("slm", "1")
        assert promoted.status == "archived"

    def test_promote_already_production_is_noop(self, registry):
        registry.promote("slm", "1")
        registry.promote("slm", "1")
        assert registry.get("slm", "1").status == "production"

        promoted = registry.promote("slm", "1")
        assert promoted.status == "production"

    def test_promote_nonexistent_raises(self, registry):
        with pytest.raises(KeyError):
            registry.promote("nonexistent", "99")

    def test_promote_persists(self, tmp_path):
        store = tmp_path / "registry.json"
        r1 = ModelRegistry(store_path=str(store))
        r1.register(name="slm", version="1", artifact_path="p1", metrics={})
        r1.promote("slm", "1")
        r1.promote("slm", "1")

        r2 = ModelRegistry(store_path=str(store))
        assert r2.get("slm", "1").status == "production"

    def test_promote_with_canary_transition(self, registry):
        registry.promote("slm", "1")  # staging → canary
        assert registry.get("slm", "1").status == "canary"


class TestModelRegistryRollback:
    @pytest.fixture
    def populated_registry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = Path(tmpdir) / "registry.json"
            r = ModelRegistry(store_path=str(store))
            r.register(name="slm", version="1", artifact_path="p1", metrics={"f1": 0.85})
            r.register(name="slm", version="2", artifact_path="p2", metrics={"f1": 0.93})
            r.register(name="slm", version="3", artifact_path="p3", metrics={"f1": 0.91})
            yield r

    def test_rollback_reverts_to_previous_production(self, populated_registry):
        r = populated_registry
        r.promote("slm", "1")
        r.promote("slm", "1")
        r.promote("slm", "2")
        r.promote("slm", "2")

        assert r.get("slm", "2").status == "production"
        assert r.get("slm", "1").status == "archived"

        rolled_back = r.rollback("slm")
        assert rolled_back.status == "production"
        assert rolled_back.version == "1"
        assert r.get("slm", "2").status == "archived"

    def test_rollback_with_no_previous_production(self, populated_registry):
        r = populated_registry
        r.promote("slm", "1")
        r.promote("slm", "1")

        with pytest.raises(ValueError, match="No previous production version"):
            r.rollback("slm")

    def test_rollback_nonexistent_model_raises(self, populated_registry):
        with pytest.raises(KeyError, match="Model 'nonexistent'"):
            populated_registry.rollback("nonexistent")

    def test_rollback_with_no_production_at_all(self, populated_registry):
        r = populated_registry
        with pytest.raises(ValueError, match="No current production version"):
            r.rollback("slm")

    def test_rollback_persists(self, tmp_path):
        store = tmp_path / "registry.json"
        r1 = ModelRegistry(store_path=str(store))
        r1.register(name="slm", version="1", artifact_path="p1", metrics={})
        r1.register(name="slm", version="2", artifact_path="p2", metrics={})
        r1.promote("slm", "1")
        r1.promote("slm", "1")
        r1.promote("slm", "2")
        r1.promote("slm", "2")
        r1.rollback("slm")

        r2 = ModelRegistry(store_path=str(store))
        assert r2.get("slm", "1").status == "production"
        assert r2.get("slm", "2").status == "archived"


class TestModelRegistryUpdateMetrics:
    @pytest.fixture
    def registry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = Path(tmpdir) / "registry.json"
            r = ModelRegistry(store_path=str(store))
            r.register(name="slm", version="1", artifact_path="p1", metrics={"f1": 0.85})
            yield r

    def test_update_metrics(self, registry):
        registry.update_metrics("slm", "1", {"f1": 0.88, "accuracy": 0.93})
        mv = registry.get("slm", "1")
        assert mv.metrics == {"f1": 0.88, "accuracy": 0.93}

    def test_update_metrics_nonexistent(self, registry):
        with pytest.raises(KeyError):
            registry.update_metrics("nonexistent", "1", {})


class TestModelRegistryDelete:
    @pytest.fixture
    def registry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = Path(tmpdir) / "registry.json"
            r = ModelRegistry(store_path=str(store))
            r.register(name="slm", version="1", artifact_path="p1", metrics={})
            r.register(name="slm", version="2", artifact_path="p2", metrics={})
            yield r

    def test_delete_version(self, registry):
        registry.delete("slm", "1")
        with pytest.raises(KeyError):
            registry.get("slm", "1")
        assert registry.get("slm", "2") is not None

    def test_delete_nonexistent(self, registry):
        with pytest.raises(KeyError):
            registry.delete("slm", "99")

    def test_delete_persists(self, tmp_path):
        store = tmp_path / "registry.json"
        r1 = ModelRegistry(store_path=str(store))
        r1.register(name="slm", version="1", artifact_path="p1", metrics={})
        r1.delete("slm", "1")

        r2 = ModelRegistry(store_path=str(store))
        assert r2.list_versions("slm") == []


class TestModelRegistryPersistence:
    def test_empty_store_creates_file_on_first_write(self, tmp_path):
        store = tmp_path / "registry.json"
        assert not store.exists()
        r = ModelRegistry(store_path=str(store))
        r.register(name="test", version="1", artifact_path="p", metrics={})
        assert store.exists()

    def test_loads_existing_file(self, tmp_path):
        store = tmp_path / "registry.json"
        data = {
            "models": {
                "slm": {
                    "1": {
                        "name": "slm",
                        "version": "1",
                        "artifact_path": "p1",
                        "metrics": {"f1": 0.85},
                        "status": "production",
                        "created_at": "2026-07-05T10:00:00",
                    }
                }
            }
        }
        store.write_text(json.dumps(data))
        r = ModelRegistry(store_path=str(store))
        assert r.get("slm", "1").status == "production"

    def test_corrupt_json_resets_state(self, tmp_path):
        store = tmp_path / "registry.json"
        store.write_text("not json at all{{{")
        r = ModelRegistry(store_path=str(store))
        assert r.list_models() == []

    def test_file_permissions_error_graceful(self, tmp_path):
        store = tmp_path / "readonly" / "registry.json"
        store.parent.mkdir()
        store.write_text("{}")
        store.parent.chmod(0o444)
        try:
            r = ModelRegistry(store_path=str(store))
            assert r.list_models() == []
        finally:
            store.parent.chmod(0o755)

    def test_concurrent_access_same_registry_file(self, tmp_path):
        store = tmp_path / "registry.json"
        r1 = ModelRegistry(store_path=str(store))
        r1.register(name="model", version="1", artifact_path="p1", metrics={})

        r2 = ModelRegistry(store_path=str(store))
        assert r2.get("model", "1").version == "1"
