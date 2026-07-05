"""Hot-reload adapter lifecycle — load/unload LoRA adapters without proxy restart.

AdapterManager orchestrates the full lifecycle:
  UNLOADED → LOADING → ACTIVE → DRAINING → RETIRING → UNLOADED
                              → ERROR → UNLOADED

HotReloadWatcher polls the filesystem for new adapter versions and
triggers hot_reload() when a change is detected.
"""

from __future__ import annotations

import fnmatch
import logging
import os
import signal
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from proxy.app.model_evolution.exceptions import AdapterError

logger = logging.getLogger(__name__)


# ── State Machine ──────────────────────────────────────────────────────────────

class AdapterState(Enum):
    """Lifecycle states for a model adapter.

    Transitions:
        UNLOADED → LOADING → ACTIVE → DRAINING → RETIRING → UNLOADED
                                ↘ ERROR → UNLOADED
    """
    UNLOADED = "unloaded"
    LOADING = "loading"
    ACTIVE = "active"
    DRAINING = "draining"
    RETIRING = "retiring"
    ERROR = "error"


_VALID_TRANSITIONS: dict[AdapterState, set[AdapterState]] = {
    AdapterState.UNLOADED:  {AdapterState.LOADING, AdapterState.ERROR},
    AdapterState.LOADING:   {AdapterState.ACTIVE, AdapterState.ERROR},
    AdapterState.ACTIVE:    {AdapterState.DRAINING, AdapterState.ERROR},
    AdapterState.DRAINING:  {AdapterState.RETIRING, AdapterState.ACTIVE, AdapterState.LOADING, AdapterState.ERROR},
    AdapterState.RETIRING:  {AdapterState.UNLOADED, AdapterState.ERROR},
    AdapterState.ERROR:     {AdapterState.UNLOADED, AdapterState.LOADING, AdapterState.ACTIVE},
}


# ── Model Adapter ──────────────────────────────────────────────────────────────

@dataclass
class ModelAdapter:
    """Wraps a model with state, version, and hot-swap capability."""

    name: str
    state: AdapterState = AdapterState.UNLOADED
    version: str = "base"
    model_path: str | None = None
    adapter_type: str = "lora"
    base_model: str = ""
    loaded_at: str | None = None
    request_count: int = 0
    error_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def transition_to(self, target: AdapterState) -> bool:
        """Attempt a state transition. Returns True if the transition is valid."""
        if target in _VALID_TRANSITIONS.get(self.state, set()):
            logger.debug(
                "Adapter %s: %s → %s", self.name, self.state.value, target.value
            )
            self.state = target
            return True
        logger.warning(
            "Invalid transition for adapter %s: %s → %s",
            self.name, self.state.value, target.value,
        )
        return False


# ── Hot-Reload Watcher ─────────────────────────────────────────────────────────

