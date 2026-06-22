"""Canary deployment controller — traffic splitting, metrics, auto-rollback.

Manages progressive canary rollout: splits traffic between a stable
baseline and a canary model, records per-request results, and
triggers automatic rollback on metric degradation.
"""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from prometheus_client import Counter, Gauge, Histogram


class CanaryPhase(Enum):
    """Progressive rollout phases from idle to full promotion."""
    IDLE = "idle"
    RAMP_5 = "ramp_5"
    RAMP_25 = "ramp_25"
    RAMP_50 = "ramp_50"
    RAMP_75 = "ramp_75"
    FULL = "full"
    ROLLBACK = "rollback"


@dataclass
class CanaryConfig:
    """Configuration for a canary deployment.

    Attributes:
        model_name: Target model (slm, llm, reranker).
        stable_version: Current production version identifier.
        canary_version: New version under canary test.
        canary_percent: Percentage of traffic routed to canary (0.0-1.0).
        min_samples: Minimum samples before rollback evaluation.
        rollback_thresholds: Metric thresholds dict {name: (threshold, comparison)}.
        cooldown_seconds: Cooldown period after rollback before retry.
    """
    model_name: str = ""
    stable_version: str = "baseline"
    canary_version: str = ""
    canary_percent: float = 0.0
    min_samples: int = 100
    rollback_thresholds: dict[str, tuple[float, str]] = field(default_factory=lambda: {
        "error_rate": (0.05, "gt"),
        "p95_latency_ms": (10000, "gt"),
    })
    cooldown_seconds: int = 3600


canary_traffic_total = Counter(
    "rag_canary_traffic_total",
    "Total requests routed by canary controller",
    ["model", "target"],
)

canary_result_total = Counter(
    "rag_canary_result_total",
    "Canary request outcomes (success/error)",
    ["model", "target", "outcome"],
)

