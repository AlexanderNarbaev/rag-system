"""Tests for proxy/app/shared/dlq.py — Dead Letter Queue."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

import pytest

from proxy.app.shared.dlq import DeadLetterQueue


@pytest.fixture(autouse=True)
def _reset_dlq():
    """Reset DLQ instances between tests."""
    DeadLetterQueue.reset_all()
    yield
    DeadLetterQueue.reset_all()


@pytest.fixture
def temp_db_path():
    """Create a temporary database path for isolated tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir) / "test_dlq.db"


@pytest.fixture
def dlq(temp_db_path):
    """Create a fresh DLQ instance per test."""
    return DeadLetterQueue("test_queue", db_path=temp_db_path, max_retries=3, backoff_base=0.01)


# ── Initialization ───────────────────────────────────────────────────────────


class TestDLQInit:
    """Test DeadLetterQueue initialization and configuration."""

    def test_creates_db_file(self, temp_db_path):
        dlq = DeadLetterQueue("init_test", db_path=temp_db_path)
        assert temp_db_path.exists()
        dlq.close()

    def test_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "nested" / "deep" / "dlq.db"
            dlq = DeadLetterQueue("nested", db_path=db_path)
            assert db_path.exists()
            dlq.close()

    def test_default_max_retries(self, temp_db_path):
        dlq = DeadLetterQueue("defaults", db_path=temp_db_path)
        assert dlq.max_retries == 3
        dlq.close()

    def test_custom_max_retries(self, temp_db_path):
        dlq = DeadLetterQueue("custom", db_path=temp_db_path, max_retries=5)
        assert dlq.max_retries == 5
        dlq.close()

    def test_custom_backoff_base(self, temp_db_path):
        dlq = DeadLetterQueue("backoff", db_path=temp_db_path, backoff_base=3.0)
        assert dlq.backoff_base == 3.0
        dlq.close()

    def test_queue_name_preserved(self, dlq):
        assert dlq.queue_name == "test_queue"

    def test_default_db_path(self):
        dlq = DeadLetterQueue("default_path")
        assert dlq.db_path.name == "dlq_default_path.db"
        dlq.clear()
        dlq.close()
        dlq.db_path.unlink(missing_ok=True)


# ── Add / Get ────────────────────────────────────────────────────────────────


class TestDLQAdd:
    """Test add() and get() operations."""

    def test_add_returns_message_id(self, dlq):
        msg_id = dlq.add({"key": "value"}, error="test error")
        assert msg_id > 0

    def test_add_increments_ids(self, dlq):
        id1 = dlq.add({"n": 1}, error="e1")
        id2 = dlq.add({"n": 2}, error="e2")
        id3 = dlq.add({"n": 3}, error="e3")
        assert id2 == id1 + 1
        assert id3 == id2 + 1

    def test_get_returns_none_for_missing(self, dlq):
        assert dlq.get(99999) is None

    def test_get_returns_message(self, dlq):
        msg_id = dlq.add({"query": "What is RAG?"}, error="timeout")
        msg = dlq.get(msg_id)
        assert msg is not None
        assert msg.payload == {"query": "What is RAG?"}
        assert msg.error == "timeout"
        assert msg.status == "pending"

    def test_add_preserves_payload_types(self, dlq):
        payload = {
            "str_val": "hello",
            "int_val": 42,
            "float_val": 3.14,
            "list_val": [1, 2, 3],
            "nested": {"a": {"b": "c"}},
        }
        msg_id = dlq.add(payload, error="type_test")
        msg = dlq.get(msg_id)
        assert msg.payload == payload

    def test_add_with_metadata(self, dlq):
        msg_id = dlq.add({"data": "test"}, error="e", metadata={"source": "retrieval", "trace_id": "abc123"})
        msg = dlq.get(msg_id)
        assert msg.metadata == {"source": "retrieval", "trace_id": "abc123"}

    def test_add_with_default_error(self, dlq):
        msg_id = dlq.add({"x": 1})
        msg = dlq.get(msg_id)
        assert msg.error == ""

    def test_add_per_message_max_retries(self, dlq):
        msg_id = dlq.add({"data": "x"}, max_retries=10)
        msg = dlq.get(msg_id)
        assert msg.max_retries == 10


# ── Ack / Nack / Retry lifecycle ─────────────────────────────────────────────