class HotReloadWatcher:
    """Watches a directory for new adapter versions via polling.

    Supports two modes:
    1. File watcher (polling) for local model directories
    2. MLflow registry polling for staged model transitions

    When a new version is detected the ``callback`` is invoked with the
    adapter name and the path to the new version.
    """

    # Default patterns for adapter file detection
    _DEFAULT_FILE_PATTERNS: list[str] = [
        "adapter_config.json",
        "adapter_model.*",
        "*.safetensors",
        "*.bin",
        "*.pt",
        "*.ckpt",
        "lora_weights.*",
        "pytorch_model.*",
    ]

    def __init__(
        self,
        watch_path: str,
        callback: Callable[[str, str, str], None] | None = None,
        poll_interval: float = 5.0,
        adapter_name: str = "",
    ):
        self._watch_path = Path(watch_path)
        self._callback = callback
        self._poll_interval = poll_interval
        self._adapter_name = adapter_name
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._known_versions: dict[str, float] = {}
        self._known_files: dict[str, float] = {}
        self._file_patterns: list[str] = []

    # ── Public API ────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the watcher background thread."""
        if self._thread is not None and self._thread.is_alive():
            logger.warning("Watcher for %s is already running", self._watch_path)
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._poll, daemon=True, name=f"hot-reload-{self._adapter_name}"
        )
        self._thread.start()
        logger.info(
            "Started HotReloadWatcher for %s at %s (interval=%.1fs)",
            self._adapter_name, self._watch_path, self._poll_interval,
        )

    def stop(self) -> None:
        """Stop the watcher background thread."""
        if self._thread is None:
            return
        self._stop_event.set()
        self._thread.join(timeout=self._poll_interval + 2)
        self._thread = None
        logger.info("Stopped HotReloadWatcher for %s", self._adapter_name)

    @property
    def running(self) -> bool:
        """Return True if the watcher thread is alive."""
        return self._thread is not None and self._thread.is_alive()

    # ── File Watching ─────────────────────────────────────────────────────

    def watch_directory(self, file_patterns: list[str] | None = None) -> None:
        """Enable file-level watching for adapter files.

        When called, the watcher will also detect new or modified adapter
        files (e.g. adapter_config.json, *.safetensors) within the watch
        path, in addition to subdirectory-based version detection.

        Args:
            file_patterns: Optional list of fnmatch patterns for adapter
                files. Defaults to common adapter file patterns if None.
        """
        self._file_patterns = (
            file_patterns if file_patterns is not None
            else list(self._DEFAULT_FILE_PATTERNS)
        )
        logger.debug(
            "File watching enabled for %s with patterns: %s",
            self._adapter_name, self._file_patterns,
        )

    def force_rescan(self) -> None:
        """Clear known-versions cache so the next poll triggers a full rescan."""
        self._known_versions.clear()
        self._known_files.clear()
        logger.info("Forced rescan requested for %s", self._adapter_name)

    # ── Internals ─────────────────────────────────────────────────────────

    def _poll(self) -> None:
        """Poll the watch directory for new adapter versions."""
        while not self._stop_event.is_set():
            try:
                self._scan_directory()
            except Exception:
                logger.exception(
                    "Error scanning watch directory %s", self._watch_path
                )
            self._stop_event.wait(timeout=self._poll_interval)

    def _scan_directory(self) -> None:
        """Scan the watch directory and invoke callback for new versions."""
        if not self._watch_path.exists() or not self._watch_path.is_dir():
            return

        try:
            entries = sorted(self._watch_path.iterdir())
        except PermissionError:
            logger.warning("Permission denied scanning %s", self._watch_path)
            return

        for entry in entries:
            # Subdirectory-based version detection
            if entry.is_dir():
                version_path = str(entry)
                mtime = entry.stat().st_mtime

                if version_path not in self._known_versions:
                    self._known_versions[version_path] = mtime
                    logger.info(
                        "New adapter version detected: %s at %s",
                        self._adapter_name, version_path,
                    )
                    if self._callback:
                        self._callback(
                            self._adapter_name, version_path, entry.name
                        )
                continue

            # File-based adapter detection (watch_directory mode)
            if not self._file_patterns or not entry.is_file():
                continue

            file_name = entry.name
            if not self._matches_file_patterns(file_name):
                continue

            file_path = str(entry)
            mtime = entry.stat().st_mtime

            # Fire callback on new or modified files
            prev_mtime = self._known_files.get(file_path)
            if prev_mtime is None or mtime > prev_mtime:
                self._known_files[file_path] = mtime
                logger.info(
                    "New adapter file detected: %s at %s",
                    self._adapter_name, file_path,
                )
                if self._callback:
                    self._callback(self._adapter_name, file_path, file_name)

    def _matches_file_patterns(self, file_name: str) -> bool:
        """Return True if file_name matches any of the configured patterns."""
        return any(
            fnmatch.fnmatch(file_name, pattern) for pattern in self._file_patterns
        )


# ── Adapter Manager ────────────────────────────────────────────────────────────

