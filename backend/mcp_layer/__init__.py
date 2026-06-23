# mcp_layer/__init__.py
# Import all tool server modules so decorators register tools at startup.

from mcp_layer.tool_registry import tool_registry   # noqa: F401  (used everywhere)

# Register all tool servers
from mcp_layer.finops_server        import tools as _finops        # noqa: F401
from mcp_layer.cloudops_server      import tools as _cloudops      # noqa: F401
from mcp_layer.execution_server     import tools as _execution     # noqa: F401
from mcp_layer.notification_server  import tools as _notification  # noqa: F401
from mcp_layer.knowledge_server     import tools as _knowledge     # noqa: F401

import logging
logger = logging.getLogger("finops.mcp")

_registered = len(tool_registry.list_tools())
logger.info(f"MCP layer initialised: {_registered} tools registered across 5 servers")