class TestDLQLifecycle:
    """Test message lifecycle: ack, nack, retry."""

    def test_ack_removes_message(self, dlq):
        msg_id = dlq.add({"data": "removable"})
        assert dlq.ack(msg_id) is True
        assert dlq.get(msg_id) is None

    def test_ack_nonexistent_returns_false(self, dlq):
        assert dlq.ack(99999) is False

    def test_nack_increments_retry_count(self, dlq):
        msg_id = dlq.add({"data": "retryable"}, error="first_fail")
        dlq.nack(msg_id, error="second_fail")
        msg = dlq.get(msg_id)
        assert msg.retry_count == 1
        assert msg.status == "pending"

    def test_nack_exhausted_becomes_dead(self, dlq):
        msg_id = dlq.add({"data": "doomed"}, error="e1", max_retries=2)
        dlq.nack(msg_id, error="e2")
        msg = dlq.get(msg_id)
        assert msg.retry_count == 1
        assert msg.status == "pending"

        dlq.nack(msg_id, error="e3")
        msg = dlq.get(msg_id)
        assert msg.retry_count == 2
        assert msg.status == "dead"

    def test_nack_nonexistent_returns_false(self, dlq):
        assert dlq.nack(99999) is False

    def test_retry_processes_all_pending(self, dlq):
        dlq.add({"name": "msg1"}, error="e1")
        dlq.add({"name": "msg2"}, error="e2")
        dlq.add({"name": "msg3"}, error="e3")

        processed = []

        def handler(payload):
            processed.append(payload["name"])

        result = dlq.retry(handler)
        assert result["processed"] == 3
        assert result["failed"] == 0
        assert result["total"] == 3
        assert sorted(processed) == ["msg1", "msg2", "msg3"]

    def test_retry_handles_failures(self, dlq):
        dlq.add({"name": "bad"}, error="e1")
        dlq.add({"name": "good"}, error="e2")

        processed = []

        def handler(payload):
            if payload["name"] == "bad":
                raise ValueError("still failing")
            processed.append(payload["name"])

        result = dlq.retry(handler)
        assert result["total"] == 2
        assert result["processed"] == 1
        assert result["failed"] == 1
        assert processed == ["good"]

    def test_retry_with_backoff(self, dlq):
        msg_id = dlq.add({"data": "backoff_test"}, error="e1")
        dlq.nack(msg_id, error="e2")
        msg = dlq.get(msg_id)
        assert msg.next_retry_at > msg.created_at

    def test_process_returns_pending_messages(self, dlq):
        dlq.add({"n": 1}, error="e1")
        dlq.add({"n": 2}, error="e2")
        msgs = dlq.process()
        assert len(msgs) == 2
        assert all(m.status == "pending" for m in msgs)

    def test_process_does_not_change_status(self, dlq):
        msg_id = dlq.add({"data": "stable"})
        msgs = dlq.process()
        assert msgs[0].status == "pending"
        assert dlq.get(msg_id).status == "pending"

    def test_dead_returns_dead_messages(self, dlq):
        msg_id = dlq.add({"data": "gone"}, error="e1", max_retries=1)
        dlq.nack(msg_id)
        dead_msgs = dlq.dead()
        assert len(dead_msgs) == 1
        assert dead_msgs[0].status == "dead"


# ── Stats / Clear / Requeue ──────────────────────────────────────────────────


class TestDLQOperations:
    """Test stats, clear, and requeue operations."""

    def test_stats_empty_queue(self, dlq):
        s = dlq.stats()
        assert s == {"total": 0, "pending": 0, "failed": 0, "dead": 0}

    def test_stats_with_messages(self, dlq):
        dlq.add({"n": 1}, error="e1")
        dlq.add({"n": 2}, error="e2")
        dead_id = dlq.add({"n": 3}, error="e3", max_retries=1)
        dlq.nack(dead_id)
        s = dlq.stats()
        assert s["total"] == 3
        assert s["pending"] == 2
        assert s["dead"] == 1

    def test_clear_all(self, dlq):
        dlq.add({"n": 1})
        dlq.add({"n": 2})
        assert dlq.clear() == 2
        assert dlq.stats()["total"] == 0

    def test_clear_by_status(self, dlq):
        dlq.add({"n": 1})
        dead_id = dlq.add({"n": 2}, max_retries=1)
        dlq.nack(dead_id)
        assert dlq.clear(status="dead") == 1
        assert dlq.stats()["total"] == 1
        assert dlq.stats()["pending"] == 1

    def test_requeue_dead_message(self, dlq):
        msg_id = dlq.add({"data": "revive"}, max_retries=1)
        dlq.nack(msg_id)
        assert dlq.get(msg_id).status == "dead"

        assert dlq.requeue(msg_id) is True
        msg = dlq.get(msg_id)
        assert msg.status == "pending"
        assert msg.retry_count == 0

    def test_requeue_non_dead_returns_false(self, dlq):
        msg_id = dlq.add({"data": "alive"})
        assert dlq.requeue(msg_id) is False

    def test_requeue_nonexistent_returns_false(self, dlq):
        assert dlq.requeue(99999) is False

    def test_process_messages_ordered_by_created_at(self, dlq):
        dlq.add({"n": 3}, error="e3")
        time.sleep(0.01)
        dlq.add({"n": 1}, error="e1")
        time.sleep(0.01)
        dlq.add({"n": 2}, error="e2")
        msgs = dlq.process()
        ids = [m.payload["n"] for m in msgs]
        assert ids == [3, 1, 2]


# ── Persistence ──────────────────────────────────────────────────────────────


