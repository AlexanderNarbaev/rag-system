# proxy/app/tracing.py
"""OpenTelemetry distributed tracing setup for RAG proxy.

Provides:
- setup_tracing() — initializes OTLP exporter and SDK when OTEL_ENABLED=true
- tracer — a module-level tracer instance (no-op when tracing is disabled)
- Utility functions get_current_span(), add_event(), set_span_error()
- span_context_from_headers() — extracts W3C trace context from HTTP headers
- inject_context_to_headers() — injects current span context into dict headers
- TraceContextMiddleware — FastAPI middleware for automatic context propagation
- traced() — decorator/context-manager for instrumenting functions

Usage:
    from proxy.app.shared.tracing import tracer

    with tracer.start_as_current_span("rag.retrieve") as span:
        span.set_attribute("rag.query", query)
        results = hybrid_search(query)
        span.set_attribute("rag.num_results", len(results))

Configuration via environment variables (see config.py):
    OTEL_ENABLED — master switch (false by default, zero overhead when off)
    OTEL_EXPORTER_ENDPOINT — OTLP HTTP/protobuf collector endpoint
    OTEL_SERVICE_NAME — service name in traces (default: "rag-proxy")
"""

import logging
from contextlib import contextmanager
from functools import wraps
from typing import Any

logger = logging.getLogger(__name__)

_tracing_initialized: bool = False
_tracer_provider: Any = None

# ── Optional OpenTelemetry imports ────────────────────────────────────────
# When opentelemetry is not installed, all APIs become no-ops.
_OTEL_AVAILABLE = False

try:
    from opentelemetry import trace  # noqa: I001
    from opentelemetry.trace import Status, StatusCode
    from opentelemetry.trace import Span as _OtelSpan
    from opentelemetry.trace import Tracer as _OtelTracer

    _otel_trace = trace
    _OTEL_AVAILABLE = True
except ImportError:
    _otel_trace = None  # type: ignore[assignment]
    _OtelSpan = None  # type: ignore[assignment,misc]
    _OtelTracer = None  # type: ignore[assignment,misc]
    Status = None  # type: ignore[assignment,misc]
    StatusCode = None  # type: ignore[assignment,misc]

_OTEL_SDK_AVAILABLE = False

try:
    from opentelemetry.sdk.resources import SERVICE_NAME, Resource
except ImportError:
    SERVICE_NAME = "service.name"
    Resource = None  # type: ignore[assignment,misc]

try:
    from opentelemetry.sdk.trace import TracerProvider
except ImportError:
    TracerProvider = None  # type: ignore[assignment,misc]

try:
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
except ImportError:
    BatchSpanProcessor = None  # type: ignore[assignment,misc]

try:
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
except ImportError:
    OTLPSpanExporter = None

if _OTEL_AVAILABLE and TracerProvider is not None and OTLPSpanExporter is not None:
    _OTEL_SDK_AVAILABLE = True

try:
    from opentelemetry.propagate import extract as _otel_extract
    from opentelemetry.propagate import inject as _otel_inject
    from opentelemetry.propagators.textmap import Getter as _TextMapGetter
except ImportError:
    _otel_extract = None  # type: ignore[assignment]
    _otel_inject = None  # type: ignore[assignment]
    _TextMapGetter = None  # type: ignore[assignment,misc]

# ── Config (deferred to avoid circular imports at module level) ────────────

_OTEL_ENABLED: bool | None = None
_OTEL_EXPORTER_ENDPOINT: str | None = None
_OTEL_SERVICE_NAME: str | None = None
_OTEL_BATCH_TIMEOUT: int = 5


def _load_config() -> None:
    global _OTEL_ENABLED, _OTEL_EXPORTER_ENDPOINT, _OTEL_SERVICE_NAME, _OTEL_BATCH_TIMEOUT
    if _OTEL_ENABLED is not None:
        return
    try:
        from proxy.app.shared.config import (
            OTEL_BATCH_TIMEOUT,
            OTEL_ENABLED,
            OTEL_EXPORTER_ENDPOINT,
            OTEL_SERVICE_NAME,
        )

        _OTEL_ENABLED = OTEL_ENABLED
        _OTEL_EXPORTER_ENDPOINT = OTEL_EXPORTER_ENDPOINT
        _OTEL_SERVICE_NAME = OTEL_SERVICE_NAME
        _OTEL_BATCH_TIMEOUT = OTEL_BATCH_TIMEOUT
    except ImportError:
        _OTEL_ENABLED = False
        _OTEL_EXPORTER_ENDPOINT = "http://localhost:4318/v1/traces"
        _OTEL_SERVICE_NAME = "rag-proxy"
        _OTEL_BATCH_TIMEOUT = 5