class AdapterManager:
    """Centralized manager for all model adapters.

    Responsibilities:
    - Load/unload adapters without proxy restart
    - Drain connections before swap
    - Track adapter versions and state
    - Coordinate canary traffic splitting
    - Expose Prometheus metrics per adapter
    """

    def __init__(self):
        self._adapters: dict[str, ModelAdapter] = {}
        self._watchers: dict[str, HotReloadWatcher] = {}
        self._lock = threading.RLock()
        self._load_callbacks: dict[str, Callable[[str, str], bool]] = {}
        self._unload_callbacks: dict[str, Callable[[str], bool]] = {}

    # ── Registration ──────────────────────────────────────────────────────

    def register_adapter(self, adapter: ModelAdapter) -> None:
        """Register an adapter for a model name."""
        with self._lock:
            if adapter.name in self._adapters:
                raise AdapterError(
                    f"Adapter '{adapter.name}' already registered"
                )
            self._adapters[adapter.name] = adapter
            logger.info(
                "Registered adapter %s (version=%s, type=%s)",
                adapter.name, adapter.version, adapter.adapter_type,
            )

    def register_load_callback(
        self, name: str, callback: Callable[[str, str], bool]
    ) -> None:
        """Register a callback that performs the actual model loading.

        The callback receives (adapter_name, model_path) and returns True
        on success.
        """
        with self._lock:
            self._load_callbacks[name] = callback

    def register_unload_callback(
        self, name: str, callback: Callable[[str], bool]
    ) -> None:
        """Register a callback that performs the actual model unloading.

        The callback receives (adapter_name) and returns True on success.
        """
        with self._lock:
            self._unload_callbacks[name] = callback

    # ── Access ────────────────────────────────────────────────────────────

    def get_adapter(self, name: str) -> ModelAdapter:
        """Get an adapter by name. Raises KeyError if not registered."""
        with self._lock:
            if name not in self._adapters:
                raise KeyError(
                    f"Adapter '{name}' not registered. "
                    f"Available: {list(self._adapters.keys())}"
                )
            return self._adapters[name]

    def list_adapters(self) -> list[ModelAdapter]:
        """Return a snapshot of all registered adapters."""
        with self._lock:
            return list(self._adapters.values())

    def has_adapter(self, name: str) -> bool:
        """Return True if an adapter with the given name is registered."""
        with self._lock:
            return name in self._adapters

    # ── Load / Unload ─────────────────────────────────────────────────────

    def load_adapter(self, name: str, model_path: str, version: str) -> ModelAdapter:
        """Load adapter weights from disk and set state to ACTIVE.

        Args:
            name: The adapter name (must be registered).
            model_path: Path to the adapter weights directory.
            version: Version string for the loaded adapter.

        Returns:
            The updated ModelAdapter.

        Raises:
            AdapterError: If the adapter fails to load.
        """
        with self._lock:
            adapter = self._adapters.get(name)
            if adapter is None:
                raise AdapterError(
                    f"Cannot load adapter '{name}': not registered"
                )

            if adapter.state == AdapterState.ACTIVE:
                logger.info(
                    "Adapter %s is already ACTIVE, skipping load", name
                )
                return adapter

            if not adapter.transition_to(AdapterState.LOADING):
                raise AdapterError(
                    f"Cannot load adapter '{name}': "
                    f"invalid transition from {adapter.state.value}"
                )

        try:
            load_cb = self._load_callbacks.get(name)
            if load_cb is not None:
                success = load_cb(name, model_path)
                if not success:
                    raise AdapterError(
                        f"Load callback returned failure for adapter '{name}'"
                    )

            with self._lock:
                adapter.version = version
                adapter.model_path = model_path
                adapter.loaded_at = datetime.now(UTC).isoformat()
                adapter.error_count = 0
                adapter.transition_to(AdapterState.ACTIVE)

            logger.info(
                "Loaded adapter %s version=%s from %s",
                name, version, model_path,
            )
            return adapter

        except Exception as exc:
            with self._lock:
                adapter.transition_to(AdapterState.ERROR)
                adapter.error_count += 1

            logger.exception("Failed to load adapter %s: %s", name, exc)
            raise AdapterError(
                f"Failed to load adapter '{name}': {exc}"
            ) from exc

    def unload_adapter(self, name: str) -> ModelAdapter:
        """Unload adapter weights and free resources.

        Transitions: ACTIVE → DRAINING → RETIRING → UNLOADED

        Args:
            name: The adapter name.

        Returns:
            The updated ModelAdapter.

        Raises:
            AdapterError: If the adapter cannot be unloaded.
        """
        with self._lock:
            adapter = self._adapters.get(name)
            if adapter is None:
                raise AdapterError(
                    f"Cannot unload adapter '{name}': not registered"
                )

            if adapter.state == AdapterState.UNLOADED:
                logger.info("Adapter %s already UNLOADED", name)
                return adapter

            if adapter.state == AdapterState.ACTIVE:
                adapter.transition_to(AdapterState.DRAINING)
            elif adapter.state == AdapterState.ERROR:
                adapter.transition_to(AdapterState.UNLOADED)
                adapter.model_path = None
                adapter.loaded_at = None
                return adapter

        try:
            unload_cb = self._unload_callbacks.get(name)
            if unload_cb is not None:
                success = unload_cb(name)
                if not success:
                    logger.warning(
                        "Unload callback returned failure for adapter '%s'", name
                    )

            with self._lock:
                adapter.transition_to(AdapterState.RETIRING)
                adapter.transition_to(AdapterState.UNLOADED)
                adapter.model_path = None
                adapter.loaded_at = None

            logger.info("Unloaded adapter %s", name)
            return adapter

        except Exception as exc:
            with self._lock:
                adapter.transition_to(AdapterState.ERROR)

            logger.exception("Failed to unload adapter %s: %s", name, exc)
            raise AdapterError(
                f"Failed to unload adapter '{name}': {exc}"
            ) from exc

    # ── Hot-Reload ─────────────────────────────────────────────────────────

    def hot_reload(
        self, name: str, new_path: str, new_version: str
    ) -> ModelAdapter:
        """Seamlessly swap adapters: load new, drain old, retire.

        Args:
            name: The adapter name.
            new_path: Path to the new adapter weights.
            new_version: Version string for the new adapter.

        Returns:
            The newly loaded ModelAdapter.

        Raises:
            AdapterError: If hot-reload fails. The old adapter stays ACTIVE.
        """
        with self._lock:
            old_adapter = self._adapters.get(name)
            if old_adapter is None:
                raise AdapterError(
                    f"Cannot hot-reload adapter '{name}': not registered"
                )

            old_version = old_adapter.version
            old_path = old_adapter.model_path

            if old_adapter.state == AdapterState.UNLOADED:
                return self.load_adapter(name, new_path, new_version)

            old_adapter.transition_to(AdapterState.DRAINING)

        try:
            new_adapter = self.load_adapter(name, new_path, new_version)
        except AdapterError:
            with self._lock:
                old_adapter.transition_to(AdapterState.ACTIVE)
            logger.error(
                "Hot-reload failed for %s, restored old adapter %s",
                name, old_version,
            )
            raise

        try:
            if old_path is not None:
                self._drain_and_retire(name, old_version)
        except AdapterError:
            logger.warning(
                "Failed to retire old adapter %s@%s, but new adapter is ACTIVE",
                name, old_version,
            )

        logger.info(
            "Hot-reload complete for %s: %s → %s", name, old_version, new_version
        )
        return new_adapter

    def _drain_and_retire(self, name: str, old_version: str) -> None:
        """Wait for in-flight requests to finish, then retire the old adapter."""
        drain_attempts = 0
        max_drain_attempts = 60

        while drain_attempts < max_drain_attempts:
            with self._lock:
                adapter = self._adapters.get(name)
                if adapter is None:
                    return
                if adapter.request_count == 0:
                    adapter.transition_to(AdapterState.RETIRING)
                    adapter.transition_to(AdapterState.UNLOADED)
                    logger.info("Old adapter %s@%s retired", name, old_version)
                    return

            time.sleep(0.5)
            drain_attempts += 1

        logger.warning(
            "Adapter %s@%s: drain timeout after %d attempts, forcing retirement",
            name, old_version, max_drain_attempts,
        )
        with self._lock:
            adapter = self._adapters.get(name)
            if adapter is not None and adapter.state == AdapterState.DRAINING:
                adapter.transition_to(AdapterState.RETIRING)
                adapter.transition_to(AdapterState.UNLOADED)

    # ── Request Tracking ───────────────────────────────────────────────────

    def begin_request(self, name: str) -> None:
        """Increment the in-flight request count for an adapter."""
        with self._lock:
            adapter = self._adapters.get(name)
            if adapter is not None:
                adapter.request_count += 1

    def end_request(self, name: str) -> None:
        """Decrement the in-flight request count for an adapter."""
        with self._lock:
            adapter = self._adapters.get(name)
            if adapter is not None and adapter.request_count > 0:
                adapter.request_count -= 1

    def record_error(self, name: str) -> None:
        """Increment the error count for an adapter."""
        with self._lock:
            adapter = self._adapters.get(name)
            if adapter is not None:
                adapter.error_count += 1

    # ── Watcher Management ─────────────────────────────────────────────────

    def enable_watcher(self, name: str, path: str, poll_interval: float = 5.0) -> None:
        """Enable filesystem watcher for an adapter.

        Args:
            name: The adapter name.
            path: Directory to watch for new versions.
            poll_interval: Seconds between polls.
        """
        with self._lock:
            if name in self._watchers:
                logger.warning("Watcher for %s already enabled, replacing", name)
                self.disable_watcher(name)

            callback: Callable[[str, str, str], None] = self._on_new_version
            watcher = HotReloadWatcher(
                watch_path=path,
                callback=callback,
                poll_interval=poll_interval,
                adapter_name=name,
            )
            self._watchers[name] = watcher
            watcher.start()

    def disable_watcher(self, name: str) -> None:
        """Disable the filesystem watcher for an adapter."""
        with self._lock:
            watcher = self._watchers.pop(name, None)
            if watcher:
                watcher.stop()

    def _on_new_version(self, name: str, path: str, version: str) -> None:
        """Callback invoked by HotReloadWatcher when a new version is detected."""
        logger.info(
            "Watcher triggered hot-reload for %s: %s (version=%s)",
            name, path, version,
        )
        try:
            self.hot_reload(name, path, version)
        except AdapterError as exc:
            logger.error("Auto hot-reload failed for %s: %s", name, exc)

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def reload_all(self, default_path: str | None = None) -> None:
        """Reload all registered adapters, scanning for latest versions.

        Call this after receiving SIGHUP or when new adapter versions
        become available.

        Args:
            default_path: Base directory to scan for new versions.
                          Each adapter's name is used as subdirectory.
        """
        with self._lock:
            for name, adapter in list(self._adapters.items()):
                if adapter.state != AdapterState.ACTIVE:
                    continue
                if default_path:
                    new_path = os.path.join(default_path, name)
                    if os.path.isdir(new_path):
                        try:
                            self.hot_reload(name, new_path, adapter.version)
                        except AdapterError as exc:
                            logger.warning(
                                "Reload of %s failed during reload_all: %s",
                                name, exc,
                            )
                logger.debug("Reload check for adapter %s", name)

    def shutdown(self) -> None:
        """Gracefully shutdown all adapters and watchers."""
        logger.info("Shutting down AdapterManager (%d adapters)", len(self._adapters))

        with self._lock:
            for name in list(self._watchers):
                self.disable_watcher(name)

            for name, adapter in self._adapters.items():
                if adapter.state in (AdapterState.ACTIVE, AdapterState.DRAINING):
                    try:
                        self.unload_adapter(name)
                    except AdapterError:
                        logger.warning(
                            "Error unloading adapter %s during shutdown", name
                        )

        logger.info("AdapterManager shutdown complete")