class TestDLQPersistence:
    """Test that messages survive reconnection."""

    def test_messages_persist_across_instances(self, temp_db_path):
        dlq1 = DeadLetterQueue("persist", db_path=temp_db_path)
        msg_id = dlq1.add({"data": "survive"}, error="test")
        dlq1.close()

        dlq2 = DeadLetterQueue("persist", db_path=temp_db_path)
        msg = dlq2.get(msg_id)
        assert msg is not None
        assert msg.payload == {"data": "survive"}
        assert msg.status == "pending"
        dlq2.close()

    def test_stats_persist_across_instances(self, temp_db_path):
        dlq1 = DeadLetterQueue("stats_persist", db_path=temp_db_path)
        dlq1.add({"n": 1})
        dlq1.add({"n": 2})
        dlq1.close()

        dlq2 = DeadLetterQueue("stats_persist", db_path=temp_db_path)
        s = dlq2.stats()
        assert s["total"] == 2
        dlq2.close()


# ── Multi-Queue Isolation ────────────────────────────────────────────────────


class TestDLQIsolation:
    """Test that different queues are isolated."""

    def test_different_queues_independent(self, temp_db_path):
        dlq_a = DeadLetterQueue("queue_a", db_path=temp_db_path)
        dlq_b = DeadLetterQueue("queue_b", db_path=temp_db_path)

        dlq_a.add({"source": "a"})
        dlq_b.add({"source": "b"})
        dlq_b.add({"source": "b2"})

        assert dlq_a.stats()["total"] == 1
        assert dlq_b.stats()["total"] == 2

        dlq_a.close()
        dlq_b.close()

    def test_get_queue_returns_instance(self, temp_db_path):
        dlq = DeadLetterQueue("shared", db_path=temp_db_path)
        found = DeadLetterQueue.get_queue("shared")
        assert found is dlq
        dlq.close()

    def test_get_queue_returns_none_for_unknown(self):
        assert DeadLetterQueue.get_queue("nonexistent") is None

    def test_reset_all_clears_instances(self):
        _dlq = DeadLetterQueue("to_reset")
        DeadLetterQueue.reset_all()
        assert DeadLetterQueue.get_queue("to_reset") is None


# ── Edge Cases ───────────────────────────────────────────────────────────────


class TestDLQEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_payload(self, dlq):
        msg_id = dlq.add({})
        msg = dlq.get(msg_id)
        assert msg.payload == {}

    def test_unicode_error_string(self, dlq):
        msg_id = dlq.add({"data": "test"}, error="Ошибка тайм-аута 🚫")
        msg = dlq.get(msg_id)
        assert "тайм-аута" in msg.error

    def test_large_payload(self, dlq):
        large = {"key": "x" * 10000}
        msg_id = dlq.add(large)
        msg = dlq.get(msg_id)
        assert msg.payload["key"] == "x" * 10000

    def test_retry_empty_queue(self, dlq):
        result = dlq.retry(lambda p: None)
        assert result == {"processed": 0, "failed": 0, "dead": 0, "total": 0}

    def test_ack_then_process_excludes(self, dlq):
        msg_id = dlq.add({"data": "temp"})
        dlq.ack(msg_id)
        assert len(dlq.process()) == 0

    def test_concurrent_adds_maintain_order(self, dlq):
        ids = []
        for i in range(20):
            ids.append(dlq.add({"n": i}))
        assert len(ids) == 20
        assert ids == sorted(ids)

    def test_to_dict_serialization(self, dlq):
        msg_id = dlq.add({"key": "val"}, error="err")
        msg = dlq.get(msg_id)
        d = msg.to_dict()
        assert d["payload"] == {"key": "val"}
        assert d["error"] == "err"
        assert d["status"] == "pending"
        assert d["queue"] == "test_queue"
        assert isinstance(d["created_at"], float)

    def test_messages_dont_leak_between_queues(self, temp_db_path):
        dlq_a = DeadLetterQueue("leak_a", db_path=temp_db_path)
        dlq_b = DeadLetterQueue("leak_b", db_path=temp_db_path)

        dlq_a_id = dlq_a.add({"owner": "a"})
        dlq_b_id = dlq_b.add({"owner": "b"})

        assert dlq_a.get(dlq_b_id) is None
        assert dlq_b.get(dlq_a_id) is None

        dlq_a.close()
        dlq_b.close()

    def test_dead_queue_ordered_by_last_error(self, dlq):
        id1 = dlq.add({"n": 1}, max_retries=1)
        dlq.nack(id1, error="first")
        time.sleep(0.01)
        id2 = dlq.add({"n": 2}, max_retries=1)
        dlq.nack(id2, error="second")

        dead_msgs = dlq.dead()
        assert len(dead_msgs) == 2
        assert dead_msgs[0].payload["n"] == 2


# ── Exception Integration ────────────────────────────────────────────────────


class TestDLQExceptionIntegration:
    """Test DLQ integration with RAG error hierarchy."""

    def test_dlq_error_is_rag_error(self):
        from proxy.app.shared.exceptions import DLQError, RAGError

        err = DLQError("dlq persistence failure")
        assert isinstance(err, RAGError)
        assert err.component == "dlq"
        assert err.recoverable is True

    def test_dlq_error_default_component(self):
        from proxy.app.shared.exceptions import DLQError

        err = DLQError("test")
        assert err.component == "dlq"
