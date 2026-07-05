from prometheus_client import Counter, Gauge, Histogram

REQUESTS_TOTAL = Counter(
    "rag_federation_requests_total",
    "Total federation requests",
    ["mode", "status"],
)

SILO_REQUESTS_TOTAL = Counter(
    "rag_federation_silo_requests_total",
    "Per-silo requests",
    ["silo", "status"],
)

SILO_LATENCY = Histogram(
    "rag_federation_silo_latency_seconds",
    "Per-silo latency",
    ["silo"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

MERGE_TOTAL_CHUNKS = Histogram(
    "rag_federation_merge_total_chunks",
    "Chunks after merge",
    buckets=[5, 10, 20, 30, 40, 50, 60, 80, 100],
)

CIRCUIT_BREAKER_STATE = Gauge(
    "rag_federation_circuit_breaker_state",
    "Circuit breaker state per silo",
    ["silo"],
)

SILOS_ACTIVE = Gauge(
    "rag_federation_silos_active",
    "Number of healthy silos",
)

TOTAL_LATENCY = Histogram(
    "rag_federation_total_latency_seconds",
    "End-to-end federation latency",
    ["mode"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)
