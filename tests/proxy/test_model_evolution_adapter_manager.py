"""Tests for proxy/app/model_evolution/adapter_manager.py — ModelAdapter, HotReloadWatcher, AdapterManager."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from proxy.app.model_evolution.adapter_manager import (
  AdapterManager, AdapterState, HotReloadWatcher, ModelAdapter, get_adapter_manager, reset_adapter_manager,
)
from proxy.app.model_evolution.exceptions import AdapterError


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture (autouse = True)
def _reset_singleton ():
  """Reset the global AdapterManager singleton before each test."""
  reset_adapter_manager ()
  yield
  reset_adapter_manager ()


@pytest.fixture
def manager () -> AdapterManager:
  return AdapterManager ()


@pytest.fixture
def sample_adapter () -> ModelAdapter:
  return ModelAdapter (name = "test-llm", version = "v1.0", adapter_type = "lora", base_model = "llama-3b")


# ── AdapterState Transitions ─────────────────────────────────────────────────


class TestAdapterStateTransitions:
  """Test ModelAdapter.state transition validation."""
  
  def test_initial_state_unloaded (self):
    adapter = ModelAdapter (name = "test")
    assert adapter.state == AdapterState.UNLOADED
  
  def test_valid_transition_unloaded_to_loading (self):
    adapter = ModelAdapter (name = "test")
    assert adapter.transition_to (AdapterState.LOADING) is True
    assert adapter.state == AdapterState.LOADING
  
  def test_valid_transition_loading_to_active (self):
    adapter = ModelAdapter (name = "test")
    adapter.transition_to (AdapterState.LOADING)
    assert adapter.transition_to (AdapterState.ACTIVE) is True
    assert adapter.state == AdapterState.ACTIVE
  
  def test_valid_transition_active_to_draining (self):
    adapter = ModelAdapter (name = "test")
    adapter.transition_to (AdapterState.LOADING)
    adapter.transition_to (AdapterState.ACTIVE)
    assert adapter.transition_to (AdapterState.DRAINING) is True
    assert adapter.state == AdapterState.DRAINING
  
  def test_valid_transition_draining_to_retiring (self):
    adapter = ModelAdapter (name = "test")
    for state in [AdapterState.LOADING, AdapterState.ACTIVE, AdapterState.DRAINING]:
      adapter.transition_to (state)
    assert adapter.transition_to (AdapterState.RETIRING) is True
    assert adapter.state == AdapterState.RETIRING
  
  def test_valid_transition_retiring_to_unloaded (self):
    adapter = ModelAdapter (name = "test")
    for state in [AdapterState.LOADING, AdapterState.ACTIVE, AdapterState.DRAINING, AdapterState.RETIRING]:
      adapter.transition_to (state)
    assert adapter.transition_to (AdapterState.UNLOADED) is True
    assert adapter.state == AdapterState.UNLOADED
  
  def test_invalid_transition_unloaded_to_active (self):
    adapter = ModelAdapter (name = "test")
    assert adapter.transition_to (AdapterState.ACTIVE) is False
    assert adapter.state == AdapterState.UNLOADED  # unchanged
  
  def test_invalid_transition_unloaded_to_draining (self):
    adapter = ModelAdapter (name = "test")
    assert adapter.transition_to (AdapterState.DRAINING) is False
    assert adapter.state == AdapterState.UNLOADED
  
  def test_invalid_transition_loading_to_unloaded (self):
    adapter = ModelAdapter (name = "test")
    adapter.transition_to (AdapterState.LOADING)
    assert adapter.transition_to (AdapterState.UNLOADED) is False
    assert adapter.state == AdapterState.LOADING
  
  def test_error_from_unloaded (self):
    adapter = ModelAdapter (name = "test")
    assert adapter.transition_to (AdapterState.ERROR) is True
    assert adapter.state == AdapterState.ERROR
  
  def test_error_from_active (self):
    adapter = ModelAdapter (name = "test")
    adapter.transition_to (AdapterState.LOADING)
    adapter.transition_to (AdapterState.ACTIVE)
    assert adapter.transition_to (AdapterState.ERROR) is True
    assert adapter.state == AdapterState.ERROR
  
  def test_recovery_from_error_to_unloaded (self):
    adapter = ModelAdapter (name = "test")
    adapter.transition_to (AdapterState.ERROR)
    assert adapter.transition_to (AdapterState.UNLOADED) is True
    assert adapter.state == AdapterState.UNLOADED
  
  def test_recovery_from_error_to_loading (self):
    adapter = ModelAdapter (name = "test")
    adapter.transition_to (AdapterState.ERROR)
    assert adapter.transition_to (AdapterState.LOADING) is True
    assert adapter.state == AdapterState.LOADING
  
  def test_draining_can_go_back_to_active (self):
    """Draining can return to ACTIVE (e.g., if drain is aborted)."""
    adapter = ModelAdapter (name = "test")
    for state in [AdapterState.LOADING, AdapterState.ACTIVE, AdapterState.DRAINING]:
      adapter.transition_to (state)
    assert adapter.transition_to (AdapterState.ACTIVE) is True
    assert adapter.state == AdapterState.ACTIVE


# ── ModelAdapter dataclass ───────────────────────────────────────────────────


class TestModelAdapter:
  """Test ModelAdapter dataclass fields and defaults."""
  
  def test_default_values (self):
    adapter = ModelAdapter (name = "test")
    assert adapter.state == AdapterState.UNLOADED
    assert adapter.version == "base"
    assert adapter.model_path is None
    assert adapter.adapter_type == "lora"
    assert adapter.request_count == 0
    assert adapter.error_count == 0
  
  def test_custom_values (self):
    adapter = ModelAdapter (name = "reranker", version = "v2.0", model_path = "/models/reranker-v2",
        adapter_type = "qlora", base_model = "bge-reranker", )
    assert adapter.name == "reranker"
    assert adapter.version == "v2.0"
    assert adapter.model_path == "/models/reranker-v2"
    assert adapter.adapter_type == "qlora"
    assert adapter.base_model == "bge-reranker"


# ── AdapterManager — Registration ────────────────────────────────────────────


class TestAdapterManagerRegistration:
  """Test adapter registration and access."""
  
  def test_register_adapter (self, manager, sample_adapter):
    manager.register_adapter (sample_adapter)
    assert manager.has_adapter ("test-llm") is True
  
  def test_register_duplicate_raises (self, manager, sample_adapter):
    manager.register_adapter (sample_adapter)
    with pytest.raises (AdapterError, match = "already registered"):
      manager.register_adapter (sample_adapter)
  
  def test_get_adapter (self, manager, sample_adapter):
    manager.register_adapter (sample_adapter)
    result = manager.get_adapter ("test-llm")
    assert result is sample_adapter
  
  def test_get_nonexistent_adapter_raises (self, manager):
    with pytest.raises (KeyError, match = "not registered"):
      manager.get_adapter ("nonexistent")
  
  def test_list_adapters (self, manager):
    manager.register_adapter (ModelAdapter (name = "a"))
    manager.register_adapter (ModelAdapter (name = "b"))
    adapters = manager.list_adapters ()
    assert len (adapters) == 2
    names = {a.name for a in adapters}
    assert names == {"a", "b"}
  
  def test_has_adapter_false (self, manager):
    assert manager.has_adapter ("nonexistent") is False


# ── AdapterManager — Load / Unload ───────────────────────────────────────────


class TestAdapterManagerLoadUnload:
  """Test load_adapter and unload_adapter lifecycle."""
  
  def test_load_adapter_transitions_to_active (self, manager):
    adapter = ModelAdapter (name = "slm")
    manager.register_adapter (adapter)
    result = manager.load_adapter ("slm", "/models/slm-v1", "v1.0")
    assert result.state == AdapterState.ACTIVE
    assert result.version == "v1.0"
    assert result.model_path == "/models/slm-v1"
    assert result.loaded_at is not None
  
  def test_load_adapter_skips_if_already_active (self, manager):
    adapter = ModelAdapter (name = "slm")
    manager.register_adapter (adapter)
    manager.load_adapter ("slm", "/models/v1", "v1.0")
    result = manager.load_adapter ("slm", "/models/v2", "v2.0")
    assert result.version == "v1.0"  # unchanged
  
  def test_load_unregistered_adapter_raises (self, manager):
    with pytest.raises (AdapterError, match = "not registered"):
      manager.load_adapter ("ghost", "/models/ghost", "v1")
  
  def test_load_with_callback_success (self, manager):
    adapter = ModelAdapter (name = "llm")
    manager.register_adapter (adapter)
    callback = MagicMock (return_value = True)
    manager.register_load_callback ("llm", callback)
    manager.load_adapter ("llm", "/models/llm-v1", "v1.0")
    callback.assert_called_once_with ("llm", "/models/llm-v1")
  
  def test_load_with_callback_failure_raises (self, manager):
    adapter = ModelAdapter (name = "llm")
    manager.register_adapter (adapter)
    callback = MagicMock (return_value = False)
    manager.register_load_callback ("llm", callback)
    with pytest.raises (AdapterError, match = "failure"):
      manager.load_adapter ("llm", "/models/llm-v1", "v1.0")
    assert adapter.state == AdapterState.ERROR
  
  def test_load_callback_exception_transitions_to_error (self, manager):
    adapter = ModelAdapter (name = "llm")
    manager.register_adapter (adapter)
    callback = MagicMock (side_effect = RuntimeError ("OOM"))
    manager.register_load_callback ("llm", callback)
    with pytest.raises (AdapterError, match = "OOM"):
      manager.load_adapter ("llm", "/models/llm-v1", "v1.0")
    assert adapter.state == AdapterState.ERROR
    assert adapter.error_count == 1
  
  def test_unload_adapter_full_lifecycle (self, manager):
    adapter = ModelAdapter (name = "slm")
    manager.register_adapter (adapter)
    manager.load_adapter ("slm", "/models/slm-v1", "v1.0")
    assert adapter.state == AdapterState.ACTIVE
    
    result = manager.unload_adapter ("slm")
    assert result.state == AdapterState.UNLOADED
    assert result.model_path is None
    assert result.loaded_at is None
  
  def test_unload_already_unloaded_is_noop (self, manager):
    adapter = ModelAdapter (name = "slm")
    manager.register_adapter (adapter)
    result = manager.unload_adapter ("slm")
    assert result.state == AdapterState.UNLOADED
  
  def test_unload_error_adapter_directly (self, manager):
    adapter = ModelAdapter (name = "slm")
    manager.register_adapter (adapter)
    adapter.transition_to (AdapterState.ERROR)
    result = manager.unload_adapter ("slm")
    assert result.state == AdapterState.UNLOADED
  
  def test_unload_with_callback (self, manager):
    adapter = ModelAdapter (name = "slm")
    manager.register_adapter (adapter)
    manager.load_adapter ("slm", "/models/v1", "v1")
    callback = MagicMock (return_value = True)
    manager.register_unload_callback ("slm", callback)
    manager.unload_adapter ("slm")
    callback.assert_called_once_with ("slm")


# ── AdapterManager — Request Tracking ────────────────────────────────────────


class TestAdapterManagerRequestTracking:
  """Test begin_request, end_request, record_error."""
  
  def test_begin_end_request (self, manager):
    adapter = ModelAdapter (name = "slm")
    manager.register_adapter (adapter)
    assert adapter.request_count == 0
    manager.begin_request ("slm")
    assert adapter.request_count == 1
    manager.begin_request ("slm")
    assert adapter.request_count == 2
    manager.end_request ("slm")
    assert adapter.request_count == 1
  
  def test_end_request_does_not_go_below_zero (self, manager):
    adapter = ModelAdapter (name = "slm")
    manager.register_adapter (adapter)
    manager.end_request ("slm")
    assert adapter.request_count == 0
  
  def test_record_error (self, manager):
    adapter = ModelAdapter (name = "slm")
    manager.register_adapter (adapter)
    manager.record_error ("slm")
    manager.record_error ("slm")
    assert adapter.error_count == 2
  
  def test_begin_request_nonexistent_adapter (self, manager):
    # Should not raise, just no-op
    manager.begin_request ("ghost")
    manager.end_request ("ghost")
    manager.record_error ("ghost")


# ── AdapterManager — Watcher ─────────────────────────────────────────────────


class TestAdapterManagerWatcher:
  """Test enable_watcher and disable_watcher."""
  
  def test_enable_watcher_creates_thread (self, manager, tmp_path):
    adapter = ModelAdapter (name = "slm")
    manager.register_adapter (adapter)
    manager.enable_watcher ("slm", str (tmp_path), poll_interval = 0.1)
    # Watcher should be running
    watcher = manager._watchers.get ("slm")
    assert watcher is not None
    assert watcher.running is True
    manager.disable_watcher ("slm")
  
  def test_disable_watcher_stops_thread (self, manager, tmp_path):
    adapter = ModelAdapter (name = "slm")
    manager.register_adapter (adapter)
    manager.enable_watcher ("slm", str (tmp_path), poll_interval = 0.1)
    manager.disable_watcher ("slm")
    assert "slm" not in manager._watchers
  
  def test_enable_replaces_existing_watcher (self, manager, tmp_path):
    adapter = ModelAdapter (name = "slm")
    manager.register_adapter (adapter)
    manager.enable_watcher ("slm", str (tmp_path), poll_interval = 0.1)
    first_watcher = manager._watchers ["slm"]
    manager.enable_watcher ("slm", str (tmp_path), poll_interval = 0.2)
    second_watcher = manager._watchers ["slm"]
    assert second_watcher is not first_watcher
    manager.disable_watcher ("slm")


# ── AdapterManager — Shutdown ────────────────────────────────────────────────


class TestAdapterManagerShutdown:
  """Test graceful shutdown."""
  
  def test_shutdown_unloads_active_adapters (self, manager):
    adapter = ModelAdapter (name = "slm")
    manager.register_adapter (adapter)
    manager.load_adapter ("slm", "/models/v1", "v1")
    assert adapter.state == AdapterState.ACTIVE
    
    manager.shutdown ()
    assert adapter.state == AdapterState.UNLOADED
  
  def test_shutdown_stops_watchers (self, manager, tmp_path):
    adapter = ModelAdapter (name = "slm")
    manager.register_adapter (adapter)
    manager.enable_watcher ("slm", str (tmp_path), poll_interval = 0.1)
    manager.shutdown ()
    assert len (manager._watchers) == 0


# ── HotReloadWatcher ─────────────────────────────────────────────────────────


class TestHotReloadWatcher:
  """Test HotReloadWatcher filesystem polling."""
  
  def test_start_and_stop (self, tmp_path):
    watcher = HotReloadWatcher (watch_path = str (tmp_path), poll_interval = 0.1, adapter_name = "test", )
    watcher.start ()
    assert watcher.running is True
    watcher.stop ()
    assert watcher.running is False
  
  def test_detects_new_subdirectory (self, tmp_path):
    detected = []
    callback = MagicMock (side_effect = lambda name, path, ver: detected.append (ver))
    watcher = HotReloadWatcher (watch_path = str (tmp_path), callback = callback, poll_interval = 0.05,
        adapter_name = "test", )
    watcher.start ()
    time.sleep (0.1)
    
    # Create a new subdirectory (simulating a new version)
    version_dir = tmp_path / "v2.0"
    version_dir.mkdir ()
    time.sleep (0.2)
    
    watcher.stop ()
    assert "v2.0" in detected
  
  def test_does_not_fire_duplicate_for_known_version (self, tmp_path):
    callback = MagicMock ()
    watcher = HotReloadWatcher (watch_path = str (tmp_path), callback = callback, poll_interval = 0.05,
        adapter_name = "test", )
    # Pre-populate known versions
    version_dir = tmp_path / "v1.0"
    version_dir.mkdir ()
    watcher._known_versions [str (version_dir)] = version_dir.stat ().st_mtime
    
    watcher.start ()
    time.sleep (0.15)
    watcher.stop ()
    # Should not have been called since version was already known
    callback.assert_not_called ()
  
  def test_force_rescan_clears_cache (self, tmp_path):
    watcher = HotReloadWatcher (watch_path = str (tmp_path), poll_interval = 0.05, adapter_name = "test", )
    watcher._known_versions ["/some/path"] = 12345.0
    watcher._known_files ["/some/file"] = 12345.0
    watcher.force_rescan ()
    assert watcher._known_versions == {}
    assert watcher._known_files == {}
  
  def test_nonexistent_directory_no_error (self, tmp_path):
    watcher = HotReloadWatcher (watch_path = str (tmp_path / "nonexistent"), poll_interval = 0.05,
        adapter_name = "test", )
    watcher.start ()
    time.sleep (0.1)
    watcher.stop ()  # Should not crash
  
  def test_watch_directory_enables_file_patterns (self, tmp_path):
    watcher = HotReloadWatcher (watch_path = str (tmp_path), poll_interval = 0.05, adapter_name = "test", )
    assert watcher._file_patterns == []
    watcher.watch_directory ()
    assert len (watcher._file_patterns) > 0
    assert "adapter_config.json" in watcher._file_patterns
  
  def test_watch_directory_custom_patterns (self, tmp_path):
    watcher = HotReloadWatcher (watch_path = str (tmp_path), poll_interval = 0.05, adapter_name = "test", )
    watcher.watch_directory (file_patterns = ["*.bin", "*.pt"])
    assert watcher._file_patterns == ["*.bin", "*.pt"]


# ── Singleton ─────────────────────────────────────────────────────────────────


class TestAdapterManagerSingleton:
  """Test get_adapter_manager singleton and reset."""
  
  def test_get_returns_singleton (self):
    m1 = get_adapter_manager ()
    m2 = get_adapter_manager ()
    assert m1 is m2
  
  def test_reset_creates_new_instance (self):
    m1 = get_adapter_manager ()
    reset_adapter_manager ()
    m2 = get_adapter_manager ()
    assert m1 is not m2
  
  def test_reset_shutdowns_existing (self):
    m = get_adapter_manager ()
    adapter = ModelAdapter (name = "test")
    m.register_adapter (adapter)
    m.load_adapter ("test", "/models/v1", "v1")
    reset_adapter_manager ()
    assert adapter.state == AdapterState.UNLOADED
