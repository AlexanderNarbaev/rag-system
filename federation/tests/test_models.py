from federation.app.models import SiloConfig


class TestSiloConfig:
    def test_is_accessible_by_matching_group(self):
        silo = SiloConfig(
            id="hr", name="HR", proxy_url="http://localhost/v1",
            access_groups=["hr", "admin"]
        )
        assert silo.is_accessible_by(["hr"]) is True
        assert silo.is_accessible_by(["engineering", "admin"]) is True

    def test_is_accessible_by_no_match(self):
        silo = SiloConfig(
            id="finance", name="Finance", proxy_url="http://localhost/v1",
            access_groups=["finance", "admin"]
        )
        assert silo.is_accessible_by(["engineering"]) is False

    def test_is_accessible_by_empty_groups(self):
        silo = SiloConfig(
            id="hr", name="HR", proxy_url="http://localhost/v1",
            access_groups=["hr"]
        )
        assert silo.is_accessible_by([]) is False
