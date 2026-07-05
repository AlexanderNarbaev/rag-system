import os
import json
import pytest
from federation.app.config import load_silos, FEDERATION_MODE, FEDERATION_MERGE_K, FEDERATION_RRF_K


SAMPLE_SILOS_JSON = json.dumps([
    {
        "id": "hr",
        "name": "HR Knowledge Base",
        "proxy_url": "http://rag-hr:8000/v1",
        "api_key": "sk-hr",
        "weight": 1.0,
        "access_groups": ["hr", "admin"],
        "collections": ["hr_policies"],
        "timeout_s": 10,
        "is_primary": False
    },
    {
        "id": "engineering",
        "name": "Engineering Wiki",
        "proxy_url": "http://rag-eng:8000/v1",
        "api_key": "sk-eng",
        "weight": 1.2,
        "access_groups": ["engineering", "admin"],
        "collections": ["confluence", "jira"],
        "timeout_s": 10,
        "is_primary": True
    }
])


class TestConfig:
    def test_load_silos_from_env_json(self, monkeypatch):
        monkeypatch.setenv("FEDERATION_INSTANCES_JSON", SAMPLE_SILOS_JSON)
        import federation.app.config as cfg
        monkeypatch.setattr(cfg, "FEDERATION_INSTANCES_JSON", SAMPLE_SILOS_JSON)
        from federation.app.config import load_silos
        silos = load_silos()
        assert len(silos) == 2
        assert silos[0].id == "hr"
        assert silos[0].weight == 1.0
        assert silos[1].id == "engineering"
        assert silos[1].is_primary is True

    def test_load_silos_empty_returns_list(self):
        from federation.app.config import load_silos
        import federation.app.config as cfg
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(cfg, "FEDERATION_INSTANCES_JSON", "[]")
        silos = load_silos()
        assert silos == []

    def test_default_config_values(self, monkeypatch):
        monkeypatch.setenv("FEDERATION_MODE", "merge")
        monkeypatch.setenv("FEDERATION_MERGE_K", "40")
        # Trigger initial module import, then reload to pick up monkeypatched env
        import federation.app.config
        import importlib
        importlib.reload(federation.app.config)
        from federation.app import config as cfg
        assert cfg.FEDERATION_MODE == "merge"
        assert cfg.FEDERATION_MERGE_K == 40
