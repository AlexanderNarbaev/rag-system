"""Tests for proxy/app/api/widget.py — chat widget endpoints."""

from pathlib import Path

import proxy.app.api.widget as widget_mod


class TestWidgetEndpoints:
    """Tests for widget HTML and JS serving."""

    def test_module_imports(self):
        """Widget module imports correctly."""
        assert hasattr(widget_mod, "serve_widget")
        assert hasattr(widget_mod, "serve_widget_js")
        assert hasattr(widget_mod, "router")

    def test_router_has_routes(self):
        """Widget router has expected routes."""
        routes = [r.path for r in widget_mod.router.routes]
        assert "/v1/widget" in routes
        assert "/v1/widget.js" in routes

    def test_widget_path_construction(self):
        """Widget path uses correct static directory structure."""
        module_path = Path(widget_mod.__file__)
        expected_static = module_path.parent.parent.parent / "static"
        assert expected_static.name == "static"

    def test_serve_widget_function_exists(self):
        """serve_widget is an async function."""
        import asyncio

        assert asyncio.iscoroutinefunction(widget_mod.serve_widget)

    def test_serve_widget_js_function_exists(self):
        """serve_widget_js is an async function."""
        import asyncio

        assert asyncio.iscoroutinefunction(widget_mod.serve_widget_js)
