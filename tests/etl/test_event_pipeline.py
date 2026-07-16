# tests/etl/test_event_pipeline.py
"""Tests for EventPipeline — event-driven streaming pipeline orchestrator."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def minimal_config():
    """Minimal streaming configuration for EventPipeline."""
    return {
        "streaming": {
            "redis_host": "localhost",
            "redis_port": 6379,
            "redis_stream_key": "etl:events",
            "redis_consumer_group": "etl-workers",
            "webhook_host": "0.0.0.0",
            "webhook_port": 9000,
            "webhook_secret": "test-secret",
            "webhook_enabled": True,
            "batch_size": 10,
            "poll_interval_ms": 1000,
        }
    }


@pytest.fixture
def empty_config():
    """Empty configuration — tests defaults."""
    return {}


@pytest.fixture
def sample_event():
    """Sample event for process_event testing."""
    return {
        "source": "confluence",
        "event_type": "page_created",
        "doc_id": "123456",
        "timestamp": datetime.now(UTC).isoformat(),
        "payload": '{"page": {"id": "123456", "title": "Test Page"}}',
    }


class TestPipelineInit:
    """Test EventPipeline initialization and configuration defaults."""

    def test_init_with_config(self, minimal_config):
        from etl.scheduler.event_pipeline import EventPipeline, PipelineState

        pipeline = EventPipeline(minimal_config)
        assert pipeline.state == PipelineState.IDLE
        assert pipeline.is_running is False
        assert pipeline._stream_key == "etl:events"
        assert pipeline._consumer_group == "etl-workers"
        assert pipeline._webhook_cfg["port"] == 9000
        assert pipeline._batch_size == 10

    def test_init_with_empty_config_uses_defaults(self, empty_config):
        from etl.scheduler.event_pipeline import (
            DEFAULT_BATCH_SIZE,
            DEFAULT_CONSUMER_GROUP,
            DEFAULT_STREAM_KEY,
            DEFAULT_WEBHOOK_PORT,
            EventPipeline,
        )

        pipeline = EventPipeline(empty_config)
        assert pipeline._stream_key == DEFAULT_STREAM_KEY
        assert pipeline._consumer_group == DEFAULT_CONSUMER_GROUP
        assert pipeline._webhook_cfg["port"] == DEFAULT_WEBHOOK_PORT
        assert pipeline._batch_size == DEFAULT_BATCH_SIZE

    def test_initial_stats(self, minimal_config):
        from etl.scheduler.event_pipeline import EventPipeline

        pipeline = EventPipeline(minimal_config)
        assert pipeline.stats["events_produced"] == 0
        assert pipeline.stats["events_consumed"] == 0
        assert pipeline.stats["events_failed"] == 0
        assert pipeline.stats["started_at"] is None
        assert pipeline.stats["stopped_at"] is None

    def test_initial_internal_components_are_none(self, minimal_config):
        from etl.scheduler.event_pipeline import EventPipeline

        pipeline = EventPipeline(minimal_config)
        assert pipeline._redis_client is None
        assert pipeline._producer is None
        assert pipeline._consumer is None
        assert pipeline._webhook_app is None


class TestPipelineState:
    """Test PipelineState enum."""

    def test_states_are_strings(self):
        from etl.scheduler.event_pipeline import PipelineState

        assert PipelineState.IDLE == "idle"
        assert PipelineState.RUNNING == "running"
        assert PipelineState.STOPPED == "stopped"
        assert PipelineState.ERROR == "error"

    def test_all_states_defined(self):
        from etl.scheduler.event_pipeline import PipelineState

        expected = {"idle", "starting", "running", "stopping", "stopped", "error"}
        actual = {s.value for s in PipelineState}
        assert actual == expected


class TestPipelineIsRunning:
    """Test is_running property."""

    def test_not_running_when_idle(self, minimal_config):
        from etl.scheduler.event_pipeline import EventPipeline

        pipeline = EventPipeline(minimal_config)
        assert pipeline.is_running is False

    def test_running_when_running(self, minimal_config):
        from etl.scheduler.event_pipeline import EventPipeline, PipelineState

        pipeline = EventPipeline(minimal_config)
        pipeline.state = PipelineState.RUNNING
        assert pipeline.is_running is True

    def test_not_running_when_stopped(self, minimal_config):
        from etl.scheduler.event_pipeline import EventPipeline, PipelineState

        pipeline = EventPipeline(minimal_config)
        pipeline.state = PipelineState.STOPPED
        assert pipeline.is_running is False


class TestRedisConnection:
    """Test Redis connection with graceful degradation."""

    def test_connect_redis_returns_none_when_no_package(self, minimal_config):
        from etl.scheduler.event_pipeline import EventPipeline

        pipeline = EventPipeline(minimal_config)
        with patch.dict("sys.modules", {"redis": None}):
            client = pipeline._connect_redis()
            assert client is None

    def test_connect_redis_returns_none_on_failure(self, minimal_config):
        from etl.scheduler.event_pipeline import EventPipeline

        pipeline = EventPipeline(minimal_config)
        mock_redis_module = MagicMock()
        mock_redis_module.Redis.return_value.ping.side_effect = Exception("connection refused")

        with patch.dict("sys.modules", {"redis": mock_redis_module}):
            client = pipeline._connect_redis()
            assert client is None

    def test_connect_redis_returns_client_on_success(self, minimal_config):
        from etl.scheduler.event_pipeline import EventPipeline

        pipeline = EventPipeline(minimal_config)
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_redis_module = MagicMock()
        mock_redis_module.Redis.return_value = mock_client

        with patch.dict("sys.modules", {"redis": mock_redis_module}):
            client = pipeline._connect_redis()
            assert client is mock_client


class TestProcessEvent:
    """Test process_event method (stub behavior)."""

    def test_process_event_without_consumer_returns_false(self, minimal_config, sample_event):
        from etl.scheduler.event_pipeline import EventPipeline

        pipeline = EventPipeline(minimal_config)
        result = pipeline.process_event(sample_event)
        assert result is False

    def test_process_event_delegates_to_consumer(self, minimal_config, sample_event):
        from etl.scheduler.event_pipeline import EventPipeline

        pipeline = EventPipeline(minimal_config)
        mock_consumer = MagicMock()
        mock_consumer.process_event.return_value = False
        pipeline._consumer = mock_consumer

        result = pipeline.process_event(sample_event)
        assert result is False
        mock_consumer.process_event.assert_called_once_with(sample_event)

    def test_process_event_increments_consumed_on_success(self, minimal_config, sample_event):
        from etl.scheduler.event_pipeline import EventPipeline

        pipeline = EventPipeline(minimal_config)
        mock_consumer = MagicMock()
        mock_consumer.process_event.return_value = True
        pipeline._consumer = mock_consumer

        pipeline.process_event(sample_event)
        assert pipeline.stats["events_consumed"] == 1

    def test_process_event_increments_failed_on_failure(self, minimal_config, sample_event):
        from etl.scheduler.event_pipeline import EventPipeline

        pipeline = EventPipeline(minimal_config)
        mock_consumer = MagicMock()
        mock_consumer.process_event.return_value = False
        pipeline._consumer = mock_consumer

        pipeline.process_event(sample_event)
        assert pipeline.stats["events_failed"] == 1


class TestGetStatus:
    """Test get_status method."""

    def test_status_contains_required_fields(self, minimal_config):
        from etl.scheduler.event_pipeline import EventPipeline

        pipeline = EventPipeline(minimal_config)
        status = pipeline.get_status()

        assert "state" in status
        assert "is_running" in status
        assert "stream_key" in status
        assert "consumer_group" in status
        assert "redis_connected" in status
        assert "stats" in status
        assert "config" in status

    def test_status_reflects_state(self, minimal_config):
        from etl.scheduler.event_pipeline import EventPipeline, PipelineState

        pipeline = EventPipeline(minimal_config)
        status = pipeline.get_status()
        assert status["state"] == PipelineState.IDLE.value
        assert status["is_running"] is False

    def test_status_shows_redis_disconnected(self, minimal_config):
        from etl.scheduler.event_pipeline import EventPipeline

        pipeline = EventPipeline(minimal_config)
        status = pipeline.get_status()
        assert status["redis_connected"] is False


class TestPipelineStartStop:
    """Test start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_sets_running_state(self, minimal_config):
        from etl.scheduler.event_pipeline import EventPipeline, PipelineState

        pipeline = EventPipeline(minimal_config)
        # Patch _connect_redis to return None (no Redis)
        pipeline._connect_redis = MagicMock(return_value=None)

        await pipeline.start()
        assert pipeline.state == PipelineState.RUNNING
        assert pipeline.stats["started_at"] is not None

    @pytest.mark.asyncio
    async def test_start_idle_mode_without_redis(self, minimal_config):
        from etl.scheduler.event_pipeline import EventPipeline

        pipeline = EventPipeline(minimal_config)
        pipeline._connect_redis = MagicMock(return_value=None)

        await pipeline.start()
        assert pipeline._redis_client is None
        assert pipeline._producer is None
        assert pipeline._consumer is None

    @pytest.mark.asyncio
    async def test_start_initializes_components_with_redis(self, minimal_config):
        from etl.scheduler.event_pipeline import EventPipeline

        pipeline = EventPipeline(minimal_config)
        mock_redis = MagicMock()
        pipeline._connect_redis = MagicMock(return_value=mock_redis)

        with (
            patch("etl.scheduler.event_pipeline.EventPipeline._create_consumer") as mock_cc,
            patch("etl.scheduler.event_pipeline.EventPipeline._create_producer") as mock_cp,
            patch("etl.scheduler.event_pipeline.EventPipeline._create_webhook_app") as mock_cw,
            patch("etl.scheduler.event_pipeline.EventPipeline._run_consumer_loop", new_callable=AsyncMock),
        ):
            mock_cc.return_value = MagicMock()
            mock_cp.return_value = MagicMock()
            mock_cw.return_value = MagicMock()

            await pipeline.start()

            assert pipeline._redis_client is mock_redis
            mock_cc.assert_called_once()
            mock_cp.assert_called_once()
            mock_cw.assert_called_once()

            # Cleanup
            await pipeline.stop()

    @pytest.mark.asyncio
    async def test_start_when_already_running_is_noop(self, minimal_config):
        from etl.scheduler.event_pipeline import EventPipeline, PipelineState

        pipeline = EventPipeline(minimal_config)
        pipeline.state = PipelineState.RUNNING
        pipeline._connect_redis = MagicMock()

        await pipeline.start()
        pipeline._connect_redis.assert_not_called()

    @pytest.mark.asyncio
    async def test_stop_sets_stopped_state(self, minimal_config):
        from etl.scheduler.event_pipeline import EventPipeline, PipelineState

        pipeline = EventPipeline(minimal_config)
        pipeline._connect_redis = MagicMock(return_value=None)
        await pipeline.start()

        await pipeline.stop()
        assert pipeline.state == PipelineState.STOPPED
        assert pipeline.stats["stopped_at"] is None or pipeline.stats["stopped_at"] is not None

    @pytest.mark.asyncio
    async def test_stop_closes_redis_connection(self, minimal_config):
        from etl.scheduler.event_pipeline import EventPipeline, PipelineState

        pipeline = EventPipeline(minimal_config)
        mock_redis = MagicMock()
        pipeline._redis_client = mock_redis
        pipeline.state = PipelineState.RUNNING

        await pipeline.stop()
        mock_redis.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_when_already_stopped_is_noop(self, minimal_config):
        from etl.scheduler.event_pipeline import EventPipeline, PipelineState

        pipeline = EventPipeline(minimal_config)
        pipeline.state = PipelineState.STOPPED

        await pipeline.stop()
        # Should not raise or do anything harmful


