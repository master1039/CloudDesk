"""Single policy-enforced execution path for asynchronous CloudDesk tools."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterable, Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from app.core.config import Settings, get_settings
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, ConfigDict, Field

from .policy import ToolPolicy


class ToolErrorCode(StrEnum):
    UNKNOWN_TOOL = "unknown_tool"
    APPROVAL_REQUIRED = "approval_required"
    TIMEOUT = "timeout"
    EXECUTION_ERROR = "execution_error"


class ToolResult(BaseModel):
    """Uniform result returned for success, policy blocks, and tool failures."""

    model_config = ConfigDict(frozen=True)

    name: str
    ok: bool
    output: Any | None = None
    error: str | None = None
    error_code: ToolErrorCode | None = None
    approval_required: bool = False
    duration_ms: float = Field(default=0.0, ge=0)


class ToolRegistry:
    """Register async LangChain tools and execute them only after policy checks."""

    def __init__(
        self,
        tools: Iterable[BaseTool] = (),
        *,
        policy: ToolPolicy | None = None,
        settings: Settings | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        active_settings = settings or get_settings()
        self.policy = policy or ToolPolicy()
        self.timeout_seconds = (
            active_settings.tool_timeout_seconds if timeout_seconds is None else timeout_seconds
        )
        if self.timeout_seconds <= 0:
            raise ValueError("tool timeout must be positive")
        self._tools: dict[str, BaseTool] = {}
        for registered_tool in tools:
            self.register(registered_tool)

    @property
    def tools(self) -> Mapping[str, BaseTool]:
        """Expose a read-only registry view for agents and future MCP discovery."""

        return MappingProxyType(self._tools)

    def register(self, registered_tool: BaseTool) -> None:
        """Register one async ``@tool`` capability exactly once."""

        if not isinstance(registered_tool, StructuredTool):
            raise TypeError("registered tools must be created with LangChain @tool")
        if registered_tool.coroutine is None:
            raise TypeError(f"tool {registered_tool.name!r} must be asynchronous")
        if not registered_tool.name.strip():
            raise ValueError("tool name must not be blank")
        if registered_tool.name in self._tools:
            raise ValueError(f"tool {registered_tool.name!r} is already registered")
        self._tools[registered_tool.name] = registered_tool

    async def execute(
        self,
        name: str,
        args: Mapping[str, Any] | None = None,
        *,
        approved: bool = False,
    ) -> ToolResult:
        """Apply policy, timeout, and exception containment around one tool invocation."""

        started = time.perf_counter()
        rule = self.policy.rule_for(name)
        registered_tool = self._tools.get(name)

        if registered_tool is None:
            return self._failure(
                name,
                started,
                code=ToolErrorCode.UNKNOWN_TOOL,
                error=f"Unknown or unregistered tool: {name}",
                approval_required=True,
            )
        if rule.requires_approval and not approved:
            return self._failure(
                name,
                started,
                code=ToolErrorCode.APPROVAL_REQUIRED,
                error=rule.reason,
                approval_required=True,
            )

        try:
            async with asyncio.timeout(self.timeout_seconds):
                output = await registered_tool.ainvoke(dict(args or {}))
        except TimeoutError:
            return self._failure(
                name,
                started,
                code=ToolErrorCode.TIMEOUT,
                error=f"Tool exceeded the {self.timeout_seconds:g}-second timeout",
                approval_required=rule.requires_approval,
            )
        except Exception as error:  # noqa: BLE001 - tool failures must not escape into the graph.
            return self._failure(
                name,
                started,
                code=ToolErrorCode.EXECUTION_ERROR,
                error=f"{type(error).__name__}: Tool execution failed",
                approval_required=rule.requires_approval,
            )

        return ToolResult(
            name=name,
            ok=True,
            output=output,
            approval_required=rule.requires_approval,
            duration_ms=self._duration_ms(started),
        )

    @staticmethod
    def _duration_ms(started: float) -> float:
        return max(0.0, (time.perf_counter() - started) * 1_000)

    def _failure(
        self,
        name: str,
        started: float,
        *,
        code: ToolErrorCode,
        error: str,
        approval_required: bool,
    ) -> ToolResult:
        return ToolResult(
            name=name,
            ok=False,
            error=error,
            error_code=code,
            approval_required=approval_required,
            duration_ms=self._duration_ms(started),
        )
