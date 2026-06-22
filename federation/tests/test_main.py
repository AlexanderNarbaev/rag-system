import contextlib
import importlib
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from federation.app.models import FederatedSearchResult, SiloSearchResult


def _reload_config_and_main(monkeypatch, instances_json, mode="merge"):
    monkeypatch.setenv("FEDERATION_INSTANCES_JSON", instances_json)
    monkeypatch.setenv("FEDERATION_MODE", mode)
    import federation.app.config as config_mod
    import federation.app.main as main_mod
    importlib.reload(config_mod)
    importlib.reload(main_mod)


async def _make_client(app):
    transport = ASGITransport(app=app)
    stack = contextlib.AsyncExitStack()
    await stack.enter_async_context(app.router.lifespan_context(app))
    client = AsyncClient(transport=transport, base_url="http://test")
    return client, stack


@pytest.mark.asyncio
async def test_health_live():
    from federation.app.main import app
    client, stack = await _make_client(app)
    try:
        response = await client.get("/v1/health/live")
    finally:
        await stack.aclose()
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_health_ready_no_silos():
    from federation.app.main import app
    client, stack = await _make_client(app)
    try:
        response = await client.get("/v1/health/ready")
    finally:
        await stack.aclose()
    assert response.status_code == 200
    data = response.json()
    assert "silos" in data


@pytest.mark.asyncio
async def test_health(monkeypatch):
    _reload_config_and_main(
        monkeypatch,
        '[{"id":"test","name":"Test","proxy_url":"http://test/v1","weight":1.0,"access_groups":["admin"],"is_primary":true}]'
    )
    from federation.app.main import app
    client, stack = await _make_client(app)
    try:
        response = await client.get("/v1/health")
    finally:
        await stack.aclose()
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "federation" in data


@pytest.mark.asyncio
async def test_silos_endpoint(monkeypatch):
    _reload_config_and_main(
        monkeypatch,
        '[{"id":"test","name":"Test","proxy_url":"http://test/v1","weight":1.0,"access_groups":["admin"],"is_primary":true}]'
    )
    from federation.app.main import app
    client, stack = await _make_client(app)
    try:
        response = await client.get("/v1/silos")
    finally:
        await stack.aclose()
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_models_endpoint():
    from federation.app.main import app
    client, stack = await _make_client(app)
    try:
        response = await client.get("/v1/models")
    finally:
        await stack.aclose()
    assert response.status_code == 200
    data = response.json()
    assert "data" in data


@pytest.mark.asyncio
async def test_chat_completions_merge_mode(monkeypatch):
    _reload_config_and_main(
        monkeypatch,
        '[{"id":"test","name":"Test","proxy_url":"http://test/v1","weight":1.0,"access_groups":["admin"],"is_primary":true}]'
    )

    mock_silo_result = SiloSearchResult(
        silo_id="test", silo_name="Test",
        chunks=[{"id": "c1", "text": "Hello", "score": 0.9, "_silo_weight": 1.0}],
        latency_ms=50,
    )
    merged_chunks = [
        {"id": "c1", "text": "Hello", "score": 0.9, "silo_id": "test", "silo_name": "Test", "_silo_weight": 1.0}
    ]
    mock_result = FederatedSearchResult(
        query="test query",
        merged_chunks=merged_chunks,
        silo_results=[mock_silo_result],
        total_latency_ms=50,
    )

    with patch("federation.app.main.federated_search") as mock_search:
        mock_search.return_value = mock_result

        from federation.app.main import app
        client, stack = await _make_client(app)
        try:
            response = await client.post(
                "/v1/chat/completions",
                json={
                    "model": "rag-federated",
                    "messages": [{"role": "user", "content": "test query"}],
                    "stream": False,
                },
            )
        finally:
            await stack.aclose()
    assert response.status_code == 200
    data = response.json()
    assert "choices" in data