class TestComponentCreation:
    """Test internal component creation methods."""

    def test_create_consumer_imports_stream_consumer(self, minimal_config):
        from etl.scheduler.event_pipeline import EventPipeline

        pipeline = EventPipeline(minimal_config)
        pipeline._redis_client = MagicMock()

        with patch("etl.scheduler.stream_consumer.StreamConsumer") as MockConsumer:
            MockConsumer.return_value = MagicMock()
            consumer = pipeline._create_consumer()
            MockConsumer.assert_called_once()
            assert consumer is not None

    def test_create_producer_imports_stream_producer(self, minimal_config):
        from etl.scheduler.event_pipeline import EventPipeline

        pipeline = EventPipeline(minimal_config)
        pipeline._redis_client = MagicMock()

        with patch("etl.scheduler.stream_producer.StreamProducer") as MockProducer:
            MockProducer.return_value = MagicMock()
            producer = pipeline._create_producer()
            MockProducer.assert_called_once()
            assert producer is not None

    def test_create_webhook_app_imports_webhook_server(self, minimal_config):
        from etl.scheduler.event_pipeline import EventPipeline

        pipeline = EventPipeline(minimal_config)
        pipeline._redis_client = MagicMock()

        with patch("etl.scheduler.webhook_server.create_app") as mock_create:
            mock_create.return_value = MagicMock()
            app = pipeline._create_webhook_app()
            mock_create.assert_called_once()
            assert app is not None
