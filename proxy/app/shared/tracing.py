# proxy/app/tracing.py
"""
OpenTelemetry distributed tracing setup for RAG proxy.

Provides:
- setup_tracing() — initializes OTLP exporter and SDK when OTEL_ENABLED=true
- tracer — a module-level tracer instance (no-op when tracing is disabled)
- Utility function get_current_span() for adding attributes to active spans

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
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

try:
  from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
except ImportError:
  OTLPSpanExporter = None

from proxy.app.shared.config import (
  OTEL_BATCH_TIMEOUT, OTEL_ENABLED, OTEL_EXPORTER_ENDPOINT, OTEL_SERVICE_NAME,
)

logger = logging.getLogger (__name__)

_tracing_initialized: bool = False
_tracer_provider: TracerProvider | None = None

# Module-level tracer instance.
# When OTEL_ENABLED=false this resolves to a no-op tracer with zero overhead.
tracer: trace.Tracer = trace.get_tracer (OTEL_SERVICE_NAME)


def setup_tracing (service_name: str = "rag-proxy") -> None:
  """Initialize OpenTelemetry tracing SDK.

  Sets up the OTLP HTTP exporter with BatchSpanProcessor when OTEL_ENABLED=true.
  When tracing is disabled, this function is a no-op (the module-level tracer
  remains a no-op ProxyTracer from the default global TracerProvider).

  Must be called once at application startup, before any span creation.
  Idempotent — subsequent calls are no-ops.
  """
  global _tracing_initialized, _tracer_provider, tracer
  
  if not OTEL_ENABLED:
    logger.debug ("OpenTelemetry tracing is disabled (OTEL_ENABLED=false)")
    return
  
  if _tracing_initialized:
    logger.debug ("OpenTelemetry tracing already initialized")
    return
  
  resource = Resource.create ({SERVICE_NAME: service_name})
  provider = TracerProvider (resource = resource)
  
  try:
    if OTLPSpanExporter is None:
      logger.warning ("OTLPSpanExporter not available (opentelemetry-exporter-otlp-proto-http not installed). "
                      "Tracing will be disabled.")
      return
    
    exporter = OTLPSpanExporter (endpoint = OTEL_EXPORTER_ENDPOINT, )
    provider.add_span_processor (
        BatchSpanProcessor (exporter, schedule_delay_millis = OTEL_BATCH_TIMEOUT * 1000, max_export_batch_size = 512, ))
    trace.set_tracer_provider (provider)
    _tracer_provider = provider
    tracer = trace.get_tracer (service_name)
    _tracing_initialized = True
    logger.info ("OpenTelemetry tracing initialized (service=%s, endpoint=%s)", service_name, OTEL_EXPORTER_ENDPOINT, )
  except Exception as e:
    logger.warning (
        "Failed to initialize OpenTelemetry exporter (endpoint=%s): %s. Tracing will be disabled for this session.",
        OTEL_EXPORTER_ENDPOINT, e, )
    _tracing_initialized = False


def get_current_span () -> trace.Span:
  """Return the currently active span (or an invalid no-op span).

  Convenience wrapper to avoid boilerplate around get_current_span().

  Returns:
      The active span from the current context, or an INVALID span if none.
  """
  return trace.get_current_span ()


def add_event (name: str, attributes: dict [str, Any] | None = None) -> None:
  """Add a named event with optional attributes to the current span.

  No-op when no span is active.

  Args:
      name: Event name (e.g., "cache.hit", "llm.token_limit.exceeded").
      attributes: Optional key-value pairs to attach to the event.
  """
  span = trace.get_current_span ()
  if span.is_recording ():
    span.add_event (name, attributes = attributes or {})


def set_span_error (exc: Exception) -> None:
  """Record an exception on the current span and set error status.

  Args:
      exc: The exception to record.
  """
  span = trace.get_current_span ()
  if span.is_recording ():
    span.record_exception (exc)
    span.set_status (trace.Status (trace.StatusCode.ERROR, str (exc)))
