"""FastMCP server wiring for Automox tools."""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from importlib import import_module
from types import ModuleType
from typing import Any, cast

from fastmcp import FastMCP

from .resources import register_resources
from .tools import register_tools

LoadDotenvFn = Callable[..., bool]

try:  # pragma: no cover - optional dependency guard
    from dotenv import load_dotenv as _dotenv_loader
except ImportError:  # pragma: no cover - fallback if python-dotenv missing
    _load_dotenv_fn: LoadDotenvFn | None = None
else:
    _load_dotenv_fn = _dotenv_loader


def _patch_stdio_transport() -> None:
    """Ensure stdio transport shuts down gracefully when pipes close."""
    try:
        from mcp.server import stdio as stdio_module
    except Exception:  # pragma: no cover - module missing in unusual installs
        return

    if getattr(stdio_module, "_automox_mcp_patched", False):
        return

    import sys
    from contextlib import asynccontextmanager
    from io import TextIOWrapper

    import anyio
    import anyio.lowlevel
    import mcp.types as types
    from anyio.streams.memory import (
        MemoryObjectReceiveStream,
        MemoryObjectSendStream,
    )
    from mcp.shared.message import SessionMessage

    @asynccontextmanager
    async def patched_stdio_server(  # type: ignore[override]
        stdin: anyio.AsyncFile[str] | None = None,
        stdout: anyio.AsyncFile[str] | None = None,
    ):
        # The implementation mirrors MCP's stock stdio_server but guards against
        # closed pipes raising ValueError/BrokenPipeError during shutdown.
        if not stdin:
            stdin = anyio.wrap_file(TextIOWrapper(sys.stdin.buffer, encoding="utf-8"))
        if not stdout:
            stdout = anyio.wrap_file(TextIOWrapper(sys.stdout.buffer, encoding="utf-8"))

        read_stream_writer: MemoryObjectSendStream[SessionMessage | Exception]
        read_stream: MemoryObjectReceiveStream[SessionMessage | Exception]
        write_stream: MemoryObjectSendStream[SessionMessage]
        write_stream_reader: MemoryObjectReceiveStream[SessionMessage]

        read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
        write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

        async def stdin_reader() -> None:
            try:
                async with read_stream_writer:
                    async for line in stdin:
                        try:
                            message = types.JSONRPCMessage.model_validate_json(line)
                        except Exception as exc:  # pragma: no cover - passthrough
                            await read_stream_writer.send(exc)
                            continue

                        session_message = SessionMessage(message)
                        await read_stream_writer.send(session_message)
            except anyio.ClosedResourceError:  # pragma: no cover - EOF race
                await anyio.lowlevel.checkpoint()

        async def stdout_writer() -> None:
            try:
                async with write_stream_reader:
                    async for session_message in write_stream_reader:
                        json = session_message.message.model_dump_json(
                            by_alias=True, exclude_none=True
                        )
                        try:
                            await stdout.write(json + "\n")
                            await stdout.flush()
                        except (BrokenPipeError, ValueError):
                            # Broken pipe or closed stdio occurs when the client
                            # disconnects; treat it as a normal shutdown signal.
                            return
            except anyio.ClosedResourceError:  # pragma: no cover - EOF race
                await anyio.lowlevel.checkpoint()

        stdin_task = cast(Callable[..., Awaitable[Any]], stdin_reader)
        stdout_task = cast(Callable[..., Awaitable[Any]], stdout_writer)
        async with anyio.create_task_group() as tg:
            tg.start_soon(stdin_task)
            tg.start_soon(stdout_task)
            yield read_stream, write_stream

    stdio_module.stdio_server = patched_stdio_server
    fastmcp_server_module: ModuleType | None = None
    try:
        fastmcp_server_module = import_module("fastmcp.server.server")
    except Exception:  # pragma: no cover - unexpected fastmcp layout
        fastmcp_server_module = None
    if fastmcp_server_module is not None:
        fastmcp_server_module.stdio_server = patched_stdio_server  # type: ignore[attr-defined]

    stdio_module._automox_mcp_patched = True  # type: ignore[attr-defined]


def _get_env(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _validate_env() -> None:
    """Validate required environment variables are present."""
    required_vars = ["AUTOMOX_API_KEY", "AUTOMOX_ACCOUNT_UUID", "AUTOMOX_ORG_ID"]
    missing = [var for var in required_vars if _get_env(var) is None]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {missing}")


def _load_env_file() -> None:
    if _load_dotenv_fn is None:
        return
    skip_value = os.environ.get("AUTOMOX_MCP_SKIP_DOTENV", "")
    if skip_value.lower() in {"1", "true", "yes"}:
        return
    _load_dotenv_fn()


def create_server() -> FastMCP:
    _patch_stdio_transport()
    _load_env_file()
    _validate_env()
    server: FastMCP = FastMCP(
        name="Automox MCP",
        instructions=(
            "Curated Automox workflows for policy health, device insights, remediation, and "
            "account management. Use these tools to summarize policies, inspect devices, "
            "surface devices needing attention, execute policies, run device commands for "
            "immediate remediation, and manage account invitations.\n\n"
            "IMPORTANT: When working with Automox data, proactively check available resources:\n"
            "- Use resource://servergroups/list to translate server_group_id values to "
            "human-readable names\n"
            "- Use resource://policies/quick-start for copy-paste policy creation templates "
            "(RECOMMENDED)\n"
            "- Use resource://policies/schema when creating or updating policies\n"
            "- Use resource://policies/schedule-syntax for scheduling help\n\n"
            "SCHEDULE INTERPRETATION:\n"
            "- When you retrieve a policy with policy_detail, check the '_important' field "
            "for current schedule\n"
            "- The schedule_interpretation field decodes bitmask values into human-readable "
            "format\n"
            "- Weekdays = 62, Weekend = 192, Every day = 254\n"
            "- To update schedules, use: {'days': ['weekend'], 'time': '02:00'} syntax\n\n"
            "UPDATING POLICIES:\n"
            "- Use format: {'action': 'update', 'policy_id': 12345, 'policy': "
            "{'schedule': {'days': ['weekend'], 'time': '02:00'}}}\n"
            "- Only include fields you want to change in the policy object\n\n"
            "Always translate numeric server_group_id values to group names in your responses."
        ),
    )

    # Register tools and resources
    register_tools(server)
    register_resources(server)

    return server


__all__ = ["create_server"]


if __name__ == "__main__":
    server: FastMCP = create_server()
    run = getattr(server, "run", None)
    if callable(run):
        run()
    else:
        raise RuntimeError(
            "FastMCP server object does not expose a run() method; use the FastMCP CLI instead."
        )
