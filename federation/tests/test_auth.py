import pytest
from federation.app.models import SiloConfig
from federation.app.exceptions import AccessDeniedError
from federation.app.auth import check_silo_access


HR_SILO = SiloConfig(id="hr", name="HR", proxy_url="http://hr/v1",
                     access_groups=["hr", "admin"])
ENG_SILO = SiloConfig(id="eng", name="Eng", proxy_url="http://eng/v1",
                      access_groups=["engineering", "admin"])


class TestCheckSiloAccess:
    def test_user_in_group_has_access(self):
        check_silo_access(HR_SILO, ["hr"])

    def test_admin_has_access(self):
        check_silo_access(ENG_SILO, ["admin", "engineering"])

    def test_user_not_in_group_raises(self):
        with pytest.raises(AccessDeniedError, match="Access denied"):
            check_silo_access(HR_SILO, ["engineering"])

    def test_nobody_sees_finance(self):
        fin = SiloConfig(id="fin", name="Finance", proxy_url="http://fin/v1",
                         access_groups=["finance", "admin"])
        check_silo_access(fin, ["admin"])
        check_silo_access(fin, ["finance"])
        with pytest.raises(AccessDeniedError):
            check_silo_access(fin, ["intern"])
