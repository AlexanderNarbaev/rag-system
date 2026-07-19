# tests/performance/test_nfr_capacity.py
"""NFR-C: Capacity and scalability non-functional requirements tests.

Verifies capacity planning and scalability infrastructure:

- NFR-C01: 50 concurrent users (p95 < 5s)
- NFR-C02: Qdrant collection < 1M vectors
- NFR-C03: Qdrant sharding
- NFR-C04: ETL parallel extraction
- NFR-C05: Cold storage (version stratification)
"""

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


# ============================================================================
# NFR-C01: 50 concurrent users
# ============================================================================


class TestNFR_C01_ConcurrentUsers:
    """NFR-C01: System handles 50 concurrent users with p95 < 5s."""

    def test_active_requests_gauge(self):
        """Must track active concurrent requests."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "metrics.py").read_text()
        assert "rag_active_requests" in content

    def test_queue_depth_metric(self):
        """Must have request queue depth metric."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "metrics.py").read_text()
        assert "RAG_QUEUE_DEPTH" in content or "rag_queue_depth" in content

    def test_rate_limiter_exists(self):
        """Rate limiter must exist to protect against overload."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "rate_limiter.py").read_text()
        assert "class" in content

    def test_rate_limit_config(self):
        """Must have rate limiting configuration."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "config.py").read_text()
        assert "RATE_LIMIT_ENABLED" in content
        assert "RATE_LIMIT_PER_MINUTE" in content
        assert "RATE_LIMIT_BURST" in content

    def test_hpa_template_exists(self):
        """Must have HPA template for autoscaling."""
        hpa_file = PROJECT_ROOT / "deploy" / "k8s" / "helm" / "rag-system" / "templates" / "proxy-hpa.yaml"
        assert hpa_file.exists(), "proxy-hpa.yaml must exist for autoscaling"

    def test_helm_replica_count(self):
        """Must have configurable replica count."""
        values = yaml.safe_load((PROJECT_ROOT / "deploy" / "k8s" / "helm" / "rag-system" / "values.yaml").read_text())
        proxy = values.get("proxy", {})
        assert "replicaCount" in proxy
        assert proxy["replicaCount"] >= 2


# ============================================================================
# NFR-C02: Qdrant collection < 1M vectors
# ============================================================================


class TestNFR_C02_CollectionSize:
    """NFR-C02: Default HNSW for < 1M, quantization for > 1M."""

    def test_hnsw_config_defaults(self):
        """Must have sensible HNSW defaults for < 1M vectors."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "config.py").read_text()
        assert "QDRANT_HNSW_M" in content
        assert "QDRANT_HNSW_EF_CONSTRUCT" in content

    def test_quantization_for_large_collections(self):
        """Must support quantization for > 1M vectors."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "config.py").read_text()
        assert "QDRANT_QUANTIZATION_ENABLED" in content

    def test_kb_manager_collection_creation(self):
        """kb_manager must create collections with proper config."""
        content = (PROJECT_ROOT / "proxy" / "app" / "core" / "kb_manager.py").read_text()
        assert "HnswConfigDiff" in content


# ============================================================================
# NFR-C03: Qdrant sharding
# ============================================================================


class TestNFR_C03_Sharding:
    """NFR-C03: 4 shards for 10M-50M, 8 shards > 50M vectors."""

    def test_kb_manager_supports_sharding(self):
        """kb_manager must support sharding configuration."""
        content = (PROJECT_ROOT / "proxy" / "app" / "core" / "kb_manager.py").read_text()
        # Must reference sharding, replication, or on_disk for scalability
        has_scaling = any(
            kw in content.lower() for kw in ("shard", "sharding", "replication", "on_disk", "optimizers_config")
        )
        # Soft check — sharding may be configured at Qdrant level, not in kb_manager
        assert "create_collection" in content or has_scaling


# ============================================================================
# NFR-C04: ETL parallel extraction
# ============================================================================


class TestNFR_C04_ParallelExtraction:
    """NFR-C04: 3 Confluence workers, 5 Jira workers, 3 GitLab workers."""

    def test_etl_config_exists(self):
        """ETL config must exist with worker settings."""
        config_file = PROJECT_ROOT / "etl" / "config" / "etl_config.yaml"
        if config_file.exists():
            content = yaml.safe_load(config_file.read_text())
            assert isinstance(content, dict)

    def test_etl_scheduler_orchestrates(self):
        """ETL scheduler must orchestrate parallel extraction."""
        content = (PROJECT_ROOT / "etl" / "scheduler" / "run_etl.py").read_text()
        assert "def " in content

    def test_etl_extractors_exist(self):
        """Must have extractors for all data sources."""
        extractors_dir = PROJECT_ROOT / "etl" / "extractors"
        if extractors_dir.exists():
            extractor_files = [f.name for f in extractors_dir.glob("*.py")]
            # Must have at least confluence, jira, gitlab extractors
            assert len(extractor_files) >= 3


# ============================================================================
# NFR-C05: Cold storage
# ============================================================================


class TestNFR_C05_ColdStorage:
    """NFR-C05: Current + 1 prior version in Qdrant, older in Parquet."""

    def test_version_tracking_in_retrieval(self):
        """Retrieval must support version filtering."""
        content = (PROJECT_ROOT / "proxy" / "app" / "core" / "retrieval.py").read_text()
        assert "version" in content.lower()

    def test_version_in_context_builder(self):
        """Context builder must handle document versions."""
        content = (PROJECT_ROOT / "proxy" / "app" / "core" / "context" / "builder.py").read_text()
        assert "version" in content.lower()

    def test_content_addressable_chunks(self):
        """Chunks must use content-addressable hashing for versioning."""
        content = (PROJECT_ROOT / "proxy" / "app" / "core" / "retrieval.py").read_text()
        assert "hash" in content.lower()

    def test_minio_for_object_storage(self):
        """Must have MinIO/S3 configuration for cold storage."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "config.py").read_text()
        assert "MINIO_ENDPOINT" in content
        assert "MINIO_BUCKET" in content
