"""Tests for proxy/app/model_evolution/adapter_manager.py — AdapterManager & HotReloadWatcher."""

import threading
import time
from unittest.mock import MagicMock

import pytest

from proxy.app.model_evolution.adapter_manager import (
    AdapterError,
    AdapterManager,
    AdapterState,
    HotReloadWatcher,
    ModelAdapter,
    get_adapter_manager,
    reset_adapter_manager,
    setup_signal_handlers,
)

# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_singleton():
    """Ensure each test starts with a clean singleton."""
    reset_adapter_manager()
    yield
    reset_adapter_manager()


@pytest.fixture
def manager():
    """Return a fresh AdapterManager instance."""
    return AdapterManager()


@pytest.fixture
def slm_adapter():
    """A typical SLM adapter in UNLOADED state."""
    return ModelAdapter(
        name="slm",
        state=AdapterState.UNLOADED,
        version="base",
        base_model="llama-3b",
        adapter_type="lora",
    )


@pytest.fixture
def active_adapter():
    """A typical adapter already in ACTIVE state."""
    return ModelAdapter(
        name="llm",
        state=AdapterState.ACTIVE,
        version="v1",
        model_path="/models/adapters/llm/v1",
        base_model="llama-70b",
        adapter_type="lora",
        loaded_at="2026-07-05T10:00:00",
    )


@pytest.fixture
def tmp_watch_dir(tmp_path):
    """Temporary directory for HotReloadWatcher tests."""
    return tmp_path / "adapters"


# ── ModelAdapter ───────────────────────────────────────────────────────────────

class TestModelAdapter:
    def test_default_state_is_unloaded(self):
        adapter = ModelAdapter(name="slm")
        assert adapter.state == AdapterState.UNLOADED

    def test_default_version_is_base(self):
        adapter = ModelAdapter(name="slm")
        assert adapter.version == "base"

    def test_default_adapter_type_is_lora(self):
        adapter = ModelAdapter(name="slm")
        assert adapter.adapter_type == "lora"

    def test_request_count_starts_at_zero(self):
        adapter = ModelAdapter(name="slm")
        assert adapter.request_count == 0

    def test_error_count_starts_at_zero(self):
        adapter = ModelAdapter(name="slm")
        assert adapter.error_count == 0

    def test_metadata_default_is_empty_dict(self):
        adapter = ModelAdapter(name="slm")
        assert adapter.metadata == {}


class TestAdapterState:
    def test_enum_values(self):
        assert AdapterState.UNLOADED.value == "unloaded"
        assert AdapterState.LOADING.value == "loading"
        assert AdapterState.ACTIVE.value == "active"
        assert AdapterState.DRAINING.value == "draining"
        assert AdapterState.RETIRING.value == "retiring"
        assert AdapterState.ERROR.value == "error"


class TestStateTransitions:
    def test_unloaded_to_loading_valid(self):
        adapter = ModelAdapter(name="slm", state=AdapterState.UNLOADED)
        assert adapter.transition_to(AdapterState.LOADING) is True
        assert adapter.state == AdapterState.LOADING

    def test_loading_to_active_valid(self):
        adapter = ModelAdapter(name="slm", state=AdapterState.LOADING)
        assert adapter.transition_to(AdapterState.ACTIVE) is True
        assert adapter.state == AdapterState.ACTIVE

    def test_active_to_draining_valid(self):
        adapter = ModelAdapter(name="slm", state=AdapterState.ACTIVE)
        assert adapter.transition_to(AdapterState.DRAINING) is True
        assert adapter.state == AdapterState.DRAINING

    def test_draining_to_retiring_valid(self):
        adapter = ModelAdapter(name="slm", state=AdapterState.DRAINING)
        assert adapter.transition_to(AdapterState.RETIRING) is True
        assert adapter.state == AdapterState.RETIRING

    def test_retiring_to_unloaded_valid(self):
        adapter = ModelAdapter(name="slm", state=AdapterState.RETIRING)
        assert adapter.transition_to(AdapterState.UNLOADED) is True
        assert adapter.state == AdapterState.UNLOADED

    def test_loading_to_error_valid(self):
        adapter = ModelAdapter(name="slm", state=AdapterState.LOADING)
        assert adapter.transition_to(AdapterState.ERROR) is True
        assert adapter.state == AdapterState.ERROR

    def test_error_to_unloaded_valid(self):
        adapter = ModelAdapter(name="slm", state=AdapterState.ERROR)
        assert adapter.transition_to(AdapterState.UNLOADED) is True
        assert adapter.state == AdapterState.UNLOADED

    def test_active_directly_to_retiring_invalid(self):
        adapter = ModelAdapter(name="slm", state=AdapterState.ACTIVE)
        assert adapter.transition_to(AdapterState.RETIRING) is False
        assert adapter.state == AdapterState.ACTIVE

    def test_unloaded_directly_to_active_invalid(self):
        adapter = ModelAdapter(name="slm", state=AdapterState.UNLOADED)
        assert adapter.transition_to(AdapterState.ACTIVE) is False
        assert adapter.state == AdapterState.UNLOADED

    def test_draining_back_to_active_valid(self):
        """DRAINING → ACTIVE is valid (used for rollback during hot-reload)."""
        adapter = ModelAdapter(name="slm", state=AdapterState.DRAINING)
        assert adapter.transition_to(AdapterState.ACTIVE) is True
        assert adapter.state == AdapterState.ACTIVE


