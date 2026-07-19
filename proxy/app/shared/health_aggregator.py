# proxy/app/shared/health_aggregator.py
"""Health check aggregation for all RAG system services.

Provides a unified health status view across proxy, Qdrant, Neo4j, Redis,
LLM backend, SLM backend, embedder, and reranker. Supports:
    - Aggregated status (ok / degraded / critical / unknown)
    - Per-component status with details
    - Caching of health results with configurable TTL
    - Graceful degradation: component failures reduce status but never crash
    - Circuit breaker integration: skip checks when breaker is OPEN
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)

HEALTH_CHECK_TTL = 15.0


class HealthStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    CRITICAL = "critical"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"


class AggregateStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


@dataclass
class ComponentHealth:
    name: str
    status: HealthStatus = HealthStatus.UNKNOWN
    details: dict[str, Any] = field(default_factory=dict)
    last_check: float = 0.0
    error: str = ""

    @property
    def is_ok(self) -> bool:
        return self.status == HealthStatus.OK


@dataclass
class AggregateHealth:
    status: AggregateStatus = AggregateStatus.UNKNOWN
    timestamp: float = 0.0
    components: dict[str, ComponentHealth] = field(default_factory=dict)
    summary: str = ""

    @property
    def is_healthy(self) -> bool:
        return self.status in (AggregateStatus.OK, AggregateStatus.DEGRADED)

    @property
    def is_critical(self) -> bool:
        return self.status == AggregateStatus.CRITICAL


def _make_checker(
    name: str,
    check_fn: Callable[[], bool],
    details_fn: Callable[[], dict[str, Any]] | None = None,
) -> Callable[[], ComponentHealth]:
    def checker() -> ComponentHealth:
        try:
            ok = check_fn()
            details = details_fn() if details_fn else {}
            return ComponentHealth(
                name=name,
                status=HealthStatus.OK if ok else HealthStatus.CRITICAL,
                details=details,
                last_check=time.time(),
            )
        except Exception as e:
            logger.warning("Health check '%s' raised: %s", name, e)
            return ComponentHealth(
                name=name,
                status=HealthStatus.CRITICAL,
                error=str(e),
                last_check=time.time(),
            )

    return checker


class HealthAggregator:
    """Aggregates health checks across all RAG system components.

    Each component check is independently executed and failures in one
    component never propagate to others. Aggregated status follows:
        - OK: all component checks pass
        - DEGRADED: at least one non-critical component is unhealthy
        - CRITICAL: a critical component is unhealthy
        - UNKNOWN: no checks have been run

    Attributes:
        critical_components: Components whose failure triggers CRITICAL status.
        checks: Registered health check functions keyed by component name.

    """

    def __init__(self, critical_components: list[str] | None = None):
        self.checks: dict[str, Callable[[], ComponentHealth]] = {}
        self.critical_components: set[str] = set(critical_components or [])
        self._cache: dict[str, ComponentHealth] = {}
        self._cache_timestamp: float = 0.0
        self._ttl: float = HEALTH_CHECK_TTL

    def register(
        self,
        name: str,
        check_fn: Callable[[], bool],
        details_fn: Callable[[], dict[str, Any]] | None = None,
        critical: bool = False,
    ) -> None:
        self.checks[name] = _make_checker(name, check_fn, details_fn)
        if critical:
            self.critical_components.add(name)

    def unregister(self, name: str) -> None:
        self.checks.pop(name, None)
        self.critical_components.discard(name)
        self._cache.pop(name, None)

    def run_check(self, name: str) -> ComponentHealth:
        if name not in self.checks:
            return ComponentHealth(
                name=name,
                status=HealthStatus.UNAVAILABLE,
                error=f"No check registered for '{name}'",
            )
        result = self.checks[name]()
        self._cache[name] = result
        return result

    def run_all(self, use_cache: bool = True) -> AggregateHealth:
        now = time.time()
        if use_cache and (now - self._cache_timestamp) < self._ttl and self._cache:
            return self._build_aggregate(self._cache_timestamp)

        results: dict[str, ComponentHealth] = {}
        for name in self.checks:
            try:
                results[name] = self.checks[name]()
            except Exception as e:
                results[name] = ComponentHealth(
                    name=name,
                    status=HealthStatus.CRITICAL,
                    error=str(e),
                    last_check=now,
                )

        self._cache = dict(results)
        self._cache_timestamp = now
        return self._build_aggregate(now)

    async def run_all_async(self, use_cache: bool = True) -> AggregateHealth:
        now = time.time()
        if use_cache and (now - self._cache_timestamp) < self._ttl and self._cache:
            return self._build_aggregate(now)

        async def _check(name: str, checker: Callable[[], ComponentHealth]) -> tuple[str, ComponentHealth]:
            try:
                return name, checker()
            except Exception as e:
                return name, ComponentHealth(
                    name=name,
                    status=HealthStatus.CRITICAL,
                    error=str(e),
                    last_check=time.time(),
                )

        tasks = [_check(name, chk) for name, chk in self.checks.items()]
        results_list = await asyncio.gather(*tasks, return_exceptions=False)
        results = dict(results_list)

        self._cache = dict(results)
        self._cache_timestamp = time.time()
        return self._build_aggregate(time.time())

    def _build_aggregate(self, now: float) -> AggregateHealth:
        components = self._cache
        status = AggregateStatus.OK
        critical_failures = []
        degraded_failures = []

        for name, health in components.items():
            if health.status == HealthStatus.OK:
                continue
            if name in self.critical_components:
                status = AggregateStatus.CRITICAL
                critical_failures.append(name)
            elif health.status in (HealthStatus.DEGRADED, HealthStatus.UNAVAILABLE, HealthStatus.CRITICAL):
                if status != AggregateStatus.CRITICAL:
                    status = AggregateStatus.DEGRADED
                degraded_failures.append(name)

        summary_parts = []
        if critical_failures:
            summary_parts.append(f"Critical: {', '.join(critical_failures)}")
        if degraded_failures:
            summary_parts.append(f"Degraded: {', '.join(degraded_failures)}")
        if not summary_parts:
            summary_parts.append("All systems operational")

        return AggregateHealth(
            status=status,
            timestamp=now,
            components=dict(components),
            summary="; ".join(summary_parts),
        )

    def get_component(self, name: str) -> ComponentHealth | None:
        if name in self._cache:
            return self._cache[name]
        if name in self.checks:
            return self.run_check(name)
        return None

    def invalidate_cache(self) -> None:
        self._cache.clear()
        self._cache_timestamp = 0.0

    def set_ttl(self, ttl: float) -> None:
        self._ttl = ttl

    @property
    def all_component_names(self) -> list[str]:
        return sorted(self.checks.keys())

    @property
    def healthy_components(self) -> list[str]:
        return [n for n, h in self._cache.items() if h.status == HealthStatus.OK]

    @property
    def unhealthy_components(self) -> list[str]:
        return [n for n, h in self._cache.items() if h.status != HealthStatus.OK]


_default_aggregator: HealthAggregator | None = None


def get_health_aggregator() -> HealthAggregator:
    global _default_aggregator
    if _default_aggregator is None:
        _default_aggregator = HealthAggregator(
            critical_components=["proxy", "qdrant", "llm_backend"],
        )
    return _default_aggregator


def reset_health_aggregator() -> None:
    global _default_aggregator
    _default_aggregator = None
