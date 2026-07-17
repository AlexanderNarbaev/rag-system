# proxy/app/api/admin_analytics.py
"""Usage analytics API — query volume, latency, token consumption, KB usage (admin only)."""

import logging
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from proxy.app.auth.rbac import Role, require_role
from proxy.app.shared.tracing import tracer

logger = logging.getLogger("rag-proxy")

router = APIRouter(prefix="/v1/admin/analytics", tags=["admin-analytics"])


# ---------------------------------------------------------------------------
# In-memory analytics store (accumulated at request time)
# ---------------------------------------------------------------------------

_analytics_lock = threading.RLock()
_daily_queries: dict[str, int] = {}  # date → count
_daily_users: dict[str, set[str]] = {}  # date → set of user_ids
_daily_tokens: dict[str, dict[str, int]] = {}  # date → {model: tokens}
_daily_kb_usage: dict[str, dict[str, int]] = {}  # date → {kb_id: count}
_request_latencies: list[float] = []  # all request latencies in seconds
_max_latency_samples = 100_000


def record_analytics_event(
    user_id: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    latency_seconds: float,
    kb_id: str = "default",
) -> None:
    """Record a RAG request for analytics purposes."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")

    with _analytics_lock:
        _daily_queries[today] = _daily_queries.get(today, 0) + 1

        if today not in _daily_users:
            _daily_users[today] = set()
        _daily_users[today].add(user_id)

        if today not in _daily_tokens:
            _daily_tokens[today] = {}
        model_tokens = _daily_tokens[today]
        model_tokens[model] = model_tokens.get(model, 0) + prompt_tokens + completion_tokens

        if today not in _daily_kb_usage:
            _daily_kb_usage[today] = {}
        kb_usage = _daily_kb_usage[today]
        kb_usage[kb_id] = kb_usage.get(kb_id, 0) + 1

        _request_latencies.append(latency_seconds)
        if len(_request_latencies) > _max_latency_samples:
            _request_latencies.pop(0)


def _compute_percentiles(values: list[float]) -> tuple[float, float, float]:
    """Compute P50, P95, P99 from a sorted list of values."""
    if not values:
        return 0.0, 0.0, 0.0
    n = len(values)
    p50 = values[int(n * 0.50)] if n > 0 else 0.0
    p95 = values[min(int(n * 0.95), n - 1)] if n > 1 else 0.0
    p99 = values[min(int(n * 0.99), n - 1)] if n > 2 else 0.0
    return p50, p95, p99


def _get_date_range(days: int) -> list[str]:
    """Generate a list of date strings for the last N days."""
    dates = []
    today = datetime.now(UTC).date()
    for i in range(days):
        d = today - timedelta(days=i)
        dates.append(d.strftime("%Y-%m-%d"))
    return sorted(dates)


def _get_latency_data(days: int) -> dict[str, list[float]]:
    """Estimate daily latency data using all stored latencies (simplified)."""
    with _analytics_lock:
        if not _request_latencies:
            return {}
        sorted_all = sorted(_request_latencies)
        dates = _get_date_range(days)
        total = len(sorted_all)
        result: dict[str, list[float]] = {}
        if total == 0:
            return result
        chunk_size = max(1, total // days)
        for i, date_str in enumerate(dates):
            start = i * chunk_size
            end = min(start + chunk_size, total)
            if start < total:
                result[date_str] = sorted_all[start:end]
        return result


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("")
async def get_analytics(
    request: Request,
    days: int = Query(30, ge=1, le=365, description="Number of days to look back"),
    user: Any = Depends(require_role(Role.ADMIN)),  # noqa: B008
) -> JSONResponse:
    """Return usage analytics for the specified time period.

    Returns total queries, unique users, latency percentiles,
    token consumption by model, and top KBs by query volume.
    """
    with tracer.start_as_current_span("admin.analytics.overview") as span:
        if span.is_recording():
            span.set_attribute("admin.analytics.days", days)

        dates = _get_date_range(days)
        latency_by_date = _get_latency_data(days)

        daily_breakdown = []
        total_queries = 0
        total_unique_users: set[str] = set()
        total_tokens_by_model: dict[str, int] = {}
        total_kb_usage: dict[str, int] = {}
        all_latencies: list[float] = []

        for date_str in dates:
            with _analytics_lock:
                q_count = _daily_queries.get(date_str, 0)
                u_count = len(_daily_users.get(date_str, set()))
                t_data = _daily_tokens.get(date_str, {})
                k_data = _daily_kb_usage.get(date_str, {})

            total_queries += q_count
            with _analytics_lock:
                if date_str in _daily_users:
                    total_unique_users.update(_daily_users[date_str])

            for model, tokens in t_data.items():
                total_tokens_by_model[model] = total_tokens_by_model.get(model, 0) + tokens

            for kb_id, count in k_data.items():
                total_kb_usage[kb_id] = total_kb_usage.get(kb_id, 0) + count

            day_latencies = latency_by_date.get(date_str, [])
            p50, p95, p99 = _compute_percentiles(sorted(day_latencies))
            all_latencies.extend(day_latencies)

            daily_breakdown.append(
                {
                    "date": date_str,
                    "queries": q_count,
                    "unique_users": u_count,
                    "latency_p50": round(p50, 3),
                    "latency_p95": round(p95, 3),
                    "latency_p99": round(p99, 3),
                    "tokens": t_data,
                }
            )

        overall_p50, overall_p95, overall_p99 = _compute_percentiles(sorted(all_latencies))
        avg_latency = round(sum(all_latencies) / len(all_latencies), 3) if all_latencies else 0.0

        top_kbs = sorted(total_kb_usage.items(), key=lambda x: x[1], reverse=True)[:10]

        return JSONResponse(
            status_code=200,
            content={
                "period_days": days,
                "total_queries": total_queries,
                "total_unique_users": len(total_unique_users),
                "average_latency_seconds": avg_latency,
                "latency_p50": round(overall_p50, 3),
                "latency_p95": round(overall_p95, 3),
                "latency_p99": round(overall_p99, 3),
                "token_consumption_by_model": total_tokens_by_model,
                "top_kbs_by_volume": [{"kb_id": kb, "queries": cnt} for kb, cnt in top_kbs],
                "daily_breakdown": daily_breakdown,
            },
        )


@router.get("/kb/{kb_id}")
async def get_kb_analytics(
    kb_id: str,
    request: Request,
    days: int = Query(30, ge=1, le=365, description="Number of days to look back"),
    user: Any = Depends(require_role(Role.ADMIN)),  # noqa: B008
) -> JSONResponse:
    """Return per-KB analytics breakdown for the specified time period."""
    with tracer.start_as_current_span("admin.analytics.kb") as span:
        if span.is_recording():
            span.set_attribute("admin.analytics.kb_id", kb_id)
            span.set_attribute("admin.analytics.days", days)

        dates = _get_date_range(days)

        total_queries = 0
        daily_breakdown = []

        for date_str in dates:
            with _analytics_lock:
                k_data = _daily_kb_usage.get(date_str, {})
            q_count = k_data.get(kb_id, 0)
            total_queries += q_count
            daily_breakdown.append(
                {
                    "date": date_str,
                    "queries": q_count,
                }
            )

        with _analytics_lock:
            all_total = sum(_daily_queries.values())

        kb_pct = round(total_queries / max(all_total, 1) * 100, 1)

        return JSONResponse(
            status_code=200,
            content={
                "kb_id": kb_id,
                "period_days": days,
                "total_queries": total_queries,
                "percentage_of_total": kb_pct,
                "daily_breakdown": daily_breakdown,
            },
        )
