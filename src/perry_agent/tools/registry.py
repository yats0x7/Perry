"""Typed tool registry for the desktop agent.

Every capability the agent exposes is a `Tool`: a unique id, a description, a Pydantic
input model, a Pydantic output model, a risk classification and a handler. The agent
re-validates every call against the input model and the risk class locally, so a bug or
compromise on the server cannot make the agent run something outside this registry.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, ValidationError

from perry_protocol import Risk, ToolCall, ToolResult, ToolSpec

log = logging.getLogger("perry.agent.tools")

ProgressFn = Callable[[str], Awaitable[None]]


class ToolError(Exception):
    """An expected, user-presentable failure (bad project name, missing script…)."""


@dataclass
class ToolContext:
    progress: ProgressFn
    cancelled: asyncio.Event


@dataclass
class Tool:
    id: str
    title: str
    description: str
    risk: Risk
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    handler: Callable[..., Any]

    def spec(self) -> ToolSpec:
        return ToolSpec(
            id=self.id,
            title=self.title,
            description=self.description,
            risk=self.risk,
            input_schema=self.input_model.model_json_schema(),
            output_schema=self.output_model.model_json_schema(),
        )


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.id in self._tools:
            raise ValueError(f"duplicate tool id {tool.id}")
        self._tools[tool.id] = tool

    def tool(
        self,
        id: str,
        *,
        title: str,
        description: str,
        risk: Risk,
        input_model: type[BaseModel],
        output_model: type[BaseModel],
    ):
        def deco(fn):
            self.register(Tool(id, title, description, risk, input_model, output_model, fn))
            return fn

        return deco

    def get(self, tool_id: str) -> Tool | None:
        return self._tools.get(tool_id)

    def specs(self) -> list[ToolSpec]:
        return [t.spec() for t in self._tools.values()]

    def ids(self) -> list[str]:
        return list(self._tools)

    async def execute(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        started = time.monotonic()

        def done(ok: bool, output=None, error=None) -> ToolResult:
            return ToolResult(
                call_id=call.call_id,
                ok=ok,
                output=output,
                error=error,
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        tool = self._tools.get(call.tool)
        if tool is None:
            return done(False, error=f"Tool '{call.tool}' is not available on this desktop.")

        # Local policy check: the server's risk label must match ours, and anything
        # consequential must arrive with an explicit approval flag.
        order = [Risk.READ, Risk.LOW, Risk.WRITE, Risk.EXECUTE]
        if order.index(call.risk) < order.index(tool.risk):
            return done(False, error="Server under-classified this action's risk; refusing to run.")
        gated = {Risk.WRITE, Risk.EXECUTE}
        if (tool.risk in gated or call.risk in gated) and not call.approved:
            return done(False, error="This action needs user approval before it can run.")

        try:
            args = tool.input_model.model_validate(call.args)
        except ValidationError as e:
            return done(False, error=f"Invalid arguments: {e.errors(include_url=False)}")

        log.info("tool start %s %s", tool.id, args.model_dump())
        try:
            result = tool.handler(args, ctx)
            if inspect.isawaitable(result):
                result = await asyncio.wait_for(result, timeout=call.timeout_s)
            out = tool.output_model.model_validate(result)
        except ToolError as e:
            return done(False, error=str(e))
        except asyncio.TimeoutError:
            return done(False, error=f"Timed out after {call.timeout_s:.0f}s.")
        except Exception as e:  # noqa: BLE001 — surfaced to the user, logged in full
            log.exception("tool %s crashed", tool.id)
            return done(False, error=f"{type(e).__name__}: {e}")
        return done(True, output=out.model_dump(mode="json"))
