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


PERIOD_MAP: dict[str, int] = {
    "24h": 1,
    "7d": 7,
    "30d": 30,
}


# ---------------------------------------------------------------------------
# In-memory analytics store (accumulated at request time)
# ---------------------------------------------------------------------------

_analytics_lock = threading.RLock()
_daily_queries: dict[str, int] = {}  # date → count
_daily_users: dict[str, set[str]] = {}  # date → set of user_ids
_daily_input_tokens: dict[str, int] = {}  # date → input tokens
_daily_output_tokens: dict[str, int] = {}  # date → output tokens
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

        _daily_input_tokens[today] = _daily_input_tokens.get(today, 0) + prompt_tokens
        _daily_output_tokens[today] = _daily_output_tokens.get(today, 0) + completion_tokens

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


def _parse_period(period: str, days: int) -> tuple[str, int]:
    """Parse period string to days. Supports '24h', '7d', '30d' and legacy days int.

    When period is explicitly provided, it takes precedence.
    When only days is changed from default, use days.
    """
    if period and period in PERIOD_MAP:
        return period, PERIOD_MAP[period]
    return f"{days}d", days


def _compute_trend(current: int, previous: int) -> str:
    """Compute percentage trend between current and previous period."""
    if previous == 0:
        return "+∞%" if current > 0 else "0%"
    change = ((current - previous) / previous) * 100
    sign = "+" if change >= 0 else ""
    return f"{sign}{round(change)}%"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("")
async def get_analytics(
    request: Request,
    period: str = Query("", description="Time period: 24h, 7d, 30d"),
    days: int = Query(30, ge=1, le=365, description="Number of days to look back (legacy)"),
    metric: str | None = Query(None, description="Filter by metric: queries,users,latency,tokens"),
    user: Any = Depends(require_role(Role.ADMIN)),  # noqa: B008
) -> JSONResponse:
    """Return usage analytics for the specified time period (FR-105).

    Supports period-based queries (24h/7d/30d) and legacy days-based queries.

    Returns queries, unique users, latency percentiles (ms),
    token consumption (input/output split), and top knowledge bases.
    """
    period_key, num_days = _parse_period(period, days)

    with tracer.start_as_current_span("admin.analytics.overview") as span:
        if span.is_recording():
            span.set_attribute("admin.analytics.period", period_key)
            span.set_attribute("admin.analytics.days", num_days)

        dates = _get_date_range(num_days)
        latency_by_date = _get_latency_data(num_days)

        # ── Previous period for trend calculation ──
        prev_dates = _get_date_range(num_days * 2)[num_days:]

        total_queries = 0
        prev_total_queries = 0
        total_unique_users: set[str] = set()
        total_input_tokens = 0
        total_output_tokens = 0
        total_kb_usage: dict[str, int] = {}
        all_latencies: list[float] = []

        for date_str in dates:
            with _analytics_lock:
                q_count = _daily_queries.get(date_str, 0)
                u_set = _daily_users.get(date_str, set())
                i_tok = _daily_input_tokens.get(date_str, 0)
                o_tok = _daily_output_tokens.get(date_str, 0)
                k_data = dict(_daily_kb_usage.get(date_str, {}))

            total_queries += q_count
            total_unique_users.update(u_set)
            total_input_tokens += i_tok
            total_output_tokens += o_tok

            for kb_id, count in k_data.items():
                total_kb_usage[kb_id] = total_kb_usage.get(kb_id, 0) + count

            day_latencies = latency_by_date.get(date_str, [])
            all_latencies.extend(day_latencies)

        for date_str in prev_dates:
            with _analytics_lock:
                prev_total_queries += _daily_queries.get(date_str, 0)

        # ── Compute metrics ──
        sorted_latencies = sorted(all_latencies)
        p50, p95, p99 = _compute_percentiles(sorted_latencies)
        avg_per_hour = round(total_queries / max(num_days * 24, 1), 1)
        trend = _compute_trend(total_queries, prev_total_queries)

        unique_users = len(total_unique_users)
        avg_queries_per_user = round(total_queries / max(unique_users, 1), 1)

        top_kbs = sorted(total_kb_usage.items(), key=lambda x: x[1], reverse=True)[:10]

        # Build response in FR-105 format
        content: dict[str, Any] = {
            "period": period_key,
        }

        requested_metrics = [m.strip() for m in metric.split(",")] if metric else []
        show_all = not requested_metrics

        if show_all or "queries" in requested_metrics:
            content["queries"] = {
                "total": total_queries,
                "avg_per_hour": avg_per_hour,
                "trend": trend,
            }

        if show_all or "users" in requested_metrics:
            content["users"] = {
                "unique": unique_users,
                "avg_queries_per_user": avg_queries_per_user,
            }

        if show_all or "latency" in requested_metrics:
            content["latency"] = {
                "p50_ms": round(p50 * 1000),
                "p95_ms": round(p95 * 1000),
                "p99_ms": round(p99 * 1000),
            }

        if show_all or "tokens" in requested_metrics:
            content["tokens"] = {
                "total_input": total_input_tokens,
                "total_output": total_output_tokens,
            }

        content["top_kbs"] = [{"name": kb, "queries": cnt} for kb, cnt in top_kbs]

        return JSONResponse(status_code=200, content=content)


@router.get("/kb/{kb_id}")
async def get_kb_analytics(
    kb_id: str,
    request: Request,
    period: str = Query("", description="Time period: 24h, 7d, 30d"),
    days: int = Query(30, ge=1, le=365, description="Number of days to look back (legacy)"),
    user: Any = Depends(require_role(Role.ADMIN)),  # noqa: B008
) -> JSONResponse:
    """Return per-KB analytics breakdown for the specified time period."""
    period_key, num_days = _parse_period(period, days)

    with tracer.start_as_current_span("admin.analytics.kb") as span:
        if span.is_recording():
            span.set_attribute("admin.analytics.kb_id", kb_id)
            span.set_attribute("admin.analytics.period", period_key)

        dates = _get_date_range(num_days)

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
                "period": period_key,
                "total_queries": total_queries,
                "percentage_of_total": kb_pct,
                "daily_breakdown": daily_breakdown,
            },
        )
