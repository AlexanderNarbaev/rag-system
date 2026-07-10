"""Tests for model evolution configuration and package foundation."""

import importlib

import pytest

import proxy.app.shared.config as config_module


class TestModelEvolutionConfigDefaults:
    """Test that model evolution config vars have correct defaults."""

    def test_default_disabled(self):
        assert config_module.MODEL_EVOLUTION_ENABLED is False

    def test_mlflow_uri_default(self):
        assert "localhost:5000" in config_module.MLFLOW_TRACKING_URI

    def test_minio_vars_default(self):
        assert config_module.MINIO_ENDPOINT == "localhost:9000"
        assert config_module.MINIO_ACCESS_KEY == "minioadmin"
        assert config_module.MINIO_SECRET_KEY == "minioadmin"
        assert config_module.MINIO_BUCKET == "rag-artifacts"
        assert config_module.MINIO_SECURE is False

    def test_hot_reload_default_disabled(self):
        assert config_module.HOT_RELOAD_ENABLED is False

    def test_canary_default_disabled(self):
        assert config_module.CANARY_ENABLED is False

    def test_training_profile_default_dev(self):
        assert config_module.TRAINING_PROFILE == "dev"

    def test_eval_gate_thresholds_have_defaults(self):
        assert config_module.EVAL_GATE_LLM_BERTSCORE_MIN == 0.70
        assert config_module.EVAL_GATE_LLM_HALLUCINATION_MAX == 0.05
        assert config_module.EVAL_GATE_SLM_F1_MIN == 0.85


class TestModelEvolutionEnvOverrides:
    """Test that environment variables override model evolution config."""

    @pytest.fixture(autouse=True)
    def _restore_config(self):
        yield
        importlib.reload(config_module)

    def test_enabled_true(self, monkeypatch):
        monkeypatch.setenv("MODEL_EVOLUTION_ENABLED", "true")
        importlib.reload(config_module)
        assert config_module.MODEL_EVOLUTION_ENABLED is True

    def test_mlflow_uri_override(self, monkeypatch):
        monkeypatch.setenv("MLFLOW_TRACKING_URI", "http://mlflow.internal:8080")
        importlib.reload(config_module)
        assert config_module.MLFLOW_TRACKING_URI == "http://mlflow.internal:8080"

    def test_minio_override(self, monkeypatch):
        monkeypatch.setenv("MINIO_ENDPOINT", "s3.internal:443")
        monkeypatch.setenv("MINIO_BUCKET", "prod-artifacts")
        importlib.reload(config_module)
        assert config_module.MINIO_ENDPOINT == "s3.internal:443"
        assert config_module.MINIO_BUCKET == "prod-artifacts"

    def test_training_profile_override(self, monkeypatch):
        monkeypatch.setenv("TRAINING_PROFILE", "prod")
        importlib.reload(config_module)
        assert config_module.TRAINING_PROFILE == "prod"

    def test_hot_reload_enabled_override(self, monkeypatch):
        monkeypatch.setenv("HOT_RELOAD_ENABLED", "true")
        importlib.reload(config_module)
        assert config_module.HOT_RELOAD_ENABLED is True

    def test_canary_enabled_override(self, monkeypatch):
        monkeypatch.setenv("CANARY_ENABLED", "true")
        importlib.reload(config_module)
        assert config_module.CANARY_ENABLED is True

    def test_eval_gate_thresholds_override(self, monkeypatch):
        monkeypatch.setenv("EVAL_GATE_LLM_BERTSCORE_MIN", "0.75")
        monkeypatch.setenv("EVAL_GATE_SLM_F1_MIN", "0.90")
        importlib.reload(config_module)
        assert config_module.EVAL_GATE_LLM_BERTSCORE_MIN == 0.75
        assert config_module.EVAL_GATE_SLM_F1_MIN == 0.90


class TestModelEvolutionPackage:
    """Test the model_evolution package foundation (exceptions + env_profile)."""

    def test_exceptions_module_exists(self):
        import proxy.app.model_evolution.exceptions  # noqa: F401

    def test_model_evolution_error(self):
        from proxy.app.model_evolution.exceptions import ModelEvolutionError

        err = ModelEvolutionError("test message")
        assert str(err) == "test message"
        assert isinstance(err, Exception)

    def test_training_error(self):
        from proxy.app.model_evolution.exceptions import TrainingError

        err = TrainingError("training failed")
        assert "training failed" in str(err)

    def test_eval_gate_error(self):
        from proxy.app.model_evolution.exceptions import EvalGateError

        err = EvalGateError("gate not passed")
        assert isinstance(err, Exception)

    def test_adapter_error(self):
        from proxy.app.model_evolution.exceptions import AdapterError

        err = AdapterError("adapter load failed")
        assert "adapter load failed" in str(err)

    def test_env_profile_module_exists(self):
        import proxy.app.model_evolution.env_profile  # noqa: F401

    def test_env_profile_enum(self):
        from proxy.app.model_evolution.env_profile import EnvProfile

        assert EnvProfile.DEV.value == "dev"
        assert EnvProfile.PROD.value == "prod"
        assert EnvProfile.CI.value == "ci"

    def test_env_profile_presets(self):
        from proxy.app.model_evolution.env_profile import EnvProfile, get_preset

        dev = get_preset(EnvProfile.DEV)
        assert dev["gpu_enabled"] is False
        assert dev["batch_size"] == 2

        prod = get_preset(EnvProfile.PROD)
        assert prod["gpu_enabled"] is True
        assert prod["batch_size"] == 16

        ci = get_preset(EnvProfile.CI)
        assert ci["gpu_enabled"] is False
        assert ci["batch_size"] == 1

    def test_env_profile_from_name(self):
        from proxy.app.model_evolution.env_profile import EnvProfile, get_profile

        assert get_profile("dev") == EnvProfile.DEV
        assert get_profile("prod") == EnvProfile.PROD
        assert get_profile("ci") == EnvProfile.CI

    def test_env_profile_invalid_name(self):
        from proxy.app.model_evolution.env_profile import EnvProfile, get_profile

        assert get_profile("unknown") == EnvProfile.DEV

    def test_package_init_exports(self):
        import proxy.app.model_evolution as me

        assert hasattr(me, "ModelEvolutionError")
        assert hasattr(me, "TrainingError")
        assert hasattr(me, "EvalGateError")
        assert hasattr(me, "AdapterError")
        assert hasattr(me, "EnvProfile")
        assert hasattr(me, "get_preset")