canary_latency_seconds = Histogram(
    "rag_canary_latency_seconds",
    "Canary request latency",
    ["model", "target"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)

canary_phase_gauge = Gauge(
    "rag_canary_phase",
    "Current canary phase (0=idle, 1=ramp_5, ..., 5=full, 6=rollback)",
    ["model"],
)

canary_split_ratio = Gauge(
    "rag_canary_split_ratio",
    "Current traffic split ratio for canary",
    ["model"],
)

canary_rollback_total = Counter(
    "rag_canary_rollback_total",
    "Total number of canary rollbacks triggered",
    ["model"],
)


class CanaryController:
    """Manages canary deployment with traffic splitting and auto-rollback.

    Routes requests between stable and canary models based on a
    configurable split percentage, records per-request outcomes,
    and evaluates Prometheus metrics to decide when to roll back.

    Thread-safe for concurrent request handling.
    """

    _PHASE_ORDER: tuple[CanaryPhase, ...] = (
        CanaryPhase.RAMP_5,
        CanaryPhase.RAMP_25,
        CanaryPhase.RAMP_50,
        CanaryPhase.RAMP_75,
        CanaryPhase.FULL,
    )

    _COMPARATORS = {
        "gt": lambda a, b: a > b,
        "gte": lambda a, b: a >= b,
        "lt": lambda a, b: a < b,
        "lte": lambda a, b: a <= b,
    }

    def __init__(self) -> None:
        self._configs: dict[str, CanaryConfig] = {}
        self._phase: dict[str, CanaryPhase] = {}
        self._phase_started_at: dict[str, float] = {}
        self._rollback_cooldown_until: dict[str, float] = {}
        self._stats: dict[str, dict[str, dict[str, int]]] = {}
        self._latencies: dict[str, dict[str, list[float]]] = {}
        self._lock = threading.RLock()
        self._rng = random.Random()

    # ── Configuration ────────────────────────────────────────────

    def set_split(self, model_name: str, canary_percent: float) -> None:
        """Set the traffic split percentage for a model.

        Args:
            model_name: Target model identifier (slm, llm, reranker).
            canary_percent: Fraction of traffic to canary (0.0 to 1.0).

        Raises:
            ValueError: If canary_percent is outside [0.0, 1.0].
        """
        if not 0.0 <= canary_percent <= 1.0:
            raise ValueError(
                f"canary_percent must be between 0.0 and 1.0, got {canary_percent}"
            )

        with self._lock:
            if model_name not in self._configs:
                self._configs[model_name] = CanaryConfig(model_name=model_name)
            config = self._configs[model_name]
            config.canary_percent = canary_percent

            if canary_percent == 0.0:
                self._phase[model_name] = CanaryPhase.IDLE
            elif canary_percent >= 1.0:
                self._phase[model_name] = CanaryPhase.FULL
            else:
                self._phase[model_name] = self._infer_phase(canary_percent)

            canary_split_ratio.labels(model=model_name).set(canary_percent)
            canary_phase_gauge.labels(model=model_name).set(
                self._phase_to_int(self._phase.get(model_name, CanaryPhase.IDLE))
            )

    def configure(
        self,
        model_name: str,
        stable_version: str = "baseline",
        canary_version: str = "",
        canary_percent: float = 0.0,
        min_samples: int = 100,
        rollback_thresholds: dict[str, tuple[float, str]] | None = None,
        cooldown_seconds: int = 3600,
    ) -> None:
        """Fully configure canary deployment for a model.

        Args:
            model_name: Target model identifier.
            stable_version: Production version label.
            canary_version: Candidate canary version label.
            canary_percent: Traffic fraction to canary (0.0-1.0).
            min_samples: Minimum requests before rollback evaluation.
            rollback_thresholds: Metric thresholds for automatic rollback.
            cooldown_seconds: Post-rollback cooldown period.
        """
        with self._lock:
            config = CanaryConfig(
                model_name=model_name,
                stable_version=stable_version,
                canary_version=canary_version,
                canary_percent=canary_percent,
                min_samples=min_samples,
                rollback_thresholds=rollback_thresholds
                or {
                    "error_rate": (0.05, "gt"),
                    "p95_latency_ms": (10000, "gt"),
                },
                cooldown_seconds=cooldown_seconds,
            )
            self._configs[model_name] = config
            if canary_percent == 0.0:
                self._phase[model_name] = CanaryPhase.IDLE
            else:
                self._phase[model_name] = self._infer_phase(canary_percent)
            self._phase_started_at[model_name] = time.time()
            canary_split_ratio.labels(model=model_name).set(canary_percent)
            canary_phase_gauge.labels(model=model_name).set(
                self._phase_to_int(self._phase[model_name])
            )

    # ── Routing ───────────────────────────────────────────────────

    def route(self, model_name: str) -> str:
        """Decide which model variant to use for a request.

        Uses weighted random selection based on the configured split.

        Args:
            model_name: Target model identifier.

        Returns:
            "stable" or "canary" — the selected model target.
        """
        with self._lock:
            config = self._configs.get(model_name)
            if config is None:
                canary_traffic_total.labels(model=model_name, target="stable").inc()
                return "stable"

            canary_percent = config.canary_percent

            if self._rollback_cooldown_until.get(model_name, 0) > time.time():
                canary_percent = 0.0

        target = (
            "canary"
            if self._rng.random() < canary_percent
            else "stable"
        )
        canary_traffic_total.labels(model=model_name, target=target).inc()
        return target

    # ── Result Recording ──────────────────────────────────────────

    def record_result(
        self,
        model_name: str,
        target: str,
        success: bool,
        latency_ms: float = 0.0,
    ) -> None:
        """Record the outcome of a canary request.

        Updates Prometheus counters and histograms for later
        metric-driven rollback decisions.

        Args:
            model_name: Target model identifier.
            target: Which model served the request ("stable" or "canary").
            success: Whether the request was successful.
            latency_ms: Request duration in milliseconds.
        """
        outcome = "success" if success else "error"
        canary_result_total.labels(
            model=model_name, target=target, outcome=outcome
        ).inc()
        if latency_ms > 0:
            canary_latency_seconds.labels(model=model_name, target=target).observe(
                latency_ms / 1000.0
            )

        with self._lock:
            if model_name not in self._stats:
                self._stats[model_name] = {}
            if target not in self._stats[model_name]:
                self._stats[model_name][target] = {"success": 0, "error": 0}
            self._stats[model_name][target][outcome] += 1

            if latency_ms > 0:
                if model_name not in self._latencies:
                    self._latencies[model_name] = {}
                if target not in self._latencies[model_name]:
                    self._latencies[model_name][target] = []
                self._latencies[model_name][target].append(latency_ms)

    # ── Rollback ──────────────────────────────────────────────────

    def get_metrics(self, model_name: str) -> dict[str, Any]:
        """Retrieve current canary metrics from internal stats.

        Computes error_rate from recorded outcomes and reads
        configured thresholds for comparison.

        Args:
            model_name: Target model identifier.

        Returns:
            Dictionary with metric names and current values.
        """
        with self._lock:
            model_stats = self._stats.get(model_name, {})
            stable_stats = model_stats.get("stable", {"success": 0, "error": 0})
            canary_stats = model_stats.get("canary", {"success": 0, "error": 0})

            total_stable = stable_stats["success"] + stable_stats["error"]
            total_canary = canary_stats["success"] + canary_stats["error"]
            errors_stable = stable_stats["error"]
            errors_canary = canary_stats["error"]

        stable_error_rate = (
            errors_stable / total_stable if total_stable > 0 else 0.0
        )
        canary_error_rate = (
            errors_canary / total_canary if total_canary > 0 else 0.0
        )

        return {
            "total_stable": total_stable,
            "total_canary": total_canary,
            "errors_stable": errors_stable,
            "errors_canary": errors_canary,
            "stable_error_rate": stable_error_rate,
            "canary_error_rate": canary_error_rate,
        }

    def should_rollback(self, model_name: str) -> bool:
        """Determine if the canary should be rolled back.

        Evaluates Prometheus metrics against configured thresholds.
        Returns True if any threshold is breached, indicating
        degradation in the canary relative to baseline.

        Args:
            model_name: Target model identifier.

        Returns:
            True if rollback is warranted, False otherwise.
        """
        with self._lock:
            config = self._configs.get(model_name)
            if config is None:
                return False

            phase = self._phase.get(model_name, CanaryPhase.IDLE)
            if phase in (CanaryPhase.IDLE, CanaryPhase.FULL, CanaryPhase.ROLLBACK):
                return False

            if self._rollback_cooldown_until.get(model_name, 0) > time.time():
                return False

            model_stats = self._stats.get(model_name, {})
            canary_stats = model_stats.get("canary", {"success": 0, "error": 0})
            total_canary = canary_stats.get("success", 0) + canary_stats.get("error", 0)
            if total_canary < config.min_samples:
                return False

            metrics = self.get_metrics(model_name)
            canary_error_rate = metrics["canary_error_rate"]

            for metric_name, (threshold, comparison) in config.rollback_thresholds.items():
                if metric_name == "error_rate":
                    current_value = canary_error_rate
                else:
                    continue

                comparator = self._COMPARATORS.get(comparison)
                if comparator is None:
                    continue

                if comparator(current_value, threshold):
                    return True

            return False

    def rollback(self, model_name: str) -> None:
        """Revert the canary to 100% baseline traffic.

        Sets traffic split to 0% canary, updates phase to ROLLBACK,
        records the rollback event, and begins cooldown period.

        Args:
            model_name: Target model identifier.
        """
        with self._lock:
            if model_name not in self._configs:
                self._configs[model_name] = CanaryConfig(model_name=model_name)

            config = self._configs[model_name]
            config.canary_percent = 0.0
            self._phase[model_name] = CanaryPhase.ROLLBACK
            self._rollback_cooldown_until[model_name] = (
                time.time() + config.cooldown_seconds
            )

            canary_split_ratio.labels(model=model_name).set(0.0)
            canary_phase_gauge.labels(model=model_name).set(
                self._phase_to_int(CanaryPhase.ROLLBACK)
            )
            canary_rollback_total.labels(model=model_name).inc()

    def promote(self, model_name: str) -> None:
        """Promote the canary to become the new baseline.

        Sets traffic to 100% canary (now stable) and marks phase FULL.

        Args:
            model_name: Target model identifier.
        """
        with self._lock:
            config = self._configs.get(model_name)
            if config is None:
                return
            config.canary_percent = 1.0
            config.stable_version = config.canary_version
            config.canary_version = ""
            self._phase[model_name] = CanaryPhase.FULL
            canary_split_ratio.labels(model=model_name).set(1.0)
            canary_phase_gauge.labels(model=model_name).set(
                self._phase_to_int(CanaryPhase.FULL)
            )

    # ── Status ────────────────────────────────────────────────────

    def status(self, model_name: str | None = None) -> dict[str, Any]:
        """Return canary deployment status.

        Args:
            model_name: Optional model filter. Returns all if omitted.

        Returns:
            Dict mapping model_name to status dict with phase,
            split, metrics, and config details.
        """
        with self._lock:
            names = [model_name] if model_name else list(self._configs.keys())
            result: dict[str, Any] = {}
            for name in names:
                config = self._configs.get(name)
                if config is None:
                    continue
                phase = self._phase.get(name, CanaryPhase.IDLE)
                cooldown_remaining = max(
                    0.0,
                    (self._rollback_cooldown_until.get(name, 0) - time.time()),
                )
                metrics = self.get_metrics(name)
                result[name] = {
                    "phase": phase.value,
                    "split": {
                        "stable": 1.0 - config.canary_percent,
                        "canary": config.canary_percent,
                    },
                    "stable_version": config.stable_version,
                    "canary_version": config.canary_version,
                    "cooldown_remaining_seconds": cooldown_remaining,
                    "metrics": metrics,
                }
            return result

    def get_phase(self, model_name: str) -> CanaryPhase:
        """Return the current canary phase for a model."""
        with self._lock:
            return self._phase.get(model_name, CanaryPhase.IDLE)

    def get_split(self, model_name: str) -> tuple[float, float]:
        """Return (stable_weight, canary_weight) for a model."""
        with self._lock:
            config = self._configs.get(model_name)
            if config is None:
                return (1.0, 0.0)
            cp = max(0.0, min(1.0, config.canary_percent))
            return (1.0 - cp, cp)

    def reset(self, model_name: str | None = None) -> None:
        """Reset canary state for testing purposes.

        Args:
            model_name: Specific model to reset, or all if None.
        """
        with self._lock:
            if model_name:
                self._configs.pop(model_name, None)
                self._phase.pop(model_name, None)
                self._phase_started_at.pop(model_name, None)
                self._rollback_cooldown_until.pop(model_name, None)
                self._stats.pop(model_name, None)
                self._latencies.pop(model_name, None)
            else:
                self._configs.clear()
                self._phase.clear()
                self._phase_started_at.clear()
                self._rollback_cooldown_until.clear()
                self._stats.clear()
                self._latencies.clear()

    # ── Internal helpers ──────────────────────────────────────────

    @staticmethod
    def _infer_phase(percent: float) -> CanaryPhase:
        if percent <= 0.0:
            return CanaryPhase.IDLE
        if percent < 0.05:
            return CanaryPhase.RAMP_5
        if percent < 0.25:
            return CanaryPhase.RAMP_25
        if percent < 0.50:
            return CanaryPhase.RAMP_50
        if percent < 0.75:
            return CanaryPhase.RAMP_75
        return CanaryPhase.FULL

    @staticmethod
    def _phase_to_int(phase: CanaryPhase) -> int:
        mapping = {
            CanaryPhase.IDLE: 0,
            CanaryPhase.RAMP_5: 1,
            CanaryPhase.RAMP_25: 2,
            CanaryPhase.RAMP_50: 3,
            CanaryPhase.RAMP_75: 4,
            CanaryPhase.FULL: 5,
            CanaryPhase.ROLLBACK: 6,
        }
        return mapping.get(phase, 0)
