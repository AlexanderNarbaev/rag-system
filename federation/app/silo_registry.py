from .models import SiloConfig
from .exceptions import ConfigError


class SiloRegistry:
    def __init__(self, silos: list[SiloConfig]):
        self._silos: dict[str, SiloConfig] = {}
        self.validate(silos)
        for silo in silos:
            self._silos[silo.id] = silo

    def validate(self, silos: list[SiloConfig]) -> None:
        seen: set[str] = set()
        for silo in silos:
            if silo.id in seen:
                raise ConfigError(f"Duplicate silo id: {silo.id}")
            seen.add(silo.id)
            if silo.weight <= 0:
                raise ConfigError(f"Silo '{silo.id}' weight must be > 0, got {silo.weight}")
            if not silo.proxy_url:
                raise ConfigError(f"Silo '{silo.id}' proxy_url is empty")

    def get(self, silo_id: str) -> SiloConfig | None:
        return self._silos.get(silo_id)

    def list_all(self) -> list[SiloConfig]:
        return list(self._silos.values())

    def list_accessible(self, user_groups: list[str]) -> list[SiloConfig]:
        return [s for s in self._silos.values() if s.is_accessible_by(user_groups)]

    def get_primary(self) -> SiloConfig | None:
        primaries = [s for s in self._silos.values() if s.is_primary]
        return primaries[0] if primaries else None

    def __len__(self) -> int:
        return len(self._silos)
