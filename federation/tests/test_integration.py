import importlib

import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import patch

from federation.app.models import SiloConfig, SiloSearchResult
from federation.app.silo_registry import SiloRegistry


@pytest.fixture
def mock_silos():
    return [
        SiloConfig(id="hr", name="HR KB", proxy_url="http://hr/v1",
                   weight=1.0, access_groups=["admin"], is_primary=True),
        SiloConfig(id="eng", name="Engineering", proxy_url="http://eng/v1",
                   weight=1.2, access_groups=["admin"], is_primary=False),
    ]


class TestFederationE2E:
    @pytest.mark.asyncio
    async def test_full_chat_flow_merge_mode(self, monkeypatch, mock_silos):
        monkeypatch.setenv("FEDERATION_MODE", "merge")
        import federation.app.config as config_mod
        import federation.app.main as main_mod
        importlib.reload(config_mod)
        importlib.reload(main_mod)

        with patch("federation.app.main.load_silos", return_value=mock_silos), \
             patch("federation.app.main.registry", SiloRegistry(mock_silos)), \
             patch("federation.app.main.federated_search") as mock_search:

            mock_search.return_value = type('obj', (object,), {
                'merged_chunks': [
                    {'id': 'c1', 'text': 'Policy: 5 days sick leave', 'score': 0.95,
                     'source_type': 'confluence', 'title': 'Sick Leave Policy',
                     'version': '2.0', 'silo_id': 'hr', 'silo_name': 'HR KB'}
                ],
                'silo_results': [
                    SiloSearchResult(silo_id='hr', silo_name='HR KB',
                                     chunks=[{'id': 'c1'}], latency_ms=50),
                    SiloSearchResult(silo_id='eng', silo_name='Engineering',
                                     chunks=[], latency_ms=120, error='timeout', partial=True),
                ],
                'total_latency_ms': 170,
                'errors': ['eng: timeout'],
                'skipped_silos': [],
            })()

            transport = ASGITransport(app=main_mod.app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post("/v1/chat/completions", json={
                    "model": "rag-federated",
                    "messages": [{"role": "user", "content": "sick leave policy"}],
                    "stream": False,
                })

        assert response.status_code == 200
        data = response.json()
        assert data["model"] == "rag-federated"
        assert len(data["rag_sources"]) == 1
        assert data["rag_sources"][0]["silo_id"] == "hr"
        assert data["federation"]["mode"] == "merge"
        assert data["federation"]["silos_queried"] == ["hr"]
        assert len(data["federation"]["warnings"]) == 1

    @pytest.mark.asyncio
    async def test_all_silos_fail_returns_error(self, monkeypatch, mock_silos):
        monkeypatch.setenv("FEDERATION_MODE", "merge")
        import federation.app.config as config_mod
        import federation.app.main as main_mod
        importlib.reload(config_mod)
        importlib.reload(main_mod)

        with patch("federation.app.main.load_silos", return_value=mock_silos), \
             patch("federation.app.main.registry", SiloRegistry(mock_silos)), \
             patch("federation.app.main.federated_search") as mock_search:

            mock_search.return_value = type('obj', (object,), {
                'merged_chunks': [],
                'silo_results': [
                    SiloSearchResult(silo_id='hr', silo_name='HR KB', chunks=[],
                                     latency_ms=5000, error='connection refused', partial=True),
                ],
                'total_latency_ms': 5000,
                'errors': ['hr: connection refused'],
                'skipped_silos': [],
            })()

            transport = ASGITransport(app=main_mod.app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post("/v1/chat/completions", json={
                    "model": "rag-federated",
                    "messages": [{"role": "user", "content": "query"}],
                })

        assert response.status_code == 503
        data = response.json()
        assert data["type"] == "AllSilosDownError"
        assert "hr" in data["error"]

    @pytest.mark.asyncio
    async def test_health_endpoint(self, monkeypatch, mock_silos):
        import federation.app.main as main_mod
        with patch("federation.app.main.load_silos", return_value=mock_silos), \
             patch("federation.app.main.registry", SiloRegistry(mock_silos)):
            transport = ASGITransport(app=main_mod.app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/v1/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["federation"]["total_silos"] == 2
        assert "hr" in data["federation"]["silos"]
        assert "eng" in data["federation"]["silos"]