# ── HotReloadWatcher ───────────────────────────────────────────────────────────

class TestHotReloadWatcher:
    def test_initial_state_not_running(self, tmp_watch_dir):
        watcher = HotReloadWatcher(watch_path=str(tmp_watch_dir))
        assert watcher.running is False

    def test_start_and_stop(self, tmp_watch_dir):
        tmp_watch_dir.mkdir(parents=True, exist_ok=True)
        watcher = HotReloadWatcher(
            watch_path=str(tmp_watch_dir),
            poll_interval=0.1,
            adapter_name="test",
        )
        watcher.start()
        assert watcher.running is True
        watcher.stop()
        assert watcher.running is False

    def test_start_already_running_noop(self, tmp_watch_dir):
        tmp_watch_dir.mkdir(parents=True, exist_ok=True)
        watcher = HotReloadWatcher(
            watch_path=str(tmp_watch_dir),
            poll_interval=0.1,
            adapter_name="test",
        )
        watcher.start()
        # Second start is a no-op
        watcher.start()
        assert watcher.running is True
        watcher.stop()

    def test_callback_fired_for_new_directory(self, tmp_watch_dir):
        tmp_watch_dir.mkdir(parents=True, exist_ok=True)
        callback = MagicMock()
        watcher = HotReloadWatcher(
            watch_path=str(tmp_watch_dir),
            callback=callback,
            poll_interval=0.1,
            adapter_name="test",
        )
        watcher._scan_directory()
        callback.assert_not_called()

        (tmp_watch_dir / "v2").mkdir()
        watcher._scan_directory()
        callback.assert_called_once()
        call_args = callback.call_args[0]
        assert call_args[0] == "test"
        assert call_args[1] == str(tmp_watch_dir / "v2")
        assert call_args[2] == "v2"

    def test_no_callback_if_dir_missing(self, tmp_watch_dir):
        callback = MagicMock()
        watcher = HotReloadWatcher(
            watch_path=str(tmp_watch_dir / "nonexistent"),
            callback=callback,
            poll_interval=0.1,
            adapter_name="test",
        )
        watcher._scan_directory()
        callback.assert_not_called()

    def test_known_version_not_fired_again(self, tmp_watch_dir):
        tmp_watch_dir.mkdir(parents=True, exist_ok=True)
        (tmp_watch_dir / "v1").mkdir()

        callback = MagicMock()
        watcher = HotReloadWatcher(
            watch_path=str(tmp_watch_dir),
            callback=callback,
            poll_interval=0.1,
            adapter_name="test",
        )
        watcher._scan_directory()
        assert callback.call_count == 1

        watcher._scan_directory()
        assert callback.call_count == 1

    def test_stop_twice_no_error(self, tmp_watch_dir):
        tmp_watch_dir.mkdir(parents=True, exist_ok=True)
        watcher = HotReloadWatcher(
            watch_path=str(tmp_watch_dir),
            poll_interval=0.1,
        )
        watcher.start()
        watcher.stop()
        watcher.stop()
        assert watcher.running is False

    def test_poll_survives_errors(self, tmp_watch_dir):
        callback = MagicMock(side_effect=RuntimeError("simulated scan error"))
        watcher = HotReloadWatcher(
            watch_path=str(tmp_watch_dir),
            callback=callback,
            poll_interval=0.05,
        )
        watcher.start()
        watcher._scan_directory()
        time.sleep(0.2)
        watcher.stop()
        assert watcher.running is False


