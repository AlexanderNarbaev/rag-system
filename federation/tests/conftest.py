import pytest

from federation.app.models import SiloConfig
from federation.app.silo_registry import SiloRegistry

HR_SILO = SiloConfig(
    id="hr", name="HR KB", proxy_url="http://hr:8000/v1",
    weight=1.0, access_groups=["hr", "admin"], is_primary=True
)
ENG_SILO = SiloConfig(
    id="engineering", name="Engineering Wiki", proxy_url="http://eng:8000/v1",
    weight=1.2, access_groups=["engineering", "admin"], is_primary=False
)


@pytest.fixture
def test_silos():
    return [HR_SILO, ENG_SILO]


@pytest.fixture
def test_registry(test_silos):
    return SiloRegistry(test_silos)
