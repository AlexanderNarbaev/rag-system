"""Tests for orchestrator VERIFY_CASCADE routing."""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert (0, str (Path (__file__).parent.parent.parent / "proxy"))


def test_check_confidence_high_score_no_escalation ():
  with patch ("proxy.app.shared.config.CONFIDENCE_THRESHOLD", 0.5):
    from proxy.app.core.orchestrator import check_confidence
    
    state = {
        "query": "What is Python?",
        "context": "Python is a programming language created in 1991 by Guido van Rossum. It is widely used.",
        "answer": ("Python is a programming language created in 1991 by Guido van Rossum. "
                   "It is widely used for development."), "rewrite_count": 0,
    }
    result = check_confidence (state)
    assert result ["confidence"] is not None
    assert result ["confidence"] > 0.5
    assert result ["needs_escalation"] is False


def test_check_confidence_low_score_escalation ():
  with (
    patch ("proxy.app.shared.config.CONFIDENCE_THRESHOLD", 0.5), patch ("proxy.app.shared.config.MAX_VERIFY_LOOPS",
                                                                        2), patch (
      "proxy.app.shared.config.ADMIN_ALERT_ENABLED", False), patch (
      "proxy.app.shared.config.HALLUCINATION_CHECK_ENABLED", True), ):
    from proxy.app.core.orchestrator import check_confidence
    
    state = {
        "query": "What is XYZ?", "context": "", "answer": "I don't know about XYZ.", "rewrite_count": 0,
    }
    result = check_confidence (state)
    assert result ["confidence"] < 0.5
    assert result ["needs_escalation"] is True


def test_check_confidence_max_loops_no_escalation ():
  with (
    patch ("proxy.app.shared.config.CONFIDENCE_THRESHOLD", 0.5), patch ("proxy.app.shared.config.MAX_VERIFY_LOOPS",
                                                                        2), patch (
      "proxy.app.shared.config.ADMIN_ALERT_ENABLED", False), patch (
      "proxy.app.shared.config.HALLUCINATION_CHECK_ENABLED", True), ):
    from proxy.app.core.orchestrator import check_confidence
    
    state = {
        "query": "What is XYZ?", "context": "", "answer": "I don't know.", "rewrite_count": 2,
    }
    result = check_confidence (state)
    assert result ["confidence"] < 0.5
    assert result ["needs_escalation"] is False


def test_check_confidence_empty_answer ():
  from proxy.app.core.orchestrator import check_confidence
  
  state = {
      "query": "test", "context": "context", "answer": "", "rewrite_count": 0,
  }
  result = check_confidence (state)
  assert result ["confidence"] is None
  assert result ["needs_escalation"] is False