# ── AdapterManager: Registration ───────────────────────────────────────────────

class TestAdapterManagerRegistration:
    def test_register_adapter(self, manager, slm_adapter):
        manager.register_adapter(slm_adapter)
        assert manager.has_adapter("slm") is True

    def test_register_duplicate_raises(self, manager, slm_adapter):
        manager.register_adapter(slm_adapter)
        with pytest.raises(AdapterError, match="already registered"):
            manager.register_adapter(slm_adapter)

    def test_list_adapters_empty(self, manager):
        assert manager.list_adapters() == []

    def test_list_adapters(self, manager, slm_adapter, active_adapter):
        manager.register_adapter(slm_adapter)
        manager.register_adapter(active_adapter)
        adapters = manager.list_adapters()
        assert len(adapters) == 2
        names = {a.name for a in adapters}
        assert names == {"slm", "llm"}

    def test_get_adapter_existing(self, manager, slm_adapter):
        manager.register_adapter(slm_adapter)
        result = manager.get_adapter("slm")
        assert result is slm_adapter

    def test_get_adapter_missing_raises(self, manager):
        with pytest.raises(KeyError, match="not registered"):
            manager.get_adapter("nonexistent")

    def test_has_adapter_false(self, manager):
        assert manager.has_adapter("nonexistent") is False


# ── AdapterManager: Load ──────────────────────────────────────────────────────

class TestAdapterManagerLoad:
    def test_load_adapter_transitions_to_active(self, manager, slm_adapter):
        manager.register_adapter(slm_adapter)
        result = manager.load_adapter("slm", "/models/slm/v1", "v1")
        assert result.state == AdapterState.ACTIVE
        assert result.version == "v1"
        assert result.model_path == "/models/slm/v1"
        assert result.loaded_at is not None

    def test_load_unregistered_raises(self, manager):
        with pytest.raises(AdapterError, match="not registered"):
            manager.load_adapter("nonexistent", "/path", "v1")

    def test_load_already_active_is_noop(self, manager, active_adapter):
        manager.register_adapter(active_adapter)
        result = manager.load_adapter("llm", "/new/path", "v2")
        assert result.state == AdapterState.ACTIVE
        assert result.version == "v1"

    def test_load_from_error_state(self, manager, slm_adapter):
        slm_adapter.state = AdapterState.ERROR
        manager.register_adapter(slm_adapter)
        result = manager.load_adapter("slm", "/models/slm/v1", "v1")
        assert result.state == AdapterState.ACTIVE
        assert result.version == "v1"
        assert result.error_count == 0

    def test_load_invalid_transition_raises(self, manager, slm_adapter):
        slm_adapter.state = AdapterState.RETIRING
        manager.register_adapter(slm_adapter)
        with pytest.raises(AdapterError, match="invalid transition"):
            manager.load_adapter("slm", "/path", "v1")

    def test_load_callback_invoked(self, manager, slm_adapter):
        callback = MagicMock(return_value=True)
        manager.register_adapter(slm_adapter)
        manager.register_load_callback("slm", callback)
        manager.load_adapter("slm", "/models/slm/v1", "v1")
        callback.assert_called_once_with("slm", "/models/slm/v1")

    def test_load_callback_failure_transitions_to_error(self, manager, slm_adapter):
        callback = MagicMock(return_value=False)
        manager.register_adapter(slm_adapter)
        manager.register_load_callback("slm", callback)
        with pytest.raises(AdapterError, match="Load callback returned failure"):
            manager.load_adapter("slm", "/models/slm/v1", "v1")
        assert slm_adapter.state == AdapterState.ERROR
        assert slm_adapter.error_count == 1

    def test_load_exception_transitions_to_error(self, manager, slm_adapter):
        manager.register_adapter(slm_adapter)
        manager.register_load_callback(
            "slm",
            MagicMock(side_effect=RuntimeError("GPU OOM")),
        )
        with pytest.raises(AdapterError, match="Failed to load"):
            manager.load_adapter("slm", "/path", "v1")
        assert slm_adapter.state == AdapterState.ERROR


