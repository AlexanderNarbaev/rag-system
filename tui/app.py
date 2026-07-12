# tui/app.py
"""
RAG System — Terminal UI (TUI).

Provides a terminal-based management interface using Textual for
monitoring, configuration, and administration of the RAG proxy system.

Usage:
    python tui/app.py
"""

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import requests
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    Log,
    Static,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROXY_URL = os.getenv("PROXY_URL", "http://localhost:8080")
PROJECT_ROOT = Path(__file__).parent.parent
ENV_FILE = PROJECT_ROOT / "proxy" / ".env"

# Service endpoints for health checks
_qdrant_host = os.getenv("QDRANT_HOST", "localhost")
_qdrant_port = os.getenv("QDRANT_PORT", "6333")
_neo4j_host = os.getenv("NEO4J_HOST", "localhost")
_neo4j_port = os.getenv("NEO4J_HTTP_PORT", "7474")
_redis_host = os.getenv("REDIS_HOST", "localhost")
_redis_port = os.getenv("REDIS_PORT", "6379")
_llm_endpoint = os.getenv("LLM_ENDPOINT", "http://localhost:8000/v1")

SERVICES = {
    "Qdrant": {
        "url": f"http://{_qdrant_host}:{_qdrant_port}/collections",
        "method": "GET",
    },
    "Neo4j": {
        "url": f"http://{_neo4j_host}:{_neo4j_port}",
        "method": "GET",
    },
    "Redis": {
        "url": f"http://{_redis_host}:{_redis_port}",
        "method": "GET",
    },
    "LLM": {
        "url": f"{_llm_endpoint}/models",
        "method": "GET",
    },
}


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def check_service_health(name: str, url: str, method: str = "GET", timeout: float = 3.0) -> dict[str, Any]:
    """Check if a service is healthy."""
    try:
        if method == "GET":
            resp = requests.get(url, timeout=timeout)
        else:
            resp = requests.request(method, url, timeout=timeout)
        return {
            "name": name,
            "status": "healthy" if resp.status_code < 400 else "degraded",
            "status_code": resp.status_code,
            "latency_ms": resp.elapsed.total_seconds() * 1000,
        }
    except requests.ConnectionError:
        return {"name": name, "status": "offline", "status_code": None, "latency_ms": None}
    except requests.Timeout:
        return {"name": name, "status": "timeout", "status_code": None, "latency_ms": None}
    except Exception as e:
        return {"name": name, "status": "error", "status_code": None, "latency_ms": None, "error": str(e)}


def get_proxy_health() -> dict[str, Any]:
    """Get proxy health status."""
    try:
        resp = requests.get(f"{PROXY_URL}/v1/health", timeout=5)
        return resp.json() if resp.status_code == 200 else {"status": "error", "code": resp.status_code}
    except Exception as e:
        return {"status": "offline", "error": str(e)}


def read_env_file() -> dict[str, str]:
    """Read .env file into a dictionary."""
    env_vars: dict[str, str] = {}
    if ENV_FILE.exists():
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    env_vars[key.strip()] = value.strip().strip('"').strip("'")
    return env_vars


def write_env_file(env_vars: dict[str, str]) -> None:
    """Write dictionary back to .env file."""
    lines = []
    if ENV_FILE.exists():
        with open(ENV_FILE) as f:
            for line in f:
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    key = stripped.split("=", 1)[0].strip()
                    if key in env_vars:
                        lines.append(f"{key}={env_vars[key]}\n")
                        continue
                lines.append(line)
    else:
        for key, value in env_vars.items():
            lines.append(f"{key}={value}\n")

    with open(ENV_FILE, "w") as f:
        f.writelines(lines)


