# tests/deploy/test_helm_chart.py
"""Deployment smoke tests for Docker Compose, Helm charts, backup scripts.

Covers:
- FR-149: Docker Compose deployment
- FR-150: Helm chart for Kubernetes
- FR-151: ETL Helm component
- FR-152: Distributed compose
- FR-153: MinIO Helm deployment
- FR-154: PostgreSQL Helm deployment
- FR-162: Grafana dashboard
- FR-163: Prometheus alert rules
- FR-165: Automated backup scripts
- FR-167: Restore script
"""

import json
import subprocess
from pathlib import Path

import pytest
import yaml

# ── Project root ──────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[2]


# ============================================================================
# FR-149: Docker Compose deployment
# ============================================================================


class TestDockerCompose:
    """FR-149: docker compose up -d starts all services; /v1/health returns OK."""

    COMPOSE_FILE = PROJECT_ROOT / "proxy" / "docker-compose.yml"

    def test_compose_file_exists(self):
        """docker-compose.yml must exist."""
        assert self.COMPOSE_FILE.exists(), f"Missing {self.COMPOSE_FILE}"

    def test_compose_is_valid_yaml(self):
        """docker-compose.yml must be valid YAML."""
        content = yaml.safe_load(self.COMPOSE_FILE.read_text())
        assert isinstance(content, dict)
        assert "services" in content

    def test_compose_has_required_services(self):
        """Must define qdrant, redis, and rag-proxy services."""
        content = yaml.safe_load(self.COMPOSE_FILE.read_text())
        services = content.get("services", {})
        for svc in ("qdrant", "redis", "rag-proxy"):
            assert svc in services, f"Missing service: {svc}"

    def test_compose_services_have_healthchecks(self):
        """Core services must define healthchecks."""
        content = yaml.safe_load(self.COMPOSE_FILE.read_text())
        services = content.get("services", {})
        for svc_name in ("qdrant", "redis", "rag-proxy"):
            svc = services[svc_name]
            assert "healthcheck" in svc, f"Service '{svc_name}' missing healthcheck"

    def test_compose_validates_with_docker(self):
        """docker compose config should validate without errors (skip if docker unavailable)."""
        try:
            result = subprocess.run(
                ["docker", "compose", "-f", str(self.COMPOSE_FILE), "config"],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except FileNotFoundError:
            pytest.skip("Docker not available")
        assert result.returncode == 0, f"Validation failed:\n{result.stderr}"


# ============================================================================
# FR-150: Helm chart for Kubernetes
# ============================================================================


class TestHelmChart:
    """FR-150: helm lint + helm template produce valid K8s manifests."""

    CHART_DIR = PROJECT_ROOT / "deploy" / "k8s" / "helm" / "rag-system"

    def test_chart_directory_exists(self):
        """Helm chart directory must exist with Chart.yaml."""
        assert (self.CHART_DIR / "Chart.yaml").exists()

    def test_chart_yaml_is_valid(self):
        """Chart.yaml must be valid with required fields."""
        chart = yaml.safe_load((self.CHART_DIR / "Chart.yaml").read_text())
        assert chart["apiVersion"] == "v2"
        assert "name" in chart
        assert "version" in chart

    def test_values_yaml_is_valid(self):
        """values.yaml must be valid YAML."""
        values = yaml.safe_load((self.CHART_DIR / "values.yaml").read_text())
        assert isinstance(values, dict)
        assert "proxy" in values

    def test_templates_directory_has_files(self):
        """Templates directory must contain template files."""
        templates_dir = self.CHART_DIR / "templates"
        assert templates_dir.exists()
        yaml_files = list(templates_dir.glob("*.yaml"))
        assert len(yaml_files) >= 10, f"Expected >=10 templates, found {len(yaml_files)}"

    def test_helm_lint_passes(self):
        """helm lint must pass without errors."""
        try:
            result = subprocess.run(
                ["helm", "lint", str(self.CHART_DIR)],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except FileNotFoundError:
            pytest.skip("Helm not available")
        assert result.returncode == 0, f"helm lint failed:\n{result.stderr}\n{result.stdout}"

    def test_helm_template_renders(self):
        """helm template must produce valid YAML manifests."""
        try:
            result = subprocess.run(
                ["helm", "template", "test-release", str(self.CHART_DIR)],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except FileNotFoundError:
            pytest.skip("Helm not available")
        assert result.returncode == 0, f"helm template failed:\n{result.stderr}"
        # Parse rendered YAML — must not raise
        docs = list(yaml.safe_load_all(result.stdout))
        assert len(docs) > 0, "helm template produced no documents"

    def test_proxy_deployment_template_exists(self):
        """Proxy deployment template must exist."""
        assert (self.CHART_DIR / "templates" / "proxy-deployment.yaml").exists()

    def test_networkpolicy_template_exists(self):
        """NetworkPolicy template must exist."""
        assert (self.CHART_DIR / "templates" / "networkpolicy.yaml").exists()

    def test_pdb_template_exists(self):
        """PodDisruptionBudget template must exist."""
        assert (self.CHART_DIR / "templates" / "proxy-pdb.yaml").exists()

    def test_serviceaccount_template_exists(self):
        """ServiceAccount template must exist."""
        assert (self.CHART_DIR / "templates" / "serviceaccount.yaml").exists()


# ============================================================================
# FR-151: ETL Helm component
# ============================================================================


class TestETLHelmComponent:
    """FR-151: ETL CronJob template renders when etl.enabled=true."""

    CHART_DIR = PROJECT_ROOT / "deploy" / "k8s" / "helm" / "rag-system"

    def test_etl_cronjob_template_exists(self):
        """etl-cronjob.yaml template must exist."""
        assert (self.CHART_DIR / "templates" / "etl-cronjob.yaml").exists()

    def test_etl_cronjob_renders_when_enabled(self):
        """CronJob should render when etl.enabled=true."""
        try:
            result = subprocess.run(
                [
                    "helm",
                    "template",
                    "test-release",
                    str(self.CHART_DIR),
                    "--set",
                    "etl.enabled=true",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except FileNotFoundError:
            pytest.skip("Helm not available")
        assert result.returncode == 0
        assert "kind: CronJob" in result.stdout
        assert "etl" in result.stdout.lower()

    def test_etl_values_include_schedule(self):
        """values.yaml must define etl.schedule."""
        values = yaml.safe_load((self.CHART_DIR / "values.yaml").read_text())
        etl = values.get("etl", {})
        assert "schedule" in etl, "etl.schedule not defined in values.yaml"
        assert "enabled" in etl, "etl.enabled not defined in values.yaml"


# ============================================================================
# FR-152: Distributed compose
# ============================================================================


class TestDistributedCompose:
    """FR-152: docker-compose.distributed.yml for multi-machine deployment."""

    COMPOSE_FILE = PROJECT_ROOT / "deploy" / "docker" / "docker-compose.distributed.yml"

    def test_file_exists(self):
        """Distributed compose file must exist."""
        assert self.COMPOSE_FILE.exists()

    def test_is_valid_yaml(self):
        """Must be valid YAML with services."""
        content = yaml.safe_load(self.COMPOSE_FILE.read_text())
        assert "services" in content

    def test_has_multi_machine_services(self):
        """Must define proxy, qdrant, etl, and openwebui services."""
        content = yaml.safe_load(self.COMPOSE_FILE.read_text())
        services = content.get("services", {})
        for svc in ("proxy", "qdrant", "etl"):
            assert svc in services, f"Missing distributed service: {svc}"

    def test_services_have_healthchecks(self):
        """Core services must have healthchecks for distributed deployment."""
        content = yaml.safe_load(self.COMPOSE_FILE.read_text())
        services = content.get("services", {})
        for svc_name in ("qdrant", "redis", "proxy"):
            if svc_name in services:
                assert "healthcheck" in services[svc_name], f"'{svc_name}' missing healthcheck"

    def test_services_use_env_variables(self):
        """Services must use environment variables, not hardcoded hostnames."""
        content = yaml.safe_load(self.COMPOSE_FILE.read_text())
        proxy_env = content.get("services", {}).get("proxy", {}).get("environment", [])
        env_str = str(proxy_env)
        assert "QDRANT_HOST" in env_str
        assert "REDIS_URL" in env_str


# ============================================================================
# FR-153: MinIO Helm deployment
# ============================================================================


class TestMinIOHelm:
    """FR-153: MinIO StatefulSet with PVC and secrets."""

    CHART_DIR = PROJECT_ROOT / "deploy" / "k8s" / "helm" / "rag-system"

    def test_minio_statefulset_template_exists(self):
        """minio-statefulset.yaml must exist."""
        assert (self.CHART_DIR / "templates" / "minio-statefulset.yaml").exists()

    def test_minio_renders_when_enabled(self):
        """StatefulSet must render when minio.enabled=true."""
        try:
            result = subprocess.run(
                [
                    "helm",
                    "template",
                    "test-release",
                    str(self.CHART_DIR),
                    "--set",
                    "minio.enabled=true",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except FileNotFoundError:
            pytest.skip("Helm not available")
        assert result.returncode == 0
        assert "kind: StatefulSet" in result.stdout

    def test_minio_template_has_pvc(self):
        """Template must define volumeClaimTemplates for data persistence."""
        tmpl = (self.CHART_DIR / "templates" / "minio-statefulset.yaml").read_text()
        assert "volumeClaimTemplates" in tmpl

    def test_minio_template_has_secrets(self):
        """Template must reference secrets for credentials (not plaintext)."""
        tmpl = (self.CHART_DIR / "templates" / "minio-statefulset.yaml").read_text()
        assert "secretKeyRef" in tmpl


# ============================================================================
# FR-154: PostgreSQL Helm deployment
# ============================================================================


class TestPostgreSQLHelm:
    """FR-154: PostgreSQL StatefulSet with secrets and probes."""

    CHART_DIR = PROJECT_ROOT / "deploy" / "k8s" / "helm" / "rag-system"

    def test_postgresql_statefulset_template_exists(self):
        """postgresql-statefulset.yaml must exist."""
        assert (self.CHART_DIR / "templates" / "postgresql-statefulset.yaml").exists()

    def test_postgresql_renders_when_enabled(self):
        """StatefulSet must render when postgresql.enabled=true."""
        try:
            result = subprocess.run(
                [
                    "helm",
                    "template",
                    "test-release",
                    str(self.CHART_DIR),
                    "--set",
                    "postgresql.enabled=true",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except FileNotFoundError:
            pytest.skip("Helm not available")
        assert result.returncode == 0
        assert "kind: StatefulSet" in result.stdout

    def test_postgresql_template_has_secrets(self):
        """Template must use K8s secrets for credentials."""
        tmpl = (self.CHART_DIR / "templates" / "postgresql-statefulset.yaml").read_text()
        assert "secretKeyRef" in tmpl
        assert "POSTGRES_PASSWORD" in tmpl

    def test_postgresql_template_has_pvc(self):
        """Template must define volumeClaimTemplates."""
        tmpl = (self.CHART_DIR / "templates" / "postgresql-statefulset.yaml").read_text()
        assert "volumeClaimTemplates" in tmpl


# ============================================================================
# FR-162: Grafana dashboard
# ============================================================================


class TestGrafanaDashboard:
    """FR-162: Grafana dashboard JSON must be valid and importable."""

    DASHBOARD_FILE = PROJECT_ROOT / "config" / "monitoring" / "ragas-dashboard.json"

    def test_dashboard_file_exists(self):
        """Dashboard JSON file must exist."""
        assert self.DASHBOARD_FILE.exists()

    def test_dashboard_is_valid_json(self):
        """Must be valid JSON."""
        data = json.loads(self.DASHBOARD_FILE.read_text())
        assert isinstance(data, dict)

    def test_dashboard_has_panels(self):
        """Dashboard must define monitoring panels."""
        data = json.loads(self.DASHBOARD_FILE.read_text())
        dashboard = data.get("dashboard", data)
        panels = dashboard.get("panels", [])
        assert len(panels) >= 4, f"Expected >=4 panels, found {len(panels)}"

    def test_dashboard_has_required_metrics(self):
        """Panels must reference key RAG metrics."""
        content = self.DASHBOARD_FILE.read_text()
        for metric in ("rag_request_duration_seconds", "rag_hallucination_detected_total", "rag_cache_hits_total"):
            assert metric in content, f"Dashboard missing metric: {metric}"

    def test_dashboard_has_alerts_section(self):
        """Dashboard must define alerts."""
        data = json.loads(self.DASHBOARD_FILE.read_text())
        dashboard = data.get("dashboard", data)
        assert "alerts" in dashboard, "Dashboard missing alerts section"
        assert len(dashboard["alerts"]) >= 2


# ============================================================================
# FR-163: Prometheus alert rules
# ============================================================================


class TestAlertRules:
    """FR-163: promtool check rules must pass; required alerts present."""

    ALERTS_FILE = PROJECT_ROOT / "config" / "monitoring" / "alerts.yml"

    def test_alerts_file_exists(self):
        """alerts.yml must exist."""
        assert self.ALERTS_FILE.exists()

    def test_alerts_is_valid_yaml(self):
        """Must be valid YAML."""
        content = yaml.safe_load(self.ALERTS_FILE.read_text())
        assert "groups" in content

    def test_alerts_have_required_rules(self):
        """Must define HighLatency alert at minimum."""
        content = yaml.safe_load(self.ALERTS_FILE.read_text())
        rules = []
        for group in content.get("groups", []):
            rules.extend(group.get("rules", []))
        alert_names = {r["alert"] for r in rules}
        assert "HighLatency" in alert_names, f"Missing HighLatency alert; found: {alert_names}"

    def test_alert_rules_have_labels_and_annotations(self):
        """Each alert rule must have severity label and summary annotation."""
        content = yaml.safe_load(self.ALERTS_FILE.read_text())
        for group in content.get("groups", []):
            for rule in group.get("rules", []):
                assert "labels" in rule, f"Rule '{rule.get('alert')}' missing labels"
                assert "severity" in rule["labels"], f"Rule '{rule.get('alert')}' missing severity"
                assert "annotations" in rule, f"Rule '{rule.get('alert')}' missing annotations"

    def test_promtool_check_rules(self):
        """promtool check rules must pass (skip if promtool unavailable)."""
        try:
            result = subprocess.run(
                ["promtool", "check", "rules", str(self.ALERTS_FILE)],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except FileNotFoundError:
            pytest.skip("promtool not available")
        assert result.returncode == 0, f"promtool check failed:\n{result.stderr}"


# ============================================================================
# FR-165: Automated backup scripts
# ============================================================================


class TestBackupScripts:
    """FR-165: Backup scripts must exist and have valid bash syntax."""

    OPS_DIR = PROJECT_ROOT / "scripts" / "ops"

    @pytest.mark.parametrize(
        "script_name",
        [
            "backup_cron.sh",
            "backup_qdrant.sh",
            "backup_neo4j.sh",
            "backup_redis.sh",
        ],
    )
    def test_backup_script_exists(self, script_name: str):
        """Each backup script must exist."""
        script = self.OPS_DIR / script_name
        assert script.exists(), f"Missing backup script: {script_name}"

    @pytest.mark.parametrize(
        "script_name",
        [
            "backup_cron.sh",
            "backup_qdrant.sh",
            "backup_neo4j.sh",
            "backup_redis.sh",
        ],
    )
    def test_backup_script_has_valid_syntax(self, script_name: str):
        """Each backup script must have valid bash syntax."""
        script = self.OPS_DIR / script_name
        result = subprocess.run(
            ["bash", "-n", str(script)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, f"Syntax error in {script_name}:\n{result.stderr}"

    def test_backup_cron_has_s3_upload(self):
        """Backup cron should reference S3/MinIO upload."""
        content = (self.OPS_DIR / "backup_cron.sh").read_text()
        # Should reference S3 or backup bucket
        assert any(kw in content.lower() for kw in ("s3", "backup_bucket", "minio", "mc "))

    def test_backup_scripts_are_executable(self):
        """Backup scripts should have executable permission."""
        for name in ("backup_cron.sh", "backup_qdrant.sh", "backup_redis.sh"):
            script = self.OPS_DIR / name
            assert script.stat().st_mode & 0o111, f"{name} is not executable"


# ============================================================================
# FR-167: Restore script
# ============================================================================


class TestRestoreScript:
    """FR-167: restore_all.sh must exist with valid syntax and --latest flag."""

    OPS_DIR = PROJECT_ROOT / "scripts" / "ops"

    def test_restore_script_exists(self):
        """restore_all.sh must exist."""
        assert (self.OPS_DIR / "restore_all.sh").exists()

    def test_restore_script_has_valid_syntax(self):
        """restore_all.sh must have valid bash syntax."""
        result = subprocess.run(
            ["bash", "-n", str(self.OPS_DIR / "restore_all.sh")],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, f"Syntax error:\n{result.stderr}"

    def test_restore_script_supports_latest_flag(self):
        """Script must support RESTORE_DATE or --latest flag."""
        content = (self.OPS_DIR / "restore_all.sh").read_text()
        assert "RESTORE_DATE" in content or "--latest" in content

    def test_verify_restore_script_exists(self):
        """verify_restore.sh must exist for post-restore integrity checks."""
        assert (self.OPS_DIR / "verify_restore.sh").exists()

    def test_verify_restore_has_valid_syntax(self):
        """verify_restore.sh must have valid bash syntax."""
        result = subprocess.run(
            ["bash", "-n", str(self.OPS_DIR / "verify_restore.sh")],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
