import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from federation.app.models import SiloConfig, SiloSearchResult
from federation.app.silo_client import query_silo


HR_SILO = SiloConfig(
    id="hr", name="HR KB", proxy_url="http://hr:8000/v1",
    api_key="sk-hr", timeout_s=5
)


class TestQuerySilo:
    @pytest.mark.asyncio
    async def test_query_silo_returns_chunks(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "rag_sources": [
                {"chunk_id": "a1", "text": "Policy text", "source": "confluence",
                 "title": "Sick Leave", "version": "1.0", "relevance": 0.94},
            ],
            "rag_metadata": {"total_retrieved": 1, "total_reranked": 1, "latency_ms": 50}
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value = mock_client

            result = await query_silo(HR_SILO, "How to take sick leave?", top_k=10)

        assert isinstance(result, SiloSearchResult)
        assert result.silo_id == "hr"
        assert result.silo_name == "HR KB"
        assert len(result.chunks) == 1
        assert result.chunks[0]["id"] == "a1"
        assert result.chunks[0]["text"] == "Policy text"
        assert result.chunks[0]["_silo_weight"] == 1.0
        assert result.error is None
        assert result.latency_ms > 0

    @pytest.mark.asyncio
    async def test_query_silo_http_error_returns_partial(self):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.post.side_effect = Exception("Connection refused")
            mock_client_cls.return_value = mock_client

            result = await query_silo(HR_SILO, "query", top_k=10)

        assert result.error is not None
        assert "Connection refused" in result.error
        assert result.chunks == []
        assert result.partial is True

    @pytest.mark.asyncio
    async def test_query_silo_uses_api_key_header(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"rag_sources": [], "rag_metadata": {}}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value = mock_client

            await query_silo(HR_SILO, "q", top_k=5)

        call_kwargs = mock_client.post.call_args.kwargs
        assert call_kwargs["headers"]["Authorization"] == "Bearer sk-hr"

    @pytest.mark.asyncio
    async def test_query_silo_attaches_silo_weight_to_chunks(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "rag_sources": [{"chunk_id": "c1", "text": "t", "relevance": 0.5}],
            "rag_metadata": {}
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value = mock_client

            result = await query_silo(HR_SILO, "q", top_k=5)

        assert result.chunks[0]["_silo_weight"] == 1.0
