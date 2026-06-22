"""Experiment tracker: wraps MLflow API with local mode fallback."""

from dataclasses import dataclass, field
from pathlib import Path
import json
import time
import uuid


@dataclass
class RunInfo:
    run_id: str
    experiment_name: str
    params: dict = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)
    artifacts: list[str] = field(default_factory=list)
    status: str = "running"
    start_time: float = 0.0
    end_time: float | None = None


class ExperimentTracker:
    MLFLOW_AVAILABLE = False

    def __init__(self, tracking_uri: str | None = None, experiment_name: str = "default"):
        self.tracking_uri = tracking_uri
        self.experiment_name = experiment_name
        self._current_run: RunInfo | None = None
        self._runs: dict[str, RunInfo] = {}

        if tracking_uri:
            try:
                import mlflow
                mlflow.set_tracking_uri(tracking_uri)
                self._mlflow = mlflow
                ExperimentTracker.MLFLOW_AVAILABLE = True
                self._local_mode = False
            except ImportError:
                self._local_mode = True
        else:
            self._local_mode = True

        if self._local_mode:
            self._data_dir = Path("data/experiments") / experiment_name
            self._data_dir.mkdir(parents=True, exist_ok=True)

    def start_run(self, run_name: str | None = None) -> RunInfo:
        run_id = str(uuid.uuid4())[:8]
        run = RunInfo(
            run_id=run_id,
            experiment_name=self.experiment_name,
            start_time=time.time(),
        )
        self._current_run = run
        self._runs[run_id] = run

        if not self._local_mode and self.MLFLOW_AVAILABLE:
            self._mlflow.set_experiment(self.experiment_name)
            self._mlflow.start_run(run_name=run_name or f"run-{run_id}")

        return run

    def log_params(self, params: dict) -> None:
        if self._current_run:
            self._current_run.params.update(params)

    def log_metrics(self, metrics: dict, step: int | None = None) -> None:
        if self._current_run:
            for k, v in metrics.items():
                self._current_run.metrics.setdefault(k, []).append({"step": step or 0, "value": v})

    def log_artifact(self, local_path: str) -> None:
        if self._current_run:
            self._current_run.artifacts.append(local_path)

    def end_run(self) -> None:
        if self._current_run:
            self._current_run.end_time = time.time()
            self._current_run.status = "finished"
            if self._local_mode:
                self._save_run(self._current_run)
            self._current_run = None

    def get_run(self, run_id: str) -> RunInfo | None:
        return self._runs.get(run_id)

    def list_runs(self) -> list[RunInfo]:
        return list(self._runs.values())

    def _save_run(self, run: RunInfo) -> None:
        path = self._data_dir / f"{run.run_id}.json"
        with open(path, "w") as f:
            json.dump({
                "run_id": run.run_id,
                "experiment_name": run.experiment_name,
                "params": run.params,
                "metrics": run.metrics,
                "artifacts": run.artifacts,
                "status": run.status,
                "start_time": run.start_time,
                "end_time": run.end_time,
            }, f, indent=2)