def get_recent_logs(n: int = 100) -> list[str]:
    """Read recent log entries from log directory."""
    log_dir = Path(os.getenv("LOG_DIR", PROJECT_ROOT / "proxy" / "logs"))
    if not log_dir.exists():
        return ["Log directory not found"]

    log_files = sorted(log_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not log_files:
        return ["No log files found"]

    try:
        with open(log_files[0]) as f:
            lines = f.readlines()
        return lines[-n:]
    except Exception as e:
        return [f"Error reading logs: {e}"]


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------


class StatusIndicator(Static):
    """A status indicator widget with colored dot."""

    status = reactive("unknown")

    def render(self) -> Text:
        status_colors = {
            "healthy": "green",
            "online": "green",
            "degraded": "yellow",
            "offline": "red",
            "timeout": "yellow",
            "error": "red",
            "unknown": "dim",
        }
        color = status_colors.get(self.status, "dim")
        icon = "●" if self.status in ("healthy", "online") else "○"
        return Text(f"{icon} {self.status}", style=color)


class ServiceStatusPanel(Static):
    """Panel showing status of all services."""

    def compose(self) -> ComposeResult:
        yield Label("Service Status", classes="panel-title")
        with Vertical(id="service-status-list"):
            for name in SERVICES:
                with Horizontal(classes="service-row"):
                    yield Label(f"{name}:", classes="service-name")
                    yield StatusIndicator(id=f"status-{name.lower()}", classes="service-indicator")

    def update_status(self, name: str, status: str) -> None:
        """Update status indicator for a service."""
        try:
            indicator = self.query_one(f"#status-{name.lower()}", StatusIndicator)
            indicator.status = status
        except Exception:
            pass


class QuickActionsPanel(Static):
    """Panel with quick action buttons."""

    def compose(self) -> ComposeResult:
        yield Label("Quick Actions", classes="panel-title")
        with Vertical():
            yield Button("🔄 Refresh Status", id="btn-refresh", variant="primary")
            yield Button("🗑️ Clear Cache", id="btn-clear-cache", variant="warning")
            yield Button("🧪 Run Tests", id="btn-run-tests", variant="default")
            yield Button("📋 View Logs", id="btn-view-logs", variant="default")
            yield Button("⚙️ Edit Config", id="btn-edit-config", variant="default")


class ConfigEditor(ModalScreen):
    """Modal screen for editing configuration."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "save", "Save"),
    ]

    def __init__(self, env_vars: dict[str, str], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.env_vars = env_vars
        self.edited_vars = env_vars.copy()

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="config-editor"):
            yield Label("Configuration Editor", classes="panel-title")
            yield Label("Press Ctrl+S to save, Escape to cancel", classes="help-text")
            with Vertical(id="config-fields"):
                for key, value in sorted(self.env_vars.items()):
                    with Horizontal(classes="config-row"):
                        yield Label(f"{key}:", classes="config-key")
                        yield Input(value=value, id=f"input-{key}", classes="config-input")
            with Horizontal(id="config-actions"):
                yield Button("Save", id="btn-save", variant="success")
                yield Button("Cancel", id="btn-cancel", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-save":
            self.action_save()
        elif event.button.id == "btn-cancel":
            self.action_cancel()

    def action_save(self) -> None:
        """Save configuration changes."""
        for key in self.env_vars:
            try:
                input_widget = self.query_one(f"#input-{key}", Input)
                self.edited_vars[key] = input_widget.value
            except Exception:
                pass
        write_env_file(self.edited_vars)
        self.dismiss(True)

    def action_cancel(self) -> None:
        """Cancel editing."""
        self.dismiss(False)


class LogViewer(ModalScreen):
    """Modal screen for viewing logs."""

    BINDINGS = [
        Binding("escape", "close", "Close"),
    ]

    def __init__(self, logs: list[str], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.logs = logs

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="log-viewer"):
            yield Label("System Logs", classes="panel-title")
            yield Label("Press Escape to close", classes="help-text")
            log_widget = Log(id="log-content")
            yield log_widget
            yield Button("Close", id="btn-close-logs", variant="default")

    def on_mount(self) -> None:
        """Load logs on mount."""
        log_widget = self.query_one("#log-content", Log)
        for line in self.logs:
            log_widget.write_line(line.rstrip())

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-close-logs":
            self.action_close()

    def action_close(self) -> None:
        """Close log viewer."""
        self.dismiss()


# ---------------------------------------------------------------------------
# Main App
# ---------------------------------------------------------------------------


class RAGDashboard(App):
    """RAG System Terminal Dashboard."""

    TITLE = "RAG System TUI"
    SUB_TITLE = "Terminal Management Interface"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("l", "view_logs", "Logs"),
        Binding("c", "edit_config", "Config"),
        Binding("d", "clear_cache", "Clear Cache"),
        Binding("t", "run_tests", "Run Tests"),
    ]

    CSS = """
    Screen {
        layout: grid;
        grid-size: 2;
        grid-gutter: 1;
        padding: 1;
    }

    .panel-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }

    .help-text {
        color: $text-muted;
        margin-bottom: 1;
    }

    #status-panel {
        width: 100%;
        height: auto;
        border: solid $primary;
        padding: 1;
    }

    #actions-panel {
        width: 100%;
        height: auto;
        border: solid $primary;
        padding: 1;
    }

    #info-panel {
        width: 100%;
        height: auto;
        border: solid $primary;
        padding: 1;
    }

    #metrics-panel {
        width: 100%;
        height: auto;
        border: solid $primary;
        padding: 1;
    }

    .service-row {
        height: 1;
        margin-bottom: 0;
    }

    .service-name {
        width: 15;
    }

    .service-indicator {
        width: 20;
    }

    Button {
        margin: 0 1;
    }

    #config-editor {
        width: 80%;
        height: 80%;
        margin: 4 10;
        border: solid $primary;
        padding: 2;
        background: $surface;
    }

    #log-viewer {
        width: 90%;
        height: 80%;
        margin: 4 5;
        border: solid $primary;
        padding: 2;
        background: $surface;
    }

    #log-content {
        height: 1fr;
        border: solid $secondary;
    }

    .config-row {
        height: 3;
        margin-bottom: 0;
    }

    .config-key {
        width: 30;
    }

    .config-input {
        width: 1fr;
    }

    #config-actions {
        margin-top: 1;
        align: center middle;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()

        # Status panel (left)
        with Container(id="status-panel"):
            yield ServiceStatusPanel()

        # Actions panel (right)
        with Container(id="actions-panel"):
            yield QuickActionsPanel()

        # Info panel (left bottom)
        with Container(id="info-panel"):
            yield Label("System Information", classes="panel-title")
            yield Static(id="system-info", expand=True)

        # Metrics panel (right bottom)
        with Container(id="metrics-panel"):
            yield Label("Key Metrics", classes="panel-title")
            yield Static(id="key-metrics", expand=True)

    def on_mount(self) -> None:
        """Initialize dashboard on mount."""
        self.refresh_status()
        self.load_system_info()

    @work(exclusive=True, thread=True)
    def refresh_status(self) -> None:
        """Refresh service status in background."""
        status_panel = self.query_one(ServiceStatusPanel)

        for name, svc in SERVICES.items():
            result = check_service_health(name, svc["url"], svc["method"])
            status = result["status"]
            self.call_from_thread(status_panel.update_status, name, status)

        # Update system info
        self.call_from_thread(self.update_system_info)

    def update_system_info(self) -> None:
        """Update system information display."""
        info_lines = []

        # Proxy health
        health = get_proxy_health()
        proxy_status = health.get("status", "unknown")
        info_lines.append(f"Proxy Status: {proxy_status}")

        # Environment
        env_vars = read_env_file()
        info_lines.append(f"LLM Endpoint: {env_vars.get('LLM_ENDPOINT', 'N/A')}")
        info_lines.append(f"Qdrant Host: {env_vars.get('QDRANT_HOST', 'N/A')}")
        info_lines.append(f"Redis: {env_vars.get('USE_REDIS', 'false')}")
        info_lines.append(f"LangGraph: {env_vars.get('USE_LANGGRAPH', 'false')}")
        info_lines.append(f"Graph: {env_vars.get('GRAPH_ENABLED', 'false')}")

        info_widget = self.query_one("#system-info", Static)
        info_widget.update("\n".join(info_lines))

        # Key metrics
        metrics_lines = []
        try:
            resp = requests.get(f"{PROXY_URL}/metrics", timeout=3)
            if resp.status_code == 200:
                for line in resp.text.split("\n"):
                    if "rag_proxy" in line and not line.startswith("#"):
                        metrics_lines.append(line)
        except Exception:
            metrics_lines.append("Metrics unavailable")

        metrics_widget = self.query_one("#key-metrics", Static)
        metrics_widget.update("\n".join(metrics_lines[:10]) if metrics_lines else "No metrics available")

    def load_system_info(self) -> None:
        """Load initial system information."""
        self.update_system_info()

    def action_refresh(self) -> None:
        """Refresh all status indicators."""
        self.refresh_status()
        self.notify("Status refreshed")

    def action_view_logs(self) -> None:
        """Open log viewer."""
        logs = get_recent_logs(200)
        self.push_screen(LogViewer(logs))

    def action_edit_config(self) -> None:
        """Open configuration editor."""
        env_vars = read_env_file()
        if env_vars:
            self.push_screen(ConfigEditor(env_vars))
        else:
            self.notify("No configuration file found", severity="warning")

    def action_clear_cache(self) -> None:
        """Clear Redis cache."""
        try:
            # Try to clear via proxy endpoint if available
            resp = requests.post(f"{PROXY_URL}/v1/admin/cache/clear", timeout=5)
            if resp.status_code == 200:
                self.notify("Cache cleared successfully", severity="information")
            else:
                self.notify("Cache clear endpoint unavailable", severity="warning")
        except Exception as e:
            self.notify(f"Failed to clear cache: {e}", severity="error")

    def action_run_tests(self) -> None:
        """Run test suite."""
        self.notify("Running tests...", severity="information")
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0:
                self.notify("All tests passed!", severity="information")
            else:
                self.notify(f"Tests failed: {result.stderr[:200]}", severity="error")
        except subprocess.TimeoutExpired:
            self.notify("Tests timed out", severity="warning")
        except Exception as e:
            self.notify(f"Error running tests: {e}", severity="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "btn-refresh":
            self.action_refresh()
        elif event.button.id == "btn-clear-cache":
            self.action_clear_cache()
        elif event.button.id == "btn-run-tests":
            self.action_run_tests()
        elif event.button.id == "btn-view-logs":
            self.action_view_logs()
        elif event.button.id == "btn-edit-config":
            self.action_edit_config()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    """Run the TUI dashboard."""
    app = RAGDashboard()
    app.run()


if __name__ == "__main__":
    main()
