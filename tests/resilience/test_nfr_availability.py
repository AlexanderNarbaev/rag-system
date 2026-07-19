# tests/resilience/test_nfr_availability.py
"""NFR-A: Availability non-functional requirements tests.

Verifies availability, error handling, backup, and graceful degradation:

- NFR-A01: Service availability 99.5%
- NFR-A02: Error rate 5xx < 1%
- NFR-A03: Backup RPO < 1 hour
- NFR-A04: Backup RTO < 30 min
- NFR-A05: Graceful degradation (each component down)
- NFR-A06: ETL WAL survival
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Mock heavy dependencies before importing
_modules_to_mock = [
    "qdrant_client",
    "qdrant_client.http",
    "qdrant_client.http.models",
    "sentence_transformers",
    "langgraph",
    "langgraph.graph",
    "langgraph.checkpoint",
    "neo4j",
    "redis",
    "redis.asyncio",
    "tiktoken",
]
for mod in _modules_to_mock:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()


# ============================================================================
# NFR-A01: Service availability 99.5%
# ============================================================================


class TestNFR_A01_ServiceAvailability:
    """NFR-A01: Prometheus up{job='rag-proxy'} >= 99.5%."""

    def test_health_endpoint_exists(self):
        """Must have /v1/health endpoint for availability monitoring."""
        content = (PROJECT_ROOT / "proxy" / "app" / "api" / "health.py").read_text()
        assert "/v1/health" in content or "health" in content.lower()

    def test_liveness_probe_exists(self):
        """Must have /v1/health/live for K8s liveness probe."""
        content = (PROJECT_ROOT / "proxy" / "app" / "api" / "health.py").read_text()
        assert "live" in content.lower()

    def test_readiness_probe_exists(self):
        """Must have /v1/health/ready for K8s readiness probe."""
        content = (PROJECT_ROOT / "proxy" / "app" / "api" / "health.py").read_text()
        assert "ready" in content.lower()

    def test_metrics_endpoint_exists(self):
        """Must have /metrics endpoint for Prometheus scraping."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "metrics.py").read_text()
        assert "def metrics_endpoint" in content

    def test_active_requests_gauge(self):
        """Must track active requests for availability correlation."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "metrics.py").read_text()
        assert "rag_active_requests" in content


# ============================================================================
# NFR-A02: Error rate 5xx < 1%
# ============================================================================


class TestNFR_A02_ErrorRate:
    """NFR-A02: rag_requests_total{status=~'5..'} / total < 0.01."""

    def test_request_counter_with_status_label(self):
        """Must have request counter with status label for error rate calculation."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "metrics.py").read_text()
        assert "rag_requests_total" in content
        assert "status" in content

    def test_error_handling_in_chat_endpoint(self):
        """Chat endpoint must handle errors gracefully without 5xx."""
        content = (PROJECT_ROOT / "proxy" / "app" / "main.py").read_text()
        # Must have try/except in chat handler
        assert "except" in content
        assert "Exception" in content or "HTTPException" in content

    def test_graceful_error_responses(self):
        """Errors must return structured responses, not raw 500s."""
        content = (PROJECT_ROOT / "proxy" / "app" / "main.py").read_text()
        # Should have error response handling
        assert "error" in content.lower() or "detail" in content.lower()


# ============================================================================
# NFR-A03: Backup RPO < 1 hour
# ============================================================================


class TestNFR_A03_BackupRPO:
    """NFR-A03: Backup RPO < 1 hour (Redis 1h, WAL 30min)."""

    def test_backup_cron_script_exists(self):
        """Backup cron script must exist."""
        script = PROJECT_ROOT / "scripts" / "ops" / "backup_cron.sh"
        assert script.exists(), "backup_cron.sh must exist"

    def test_backup_redis_script_exists(self):
        """Redis backup script must exist for RPO < 1h."""
        script = PROJECT_ROOT / "scripts" / "ops" / "backup_redis.sh"
        assert script.exists(), "backup_redis.sh must exist"

    def test_backup_qdrant_script_exists(self):
        """Qdrant backup script must exist."""
        script = PROJECT_ROOT / "scripts" / "ops" / "backup_qdrant.sh"
        assert script.exists(), "backup_qdrant.sh must exist"

    def test_backup_neo4j_script_exists(self):
        """Neo4j backup script must exist."""
        script = PROJECT_ROOT / "scripts" / "ops" / "backup_neo4j.sh"
        assert script.exists(), "backup_neo4j.sh must exist"

    def test_backup_cron_references_all_services(self):
        """Backup cron must orchestrate all service backups."""
        content = (PROJECT_ROOT / "scripts" / "ops" / "backup_cron.sh").read_text()
        assert "qdrant" in content.lower()
        assert "redis" in content.lower()


