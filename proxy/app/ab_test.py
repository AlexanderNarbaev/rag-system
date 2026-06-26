"""A/B test harness for RAG pipeline variants.

Allows comparing different pipeline configurations (rerankers, top-k values,
LangGraph on/off) with statistical significance testing via Welch's t-test.
"""

import math
import os
import random
from dataclasses import dataclass, field
from statistics import mean, stdev


AB_TEST_ENABLED = os.getenv("AB_TEST_ENABLED", "false").lower() == "true"


@dataclass
class ABVariant:
    """A single A/B test variant with config, metrics, and trial tracking."""

    name: str
    config: dict
    weight: float = 1.0
    trials: int = 0
    metrics: dict[str, list[float]] = field(default_factory=dict)

    def record(self, metric_name: str, value: float) -> None:
        self.metrics.setdefault(metric_name, []).append(value)

    def record_trial(self) -> None:
        self.trials += 1

    def metric_stats(self, metric_name: str) -> dict:
        values = self.metrics.get(metric_name, [])
        if not values:
            return {"count": 0}
        return {
            "count": len(values),
            "mean": mean(values),
            "std": stdev(values) if len(values) > 1 else 0.0,
            "min": min(values),
            "max": max(values),
            "sum": sum(values),
        }

    def clear_metrics(self) -> None:
        self.metrics.clear()
        self.trials = 0


class ABTest:
    """Manages A/B test variants, weighted selection, and statistical comparison.

    Usage:
        ab = ABTest("reranker_comparison")
        ab.register("miniLM", {"reranker": "MiniLM-L6"}, weight=0.5)
        ab.register("bge", {"reranker": "BGE-reranker-v2"}, weight=0.5)

        variant = ab.select_variant()
        # ... run pipeline with variant.config ...
        ab.record_result(variant.name, {"latency_ms": 150, "confidence": 0.85})

        comparison = ab.compare("confidence", "miniLM", "bge")
    """

    def __init__(self, name: str):
        self.name = name
        self._variants: dict[str, ABVariant] = {}

    @property
    def variants(self) -> list[ABVariant]:
        return list(self._variants.values())

    def register(self, name: str, config: dict, weight: float = 1.0) -> ABVariant:
        if name in self._variants:
            raise ValueError(f"Variant '{name}' already registered in test '{self.name}'")
        variant = ABVariant(name=name, config=config, weight=weight)
        self._variants[name] = variant
        return variant

    def select_variant(self) -> ABVariant:
        if not self._variants:
            raise ValueError(f"No variants registered in test '{self.name}'")

        names = list(self._variants.keys())
        weights = [self._variants[n].weight for n in names]
        total = sum(weights)
        if total <= 0:
            return self._variants[random.choice(names)]

        normalized = [w / total for w in weights]
        choice = random.choices(names, weights=normalized, k=1)[0]
        return self._variants[choice]

    def record_result(self, variant_name: str, metrics: dict[str, float]) -> None:
        variant = self._variants.get(variant_name)
        if variant is None:
            raise ValueError(f"Unknown variant '{variant_name}' in test '{self.name}'")
        variant.record_trial()
        for key, value in metrics.items():
            variant.record(key, value)

    def compare(self, metric_name: str, variant_a: str, variant_b: str) -> dict:
        va = self._variants.get(variant_a)
        vb = self._variants.get(variant_b)
        if va is None or vb is None:
            raise ValueError(f"Variant not found: {variant_a if va is None else variant_b}")

        values_a = va.metrics.get(metric_name, [])
        values_b = vb.metrics.get(metric_name, [])

        stats_a = va.metric_stats(metric_name)
        stats_b = vb.metric_stats(metric_name)

        result = {
            "metric": metric_name,
            "variant_a": variant_a,
            "variant_b": variant_b,
            "mean_a": stats_a.get("mean"),
            "mean_b": stats_b.get("mean"),
            "std_a": stats_a.get("std"),
            "std_b": stats_b.get("std"),
            "count_a": stats_a["count"],
            "count_b": stats_b["count"],
            "p_value": None,
            "significant": False,
        }

        if len(values_a) >= 2 and len(values_b) >= 2:
            result["p_value"] = get_statistical_significance(values_a, values_b)
            result["significant"] = result["p_value"] < 0.05
            result["effect_size"] = compute_effect_size(values_a, values_b)

        return result

    def is_significant(self, metric_name: str, variant_a: str, variant_b: str, threshold: float = 0.05) -> bool:
        comparison = self.compare(metric_name, variant_a, variant_b)
        p_value = comparison.get("p_value")
        if p_value is None:
            return False
        return p_value < threshold

    def get_report(self) -> dict:
        report: dict = {
            "name": self.name,
            "variants": [],
            "total_trials": sum(v.trials for v in self._variants.values()),
        }
        for v in self._variants.values():
            v_report = {
                "name": v.name,
                "trials": v.trials,
                "weight": v.weight,
                "metrics": {k: v.metric_stats(k) for k in v.metrics},
            }
            report["variants"].append(v_report)
        return report

    def reset(self) -> None:
        for v in self._variants.values():
            v.clear_metrics()


