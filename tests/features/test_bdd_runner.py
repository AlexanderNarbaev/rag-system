"""BDD test runner using pytest-bdd.

All BDD tests require RAG_PROXY_URL to be set (pointing to a running proxy).
Without it, all tests are skipped — they are integration-level BDD scenarios.
"""

import os

import pytest

# Skip all BDD tests unless RAG_PROXY_URL is set
pytestmark = pytest.mark.skipif(
    not os.getenv("RAG_PROXY_URL"),
    reason="RAG_PROXY_URL not set — BDD tests require a running proxy",
)

# Import step definitions to register them with pytest-bdd
from tests.features.steps.auth_steps import *  # noqa: E402, F401, F403
from tests.features.steps.chat_steps import *  # noqa: E402, F401, F403
from tests.features.steps.etl_steps import *  # noqa: E402, F401, F403
from tests.features.steps.qa_steps import *  # noqa: E402, F401, F403
from tests.features.steps.retrieval_steps import *  # noqa: E402, F401, F403
