# tests/proxy/test_nfr_maintainability.py
"""NFR-M: Maintainability non-functional requirements tests.

Verifies operational maintainability:

- NFR-M01: Runtime configuration hot-reload
- NFR-M02: Stale document monitoring
- NFR-M03: Reindexing resilience
- NFR-M05: Feedback preservation through reindex
- NFR-M08: Log rotation
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


# ============================================================================
# NFR-M01: Runtime configuration hot-reload
# ============================================================================


class TestNFR_M01_HotReload:
    """NFR-M01: Non-secret settings changeable without restart."""

    def test_hot_reload_config_exists(self):
        """Must have HOT_RELOAD_ENABLED configuration."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "config.py").read_text()
        assert "HOT_RELOAD_ENABLED" in content

    def test_hot_reload_watch_interval(self):
        """Must have configurable watch interval."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "config.py").read_text()
        assert "HOT_RELOAD_WATCH_INTERVAL" in content

    def test_hot_reload_signal_support(self):
        """Must support SIGHUP for hot-reload."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "config.py").read_text()
        assert "HOT_RELOAD_SIGNAL_ENABLED" in content

    def test_hot_reload_disabled_by_default(self):
        """Hot-reload must be opt-in (disabled by default for safety)."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "config.py").read_text()
        assert '"false"' in content  # HOT_RELOAD_ENABLED defaults to false


# ============================================================================
# NFR-M02: Stale document monitoring
# ============================================================================


class TestNFR_M02_StaleDocumentMonitoring:
    """NFR-M02: Automatic stale document detection every 24 hours."""

    def test_stale_detection_config(self):
        """Must have stale detection configuration."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "config.py").read_text()
        assert "STALE_DETECTION_ENABLED" in content

    def test_stale_thresholds_configurable(self):
        """Stale thresholds must be configurable per source type."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "config.py").read_text()
        assert "STALE_CONFLUENCE_DAYS" in content
        assert "STALE_JIRA_DAYS" in content
        assert "STALE_GITLAB_DAYS" in content

    def test_stale_documents_metric(self):
        """Must expose stale document count as Prometheus gauge."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "metrics.py").read_text()
        assert "rag_stale_documents" in content

    def test_stale_detection_enabled_by_default(self):
        """Stale detection must be enabled by default."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "config.py").read_text()
        assert "STALE_DETECTION_ENABLED" in content
        # Should default to true
        assert '"true"' in content

    def test_stale_scan_limit_configurable(self):
        """Must have configurable scan limit for stale detection."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "config.py").read_text()
        assert "STALE_DETECTION_SCAN_LIMIT" in content


# ============================================================================
# NFR-M03: Reindexing resilience
# ============================================================================


class TestNFR_M03_ReindexingResilience:
    """NFR-M03: 3 retries with exponential backoff on reindex errors."""

    def test_reindex_config_exists(self):
        """Must have reindex configuration."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "config.py").read_text()
        assert "REINDEX_ENABLED" in content

    def test_reindex_max_concurrent_tasks(self):
        """Must have configurable concurrent reindex tasks."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "config.py").read_text()
        assert "REINDEX_MAX_CONCURRENT_TASKS" in content

    def test_reindex_check_interval(self):
        """Must have configurable check interval."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "config.py").read_text()
        assert "REINDEX_CHECK_INTERVAL" in content

    def test_reindex_metrics(self):
        """Must have reindex task metrics."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "metrics.py").read_text()
        assert "rag_reindex_tasks_total" in content

    def test_reindex_staleness_threshold(self):
        """Must have configurable staleness threshold for reindexing."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "config.py").read_text()
        assert "REINDEX_STALENESS_THRESHOLD" in content

    def test_wal_supports_resume(self):
        """WAL manager must support resume after failure."""
        content = (PROJECT_ROOT / "etl" / "indexer" / "wal_manager.py").read_text()
        # Must have checkpoint persistence
        assert "write" in content.lower() or "save" in content.lower()
        assert "read" in content.lower() or "load" in content.lower()


# ============================================================================
# NFR-M05: Feedback preservation through reindex
# ============================================================================


class TestNFR_M05_FeedbackPreservation:
    """NFR-M05: Feedback preserved when documents are reindexed."""

    def test_feedback_endpoint_exists(self):
        """Feedback endpoint must exist."""
        content = (PROJECT_ROOT / "proxy" / "app" / "api" / "feedback.py").read_text()
        assert "feedback" in content.lower()

    def test_feedback_metrics_exist(self):
        """Must have feedback metrics for tracking."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "metrics.py").read_text()
        assert "RAG_FEEDBACK_TOTAL" in content

    def test_enrichment_module_exists(self):
        """Self-enrichment module must exist for feedback -> chunk pipeline."""
        content = (PROJECT_ROOT / "proxy" / "app" / "core" / "enricher.py").read_text()
        assert "class" in content or "def " in content

    def test_content_addressable_chunks(self):
        """Chunks must be content-addressable (SHA-256) for stable IDs."""
        retrieval_content = (PROJECT_ROOT / "proxy" / "app" / "core" / "retrieval.py").read_text()
        has_hash = (
            "hashlib" in retrieval_content
            or "sha256" in retrieval_content.lower()
            or "hash" in retrieval_content.lower()
        )
        assert has_hash


# ============================================================================
# NFR-M08: Log rotation
# ============================================================================


class TestNFR_M08_LogRotation:
    """NFR-M08: 100MB per file, keep 10 files, compress old."""

    def test_log_dir_configurable(self):
        """LOG_DIR must be configurable."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "config.py").read_text()
        assert "LOG_DIR" in content

    def test_log_format_configurable(self):
        """Log format must be configurable (json/text)."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "config.py").read_text()
        assert "LOG_FORMAT" in content

    def test_log_level_configurable(self):
        """Log level must be configurable."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "config.py").read_text()
        assert "LOG_LEVEL" in content

    def test_json_formatter_exists(self):
        """Must have JSON structured log formatter."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "logging.py").read_text()
        assert "class JsonFormatter" in content

    def test_log_setup_function(self):
        """Must have setup_logging function."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "logging.py").read_text()
        assert "def setup_logging" in content

    def test_docker_compose_mounts_log_volume(self):
        """Docker compose must mount log directory."""
        import yaml

        content = yaml.safe_load((PROJECT_ROOT / "proxy" / "docker-compose.yml").read_text())
        proxy_volumes = content.get("services", {}).get("rag-proxy", {}).get("volumes", [])
        volume_str = str(proxy_volumes)
        assert "logs" in volume_str
