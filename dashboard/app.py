# dashboard/app.py
"""
RAG System — Streamlit Web Dashboard.

Provides a web-based management interface for monitoring, configuration,
and administration of the RAG proxy system.

Usage:
    streamlit run dashboard/app.py --server.port 8501
"""

import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
import streamlit as st

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
        resp = requests.get(url, timeout=timeout) if method == "GET" else requests.request(method, url, timeout=timeout)
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


def get_proxy_metrics() -> str:
    """Get Prometheus metrics from proxy."""
    try:
        resp = requests.get(f"{PROXY_URL}/metrics", timeout=5)
        return resp.text if resp.status_code == 200 else "Metrics unavailable"
    except Exception:
        return "Metrics endpoint unreachable"


def get_feedback_list(limit: int = 50) -> list[dict]:
    """Get recent feedback entries."""
    try:
        resp = requests.get(f"{PROXY_URL}/v1/feedback", params={"limit": limit}, timeout=5)
        if resp.status_code == 200:
            return resp.json().get("feedback", [])
    except Exception:
        pass
    return []


def get_tools_list() -> list[dict]:
    """Get registered tools."""
    try:
        resp = requests.get(f"{PROXY_URL}/v1/tools", timeout=5)
        if resp.status_code == 200:
            return resp.json().get("tools", [])
    except Exception:
        pass
    return []


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
# Streamlit App
# ---------------------------------------------------------------------------


