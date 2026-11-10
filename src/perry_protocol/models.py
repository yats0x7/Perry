from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

__all__ = [
    "Risk",
    "ToolSpec",
    "ProjectSummary",
    "DesktopManifest",
    "PlanStep",
    "Plan",
    "StepStatus",
    "TaskStatus",
    "ToolCall",
    "ToolResult",
    "ToolProgress",
]


class Risk(str, Enum):
    """Permission classification of a tool.

    READ     – inspects state, never changes anything (git status, list files).
    LOW      – visible but harmless and reversible side effects (open an app or URL,
               stop a process Perry itself started).
    EXECUTE  – starts processes / runs project scripts. Always needs approval.
    WRITE    – creates or modifies files. Always needs approval.
    """

    READ = "read"
    LOW = "low"
    EXECUTE = "execute"
    WRITE = "write"


class ToolSpec(BaseModel):
    id: str
    title: str
    description: str
    risk: Risk
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]


class ProjectSummary(BaseModel):
    id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    path: str
    has_git: bool = False
    scripts: list[str] = Field(default_factory=list)
    package_manager: str | None = None


class DesktopManifest(BaseModel):
    agent_version: str
    platform: Literal["macos", "windows", "linux"]
    platform_version: str = ""
    hostname: str = ""
    platform_supported: bool = True
    tools: list[ToolSpec] = Field(default_factory=list)
    projects: list[ProjectSummary] = Field(default_factory=list)
    apps: list[str] = Field(default_factory=list)
    editor: str | None = None


class StepStatus(str, Enum):
    PLANNED = "planned"
    APPROVED = "approved"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class PlanStep(BaseModel):
    id: str
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    risk: Risk = Risk.READ
    requires_approval: bool = False
    status: StepStatus = StepStatus.PLANNED
    output: dict[str, Any] | None = None
    error: str | None = None
    started_at: float | None = None
    finished_at: float | None = None
    progress: list[str] = Field(default_factory=list)


class Plan(BaseModel):
    steps: list[PlanStep] = Field(default_factory=list)
    understanding: str = ""
    planner: str = ""
    # When the planner cannot act it explains why (clarification / unsupported).
    reply_without_action: str | None = None
    project_id: str | None = None


class TaskStatus(str, Enum):
    THINKING = "thinking"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    RESPONDING = "responding"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


# ---- desktop <-> server tool messages ---------------------------------------------------


class ToolCall(BaseModel):
    type: Literal["tool.call"] = "tool.call"
    call_id: str
    task_id: str
    tool: str
    args: dict[str, Any]
    risk: Risk
    approved: bool
    timeout_s: float = 60


class ToolProgress(BaseModel):
    type: Literal["tool.progress"] = "tool.progress"
    call_id: str
    message: str


class ToolResult(BaseModel):
    type: Literal["tool.result"] = "tool.result"
    call_id: str
    ok: bool
    output: dict[str, Any] | None = None
    error: str | None = None
    duration_ms: int = 0
