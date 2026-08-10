"""Targeted tests for proxy/app/shared/config.py.

Covers ``validate_auth_config`` (ephemeral-secret warnings) and
``print_config`` (secret masking). Most of the module is env-loaded
constants already exercised indirectly by existing test_config*.
"""

from __future__ import annotations

import warnings
from unittest.mock import patch

from proxy.app.shared import config as cfg

# ---------------------------------------------------------------------------
# validate_auth_config
# ---------------------------------------------------------------------------


class TestValidateAuthConfig:
    def test_jwt_secret_ephemeral_warns(self, monkeypatch):
        # Force ephemeral state
        monkeypatch.setattr(cfg, "_JWT_IS_EPHEMERAL", True)
        monkeypatch.setattr(cfg, "_ETL_SECRET_IS_EPHEMERAL", False)
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            cfg.validate_auth_config()
        # At least one warning was issued
        jwt_warnings = [w for w in captured if "JWT_SECRET" in str(w.message)]
        assert jwt_warnings

    def test_etl_secret_ephemeral_warns(self, monkeypatch):
        monkeypatch.setattr(cfg, "_JWT_IS_EPHEMERAL", False)
        monkeypatch.setattr(cfg, "_ETL_SECRET_IS_EPHEMERAL", True)
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            cfg.validate_auth_config()
        etl_warnings = [w for w in captured if "ETL_SECRET" in str(w.message)]
        assert etl_warnings

    def test_no_warnings_when_persistent(self, monkeypatch):
        monkeypatch.setattr(cfg, "_JWT_IS_EPHEMERAL", False)
        monkeypatch.setattr(cfg, "_ETL_SECRET_IS_EPHEMERAL", False)
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            cfg.validate_auth_config()
        # No warnings
        assert len(captured) == 0


# ---------------------------------------------------------------------------
# print_config
# ---------------------------------------------------------------------------


class TestPrintConfig:
    def test_prints_header(self, capsys):
        cfg.print_config()
        captured = capsys.readouterr()
        assert "RAG Proxy Configuration" in captured.out

    def test_masks_api_key(self, capsys):
        with patch.object(cfg, "EMBEDDER_API_KEY", "super-secret-value"):
            cfg.print_config()
        captured = capsys.readouterr()
        assert "***" in captured.out
        assert "super-secret-value" not in captured.out

    def test_masks_password(self, capsys):
        with patch.object(cfg, "NEO4J_PASSWORD", "shh-real-pass"):
            cfg.print_config()
        captured = capsys.readouterr()
        assert "shh-real-pass" not in captured.out

    def test_masks_secret(self, capsys):
        with patch.object(cfg, "JWT_SECRET", "the-real-key"):
            cfg.print_config()
        captured = capsys.readouterr()
        assert "the-real-key" not in captured.out

    def test_no_mask_for_unrelated_keys(self, capsys):
        # Non-secret keys should print as-is
        with patch.object(cfg, "QDRANT_HOST", "localhost-qdrant"):
            cfg.print_config()
        captured = capsys.readouterr()
        assert "localhost-qdrant" in captured.out


# ---------------------------------------------------------------------------
# Env-derived constants sanity
# ---------------------------------------------------------------------------


class TestConfigConstants:
    def test_qdrant_port_is_int(self):
        assert isinstance(cfg.QDRANT_PORT, int)

    def test_feature_flags_are_bool(self):
        assert isinstance(cfg.RERANKER_FALLBACK_LOCAL, bool)
        assert isinstance(cfg.EMBEDDER_FALLBACK_LOCAL, bool)
        assert isinstance(cfg.AD_ENABLED, bool)
        assert isinstance(cfg.RBAC_ENABLED, bool)

    def test_token_minutes_positive(self):
        assert cfg.ACCESS_TOKEN_MINUTES > 0
        assert cfg.REFRESH_TOKEN_DAYS > 0
