"""Tests for proxy/app/model_evolution/experiment_tracker.py — ExperimentTracker."""
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from proxy.app.model_evolution.experiment_tracker import ExperimentTracker


class TestExperimentTrackerLocalMode:
    """Tests for ExperimentTracker in local (file-based) mode."""

    @pytest.fixture
    def tmp_data_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_default_local_mode_when_no_mlflow_uri(self):
        tracker = ExperimentTracker()
        assert tracker.local_mode is True
        assert tracker._tracking_uri is None

    def test_start_run_creates_run_directory(self, tmp_data_dir):
        tracker = ExperimentTracker(data_dir=tmp_data_dir, experiment_name="test_experiment")
        run_id = tracker.start_run(run_name="test_run")
        assert run_id is not None
        assert len(run_id) > 0
        run_dir = Path(tmp_data_dir) / "test_experiment" / run_id
        assert run_dir.exists()
        assert (run_dir / "metadata.json").exists()

    def test_start_run_returns_unique_ids(self, tmp_data_dir):
        tracker = ExperimentTracker(data_dir=tmp_data_dir)
        run1 = tracker.start_run(run_name="run_a")
        run2 = tracker.start_run(run_name="run_b")
        assert run1 != run2

    def test_log_params_stores_in_run_dir(self, tmp_data_dir):
        tracker = ExperimentTracker(data_dir=tmp_data_dir)
        run_id = tracker.start_run(run_name="param_test")
        tracker.log_params({"learning_rate": 0.001, "batch_size": 32})

        params_path = Path(tmp_data_dir) / "default" / run_id / "params.json"
        assert params_path.exists()
        with open(params_path) as f:
            params = json.load(f)
        assert params == {"learning_rate": 0.001, "batch_size": 32}

    def test_log_params_raises_when_no_active_run(self):
        tracker = ExperimentTracker()
        with pytest.raises(RuntimeError, match="No active run"):
            tracker.log_params({"key": "value"})

    def test_log_metrics_stores_in_run_dir(self, tmp_data_dir):
        tracker = ExperimentTracker(data_dir=tmp_data_dir)
        run_id = tracker.start_run(run_name="metric_test")
        tracker.log_metrics({"accuracy": 0.95, "loss": 0.12})

        metrics_path = Path(tmp_data_dir) / "default" / run_id / "metrics.json"
        assert metrics_path.exists()
        with open(metrics_path) as f:
            metrics = json.load(f)
        assert metrics == {"accuracy": 0.95, "loss": 0.12}

    def test_log_metrics_appends_to_existing(self, tmp_data_dir):
        tracker = ExperimentTracker(data_dir=tmp_data_dir)
        run_id = tracker.start_run(run_name="metric_append_test")
        tracker.log_metrics({"accuracy": 0.90})
        tracker.log_metrics({"loss": 0.15})

        metrics_path = Path(tmp_data_dir) / "default" / run_id / "metrics.json"
        with open(metrics_path) as f:
            metrics = json.load(f)
        assert metrics == {"accuracy": 0.90, "loss": 0.15}

    def test_log_metrics_raises_when_no_active_run(self):
        tracker = ExperimentTracker()
        with pytest.raises(RuntimeError, match="No active run"):
            tracker.log_metrics({"accuracy": 0.9})

    def test_log_artifact_copies_file_to_run_dir(self, tmp_data_dir):
        tracker = ExperimentTracker(data_dir=tmp_data_dir)
        run_id = tracker.start_run(run_name="artifact_test")

        src_file = Path(tmp_data_dir) / "model.txt"
        src_file.write_text("model weights placeholder")

        tracker.log_artifact(str(src_file))

        artifact_path = Path(tmp_data_dir) / "default" / run_id / "artifacts" / "model.txt"
        assert artifact_path.exists()
        assert artifact_path.read_text() == "model weights placeholder"

    def test_log_artifact_raises_when_no_active_run(self, tmp_data_dir):
        tracker = ExperimentTracker(data_dir=tmp_data_dir)
        src_file = Path(tmp_data_dir) / "model.txt"
        src_file.write_text("data")
        with pytest.raises(RuntimeError, match="No active run"):
            tracker.log_artifact(str(src_file))

    def test_log_artifact_raises_when_file_not_found(self, tmp_data_dir):
        tracker = ExperimentTracker(data_dir=tmp_data_dir)
        tracker.start_run(run_name="missing_artifact_test")
        with pytest.raises(FileNotFoundError):
            tracker.log_artifact("/nonexistent/file.txt")

    def test_end_run_clears_active_run(self, tmp_data_dir):
        tracker = ExperimentTracker(data_dir=tmp_data_dir)
        tracker.start_run(run_name="end_test")
        tracker.end_run()
        assert tracker._active_run_id is None
        with pytest.raises(RuntimeError, match="No active run"):
            tracker.log_params({"key": "value"})

    def test_full_run_lifecycle(self, tmp_data_dir):
        tracker = ExperimentTracker(data_dir=tmp_data_dir, experiment_name="full_test")
        run_id = tracker.start_run(run_name="lifecycle_run")

        tracker.log_params({"model": "bert-base", "epochs": 3})
        tracker.log_metrics({"train_loss": 0.5})
        tracker.log_metrics({"val_loss": 0.4})

        src = Path(tmp_data_dir) / "config.yaml"
        src.write_text("key: value")
        tracker.log_artifact(str(src))

        tracker.end_run()

        run_dir = Path(tmp_data_dir) / "full_test" / run_id
        with open(run_dir / "params.json") as f:
            params = json.load(f)
        with open(run_dir / "metrics.json") as f:
            metrics = json.load(f)

        assert params == {"model": "bert-base", "epochs": 3}
        assert metrics == {"train_loss": 0.5, "val_loss": 0.4}
        assert (run_dir / "artifacts" / "config.yaml").exists()


