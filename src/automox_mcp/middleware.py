"""FastMCP middleware for cross-cutting concerns."""

from __future__ import annotations

import contextvars
import logging
import time
import uuid
from typing import Any

from fastmcp.server.middleware import Middleware

logger = logging.getLogger(__name__)

_correlation_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "correlation_id", default=None
)


def get_correlation_id() -> str | None:
    """Return the correlation ID for the current tool invocation, or None."""
    return _correlation_id_var.get()


class CorrelationMiddleware(Middleware):
    """Attach a unique correlation ID to every tool call and log timing."""

    async def on_call_tool(self, context: Any, call_next: Any) -> Any:
        correlation_id = str(uuid.uuid4())
        token = _correlation_id_var.set(correlation_id)
        tool_name = context.message.name
        start = time.perf_counter()
        try:
            result = await call_next(context)
            latency = time.perf_counter() - start
            logger.info(
                "tool_call tool=%s correlation_id=%s status=ok latency=%.3fs",
                tool_name,
                correlation_id,
                latency,
            )
            return result
        except Exception:
            latency = time.perf_counter() - start
            logger.info(
                "tool_call tool=%s correlation_id=%s status=error latency=%.3fs",
                tool_name,
                correlation_id,
                latency,
            )
            raise
        finally:
            _correlation_id_var.reset(token)


__all__ = ["CorrelationMiddleware", "get_correlation_id"]
