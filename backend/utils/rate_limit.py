"""Per-user rate limiting for the MCP tool-call surface.

slowapi (main.py) keys by client IP - the right model for the credential
endpoints (brute-force protection at the network edge). The MCP surface
needs the opposite key: the AUTHENTICATED USER, because the budget is
what one account's clients (MCP clients, agent workflows, a leaked tool
key) may call, and behind a reverse proxy every caller looks like the
proxy's IP anyway. slowapi's decorator model resolves the key BEFORE
FastAPI dependencies run, so the authenticated user is not available at
check time - hence this small fixed-window counter, checked manually at
the two spots where the user IS resolved:

- native /api/mcp/mcp stream -> api/mcp_stream.py (MCPStreamAuthMiddleware)
- proxy routes               -> api/mcp_endpoints.py (get_proxy_context)

Both check the SAME instance, so the two surfaces share one per-user
budget (a client cannot split the budget across surface types).
In-memory, the same single-process model as the slowapi store it
complements.
"""

import os
import threading
import time


class McpRateLimited(Exception):
    """Raised when a user exceeds the per-minute MCP tool-call budget."""


class McpToolCallLimiter:
    """Fixed 60-second window, one bucket per user id.

    The check + increment is one critical section, so a burst from one
    user is serialized correctly. Stale buckets are pruned amortized when
    the dict grows (no background task).
    """

    WINDOW_SECONDS = 60

    def __init__(self, limit_per_window: int):
        self.limit = limit_per_window
        self._lock = threading.Lock()
        self._buckets: dict[int, tuple[float, int]] = {}

    def hit(self, user_id: int) -> None:
        """Count one request for user_id; raise McpRateLimited when over."""
        now = time.monotonic()
        with self._lock:
            start, count = self._buckets.get(user_id, (0.0, 0))
            if now - start >= self.WINDOW_SECONDS:
                start, count = now, 0
            count += 1
            self._buckets[user_id] = (start, count)
            if len(self._buckets) > 1024:
                self._buckets = {
                    k: v for k, v in self._buckets.items()
                    if now - v[0] < self.WINDOW_SECONDS
                }
            if count > self.limit:
                raise McpRateLimited

    def reset(self) -> None:
        """Clear all buckets (used between tests; mirrors slowapi's reset)."""
        with self._lock:
            self._buckets.clear()


# 120/min per user (Max's call, 11-27 launch pass): agent workflows burst
# (10-15 rapid calls is normal), three parallel workflows stay well under
# this, and a runaway loop or a leaked key 429s within a minute.
mcp_tool_call_limiter = McpToolCallLimiter(
    int(os.getenv("MCP_TOOL_CALLS_PER_MINUTE", "120"))
)
