"""Tests for model_evolution dependencies in requirements_proxy.txt and Dockerfile."""

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent.parent


class TestRequirementsProxy:
    """Verify model_evolution dependencies are present and GPU deps are optional."""

    @pytest.fixture
    def requirements_path(self) -> Path:
        return ROOT / "proxy" / "requirements_proxy.txt"

    @pytest.fixture
    def requirements_lines(self, requirements_path: Path) -> list[str]:
        return requirements_path.read_text().splitlines()

    # ── Model evolution core deps ──

    def test_peft_in_requirements(self, requirements_lines: list[str]):
        assert any(line.strip().startswith("peft") for line in requirements_lines), \
            "peft dependency not found in requirements_proxy.txt"

    def test_mlflow_in_requirements(self, requirements_lines: list[str]):
        assert any(line.strip().startswith("mlflow") for line in requirements_lines), \
            "mlflow dependency not found in requirements_proxy.txt"

    def test_boto3_in_requirements(self, requirements_lines: list[str]):
        assert any(line.strip().startswith("boto3") for line in requirements_lines), \
            "boto3 dependency not found in requirements_proxy.txt"

    def test_rouge_score_in_requirements(self, requirements_lines: list[str]):
        assert any(line.strip().startswith("rouge-score") for line in requirements_lines), \
            "rouge-score dependency not found in requirements_proxy.txt"

    # ── GPU deps are marked as optional ──

    def test_bitsandbytes_marked_optional(self, requirements_lines: list[str]):
        """bitsandbytes must be present (commented or not) and marked as GPU/optional."""
        for line in requirements_lines:
            stripped = line.strip()
            if "bitsandbytes" in stripped.lower():
                lower = stripped.lower()
                assert any(
                    keyword in lower for keyword in ("optional", "gpu", "опционально", "#")
                ), f"bitsandbytes should be marked optional but got: {stripped}"
                return
        pytest.fail("bitsandbytes not found in requirements_proxy.txt")

    def test_accelerate_marked_optional(self, requirements_lines: list[str]):
        """accelerate must be present (commented or not) and marked as GPU/optional."""
        for line in requirements_lines:
            stripped = line.strip()
            if "accelerate" in stripped.lower():
                lower = stripped.lower()
                assert any(
                    keyword in lower for keyword in ("optional", "gpu", "опционально", "#")
                ), f"accelerate should be marked optional but got: {stripped}"
                return
        pytest.fail("accelerate not found in requirements_proxy.txt")

    def test_bert_score_marked_optional(self, requirements_lines: list[str]):
        """bert-score must be present and marked as optional."""
        for line in requirements_lines:
            stripped = line.strip()
            if "bert-score" in stripped.lower():
                lower = stripped.lower()
                assert any(
                    keyword in lower for keyword in ("optional", "#")
                ), f"bert-score should be marked optional but got: {stripped}"
                return
        pytest.fail("bert-score not found in requirements_proxy.txt")

    # ── Section structure ──

    def test_model_evolution_section_exists(self, requirements_lines: list[str]):
        """There should be a model_evolution (or similar) section header."""
        section_found = any(
            "#" in line and any(
                kw in line.lower() for kw in ("model evolution", "model_evolution", "дообучение", "fine-tuning")
            )
            for line in requirements_lines
        )
        assert section_found, "No model_evolution section header found in requirements_proxy.txt"

    def test_gpu_section_exists(self, requirements_lines: list[str]):
        """There should be a GPU section header for optional GPU deps."""
        section_found = any(
            "#" in line and any(
                kw in line.lower() for kw in ("gpu", "опционально", "опциональные", "optional")
            )
            for line in requirements_lines
        )
        assert section_found, "No GPU/optional section header found in requirements_proxy.txt"

    def test_gpu_extras_file_exists(self):
        """There should be a separate requirements_proxy_gpu.txt for GPU extras."""
        gpu_req_path = ROOT / "proxy" / "requirements_proxy_gpu.txt"
        assert gpu_req_path.exists(), \
            "requirements_proxy_gpu.txt not found — GPU deps should have a separate extras file"
        content = gpu_req_path.read_text()
        assert "bitsandbytes" in content, \
            "requirements_proxy_gpu.txt should contain bitsandbytes"
        assert "accelerate" in content, \
            "requirements_proxy_gpu.txt should contain accelerate"


class TestDockerfile:
    """Verify Dockerfile has model_evolution support and GPU comments."""

    @pytest.fixture
    def dockerfile_path(self) -> Path:
        return ROOT / "proxy" / "Dockerfile"

    @pytest.fixture
    def dockerfile_lines(self, dockerfile_path: Path) -> list[str]:
        return dockerfile_path.read_text().splitlines()

    def test_dockerfile_copy_model_evolution_package(self, dockerfile_lines: list[str]):
        """Dockerfile should COPY the model_evolution package."""
        copy_model_evo = any(
            "model_evolution" in line for line in dockerfile_lines
        )
        assert copy_model_evo, \
            "Dockerfile does not reference model_evolution package"

    def test_dockerfile_has_gpu_comment(self, dockerfile_lines: list[str]):
        """Dockerfile should have a comment about GPU support."""
        gpu_comment = any(
            "#" in line and any(
                kw in line.lower() for kw in ("gpu", "cuda", "nvidia")
            )
            for line in dockerfile_lines
        )
        assert gpu_comment, \
            "Dockerfile has no GPU-related comment"

    def test_dockerfile_comment_mentions_optional_gpu_deps(self, dockerfile_lines: list[str]):
        """GPU deps comment should mention they are optional."""
        for line in dockerfile_lines:
            if "GPU" in line or "gpu" in line.lower():
                lower = line.lower()
                if "optional" in lower or "опционально" in lower:
                    return
        pytest.fail("Dockerfile GPU comment does not mention that GPU deps are optional")

    def test_dockerfile_no_hard_bitsandbytes_install(self, dockerfile_lines: list[str]):
        """Dockerfile should not have a hard RUN for bitsandbytes without optional comment."""
        for line in dockerfile_lines:
            stripped = line.strip()
            if stripped.lower().startswith("run") and "bitsandbytes" in stripped:
                pytest.fail(
                    f"Dockerfile has hard-coded bitsandbytes install: {stripped}. "
                    "GPU deps should be optional."
                )
