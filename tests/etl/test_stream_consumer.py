# tests/etl/test_stream_consumer.py
"""Tests for Redis Streams consumer: event processing, crash recovery, graceful degradation."""

import json
import pytest
from unittest.mock import MagicMock, patch, call
from datetime import datetime, timezone


@pytest.fixture
def mock_redis_client():
    client = MagicMock()
    client.ping = MagicMock(return_value=True)
    client.xgroup_create = MagicMock(return_value=True)
    client.xreadgroup = MagicMock(return_value=[])
    client.xack = MagicMock(return_value=1)
    client.xpending = MagicMock(return_value={"pending": 0})
    client.xautoclaim = MagicMock(return_value=([], []))
    client.xdel = MagicMock(return_value=1)
    return client


@pytest.fixture
def sample_confluence_event():
    return {
        "source": "confluence",
        "event_type": "page_created",
        "doc_id": "123456",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": json.dumps({
            "event": "page_created",
            "page": {
                "id": "123456",
                "title": "Test Page",
                "space": {"key": "DEV"},
                "body": {"storage": {"value": "<p>Test content</p>"}},
            },
        }),
    }


@pytest.fixture
def sample_gitlab_event():
    return {
        "source": "gitlab",
        "event_type": "push",
        "doc_id": "42",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": json.dumps({
            "object_kind": "push",
            "commits": [{"id": "abc123", "message": "Test commit"}],
        }),
    }


def _make_stream_message(msg_id: str, event: dict) -> list:
    """Build Redis Streams message format: [[stream, [(msg_id, fields)]], ...]"""
    return [["etl:events", [(msg_id.encode() if isinstance(msg_id, str) else msg_id, event)]]]


class TestConsumerInit:
    def test_consumer_creates_group(self, mock_redis_client):
        from etl.scheduler.stream_consumer import StreamConsumer

        consumer = StreamConsumer(
            redis_client=mock_redis_client,
            stream_key="etl:events",
            consumer_group="etl-workers",
        )
        assert consumer.stream_key == "etl:events"
        assert consumer.consumer_group == "etl-workers"

    def test_consumer_graceful_init_without_redis(self):
        from etl.scheduler.stream_consumer import StreamConsumer

        consumer = StreamConsumer(redis_client=None)
        assert consumer.redis is None


class TestEventProcessing:
    def test_process_confluence_created_event(self, mock_redis_client, sample_confluence_event):
        from etl.scheduler.stream_consumer import StreamConsumer

        consumer = StreamConsumer(redis_client=mock_redis_client)
        result = consumer.process_event(sample_confluence_event)
        assert result is True

    def test_process_gitlab_push_event(self, mock_redis_client, sample_gitlab_event):
        from etl.scheduler.stream_consumer import StreamConsumer

        consumer = StreamConsumer(redis_client=mock_redis_client)
        result = consumer.process_event(sample_gitlab_event)
        assert result is True

    def test_process_event_invalid_returns_false(self, mock_redis_client):
        from etl.scheduler.stream_consumer import StreamConsumer

        consumer = StreamConsumer(redis_client=mock_redis_client)
        result = consumer.process_event({"invalid": "event"})
        assert result is False

    def test_process_event_missing_source_logs_warning(self, mock_redis_client, caplog):
        from etl.scheduler.stream_consumer import StreamConsumer

        consumer = StreamConsumer(redis_client=mock_redis_client)
        consumer.process_event({"event_type": "unknown", "doc_id": "1", "payload": "{}"})
        assert any("Unknown source" in rec.message for rec in caplog.records)


