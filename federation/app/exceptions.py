class FederationError(Exception):
    """Base exception for federation layer."""
    pass


class SiloUnavailableError(FederationError):
    """A silo is unreachable or circuit breaker is open."""
    def __init__(self, silo_id: str, reason: str = ""):
        self.silo_id = silo_id
        self.reason = reason
        super().__init__(f"Silo '{silo_id}' unavailable: {reason}")


class AllSilosDownError(FederationError):
    """All configured silos are unavailable."""
    def __init__(self, failed_silos: list[str]):
        self.failed_silos = failed_silos
        super().__init__(f"All silos unavailable: {failed_silos}")


class AccessDeniedError(FederationError):
    """User does not have access to requested silo."""
    def __init__(self, silo_id: str, user_groups: list[str]):
        self.silo_id = silo_id
        self.user_groups = user_groups
        super().__init__(f"Access denied to silo '{silo_id}' for groups {user_groups}")


class ConfigError(FederationError):
    """Invalid federation configuration."""
    pass