def get_statistical_significance(control: list[float], treatment: list[float]) -> float:
    """Compute p-value using Welch's t-test (unequal variance).

    Returns a p-value as float between 0.0 and 1.0.
    Lower values indicate stronger evidence of a difference.
    """
    n1, n2 = len(control), len(treatment)
    if n1 < 2 or n2 < 2:
        raise ValueError("Both groups must have at least 2 samples for statistical testing")

    m1, m2 = mean(control), mean(treatment)
    v1 = stdev(control) ** 2 if n1 > 1 else 0.0
    v2 = stdev(treatment) ** 2 if n2 > 1 else 0.0

    if abs(m1 - m2) < 1e-15:
        return 1.0

    se = math.sqrt(v1 / n1 + v2 / n2)
    if se == 0:
        return 1.0

    t_stat = abs(m1 - m2) / se

    df_num = (v1 / n1 + v2 / n2) ** 2
    df_den = (v1 / n1) ** 2 / (n1 - 1) + (v2 / n2) ** 2 / (n2 - 1)
    df = df_num / df_den if df_den > 0 else n1 + n2 - 2

    p_value = _t_cdf_approx(t_stat, df)
    return p_value


def compute_effect_size(control: list[float], treatment: list[float]) -> float:
    """Compute Cohen's d effect size.

    d = (mean1 - mean2) / pooled_std
    Small effect: ~0.2, Medium: ~0.5, Large: ~0.8
    """
    n1, n2 = len(control), len(treatment)
    if n1 == 0 and n2 == 0:
        return 0.0
    if n1 < 1 or n2 < 1:
        return 0.0

    m1, m2 = mean(control), mean(treatment)
    if n1 == 1 and n2 == 1:
        return m1 - m2

    v1 = stdev(control) ** 2 if n1 > 1 else 0.0
    v2 = stdev(treatment) ** 2 if n2 > 1 else 0.0

    pooled_std = math.sqrt(((n1 - 1) * v1 + (n2 - 1) * v2) / (n1 + n2 - 2)) if n1 + n2 > 2 else 1.0
    if pooled_std == 0:
        return 0.0

    return (m1 - m2) / pooled_std


def _t_cdf_approx(t: float, df: float) -> float:
    """Approximate the two-tailed p-value from Student's t-distribution.

    Uses the incomplete beta function approximation for the CDF.
    Returns 2 * (1 - CDF(|t|)) for two-tailed test.
    """
    x = df / (df + t * t)
    prob = _betai(0.5 * df, 0.5, x)
    return 2.0 * min(prob, 1.0 - prob)


def _betai(a: float, b: float, x: float) -> float:
    """Incomplete beta function regularized I_x(a,b)."""
    if x < 0.0 or x > 1.0:
        return 0.0
    if x == 0.0 or x == 1.0:
        return x

    bt = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def _betacf(a: float, b: float, x: float, max_iter: int = 100) -> float:
    """Continued fraction for incomplete beta function."""
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < 1e-30:
        d = 1e-30
    d = 1.0 / d
    h = d

    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        del_ = d * c
        h *= del_
        if abs(del_ - 1.0) < 3e-7:
            break

    return h