class TestStreamProcessing:
    def test_consume_pending_messages(self, mock_redis_client, sample_confluence_event):
        from etl.scheduler.stream_consumer import StreamConsumer

        msg_id = "1719000000000-0"
        mock_redis_client.xreadgroup.return_value = _make_stream_message(
            msg_id, sample_confluence_event
        )

        consumer = StreamConsumer(redis_client=mock_redis_client)
        processed = consumer.consume_batch(block_ms=100)
        assert processed == 1
        mock_redis_client.xreadgroup.assert_called_once()
        mock_redis_client.xack.assert_called_once_with("etl:events", "etl-workers", msg_id)

    def test_consume_empty_stream(self, mock_redis_client):
        from etl.scheduler.stream_consumer import StreamConsumer

        mock_redis_client.xreadgroup.return_value = []
        consumer = StreamConsumer(redis_client=mock_redis_client)
        processed = consumer.consume_batch(block_ms=100)
        assert processed == 0

    def test_consume_multiple_messages(self, mock_redis_client):
        from etl.scheduler.stream_consumer import StreamConsumer

        event1 = {
            "source": "confluence",
            "event_type": "page_created",
            "doc_id": "1",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": "{}",
        }
        event2 = {
            "source": "gitlab",
            "event_type": "push",
            "doc_id": "2",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": "{}",
        }
        mock_redis_client.xreadgroup.return_value = [
            [
                "etl:events",
                [
                    (b"1719000000000-0", event1),
                    (b"1719000000000-1", event2),
                ],
            ]
        ]

        consumer = StreamConsumer(redis_client=mock_redis_client)
        processed = consumer.consume_batch(block_ms=100)
        assert processed == 2
        assert mock_redis_client.xack.call_count == 2

    def test_acknowledge_after_success(self, mock_redis_client, sample_confluence_event):
        from etl.scheduler.stream_consumer import StreamConsumer

        msg_id = b"1719000000000-0"
        mock_redis_client.xreadgroup.return_value = [
            ["etl:events", [(msg_id, sample_confluence_event)]]
        ]

        consumer = StreamConsumer(redis_client=mock_redis_client)
        consumer.consume_batch(block_ms=100)
        mock_redis_client.xack.assert_called_with("etl:events", "etl-workers", msg_id.decode())

    def test_no_acknowledge_on_failure(self, mock_redis_client):
        from etl.scheduler.stream_consumer import StreamConsumer

        bad_event = {"invalid": True}
        mock_redis_client.xreadgroup.return_value = [
            ["etl:events", [(b"1719000000000-0", bad_event)]]
        ]

        consumer = StreamConsumer(redis_client=mock_redis_client)
        consumer.consume_batch(block_ms=100)
        mock_redis_client.xack.assert_not_called()


class TestCrashRecovery:
    def test_claim_pending_on_startup(self, mock_redis_client):
        from etl.scheduler.stream_consumer import StreamConsumer

        mock_redis_client.xpending.return_value = {"pending": 2}
        consumer = StreamConsumer(redis_client=mock_redis_client)
        claimed = consumer.claim_pending()
        assert claimed >= 0
        mock_redis_client.xautoclaim.assert_called_once()

    def test_no_pending_messages(self, mock_redis_client):
        from etl.scheduler.stream_consumer import StreamConsumer

        mock_redis_client.xpending.return_value = {"pending": 0}
        consumer = StreamConsumer(redis_client=mock_redis_client)
        claimed = consumer.claim_pending()
        assert claimed == 0
        mock_redis_client.xautoclaim.assert_not_called()

    def test_consumer_stop_signal(self, mock_redis_client):
        from etl.scheduler.stream_consumer import StreamConsumer

        consumer = StreamConsumer(redis_client=mock_redis_client)
        assert consumer.running is True
        consumer.stop()
        assert consumer.running is False


class TestConsumerGracefulDegradation:
    def test_consume_batch_no_redis(self):
        from etl.scheduler.stream_consumer import StreamConsumer

        consumer = StreamConsumer(redis_client=None)
        processed = consumer.consume_batch()
        assert processed == 0

    def test_redis_error_returns_zero(self, mock_redis_client):
        from etl.scheduler.stream_consumer import StreamConsumer

        mock_redis_client.xreadgroup.side_effect = Exception("connection lost")
        consumer = StreamConsumer(redis_client=mock_redis_client)
        processed = consumer.consume_batch(block_ms=100)
        assert processed == 0
