import pytest

from federation.app.auto_router import classify_query
from federation.app.models import SiloConfig
from federation.app.silo_registry import SiloRegistry

HR_SILO = SiloConfig(
    id="hr", name="HR KB", proxy_url="http://hr/v1",
    weight=1.0, access_groups=["hr", "admin"],
    collections=["hr_policies", "hr_onboarding"]
)
ENG_SILO = SiloConfig(
    id="engineering", name="Engineering Wiki", proxy_url="http://eng/v1",
    weight=1.2, access_groups=["engineering", "admin"],
    collections=["confluence", "jira", "gitlab"]
)


class TestClassifyQuery:
    @pytest.mark.asyncio
    async def test_hr_query_routes_to_hr(self):
        registry = SiloRegistry([HR_SILO, ENG_SILO])
        result = await classify_query("How to request sick leave?", registry)
        assert "hr" in result

    @pytest.mark.asyncio
    async def test_engineering_query_routes_to_engineering(self):
        registry = SiloRegistry([HR_SILO, ENG_SILO])
        result = await classify_query("How to deploy to production?", registry)
        assert "engineering" in result

    @pytest.mark.asyncio
    async def test_unclear_query_routes_to_all(self):
        registry = SiloRegistry([HR_SILO, ENG_SILO])
        result = await classify_query("update documentation", registry)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_disabled_returns_all_accessible(self, monkeypatch):
        from federation.app import auto_router
        monkeypatch.setattr(auto_router, "FEDERATION_AUTO_SLM_ENABLED", False)
        registry = SiloRegistry([HR_SILO, ENG_SILO])
        result = await classify_query("any query", registry)
        assert len(result) == 2