def main():
    st.set_page_config(
        page_title="RAG System Dashboard",
        page_icon="🤖",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.title("🤖 RAG System Dashboard")
    st.caption("System management and monitoring interface")

    # Sidebar navigation
    page = st.sidebar.radio(
        "Navigation",
        ["🏠 System Status", "📊 Metrics", "⚙️ Configuration", "💬 Feedback", "🔧 Tools", "📋 Logs"],
        index=0,
    )

    if page == "🏠 System Status":
        show_system_status()
    elif page == "📊 Metrics":
        show_metrics()
    elif page == "⚙️ Configuration":
        show_configuration()
    elif page == "💬 Feedback":
        show_feedback()
    elif page == "🔧 Tools":
        show_tools()
    elif page == "📋 Logs":
        show_logs()


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


def show_system_status():
    """System Status page — show health of all services."""
    st.header("System Status")

    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader("Proxy Health")
        health = get_proxy_health()
        status = health.get("status", "unknown")

        if status == "ok":
            st.success("✅ Proxy is healthy")
        elif status == "offline":
            st.error(f"❌ Proxy is offline: {health.get('error', 'Unknown error')}")
        else:
            st.warning(f"⚠️ Proxy status: {status}")

        if "components" in health:
            for comp, comp_status in health["components"].items():
                icon = "✅" if comp_status == "ok" else "⚠️"
                st.text(f"{icon} {comp}: {comp_status}")

    with col2:
        st.subheader("Service Health")
        for name, svc in SERVICES.items():
            result = check_service_health(name, svc["url"], svc["method"])
            status = result["status"]
            latency = result.get("latency_ms")

            if status == "healthy":
                icon = "✅"
                latency_str = f" ({latency:.0f}ms)" if latency else ""
                st.success(f"{icon} {name}: Online{latency_str}")
            elif status == "offline":
                st.error(f"❌ {name}: Offline")
            elif status == "timeout":
                st.warning(f"⏱️ {name}: Timeout")
            else:
                st.warning(f"⚠️ {name}: {status}")

    # Refresh button
    if st.button("🔄 Refresh Status"):
        st.rerun()


def show_metrics():
    """Metrics page — show key metrics from Prometheus endpoint."""
    st.header("System Metrics")

    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader("Prometheus Metrics")
        metrics_text = get_proxy_metrics()

        # Parse key metrics
        metrics_data = {}
        for line in metrics_text.split("\n"):
            if line.startswith("#") or not line.strip():
                continue
            parts = line.split(" ")
            if len(parts) == 2:
                name, value = parts
                metrics_data[name] = value

        # Display key metrics
        key_metrics = {
            "Total Requests": "rag_proxy_requests_total",
            "Avg Latency (s)": "rag_proxy_request_duration_seconds_sum",
            "Cache Hits": "rag_proxy_cache_hits_total",
            "Retrieval Count": "rag_proxy_retrieval_chunks_total",
        }

        for label, metric_name in key_metrics.items():
            value = metrics_data.get(metric_name, "N/A")
            st.metric(label, value)

    with col2:
        st.subheader("Raw Metrics")
        st.code(metrics_text[:3000] if len(metrics_text) > 3000 else metrics_text, language="text")

    # Auto-refresh
    auto_refresh = st.checkbox("Auto-refresh (30s)")
    if auto_refresh:
        time.sleep(30)
        st.rerun()


def show_configuration():
    """Configuration page — view and edit .env settings."""
    st.header("Configuration")

    env_vars = read_env_file()

    if not env_vars:
        st.warning("No .env file found or file is empty")
        st.info(f"Expected location: {ENV_FILE}")
        return

    # Group settings by category
    categories: dict[str, dict[str, str]] = {}
    for key, value in env_vars.items():
        category = key.split("_")[0] if "_" in key else "General"
        if category not in categories:
            categories[category] = {}
        categories[category][key] = value

    # Sensitive keys to mask
    sensitive_patterns = ["API_KEY", "PASSWORD", "SECRET", "TOKEN"]

    # Edit mode toggle
    edit_mode = st.toggle("Edit Mode", value=False)

    if edit_mode:
        st.subheader("Edit Configuration")
        st.warning("⚠️ Changes will modify the .env file. Restart proxy to apply.")

        edited_vars: dict[str, str] = {}
        for category in sorted(categories.keys()):
            with st.expander(f"📁 {category.upper()}", expanded=False):
                for key, value in sorted(categories[category].items()):
                    is_sensitive = any(p in key for p in sensitive_patterns)
                    if is_sensitive:
                        edited_vars[key] = st.text_input(key, value="***", type="password", key=f"edit_{key}")
                    else:
                        edited_vars[key] = st.text_input(key, value=value, key=f"edit_{key}")

        if st.button("💾 Save Configuration"):
            # Restore sensitive values if not changed
            for key, value in edited_vars.items():
                if value == "***":
                    edited_vars[key] = env_vars[key]
            write_env_file(edited_vars)
            st.success("Configuration saved! Restart proxy to apply changes.")
            st.rerun()
    else:
        st.subheader("Current Configuration")
        for category in sorted(categories.keys()):
            with st.expander(f"📁 {category.upper()}", expanded=False):
                for key, value in sorted(categories[category].items()):
                    is_sensitive = any(p in key for p in sensitive_patterns)
                    display_value = "***" if is_sensitive else value
                    st.text_input(key, value=display_value, disabled=True, key=f"view_{key}")


def show_feedback():
    """Feedback page — view and manage user feedback."""
    st.header("User Feedback")

    feedback = get_feedback_list()

    if not feedback:
        st.info("No feedback entries found")
        return

    # Feedback statistics
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Feedback", len(feedback))
    with col2:
        positive = sum(1 for f in feedback if f.get("rating") == "positive")
        st.metric("Positive", positive)
    with col3:
        negative = sum(1 for f in feedback if f.get("rating") == "negative")
        st.metric("Negative", negative)

    st.divider()

    # Feedback list
    for entry in feedback[:20]:
        rating = entry.get("rating", "unknown")
        icon = "👍" if rating == "positive" else "👎" if rating == "negative" else "❓"
        timestamp = entry.get("timestamp", "N/A")

        with st.expander(f"{icon} {timestamp} — {entry.get('query', 'N/A')[:50]}..."):
            st.text(f"Query: {entry.get('query', 'N/A')}")
            st.text(f"Rating: {rating}")
            if entry.get("comment"):
                st.text(f"Comment: {entry['comment']}")
            if entry.get("correction"):
                st.text(f"Correction: {entry['correction']}")


def show_tools():
    """Tools page — list and test registered tools."""
    st.header("Registered Tools")

    tools = get_tools_list()

    if not tools:
        st.info("No tools registered or tools endpoint unavailable")
        return

    st.metric("Total Tools", len(tools))

    for tool in tools:
        with st.expander(f"🔧 {tool.get('name', 'Unknown')}"):
            st.text(f"Description: {tool.get('description', 'N/A')}")
            st.text(f"Category: {tool.get('category', 'N/A')}")
            st.text(f"Provider: {tool.get('provider', 'N/A')}")

            params = tool.get("parameters", {})
            if params:
                st.json(params)

            # Test button
            if st.button(f"Test {tool.get('name', 'Tool')}", key=f"test_{tool.get('name')}"):
                st.info("Tool testing not yet implemented")


def show_logs():
    """Logs page — view recent log entries."""
    st.header("System Logs")

    col1, col2 = st.columns([3, 1])
    with col1:
        log_lines = st.slider("Lines to show", min_value=50, max_value=500, value=100, step=50)
    with col2:
        auto_refresh = st.checkbox("Auto-refresh")

    logs = get_recent_logs(log_lines)

    # Filter by log level
    level_filter = st.multiselect(
        "Filter by level",
        ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default=["INFO", "WARNING", "ERROR", "CRITICAL"],
    )

    filtered_logs = []
    for line in logs:
        if any(level in line for level in level_filter):
            filtered_logs.append(line)

    # Display logs
    log_text = "".join(filtered_logs[-log_lines:])
    st.code(log_text, language="text")

    # Download logs
    if st.button("📥 Download Logs"):
        st.download_button(
            label="Download Log File",
            data=log_text,
            file_name=f"rag_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            mime="text/plain",
        )

    if auto_refresh:
        time.sleep(10)
        st.rerun()


if __name__ == "__main__":
    main()
