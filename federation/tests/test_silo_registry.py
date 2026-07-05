import pytest
from federation.app.models import SiloConfig
from federation.app.silo_registry import SiloRegistry
from federation.app.exceptions import ConfigError


HR_SILO = SiloConfig(
    id="hr", name="HR KB", proxy_url="http://hr:8000/v1",
    weight=1.0, access_groups=["hr", "admin"], is_primary=True
)
ENG_SILO = SiloConfig(
    id="engineering", name="Engineering Wiki", proxy_url="http://eng:8000/v1",
    weight=1.2, access_groups=["engineering", "admin"], is_primary=False
)
FIN_SILO = SiloConfig(
    id="finance", name="Finance Docs", proxy_url="http://fin:8000/v1",
    weight=0.8, access_groups=["finance", "admin"], is_primary=False
)


class TestSiloRegistry:
    def test_get_by_id(self):
        reg = SiloRegistry([HR_SILO, ENG_SILO])
        assert reg.get("hr") == HR_SILO
        assert reg.get("engineering") == ENG_SILO
        assert reg.get("nonexistent") is None

    def test_list_all(self):
        reg = SiloRegistry([HR_SILO, ENG_SILO])
        assert len(reg.list_all()) == 2

    def test_list_accessible_filters_by_user_groups(self):
        reg = SiloRegistry([HR_SILO, ENG_SILO, FIN_SILO])
        accessible = reg.list_accessible(["engineering"])
        assert len(accessible) == 1
        assert accessible[0].id == "engineering"

    def test_list_accessible_admin_sees_all(self):
        reg = SiloRegistry([HR_SILO, ENG_SILO, FIN_SILO])
        accessible = reg.list_accessible(["admin"])
        assert len(accessible) == 3

    def test_get_primary(self):
        reg = SiloRegistry([HR_SILO, ENG_SILO])
        assert reg.get_primary() == HR_SILO

    def test_get_primary_none_when_no_primary(self):
        reg = SiloRegistry([SiloConfig(id="x", name="X", proxy_url="http://x/v1")])
        assert reg.get_primary() is None

    def test_validate_duplicate_ids_raises(self):
        with pytest.raises(ConfigError, match="Duplicate silo id"):
            SiloRegistry([HR_SILO, HR_SILO])

    def test_validate_negative_weight_raises(self):
        bad = SiloConfig(id="bad", name="Bad", proxy_url="http://bad/v1", weight=-1.0)
        with pytest.raises(ConfigError, match="weight"):
            SiloRegistry([bad])

    def test_validate_missing_url_raises(self):
        bad = SiloConfig(id="bad", name="Bad", proxy_url="")
        with pytest.raises(ConfigError, match="proxy_url"):
            SiloRegistry([bad])
