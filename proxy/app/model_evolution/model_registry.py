"""Model Registry — versioned model management with JSON persistence.

Air-gapped compatible: stores state as a local JSON file.
Supports staging → canary → production promotion flow and rollback.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass
class ModelVersion:
    """A versioned model artifact with metrics and lifecycle status.

    Status transitions:
        staging → canary → production
        production → archived (on promote of newer version)
        any → archived (manual)
    """

    name: str
    version: str
    artifact_path: str
    metrics: dict[str, float] = field(default_factory=dict)
    status: str = "staging"
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(UTC).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "artifact_path": self.artifact_path,
            "metrics": self.metrics,
            "status": self.status,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ModelVersion:
        return cls(
            name=d["name"],
            version=d["version"],
            artifact_path=d["artifact_path"],
            metrics=d.get("metrics", {}),
            status=d.get("status", "staging"),
            created_at=d.get("created_at", ""),
        )


_STATUS_ORDER = {"staging": 0, "canary": 1, "production": 2, "archived": 3}


class ModelRegistry:
    """Manages model versions with JSON file persistence.

    Stores registry state as a JSON file on the local filesystem,
    making it suitable for air-gapped environments.

    Lifecycle:
        register() → staging
        promote() → staging → canary → production
        rollback() → revert to previous production version

    Thread-safe for concurrent access from a single process.
    """

    def __init__(self, store_path: str | None = None) -> None:
        if store_path is None:
            store_path = os.getenv("MODEL_REGISTRY_PATH", "./data/model_registry.json")
        self._store_path = Path(store_path)
        self._lock = threading.RLock()
        self._models: dict[str, dict[str, ModelVersion]] = {}
        self._load()

    def register(
        self,
        name: str,
        artifact_path: str,
        metrics: dict[str, float] | None = None,
        version: str | None = None,
    ) -> ModelVersion:
        """Register a new model version. Defaults to staging status.

        If version is not specified, auto-increments from existing versions.
        """
        if not name:
            raise ValueError("model name must not be empty")
        if not artifact_path:
            raise ValueError("artifact_path must not be empty")

        with self._lock:
            versions = self._models.setdefault(name, {})
            if version is None:
                version = str(len(versions) + 1)
            if version in versions:
                raise ValueError(f"Version '{version}' of model '{name}' already exists")
            mv = ModelVersion(
                name=name,
                version=version,
                artifact_path=artifact_path,
                metrics=metrics or {},
                status="staging",
            )
            versions[version] = mv
            self._save()
            return mv

    def get(self, name: str, version: str) -> ModelVersion:
        """Get a specific model version."""
        with self._lock:
            if name not in self._models:
                raise KeyError(f"Model '{name}' not found in registry")
            if version not in self._models[name]:
                raise KeyError(f"Version '{version}' not found for model '{name}'")
            return self._models[name][version]

    def get_latest_production(self, name: str) -> ModelVersion | None:
        """Get the current production version of a model, or None."""
        with self._lock:
            if name not in self._models:
                return None
            for mv in sorted(self._models[name].values(), key=lambda v: int(v.version), reverse=True):
                if mv.status == "production":
                    return mv
            return None

    def get_latest(self, name: str) -> ModelVersion | None:
        """Get the latest registered version of a model (any status)."""
        with self._lock:
            if name not in self._models:
                return None
            versions = self._models[name]
            if not versions:
                return None
            return versions[max(versions.keys(), key=int)]

    def list_models(self) -> list[str]:
        """List all registered model names."""
        with self._lock:
            return sorted(self._models.keys())

    def list_versions(self, name: str) -> list[ModelVersion]:
        """List all versions of a model, sorted by version number."""
        with self._lock:
            if name not in self._models:
                return []
            return sorted(
                self._models[name].values(),
                key=lambda v: int(v.version),
            )

    def list_by_status(self, name: str, status: str) -> list[ModelVersion]:
        """List versions of a model filtered by status."""
        return [v for v in self.list_versions(name) if v.status == status]

    def promote(self, name: str, version: str) -> ModelVersion:
        """Advance a model version through the promotion flow.

        Status transitions:
            staging → canary
            canary → production (archives previous production)
            production → production (no-op)
            archived → archived (no-op)
        """
        with self._lock:
            mv = self._get_or_raise(name, version)
            current_status = mv.status

            if current_status == "staging":
                mv.status = "canary"
            elif current_status == "canary":
                self._archive_previous_production(name, version)
                mv.status = "production"
            elif current_status == "production" or current_status == "archived":
                pass

            self._save()
            return mv

    def rollback(self, name: str) -> ModelVersion:
        """Revert to the previous production version.

        Finds the current production version, archives it, and restores
        the most recent archived version back to production.
        """
        with self._lock:
            if name not in self._models:
                raise KeyError(f"Model '{name}' not found in registry")

            current = self.get_latest_production(name)
            if current is None:
                raise ValueError(f"No current production version for model '{name}'")

            previous = self._find_previous_production(name, current.version)
            if previous is None:
                raise ValueError(f"No previous production version to roll back to for model '{name}'")

            current.status = "archived"
            previous.status = "production"
            self._save()
            return previous

    def update_metrics(self, name: str, version: str, metrics: dict[str, float]) -> None:
        """Update metrics for a model version."""
        with self._lock:
            mv = self._get_or_raise(name, version)
            mv.metrics = dict(metrics)
            self._save()

    def delete(self, name: str, version: str) -> None:
        """Remove a model version from the registry."""
        with self._lock:
            if name not in self._models:
                raise KeyError(f"Model '{name}' not found in registry")
            if version not in self._models[name]:
                raise KeyError(f"Version '{version}' not found for model '{name}'")
            del self._models[name][version]
            if not self._models[name]:
                del self._models[name]
            self._save()

    def _get_or_raise(self, name: str, version: str) -> ModelVersion:
        if name not in self._models:
            raise KeyError(f"Model '{name}' not found in registry")
        if version not in self._models[name]:
            raise KeyError(f"Version '{version}' not found for model '{name}'")
        return self._models[name][version]

    def _archive_previous_production(self, name: str, new_version: str) -> None:
        """Archive the current production version when promoting a new one."""
        for mv in self._models[name].values():
            if mv.status == "production" and mv.version != new_version:
                mv.status = "archived"

    def _find_previous_production(self, name: str, current_version: str) -> ModelVersion | None:
        """Find the most recent archived version (previous production)."""
        candidates = [
            mv for mv in self._models[name].values() if mv.status == "archived" and mv.version != current_version
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda v: int(v.version))

    def _load(self) -> None:
        """Load registry state from JSON file."""
        try:
            if self._store_path.exists():
                with open(self._store_path, encoding="utf-8") as f:
                    data = json.load(f)
                models: dict[str, dict[str, ModelVersion]] = {}
                for model_name, versions_data in data.get("models", {}).items():
                    models[model_name] = {}
                    for ver_str, ver_data in versions_data.items():
                        models[model_name][ver_str] = ModelVersion.from_dict(ver_data)
                self._models = models
            else:
                self._models = {}
        except (json.JSONDecodeError, PermissionError):
            self._models = {}

    def _save(self) -> None:
        """Save registry state to JSON file."""
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "models": {
                name: {ver: mv.to_dict() for ver, mv in versions.items()} for name, versions in self._models.items()
            }
        }
        tmp_path = self._store_path.with_suffix(self._store_path.suffix + ".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, self._store_path)