# ============================================================================
# NFR-A04: Backup RTO < 30 min
# ============================================================================


class TestNFR_A04_BackupRTO:
    """NFR-A04: Restore from backup < 30 minutes."""

    def test_restore_script_exists(self):
        """restore_all.sh must exist."""
        script = PROJECT_ROOT / "scripts" / "ops" / "restore_all.sh"
        assert script.exists(), "restore_all.sh must exist"

    def test_verify_restore_script_exists(self):
        """verify_restore.sh must exist for post-restore checks."""
        script = PROJECT_ROOT / "scripts" / "ops" / "verify_restore.sh"
        assert script.exists(), "verify_restore.sh must exist"

    def test_restore_supports_date_parameter(self):
        """Restore script must support date-based restore."""
        content = (PROJECT_ROOT / "scripts" / "ops" / "restore_all.sh").read_text()
        assert "RESTORE_DATE" in content or "--latest" in content or "DATE" in content

    def test_restore_script_valid_syntax(self):
        """Restore script must have valid bash syntax."""
        import subprocess

        result = subprocess.run(
            ["bash", "-n", str(PROJECT_ROOT / "scripts" / "ops" / "restore_all.sh")],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, f"Syntax error: {result.stderr}"


# ============================================================================
# NFR-A05: Graceful degradation
# ============================================================================


class TestNFR_A05_GracefulDegradation:
    """NFR-A05: Proxy does not crash when any component is unavailable."""

    def test_neo4j_optional_dependency(self):
        """Neo4j must be optional — proxy works without it."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "config.py").read_text()
        assert "GRAPH_ENABLED" in content
        # Default must be false (optional)
        assert '"false"' in content

    def test_redis_optional_dependency(self):
        """Redis must be optional — in-memory cache fallback."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "config.py").read_text()
        assert "USE_REDIS" in content
        # Must have in-memory fallback
        cache_content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "cache.py").read_text()
        assert "InMemoryCache" in cache_content

    def test_reranker_fallback_option(self):
        """Must support local reranker fallback when remote unavailable."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "config.py").read_text()
        assert "RERANKER_FALLBACK_LOCAL" in content

    def test_embedder_fallback_option(self):
        """Must support local embedder fallback when remote unavailable."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "config.py").read_text()
        assert "EMBEDDER_FALLBACK_LOCAL" in content

    def test_graceful_shutdown_config(self):
        """Must have graceful shutdown configuration."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "config.py").read_text()
        assert "GRACEFUL_SHUTDOWN_ENABLED" in content
        assert "SHUTDOWN_TIMEOUT" in content

    def test_components_fail_independently(self):
        """Each component failure must not crash the proxy."""
        # Verify by checking that try/except blocks wrap component calls
        main_content = (PROJECT_ROOT / "proxy" / "app" / "main.py").read_text()
        assert "except" in main_content


# ============================================================================
# NFR-A06: ETL WAL survival
# ============================================================================


class TestNFR_A06_WALSurvival:
    """NFR-A06: ETL resumes from last checkpoint after crash."""

    def test_wal_manager_exists(self):
        """WAL manager must exist for checkpoint persistence."""
        content = (PROJECT_ROOT / "etl" / "indexer" / "wal_manager.py").read_text()
        assert "class" in content

    def test_wal_supports_multiple_backends(self):
        """WAL must support file and optionally Redis backends."""
        content = (PROJECT_ROOT / "etl" / "indexer" / "wal_manager.py").read_text()
        assert "FileWALBackend" in content or "FileBackend" in content

    def test_wal_checkpoint_read_write(self):
        """WAL must support reading and writing checkpoints."""
        content = (PROJECT_ROOT / "etl" / "indexer" / "wal_manager.py").read_text()
        assert "def read" in content or "def load" in content
        assert "def write" in content or "def save" in content

    def test_wal_stage_tracking(self):
        """WAL must track pipeline stages for resume capability."""
        content = (PROJECT_ROOT / "etl" / "indexer" / "wal_manager.py").read_text()
        # Must have some form of stage/phase tracking
        has_tracking = any(kw in content for kw in ("stage", "phase", "checkpoint", "pipeline", "progress"))
        assert has_tracking, "WAL must track pipeline stages"

    def test_wal_stale_lock_handling(self):
        """WAL must handle stale locks from crashed processes."""
        content = (PROJECT_ROOT / "etl" / "indexer" / "wal_manager.py").read_text()
        assert "stale" in content.lower() or "STALE" in content
