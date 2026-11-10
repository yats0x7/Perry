"""Task lifecycle: understand → plan → policy → approve → execute → respond → speak.

Reasoning (planner), policy, execution (desktop) and response generation are separate
components. The plan is fixed *before* execution; tool output never feeds back into tool
selection, so text inside files, web pages or terminal logs cannot trigger new actions.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

from perry_protocol import Plan, StepStatus, TaskStatus, ToolCall

from ..db import DB
from ..hub import Hub
from ..voice.speech import SpeechService
from .catalog import SpotifyCatalog, enrich_plan
from .language import detect_style
from .planner import Planner, PlanningContext, RulePlanner
from .policy import PolicyEngine, PolicyViolation, plan_digest
from .responder import compose_reply

log = logging.getLogger("perry.orchestrator")

TERMINAL = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.REJECTED}


class Task(BaseModel):
    id: str
    controller_id: str
    desktop_id: str | None
    desktop_name: str | None = None
    source: Literal["voice", "text"] = "text"
    input_text: str
    transcript: dict[str, Any] | None = None
    style: str = "hinglish"
    status: TaskStatus = TaskStatus.THINKING
    plan: Plan | None = None
    plan_digest: str | None = None
    response_text: str | None = None
    speech: dict[str, Any] | None = None
    error: str | None = None
    timeline: list[dict[str, Any]] = Field(default_factory=list)
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


class _Live:
    def __init__(self) -> None:
        self.decision: asyncio.Future = asyncio.get_running_loop().create_future()
        self.cancelled = asyncio.Event()
        self.current_call: str | None = None


class Orchestrator:
    def __init__(self, db: DB, hub: Hub, speech: SpeechService, policy: PolicyEngine,
                 planner: Planner, fallback: Planner | None = None, approval_timeout_s: int = 300,
                 spotify: SpotifyCatalog | None = None):
        self.db, self.hub, self.speech, self.policy = db, hub, speech, policy
        self.planner = planner
        self.fallback = fallback or RulePlanner()
        self.approval_timeout_s = approval_timeout_s
        self.spotify = spotify
        self.tasks: dict[str, Task] = {}
        self.live: dict[str, _Live] = {}
        self.memory: dict[str, dict[str, Any]] = {}  # controller_id → {"project_id", "history"}

    # ---- persistence / fan-out ---------------------------------------------------------
    async def _emit(self, task: Task, event: str | None = None, **detail) -> None:
        task.updated_at = time.time()
        if event:
            task.timeline.append({"ts": task.updated_at, "event": event, **detail})
        self.db.exec(
            "INSERT INTO tasks(id, controller_id, desktop_id, status, created_at, updated_at, data_json) "
            "VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status, "
            "updated_at=excluded.updated_at, data_json=excluded.data_json",
            (task.id, task.controller_id, task.desktop_id, task.status.value, task.created_at,
             task.updated_at, task.model_dump_json()),
        )
        await self.hub.send_client(task.controller_id, {"type": "task", "task": task.model_dump(mode="json")})

    def history(self, controller_id: str, limit: int = 30) -> list[dict]:
        rows = self.db.all("SELECT data_json FROM tasks WHERE controller_id=? ORDER BY created_at DESC LIMIT ?",
                           (controller_id, limit))
        return [json.loads(r["data_json"]) for r in rows]

    # ---- entry points --------------------------------------------------------------------
    async def submit(self, controller_id: str, desktop_id: str, text: str, source: str,
                     transcript: dict | None = None) -> Task:
        conn = self.hub.online(desktop_id)
        task = Task(
            id=uuid.uuid4().hex[:12], controller_id=controller_id, desktop_id=desktop_id,
            desktop_name=conn.name if conn else None, source=source,  # type: ignore[arg-type]
            input_text=text.strip()[:1000], transcript=transcript, style=detect_style(text),
        )
        self.tasks[task.id] = task
        self.live[task.id] = _Live()
        await self._emit(task, "received", source=source)
        asyncio.create_task(self._run(task))
        return task

    def _owned(self, controller_id: str, task_id: str) -> Task | None:
        t = self.tasks.get(task_id)
        return t if t and t.controller_id == controller_id else None

    async def decide(self, controller_id: str, task_id: str, approve: bool, digest: str | None) -> str | None:
        t = self._owned(controller_id, task_id)
        live = self.live.get(task_id)
        if not t or not live or t.status != TaskStatus.AWAITING_APPROVAL:
            return "This task is not waiting for approval."
        if approve and digest != t.plan_digest:
            return "The plan changed since you saw it; not approving."
        if not live.decision.done():
            live.decision.set_result(approve)
        self.db.audit(f"controller:{controller_id}", "plan.approved" if approve else "plan.rejected",
                      desktop_id=t.desktop_id, task_id=t.id, digest=digest)
        return None

    async def cancel(self, controller_id: str, task_id: str) -> str | None:
        t = self._owned(controller_id, task_id)
        live = self.live.get(task_id)
        if not t or not live or t.status in TERMINAL:
            return "Nothing to cancel."
        live.cancelled.set()
        if not live.decision.done():
            live.decision.set_result(False)
        if live.current_call and t.desktop_id:
            await self.hub.cancel_call(t.desktop_id, live.current_call)
        self.db.audit(f"controller:{controller_id}", "task.cancel", desktop_id=t.desktop_id, task_id=t.id)
        return None

    # ---- lifecycle ------------------------------------------------------------------------
    async def _run(self, task: Task) -> None:
        live = self.live[task.id]
        try:
            await self._lifecycle(task, live)
        except Exception as e:  # noqa: BLE001
            log.exception("task %s crashed", task.id)
            task.status, task.error = TaskStatus.FAILED, f"Internal error: {e}"
            await self._finish(task)
        finally:
            self.live.pop(task.id, None)

    async def _lifecycle(self, task: Task, live: _Live) -> None:
        conn = self.hub.online(task.desktop_id or "")
        if conn is None:
            task.status, task.error = TaskStatus.FAILED, "Your desktop is offline. Start `perry-agent run` on it."
            return await self._finish(task)
        mem = self.memory.setdefault(task.controller_id, {"project_id": None, "history": []})

        # 1. understand + plan (reasoning)
        task.status = TaskStatus.PLANNING
        await self._emit(task, "planning", planner=self.planner.name)
        ctx = PlanningContext(manifest=conn.manifest, last_project_id=mem["project_id"], history=mem["history"][-4:])
        try:
            plan = await self.planner.plan(task.input_text, ctx)
        except Exception as e:  # noqa: BLE001 — LLM outage etc.; disclosed in the timeline
            log.warning("planner %s failed: %s; using %s", self.planner.name, e, self.fallback.name)
            await self._emit(task, "planner_fallback", reason=str(e)[:200], planner=self.fallback.name)
            plan = await self.fallback.plan(task.input_text, ctx)

        # 1b. resolve catalog references (e.g. song name → Spotify track) so approval shows the exact item
        plan = await enrich_plan(plan, conn.manifest, self.spotify)

        # 2. policy (deterministic, independent of the planner)
        try:
            plan = self.policy.review(plan, conn.manifest)
        except PolicyViolation as e:
            task.plan, task.status, task.error = plan, TaskStatus.FAILED, f"Blocked by policy: {e}"
            self.db.audit("policy", "plan.blocked", desktop_id=task.desktop_id, task_id=task.id, reason=str(e))
            return await self._finish(task)
        task.plan, task.plan_digest = plan, plan_digest(plan)
        if plan.project_id:
            mem["project_id"] = plan.project_id
        await self._emit(task, "planned", steps=len(plan.steps))
        if not plan.steps:
            task.status = TaskStatus.COMPLETED
            return await self._finish(task)

        # 3. approval
        if any(s.requires_approval for s in plan.steps):
            task.status = TaskStatus.AWAITING_APPROVAL
            await self._emit(task, "awaiting_approval")
            try:
                approved = await asyncio.wait_for(asyncio.shield(live.decision), self.approval_timeout_s)
            except asyncio.TimeoutError:
                approved = False
                task.error = "Approval timed out."
            if live.cancelled.is_set():
                for s in plan.steps:
                    s.status = StepStatus.CANCELLED
                task.status = TaskStatus.CANCELLED
                return await self._finish(task)
            if not approved:
                for s in plan.steps:
                    s.status = StepStatus.REJECTED
                task.status = TaskStatus.REJECTED
                return await self._finish(task)
            await self._emit(task, "approved")
        for s in plan.steps:
            s.status = StepStatus.APPROVED

        # 4. execute on the desktop, in order, stopping at the first failure
        task.status = TaskStatus.EXECUTING
        await self._emit(task, "executing")
        for i, step in enumerate(plan.steps):
            if live.cancelled.is_set():
                for s in plan.steps[i:]:
                    s.status = StepStatus.CANCELLED
                task.status = TaskStatus.CANCELLED
                return await self._finish(task)
            step.status, step.started_at = StepStatus.RUNNING, time.time()
            await self._emit(task, "step_started", step=step.id, tool=step.tool)
            call = ToolCall(call_id=uuid.uuid4().hex, task_id=task.id, tool=step.tool, args=step.args,
                            risk=step.risk, approved=True if step.requires_approval else False,
                            timeout_s=self.policy.timeout_for(step.tool))
            live.current_call = call.call_id

            async def progress(msg: str, step=step) -> None:
                step.progress.append(msg)
                await self._emit(task)

            self.db.audit("server", "tool.dispatch", desktop_id=task.desktop_id, task_id=task.id,
                          tool=step.tool, args=step.args, risk=step.risk.value)
            result = await self.hub.call_tool(task.desktop_id or "", call, progress)
            live.current_call = None
            step.finished_at = time.time()
            if live.cancelled.is_set() and not result.ok:
                step.status, step.error = StepStatus.CANCELLED, result.error
            elif result.ok:
                step.status, step.output = StepStatus.SUCCEEDED, result.output
            else:
                step.status, step.error = StepStatus.FAILED, result.error
            self.db.audit("desktop", "tool.result", desktop_id=task.desktop_id, task_id=task.id,
                          tool=step.tool, ok=result.ok, error=result.error, ms=result.duration_ms)
            await self._emit(task, "step_finished", step=step.id, ok=result.ok)
            if step.status != StepStatus.SUCCEEDED:
                for s in plan.steps[i + 1:]:
                    s.status = StepStatus.CANCELLED if live.cancelled.is_set() else StepStatus.SKIPPED
                break

        if live.cancelled.is_set():
            task.status = TaskStatus.CANCELLED
        elif all(s.status == StepStatus.FAILED or s.status == StepStatus.SKIPPED for s in plan.steps):
            task.status = TaskStatus.FAILED
            task.error = next((s.error for s in plan.steps if s.error), None)
        else:
            task.status = TaskStatus.COMPLETED
        await self._finish(task)

    async def _finish(self, task: Task) -> None:
        """Generate the reply text (from structured results) and the Timbre speech URL."""
        final = task.status
        task.response_text = compose_reply(task.plan, final, task.style, task.error)
        task.speech = self.speech.prepare(task.response_text, task.style)
        mem = self.memory.setdefault(task.controller_id, {"project_id": None, "history": []})
        mem["history"].append((task.input_text, task.response_text))
        mem["history"] = mem["history"][-8:]
        await self._emit(task, final.value)