class TestExperimentTrackerMLflowMode:
    """Tests for ExperimentTracker with MLflow delegation."""

    @pytest.fixture
    def mock_mlflow(self):
        with patch("proxy.app.model_evolution.experiment_tracker._MLFLOW_AVAILABLE", True), patch(
            "proxy.app.model_evolution.experiment_tracker.mlflow"
        ) as mock:
                mock.active_run.return_value = None
                mock.create_experiment.return_value = "exp-123"
                mock.start_run.return_value = MagicMock()
                mock.start_run.return_value.__enter__ = MagicMock(return_value=MagicMock())
                mock.start_run.return_value.__exit__ = MagicMock(return_value=False)
                mock.start_run.return_value.info.run_id = "mlflow-run-abc"
                yield mock

    def test_mlflow_mode_when_tracking_uri_provided(self, mock_mlflow):
        tracker = ExperimentTracker(tracking_uri="http://localhost:5000")
        assert tracker.local_mode is False
        assert tracker._tracking_uri == "http://localhost:5000"

    def test_start_run_delegates_to_mlflow(self, mock_mlflow):
        tracker = ExperimentTracker(tracking_uri="http://localhost:5000")
        run_id = tracker.start_run(run_name="mlflow_test")
        mock_mlflow.set_tracking_uri.assert_called_once_with("http://localhost:5000")
        mock_mlflow.start_run.assert_called_once()
        assert run_id == "mlflow-run-abc"

    def test_log_params_delegates_to_mlflow(self, mock_mlflow):
        tracker = ExperimentTracker(tracking_uri="http://localhost:5000")
        tracker.start_run(run_name="mlflow_test")
        tracker.log_params({"lr": 0.01})
        mock_mlflow.log_params.assert_called_once_with({"lr": 0.01})

    def test_log_metrics_delegates_to_mlflow(self, mock_mlflow):
        tracker = ExperimentTracker(tracking_uri="http://localhost:5000")
        tracker.start_run(run_name="mlflow_test")
        tracker.log_metrics({"acc": 0.99})
        mock_mlflow.log_metrics.assert_called_once_with({"acc": 0.99}, step=None)

    def test_log_metrics_step_delegates_to_mlflow(self, mock_mlflow):
        tracker = ExperimentTracker(tracking_uri="http://localhost:5000")
        tracker.start_run(run_name="mlflow_test")
        tracker.log_metrics({"acc": 0.99}, step=10)
        mock_mlflow.log_metrics.assert_called_once_with({"acc": 0.99}, step=10)

    def test_log_artifact_delegates_to_mlflow(self, mock_mlflow):
        tracker = ExperimentTracker(tracking_uri="http://localhost:5000")
        tracker.start_run(run_name="mlflow_test")
        tracker.log_artifact("/tmp/model.pt")
        mock_mlflow.log_artifact.assert_called_once_with("/tmp/model.pt")

    def test_end_run_delegates_to_mlflow(self, mock_mlflow):
        tracker = ExperimentTracker(tracking_uri="http://localhost:5000")
        tracker.start_run(run_name="mlflow_test")
        tracker.end_run()
        mock_mlflow.end_run.assert_called_once()

    def test_mlflow_unavailable_falls_back_to_local(self, tmp_path):
        with patch("proxy.app.model_evolution.experiment_tracker._MLFLOW_AVAILABLE", False):
            tracker = ExperimentTracker(
                tracking_uri="http://localhost:5000",
                data_dir=str(tmp_path),
            )
            assert tracker.local_mode is True
            run_id = tracker.start_run(run_name="fallback_run")
            assert run_id is not None
            tracker.log_params({"key": "val"})
            run_dir = tmp_path / "default" / run_id
            assert (run_dir / "params.json").exists()
            tracker.end_run()
