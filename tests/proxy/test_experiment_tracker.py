"""Tests for proxy/app/model_evolution/experiment_tracker.py — local-mode ExperimentTracker."""

import json
from unittest.mock import patch

import pytest

from proxy.app.model_evolution.experiment_tracker import ExperimentTracker, RunInfo


class TestRunInfo:
    """Tests for RunInfo dataclass."""

    def test_defaults(self):
        run = RunInfo(run_id="r1", experiment_name="exp")
        assert run.params == {}
        assert run.metrics == {}
        assert run.artifacts == []
        assert run.status == "running"
        assert run.start_time == 0.0
        assert run.end_time is None

    def test_custom_values(self):
        run = RunInfo(
            run_id="r1",
            experiment_name="exp",
            params={"lr": 0.01},
            metrics={"loss": 0.5},
            artifacts=["/path/to/model"],
            status="finished",
            start_time=100.0,
            end_time=200.0,
        )
        assert run.params["lr"] == 0.01
        assert run.status == "finished"


class TestExperimentTrackerLocalMode:
    """Tests for ExperimentTracker in local (no-MLflow) mode."""

    @pytest.fixture
    def tracker(self, tmp_path):
        """Create a local-mode tracker using tmp directory."""
        with patch("proxy.app.model_evolution.experiment_tracker.Path") as mock_path:
            data_dir = tmp_path / "experiments" / "test-exp"
            data_dir.mkdir(parents=True, exist_ok=True)
            mock_path.return_value = data_dir
            tracker = ExperimentTracker(experiment_name="test-exp")
            tracker._data_dir = data_dir
            yield tracker

    def test_init_local_mode_no_uri(self, tmp_path):
        """Tracker defaults to local mode when no tracking_uri."""
        tracker = ExperimentTracker(experiment_name="my-exp")
        assert tracker._local_mode is True

    def test_init_local_mode_mlflow_import_error(self, tmp_path):
        """Tracker falls back to local mode when mlflow is not available."""
        with patch.dict("sys.modules", {"mlflow": None}):
            tracker = ExperimentTracker(tracking_uri="http://mlflow:5000", experiment_name="exp")
            # Will be local mode because mlflow import fails
            assert tracker._local_mode is True

    def test_start_run(self, tracker):
        """start_run creates a new RunInfo and sets it as current."""
        run = tracker.start_run("my-run")
        assert isinstance(run, RunInfo)
        assert run.experiment_name == "test-exp"
        assert run.start_time > 0
        assert tracker._current_run is run
        assert run.run_id in tracker._runs

    def test_start_run_no_name(self, tracker):
        """start_run with no name still creates a run."""
        run = tracker.start_run()
        assert run.run_id

    def test_log_params(self, tracker):
        """log_params updates current run's params."""
        tracker.start_run()
        tracker.log_params({"lr": 0.01, "epochs": 3})
        assert tracker._current_run.params["lr"] == 0.01
        assert tracker._current_run.params["epochs"] == 3

    def test_log_params_no_run(self, tracker):
        """log_params is a no-op when no run is active."""
        tracker.log_params({"lr": 0.01})  # Should not raise

    def test_log_metrics(self, tracker):
        """log_metrics appends metrics with step info."""
        tracker.start_run()
        tracker.log_metrics({"loss": 0.5}, step=1)
        tracker.log_metrics({"loss": 0.4}, step=2)
        assert len(tracker._current_run.metrics["loss"]) == 2
        assert tracker._current_run.metrics["loss"][0]["value"] == 0.5
        assert tracker._current_run.metrics["loss"][1]["value"] == 0.4

    def test_log_metrics_no_run(self, tracker):
        """log_metrics is a no-op when no run is active."""
        tracker.log_metrics({"loss": 0.5})  # Should not raise

    def test_log_artifact(self, tracker):
        """log_artifact appends path to current run."""
        tracker.start_run()
        tracker.log_artifact("/path/to/model.bin")
        assert "/path/to/model.bin" in tracker._current_run.artifacts

    def test_log_artifact_no_run(self, tracker):
        """log_artifact is a no-op when no run is active."""
        tracker.log_artifact("/path")  # Should not raise

    def test_end_run(self, tracker):
        """end_run saves run to disk and clears current run."""
        run = tracker.start_run("test-run")
        tracker.log_params({"lr": 0.01})
        tracker.log_metrics({"loss": 0.5})
        tracker.end_run()

        assert tracker._current_run is None
        assert run.status == "finished"
        assert run.end_time is not None

        # Verify saved to disk
        saved_file = tracker._data_dir / f"{run.run_id}.json"
        assert saved_file.exists()
        data = json.loads(saved_file.read_text())
        assert data["run_id"] == run.run_id
        assert data["status"] == "finished"

    def test_end_run_no_run(self, tracker):
        """end_run is a no-op when no run is active."""
        tracker.end_run()  # Should not raise

    def test_get_run(self, tracker):
        """get_run returns a run by ID."""
        run = tracker.start_run()
        found = tracker.get_run(run.run_id)
        assert found is run

    def test_get_run_not_found(self, tracker):
        """get_run returns None for unknown ID."""
        assert tracker.get_run("nonexistent") is None

    def test_list_runs(self, tracker):
        """list_runs returns all tracked runs."""
        tracker.start_run("run-1")
        tracker.end_run()
        tracker.start_run("run-2")
        tracker.end_run()

        runs = tracker.list_runs()
        assert len(runs) == 2

    def test_list_runs_empty(self, tracker):
        """list_runs returns empty list when no runs."""
        assert tracker.list_runs() == []

    def test_multiple_runs_workflow(self, tracker):
        """Full workflow with multiple runs and params/metrics."""
        # Run 1
        r1 = tracker.start_run("run-1")
        tracker.log_params({"model": "bert-base"})
        tracker.log_metrics({"accuracy": 0.85}, step=1)
        tracker.log_metrics({"accuracy": 0.87}, step=2)
        tracker.log_artifact("/models/bert-base")
        tracker.end_run()

        # Run 2
        r2 = tracker.start_run("run-2")
        tracker.log_params({"model": "roberta-base"})
        tracker.log_metrics({"accuracy": 0.90}, step=1)
        tracker.end_run()

        runs = tracker.list_runs()
        assert len(runs) == 2
        assert r1.run_id != r2.run_id
