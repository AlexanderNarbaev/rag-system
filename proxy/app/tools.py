# proxy/app/tools.py
"""DEPRECATED: This module is a deprecation shim.

Import from proxy.app.tools package instead:
    from proxy.app.tools import ToolRegistry, execute_tool, ...

For new-style tool definitions:
    from proxy.app.tools.definition import ToolDefinition, ToolParam, ...

For tool errors:
    from proxy.app.tools.errors import ToolError, ToolNotFoundError, ...

For enhanced registry:
    from proxy.app.tools import get_enhanced_registry
"""

import warnings

warnings.warn(
    "proxy.app.tools module is deprecated. Import from proxy.app.tools package instead.",
    DeprecationWarning,
    stacklevel=2,
)
