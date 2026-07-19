# tests/model_evolution/test_training_api.py
"""Smoke tests for the Model Evolution service endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    """Create a test client for the Model Evolution service."""
    from model_evolution_service.main import app

    return TestClient(app)


class TestHealthEndpoint:
    """Tests for the /health endpoint."""

    def test_health_returns_ok(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "model-evolution"

    def test_health_response_shape(self, client: TestClient) -> None:
        response = client.get("/health")
        data = response.json()
        assert "status" in data
        assert "service" in data
        assert "version" in data


class TestTrainingEndpoints:
    """Tests for training job endpoints."""

    def test_train_returns_job_id(self, client: TestClient) -> None:
        response = client.post(
            "/v1/admin/models/train",
            json={
                "trainer_type": "slm",
                "base_model": "bert-base-uncased",
                "profile": "ci",
                "epochs": 1,
                "batch_size": 1,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "job_id" in data
        assert data["trainer_type"] == "slm"
        assert data["status"] == "running"

    def test_train_invalid_trainer_type(self, client: TestClient) -> None:
        response = client.post(
            "/v1/admin/models/train",
            json={
                "trainer_type": "invalid_type",
                "base_model": "test",
            },
        )
        assert response.status_code == 422  # Validation error

    def test_train_status_not_found(self, client: TestClient) -> None:
        response = client.get("/v1/admin/models/status/nonexistent-job-id")
        assert response.status_code == 404

    def test_train_and_poll_status(self, client: TestClient) -> None:
        # Start a training job
        train_response = client.post(
            "/v1/admin/models/train",
            json={
                "trainer_type": "slm",
                "base_model": "bert-base-uncased",
                "profile": "ci",
                "epochs": 1,
                "batch_size": 1,
            },
        )
        assert train_response.status_code == 200
        job_id = train_response.json()["job_id"]

        # Poll status
        status_response = client.get(f"/v1/admin/models/status/{job_id}")
        assert status_response.status_code == 200
        status_data = status_response.json()
        assert status_data["job_id"] == job_id
        assert status_data["trainer_type"] == "slm"


class TestModelRegistryEndpoints:
    """Tests for model registry endpoints."""

    def test_list_models_empty(self, client: TestClient) -> None:
        response = client.get("/v1/admin/models")
        assert response.status_code == 200
        data = response.json()
        assert "models" in data

    def test_promote_nonexistent_model(self, client: TestClient) -> None:
        response = client.post(
            "/v1/admin/models/promote",
            json={
                "model_name": "nonexistent",
                "version": "1",
            },
        )
        assert response.status_code == 404

    def test_rollback_nonexistent_model(self, client: TestClient) -> None:
        response = client.post(
            "/v1/admin/models/rollback",
            json={"model_name": "nonexistent"},
        )
        assert response.status_code == 404

    def test_evaluate_model(self, client: TestClient) -> None:
        response = client.post(
            "/v1/admin/models/evaluate",
            json={
                "model_name": "test_model",
                "version": "1",
                "metrics": {
                    "accuracy": 0.95,
                    "weighted_f1": 0.90,
                    "mrr": 0.75,
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["model_name"] == "test_model"
        assert "status" in data
        assert "failures" in data
        assert "warnings" in data


class TestCanaryEndpoints:
    """Tests for canary deployment endpoints."""

    def test_canary_split(self, client: TestClient) -> None:
        response = client.post(
            "/v1/admin/models/canary/split",
            json={
                "model_name": "test_model",
                "traffic_split": 0.1,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["model_name"] == "test_model"
        assert data["traffic_split"] == 0.1

    def test_canary_status(self, client: TestClient) -> None:
        response = client.get("/v1/admin/models/canary/status")
        assert response.status_code == 200
        data = response.json()
        assert "canary_models" in data