# ── No-op stubs ────────────────────────────────────────────────────────────


class _NoOpSpan:
    """Drop-in replacement for a Span that silently accepts all operations."""

    def __enter__(self) -> "_NoOpSpan":
        return self

    def __exit__(self, *args: object) -> None:
        pass

    def is_recording(self) -> bool:
        return False

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def set_attributes(self, attributes: dict[str, Any]) -> None:
        pass

    def add_event(self, name: str, attributes: dict[str, Any] | None = None, timestamp: int | None = None) -> None:
        pass

    def record_exception(self, exception: Exception, attributes: dict[str, Any] | None = None) -> None:
        pass

    def set_status(self, status: Any) -> None:
        pass

    def end(self, end_time: int | None = None) -> None:
        pass

    def get_span_context(self) -> Any:
        return _NoOpSpanContext()


class _NoOpSpanContext:
    trace_id: int = 0
    span_id: int = 0
    is_remote: bool = False
    trace_flags: Any = None


class _NoOpTracer:
    """No-op Tracer that returns _NoOpSpan instances."""

    @contextmanager
    def start_as_current_span(
        self,
        name: str,
        context: Any = None,
        kind: Any = None,
        attributes: dict[str, Any] | None = None,
        links: Any = None,
        start_time: int | None = None,
        record_exception: bool = True,
        set_status_on_exception: bool = True,
        end_on_exit: bool = True,
    ) -> Any:
        yield _NoOpSpan()

    def start_span(
        self,
        name: str,
        context: Any = None,
        kind: Any = None,
        attributes: dict[str, Any] | None = None,
        links: Any = None,
        start_time: int | None = None,
    ) -> _NoOpSpan:
        return _NoOpSpan()


_NOOP_TRACER = _NoOpTracer()
_NOOP_SPAN = _NoOpSpan()
_NOOP_SPAN_CONTEXT = _NoOpSpanContext()

# ── Module-level tracer (lazy init) ────────────────────────────────────────

_tracer: Any = None


def _get_tracer() -> Any:
    """Return the current tracer, initializing if needed."""
    global _tracer
    if _tracer is not None:
        return _tracer
    _load_config()
    if _OTEL_AVAILABLE and _otel_trace is not None:
        _tracer = _otel_trace.get_tracer(_OTEL_SERVICE_NAME or "rag-proxy")
    else:
        _tracer = _NOOP_TRACER
    return _tracer


class _TracerProxy:
    """Lazy-proxy for module-level tracer access without property decorator.

    Usage: ``tracer.start_as_current_span("name")`` — resolves the real tracer on access.
    """

    def __getattr__(self, name: str) -> Any:
        return getattr(_get_tracer(), name)


tracer: Any = _TracerProxy()


# ── Public API ─────────────────────────────────────────────────────────────


def setup_tracing(service_name: str = "rag-proxy") -> None:
    """Initialize OpenTelemetry tracing SDK.

    Sets up the OTLP HTTP exporter with BatchSpanProcessor when OTEL_ENABLED=true.
    When tracing is disabled, this function is a no-op.

    Must be called once at application startup, before any span creation.
    Idempotent — subsequent calls are no-ops.
    """
    global _tracing_initialized, _tracer_provider

    _load_config()

    if not _OTEL_ENABLED:
        logger.debug("OpenTelemetry tracing is disabled (OTEL_ENABLED=false)")
        return

    if not _OTEL_AVAILABLE:
        logger.debug("OpenTelemetry API not installed — tracing unavailable")
        return

    if not _OTEL_SDK_AVAILABLE:
        logger.debug("OpenTelemetry SDK not installed — tracing unavailable")
        return

    if _tracing_initialized:
        logger.debug("OpenTelemetry tracing already initialized")
        return

    assert TracerProvider is not None and Resource is not None
    resource_kwargs = {SERVICE_NAME: service_name}
    provider = TracerProvider(resource=Resource.create(resource_kwargs))

    try:
        assert OTLPSpanExporter is not None
        exporter = OTLPSpanExporter(endpoint=_OTEL_EXPORTER_ENDPOINT)
        provider.add_span_processor(
            BatchSpanProcessor(
                exporter,
                schedule_delay_millis=_OTEL_BATCH_TIMEOUT * 1000,
                max_export_batch_size=512,
            ),
        )
        _otel_trace.set_tracer_provider(provider)
        _tracer_provider = provider
        global _tracer
        _tracer = _otel_trace.get_tracer(service_name)
        _tracing_initialized = True
        logger.info(
            "OpenTelemetry tracing initialized (service=%s, endpoint=%s)",
            service_name,
            _OTEL_EXPORTER_ENDPOINT,
        )
    except Exception as e:
        logger.warning(
            "Failed to initialize OpenTelemetry exporter (endpoint=%s): %s. Tracing disabled for this session.",
            _OTEL_EXPORTER_ENDPOINT,
            e,
        )
        _tracing_initialized = False