# ── Singleton ──────────────────────────────────────────────────────────────────

_adapter_manager: AdapterManager | None = None
_manager_lock = threading.Lock()


def get_adapter_manager() -> AdapterManager:
    """Return the global AdapterManager singleton."""
    global _adapter_manager
    if _adapter_manager is None:
        with _manager_lock:
            if _adapter_manager is None:
                _adapter_manager = AdapterManager()
    return _adapter_manager


def reset_adapter_manager() -> None:
    """Reset the global singleton (for testing)."""
    global _adapter_manager
    with _manager_lock:
        if _adapter_manager is not None:
            _adapter_manager.shutdown()
        _adapter_manager = None


# ── Signal Handling ────────────────────────────────────────────────────────────

_sighup_registered: bool = False


def setup_signal_handlers(manager: AdapterManager | None = None) -> None:
    """Register SIGHUP handler to trigger adapter reload on HUP signal.

    On SIGHUP, all registered adapters are rescanned for new versions
    via ``manager.reload_all()``. Safe to call multiple times — only
    registers the handler once.

    Args:
        manager: The AdapterManager instance to reload. If None, the
                 global singleton is used.
    """
    global _sighup_registered
    if _sighup_registered:
        return

    mgr = manager or get_adapter_manager()

    def _handle_sighup(signum: int, frame: Any) -> None:
        logger.info("Received SIGHUP, triggering adapter reload")
        try:
            mgr.reload_all()
        except Exception as exc:
            logger.exception("SIGHUP reload failed: %s", exc)

    signal.signal(signal.SIGHUP, _handle_sighup)
    _sighup_registered = True
    logger.info("Registered SIGHUP handler for adapter reload")