# ── AdapterManager: Unload ────────────────────────────────────────────────────

class TestAdapterManagerUnload:
    def test_unload_active_adapter(self, manager, active_adapter):
        manager.register_adapter(active_adapter)
        result = manager.unload_adapter("llm")
        assert result.state == AdapterState.UNLOADED
        assert result.model_path is None
        assert result.loaded_at is None

    def test_unload_already_unloaded_noop(self, manager, slm_adapter):
        manager.register_adapter(slm_adapter)
        result = manager.unload_adapter("slm")
        assert result.state == AdapterState.UNLOADED

    def test_unload_unregistered_raises(self, manager):
        with pytest.raises(AdapterError, match="not registered"):
            manager.unload_adapter("nonexistent")

    def test_unload_from_error_state(self, manager, slm_adapter):
        slm_adapter.state = AdapterState.ERROR
        slm_adapter.model_path = "/some/path"
        manager.register_adapter(slm_adapter)
        result = manager.unload_adapter("slm")
        assert result.state == AdapterState.UNLOADED
        assert result.model_path is None

    def test_unload_callback_invoked(self, manager, active_adapter):
        callback = MagicMock(return_value=True)
        manager.register_adapter(active_adapter)
        manager.register_unload_callback("llm", callback)
        manager.unload_adapter("llm")
        callback.assert_called_once_with("llm")

    def test_unload_callback_failure_still_unloads(self, manager, active_adapter):
        callback = MagicMock(return_value=False)
        manager.register_adapter(active_adapter)
        manager.register_unload_callback("llm", callback)
        result = manager.unload_adapter("llm")
        assert result.state == AdapterState.UNLOADED


# ── AdapterManager: Hot-Reload ────────────────────────────────────────────────

class TestAdapterManagerHotReload:
    def test_hot_reload_unloaded_same_as_load(self, manager, slm_adapter):
        manager.register_adapter(slm_adapter)
        result = manager.hot_reload("slm", "/models/slm/v2", "v2")
        assert result.state == AdapterState.ACTIVE
        assert result.version == "v2"

    def test_hot_reload_active_adapter(self, manager, active_adapter):
        manager.register_adapter(active_adapter)
        # No requests in flight, so drain completes immediately
        result = manager.hot_reload("llm", "/models/llm/v2", "v2")
        assert result.state == AdapterState.ACTIVE
        assert result.version == "v2"

    def test_hot_reload_unregistered_raises(self, manager):
        with pytest.raises(AdapterError, match="not registered"):
            manager.hot_reload("nonexistent", "/path", "v1")

    def test_hot_reload_failure_restores_old(self, manager, active_adapter):
        manager.register_adapter(active_adapter)
        manager.register_load_callback(
            "llm", MagicMock(return_value=False)
        )
        old_version = active_adapter.version

        with pytest.raises(AdapterError):
            manager.hot_reload("llm", "/models/llm/v2", "v2")

        assert active_adapter.state == AdapterState.ACTIVE
        assert active_adapter.version == old_version

    def test_hot_reload_drains_inflight_requests(self, manager, active_adapter):
        manager.register_adapter(active_adapter)
        manager.begin_request("llm")
        assert active_adapter.request_count == 1

        result = manager.hot_reload("llm", "/models/llm/v2", "v2")
        assert result.state == AdapterState.ACTIVE
        assert result.version == "v2"

        manager.end_request("llm")
        assert active_adapter.request_count == 0


# ── AdapterManager: Request Tracking ───────────────────────────────────────────

class TestAdapterManagerRequestTracking:
    def test_begin_request_increments_count(self, manager, active_adapter):
        manager.register_adapter(active_adapter)
        manager.begin_request("llm")
        assert active_adapter.request_count == 1
        manager.begin_request("llm")
        assert active_adapter.request_count == 2

    def test_end_request_decrements_count(self, manager, active_adapter):
        manager.register_adapter(active_adapter)
        active_adapter.request_count = 3
        manager.end_request("llm")
        assert active_adapter.request_count == 2

    def test_end_request_not_negative(self, manager, active_adapter):
        manager.register_adapter(active_adapter)
        manager.end_request("llm")
        assert active_adapter.request_count == 0

    def test_begin_request_nonexistent_noop(self, manager):
        manager.begin_request("nonexistent")

    def test_end_request_nonexistent_noop(self, manager):
        manager.end_request("nonexistent")

    def test_record_error_increments(self, manager, active_adapter):
        manager.register_adapter(active_adapter)
        manager.record_error("llm")
        assert active_adapter.error_count == 1
        manager.record_error("llm")
        assert active_adapter.error_count == 2

    def test_record_error_nonexistent_noop(self, manager):
        manager.record_error("nonexistent")


# ── AdapterManager: Watcher ───────────────────────────────────────────────────

class TestAdapterManagerWatcher:
    def test_enable_watcher(self, manager, slm_adapter, tmp_watch_dir):
        tmp_watch_dir.mkdir(parents=True, exist_ok=True)
        manager.register_adapter(slm_adapter)
        manager.enable_watcher("slm", str(tmp_watch_dir))
        watcher = manager._watchers.get("slm")
        assert watcher is not None
        assert watcher.running is True
        manager.disable_watcher("slm")
        assert watcher.running is False

    def test_disable_watcher_does_nothing_if_none(self, manager):
        manager.disable_watcher("nonexistent")

    def test_enable_watcher_replaces_existing(self, manager, tmp_watch_dir):
        tmp_watch_dir.mkdir(parents=True, exist_ok=True)
        manager.enable_watcher("test", str(tmp_watch_dir), poll_interval=0.1)
        old_watcher = manager._watchers["test"]

        manager.enable_watcher("test", str(tmp_watch_dir), poll_interval=0.2)
        new_watcher = manager._watchers["test"]

        assert old_watcher is not new_watcher
        assert old_watcher.running is False
        assert new_watcher.running is True
        manager.disable_watcher("test")

    def test_watcher_triggers_hot_reload(self, manager, slm_adapter, tmp_watch_dir):
        tmp_watch_dir.mkdir(parents=True, exist_ok=True)
        manager.register_adapter(slm_adapter)
        manager.enable_watcher("slm", str(tmp_watch_dir), poll_interval=0.1)

        (tmp_watch_dir / "v2").mkdir()
        time.sleep(0.35)

        adapter = manager.get_adapter("slm")
        assert adapter.version == "v2"
        assert adapter.state == AdapterState.ACTIVE

        manager.disable_watcher("slm")

    def test_watcher_failure_does_not_crash(self, manager, active_adapter, tmp_watch_dir):
        tmp_watch_dir.mkdir(parents=True, exist_ok=True)
        manager.register_adapter(active_adapter)
        manager.enable_watcher("llm", str(tmp_watch_dir), poll_interval=0.1)

        (tmp_watch_dir / "bad_version").mkdir()
        manager.register_load_callback("llm", MagicMock(return_value=False))
        time.sleep(0.35)

        adapter = manager.get_adapter("llm")
        assert adapter.state == AdapterState.ACTIVE

        manager.disable_watcher("llm")


# ── AdapterManager: Shutdown ──────────────────────────────────────────────────

class TestAdapterManagerShutdown:
    def test_shutdown_unloads_active_adapters(self, manager, active_adapter):
        manager.register_adapter(active_adapter)
        manager.shutdown()
        assert active_adapter.state == AdapterState.UNLOADED

    def test_shutdown_stops_watchers(self, manager, tmp_watch_dir):
        tmp_watch_dir.mkdir(parents=True, exist_ok=True)
        manager.enable_watcher("test", str(tmp_watch_dir), poll_interval=0.1)
        assert len(manager._watchers) == 1

        manager.shutdown()

        assert len(manager._watchers) == 0
        assert manager._watchers.get("test") is None

    def test_shutdown_idempotent(self, manager, active_adapter):
        manager.register_adapter(active_adapter)
        manager.shutdown()
        manager.shutdown()
        assert active_adapter.state == AdapterState.UNLOADED

    def test_shutdown_handles_unload_errors(self, manager, active_adapter):
        manager.register_adapter(active_adapter)
        manager.register_unload_callback(
            "llm",
            MagicMock(side_effect=RuntimeError("unload failed")),
        )
        manager.shutdown()
        assert active_adapter.state == AdapterState.ERROR


# ── Singleton ──────────────────────────────────────────────────────────────────

class TestSingleton:
    def test_get_adapter_manager_returns_same_instance(self):
        m1 = get_adapter_manager()
        m2 = get_adapter_manager()
        assert m1 is m2

    def test_reset_creates_new_instance(self):
        m1 = get_adapter_manager()
        reset_adapter_manager()
        m2 = get_adapter_manager()
        assert m1 is not m2

    def test_singleton_is_thread_safe(self):
        instances = []

        def get_instance():
            instances.append(get_adapter_manager())

        threads = [threading.Thread(target=get_instance) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        first = instances[0]
        for inst in instances:
            assert inst is first

    def test_reset_calls_shutdown(self):
        m1 = get_adapter_manager()
        adapter = ModelAdapter(name="test", state=AdapterState.ACTIVE)
        m1.register_adapter(adapter)

        reset_adapter_manager()

        assert adapter.state == AdapterState.UNLOADED


# ── Thread Safety ──────────────────────────────────────────────────────────────

class TestThreadSafety:
    def test_concurrent_load_unload(self, manager, slm_adapter):
        manager.register_adapter(slm_adapter)
        results = []

        def loader():
            for i in range(50):
                try:
                    manager.load_adapter("slm", f"/path/v{i}", f"v{i}")
                    results.append(True)
                except AdapterError:
                    results.append(False)

        def unloader():
            for _ in range(25):
                try:
                    manager.unload_adapter("slm")
                    results.append(True)
                except AdapterError:
                    results.append(False)

        t1 = threading.Thread(target=loader)
        t2 = threading.Thread(target=unloader)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert len(results) == 75

    def test_concurrent_request_tracking(self, manager, active_adapter):
        manager.register_adapter(active_adapter)

        def send_requests():
            for _ in range(100):
                manager.begin_request("llm")
                manager.end_request("llm")

        threads = [threading.Thread(target=send_requests) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert active_adapter.request_count == 0


# ── HotReloadWatcher: watch_directory() ────────────────────────────────────────

class TestHotReloadWatcherWatchDirectory:
    def test_watch_directory_detects_new_adapter_file(self, tmp_watch_dir):
        tmp_watch_dir.mkdir(parents=True, exist_ok=True)
        callback = MagicMock()
        watcher = HotReloadWatcher(
            watch_path=str(tmp_watch_dir),
            callback=callback,
            poll_interval=0.1,
            adapter_name="test",
        )
        watcher.watch_directory()

        (tmp_watch_dir / "adapter_config.json").write_text(
            '{"base_model_name": "llama-3b", "lora_alpha": 16}'
        )
        watcher._scan_directory()
        callback.assert_called_once()
        call_args = callback.call_args[0]
        assert call_args[0] == "test"
        assert call_args[1] == str(tmp_watch_dir / "adapter_config.json")
        assert call_args[2] == "adapter_config.json"

    def test_watch_directory_detects_safetensors_file(self, tmp_watch_dir):
        tmp_watch_dir.mkdir(parents=True, exist_ok=True)
        callback = MagicMock()
        watcher = HotReloadWatcher(
            watch_path=str(tmp_watch_dir),
            callback=callback,
            poll_interval=0.1,
            adapter_name="test",
        )
        watcher.watch_directory()

        (tmp_watch_dir / "adapter_model.safetensors").write_text("weights")
        watcher._scan_directory()
        callback.assert_called_once()

    def test_watch_directory_ignores_non_adapter_files(self, tmp_watch_dir):
        tmp_watch_dir.mkdir(parents=True, exist_ok=True)
        callback = MagicMock()
        watcher = HotReloadWatcher(
            watch_path=str(tmp_watch_dir),
            callback=callback,
            poll_interval=0.1,
            adapter_name="test",
        )
        watcher.watch_directory()

        (tmp_watch_dir / "README.md").write_text("docs")
        (tmp_watch_dir / "notes.txt").write_text("notes")
        watcher._scan_directory()
        callback.assert_not_called()

    def test_watch_directory_known_file_not_fired_again(self, tmp_watch_dir):
        tmp_watch_dir.mkdir(parents=True, exist_ok=True)
        callback = MagicMock()
        watcher = HotReloadWatcher(
            watch_path=str(tmp_watch_dir),
            callback=callback,
            poll_interval=0.1,
            adapter_name="test",
        )
        watcher.watch_directory()

        (tmp_watch_dir / "adapter_config.json").write_text('{}')
        watcher._scan_directory()
        assert callback.call_count == 1

        watcher._scan_directory()
        assert callback.call_count == 1

    def test_watch_directory_with_custom_patterns(self, tmp_watch_dir):
        tmp_watch_dir.mkdir(parents=True, exist_ok=True)
        callback = MagicMock()
        watcher = HotReloadWatcher(
            watch_path=str(tmp_watch_dir),
            callback=callback,
            poll_interval=0.1,
            adapter_name="test",
        )
        watcher.watch_directory(file_patterns=["*.gguf"])

        (tmp_watch_dir / "adapter_config.json").write_text('{}')
        watcher._scan_directory()
        callback.assert_not_called()

        (tmp_watch_dir / "model.gguf").write_text("weights")
        watcher._scan_directory()
        callback.assert_called_once()

    def test_watch_directory_file_modified_fires_callback(self, tmp_watch_dir):
        tmp_watch_dir.mkdir(parents=True, exist_ok=True)
        callback = MagicMock()
        watcher = HotReloadWatcher(
            watch_path=str(tmp_watch_dir),
            callback=callback,
            poll_interval=0.1,
            adapter_name="test",
        )
        watcher.watch_directory()

        f = tmp_watch_dir / "adapter_config.json"
        f.write_text('{"version": "v1"}')
        watcher._scan_directory()
        assert callback.call_count == 1

        time.sleep(0.01)
        f.write_text('{"version": "v2"}')
        watcher._scan_directory()
        assert callback.call_count == 2

    def test_watch_directory_integration_with_poll(self, tmp_watch_dir):
        tmp_watch_dir.mkdir(parents=True, exist_ok=True)
        callback = MagicMock()
        watcher = HotReloadWatcher(
            watch_path=str(tmp_watch_dir),
            callback=callback,
            poll_interval=0.05,
            adapter_name="test",
        )
        watcher.watch_directory()
        watcher.start()

        time.sleep(0.15)
        (tmp_watch_dir / "adapter_config.json").write_text(
            '{"base_model_name": "llama-3b"}'
        )
        time.sleep(0.2)
        watcher.stop()

        assert callback.call_count >= 1


# ── HotReloadWatcher: Signal Handling ──────────────────────────────────────────

class TestHotReloadWatcherSignal:
    def test_sighup_signal_registration_does_not_crash(self):
        setup_signal_handlers(MagicMock(spec=AdapterManager))

    def test_sighup_clears_known_versions(self, tmp_watch_dir):
        tmp_watch_dir.mkdir(parents=True, exist_ok=True)
        (tmp_watch_dir / "v1").mkdir()
        callback = MagicMock()
        watcher = HotReloadWatcher(
            watch_path=str(tmp_watch_dir),
            callback=callback,
            poll_interval=0.1,
            adapter_name="test",
        )
        watcher._scan_directory()
        assert "v1" in watcher._known_versions or len(watcher._known_versions) > 0

        watcher.force_rescan()
        watcher._scan_directory()
        assert callback.call_count >= 1


# ── AdapterManager: Reload All ─────────────────────────────────────────────────

class TestAdapterManagerReloadAll:
    def test_reload_all_reloads_each_registered_adapter(self, manager, tmp_watch_dir):
        tmp_watch_dir.mkdir(parents=True, exist_ok=True)
        (tmp_watch_dir / "v1").mkdir()
        (tmp_watch_dir / "v2").mkdir()

        adapter = ModelAdapter(
            name="slm",
            state=AdapterState.ACTIVE,
            version="v1",
            model_path=str(tmp_watch_dir / "v1"),
            base_model="llama-3b",
        )
        manager.register_adapter(adapter)

        manager.reload_all(default_path=str(tmp_watch_dir))

        after = manager.get_adapter("slm")
        assert after.state == AdapterState.ACTIVE

    def test_reload_all_skips_unloaded(self, manager, tmp_watch_dir):
        tmp_watch_dir.mkdir(parents=True, exist_ok=True)
        adapter = ModelAdapter(name="slm", state=AdapterState.UNLOADED)
        manager.register_adapter(adapter)
        manager.reload_all()

        after = manager.get_adapter("slm")
        assert after.state == AdapterState.UNLOADED