def get_current_span() -> Any:
    """Return the currently active span (or a no-op span).

    Returns:
        The active span, or a non-recording no-op span if no tracing is active.

    """
    if _OTEL_AVAILABLE and _otel_trace is not None:
        return _otel_trace.get_current_span()
    return _NOOP_SPAN


def add_event(name: str, attributes: dict[str, Any] | None = None) -> None:
    """Add a named event with optional attributes to the current span.

    No-op when no span is active or tracing is disabled.

    Args:
        name: Event name (e.g., "cache.hit", "llm.token_limit.exceeded").
        attributes: Optional key-value pairs to attach to the event.

    """
    span = get_current_span()
    if span.is_recording():
        span.add_event(name, attributes=attributes or {})


def set_span_error(exc: Exception) -> None:
    """Record an exception on the current span and set error status.

    No-op when no span is active or tracing is disabled.

    Args:
        exc: The exception to record.

    """
    span = get_current_span()
    if span.is_recording():
        span.record_exception(exc)
        if _OTEL_AVAILABLE:
            span.set_status(Status(StatusCode.ERROR, str(exc)))


def span_context_from_headers(headers: dict[str, str]) -> Any:
    """Extract a W3C trace context from HTTP request headers.

    Returns a Context object for use as ``context=`` in ``start_as_current_span``.

    Args:
        headers: Dict of HTTP header names to values.

    Returns:
        A Context object, or None if no traceparent header is present.

    """
    if not _OTEL_AVAILABLE or _otel_extract is None:
        return None

    # Only extract if traceparent header is present
    has_traceparent = any(k.lower() in ("traceparent",) for k in headers)
    if not has_traceparent:
        return None

    class _HeaderGetter(_TextMapGetter[str]):  # type: ignore[misc,override,unused-ignore]
        def get(self, carrier: dict[str, str], key: str) -> list[str] | None:  # type: ignore[override]
            val = carrier.get(key)
            return [val] if val is not None else None

        def keys(self, carrier: dict[str, str]) -> list[str]:  # type: ignore[override]
            return list(carrier.keys())

    return _otel_extract(headers, getter=_HeaderGetter())  # type: ignore[misc]


def inject_context_to_headers(headers: dict[str, str]) -> None:
    """Inject the current span context into a dict of outgoing request headers.

    Adds ``traceparent`` and ``tracestate`` headers if tracing is active.

    Args:
        headers: Dict of header names to values (mutated in place).

    """
    if not _OTEL_AVAILABLE or _otel_inject is None:
        return
    _otel_inject(headers)


# ── Decorator for function-level instrumentation ────────────────────────────


def traced(span_name: str | None = None, attributes: dict[str, Any] | None = None) -> Any:
    """Decorate a function to create a span around its execution.

    Can also be used as a context manager::

        with traced("rag.search") as span:
            span.set_attribute("rag.query", q)
            ...

    Args:
        span_name: Name for the span. Defaults to ``module.func_name``.
        attributes: Optional attributes to set on the span at start.

    """

    def decorator(func: Any) -> Any:
        name = span_name or f"{func.__module__}.{func.__name__}"

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            t = _get_tracer()
            with t.start_as_current_span(name) as span:
                if attributes:
                    span.set_attributes(attributes)
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    if span.is_recording():
                        span.record_exception(exc)
                        if _OTEL_AVAILABLE:
                            span.set_status(Status(StatusCode.ERROR, str(exc)))
                    raise

        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            t = _get_tracer()
            with t.start_as_current_span(name) as span:
                if attributes:
                    span.set_attributes(attributes)
                try:
                    return await func(*args, **kwargs)
                except Exception as exc:
                    if span.is_recording():
                        span.record_exception(exc)
                        if _OTEL_AVAILABLE:
                            span.set_status(Status(StatusCode.ERROR, str(exc)))
                    raise

        import inspect as _inspect

        if _inspect.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator
