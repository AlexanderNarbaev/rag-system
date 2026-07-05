import pytest
from unittest.mock import AsyncMock, patch
from federation.app.models import (
    SiloConfig, SiloSearchResult, FederatedSearchResult, FederationContext
)
from federation.app.silo_registry import SiloRegistry
from federation.app.router import federated_search
from federation.app.auto_router import classify_query


HR_SILO = SiloConfig(id="hr", name="HR KB", proxy_url="http://hr/v1", weight=1.0, access_groups=["hr", "admin"])
ENG_SILO = SiloConfig(id="eng", name="Engineering", proxy_url="http://eng/v1", weight=1.2, access_groups=["engineering", "admin"])


def make_silo_result(silo_id, silo_name, chunks, latency=50.0):
    return SiloSearchResult(silo_id=silo_id, silo_name=silo_name, chunks=chunks, latency_ms=latency)


class TestFederatedSearch:
    @pytest.mark.asyncio
    async def test_merge_mode_fans_out_to_all_accessible(self):
        ctx = FederationContext(
            mode="merge", target_silos=[], merge_strategy="weighted_rrf",
            merge_k=10, rrf_k=60, user_groups=["engineering", "admin"]
        )
        registry = SiloRegistry([HR_SILO, ENG_SILO])

        mock_hr = make_silo_result("hr", "HR KB", [
            {"id": "c1", "text": "HR text", "score": 0.9, "_silo_weight": 1.0}
        ])
        mock_eng = make_silo_result("eng", "Engineering", [
            {"id": "c2", "text": "Eng text", "score": 0.95, "_silo_weight": 1.2}
        ])

        with patch("federation.app.router.query_silo") as mock_query:
            async def side_effect(silo, query, top_k, timeout_s=None):
                if silo.id == "hr":
                    return mock_hr
                return mock_eng
            mock_query.side_effect = side_effect

            result = await federated_search(ctx, registry)

        assert isinstance(result, FederatedSearchResult)
        assert len(result.merged_chunks) == 2
        assert result.merged_chunks[0]["id"] == "c2"  # eng has higher weight
        assert len(result.silo_results) == 2
        assert result.errors == []
        assert result.skipped_silos == []

    @pytest.mark.asyncio
    async def test_strict_mode_queries_only_specified_silo(self):
        ctx = FederationContext(
            mode="strict", target_silos=["hr"], merge_strategy="weighted_rrf",
            merge_k=10, rrf_k=60, user_groups=["hr"]
        )
        registry = SiloRegistry([HR_SILO, ENG_SILO])

        mock_hr = make_silo_result("hr", "HR KB", [
            {"id": "c1", "text": "HR only", "score": 0.9, "_silo_weight": 1.0}
        ])

        with patch("federation.app.router.query_silo") as mock_query:
            mock_query.return_value = mock_hr

            result = await federated_search(ctx, registry)

        assert len(result.silo_results) == 1
        assert result.silo_results[0].silo_id == "hr"
        mock_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_partial_silo_failure_is_graceful(self):
        ctx = FederationContext(
            mode="merge", target_silos=[], merge_strategy="weighted_rrf",
            merge_k=10, rrf_k=60, user_groups=["admin"]
        )
        registry = SiloRegistry([HR_SILO, ENG_SILO])

        mock_hr = SiloSearchResult(silo_id="hr", silo_name="HR KB", chunks=[
            {"id": "c1", "text": "HR text", "score": 0.9, "_silo_weight": 1.0}
        ], latency_ms=50)
        mock_eng = SiloSearchResult(silo_id="eng", silo_name="Engineering", chunks=[],
                                    latency_ms=5000, error="timeout", partial=True)

        with patch("federation.app.router.query_silo") as mock_query:
            async def side_effect(silo, query, top_k, timeout_s=None):
                if silo.id == "hr":
                    return mock_hr
                return mock_eng
            mock_query.side_effect = side_effect

            result = await federated_search(ctx, registry)

        assert len(result.merged_chunks) == 1  # only HR returned
        assert len(result.errors) == 1
        assert "eng" in result.errors[0]

    @pytest.mark.asyncio
    async def test_all_silos_fail_returns_empty(self):
        ctx = FederationContext(
            mode="merge", target_silos=[], merge_strategy="weighted_rrf",
            merge_k=10, rrf_k=60, user_groups=["admin"]
        )
        registry = SiloRegistry([HR_SILO])

        mock_hr = SiloSearchResult(silo_id="hr", silo_name="HR KB", chunks=[],
                                    latency_ms=100, error="down", partial=True)

        with patch("federation.app.router.query_silo") as mock_query:
            mock_query.return_value = mock_hr
            result = await federated_search(ctx, registry)

        assert result.merged_chunks == []
        assert len(result.errors) == 1

    @pytest.mark.asyncio
    async def test_no_silos_found_for_user_returns_empty(self):
        ctx = FederationContext(
            mode="merge", target_silos=[], merge_strategy="weighted_rrf",
            merge_k=10, rrf_k=60, user_groups=["nobody"]
        )
        registry = SiloRegistry([HR_SILO, ENG_SILO])

        with patch("federation.app.router.query_silo") as mock_query:
            result = await federated_search(ctx, registry)

        assert result.merged_chunks == []
        assert len(result.silo_results) == 0
        mock_query.assert_not_called()

    @pytest.mark.asyncio
    async def test_auto_mode_uses_classifier(self):
        ctx = FederationContext(
            mode="auto", target_silos=[], merge_strategy="weighted_rrf",
            merge_k=10, rrf_k=60, user_groups=["admin"], query="sick leave policy"
        )
        registry = SiloRegistry([HR_SILO, ENG_SILO])

        mock_hr = make_silo_result("hr", "HR KB", [
            {"id": "c1", "text": "HR text", "score": 0.9, "_silo_weight": 1.0}
        ])

        with patch("federation.app.router.classify_query", new_callable=AsyncMock) as mock_classify, \
             patch("federation.app.router.query_silo") as mock_query:
            mock_classify.return_value = ["hr"]
            mock_query.return_value = mock_hr

            result = await federated_search(ctx, registry)

        assert len(result.silo_results) == 1
        assert result.silo_results[0].silo_id == "hr"
