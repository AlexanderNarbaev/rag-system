from .models import SiloConfig
from .exceptions import AccessDeniedError


def check_silo_access(silo: SiloConfig, user_groups: list[str]) -> None:
    if not silo.is_accessible_by(user_groups):
        raise AccessDeniedError(silo_id=silo.id, user_groups=user_groups)
