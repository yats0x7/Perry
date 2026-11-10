"""Execution policy — deterministic, independent of any planner or LLM.

Every proposed plan passes through `PolicyEngine.review` before the user sees it:

* the tool must be on the server allowlist AND advertised by the target desktop;
* the risk class is the stricter of the server's own table and the desktop's claim
  (tools unknown to the server are treated as EXECUTE — gated by default);
* arguments are validated against the tool's JSON Schema;
* plans are capped in length;
* READ runs without approval; LOW without approval in `standard` mode;
  EXECUTE / WRITE always require explicit approval;
* the approved plan is pinned by a SHA-256 digest, so what runs is exactly what the
  user saw.
"""

from __future__ import annotations

import hashlib
import json

import jsonschema

from perry_protocol import DesktopManifest, Plan, Risk
from perry_protocol.command_guard import check_command

MAX_STEPS = 8

# Server-side source of truth for risk. A desktop can only make a tool *stricter*.
SERVER_RISK: dict[str, Risk] = {
    "app.open": Risk.LOW, "app.focus": Risk.LOW, "url.open": Risk.LOW,
    "project.list": Risk.READ, "project.open": Risk.LOW, "project.info": Risk.READ,
    "git.status": Risk.READ, "git.log": Risk.READ,
    "dev.start_server": Risk.EXECUTE, "dev.run_script": Risk.EXECUTE,
    "process.list": Risk.READ, "process.logs": Risk.READ, "process.stop": Risk.LOW,
    "files.list": Risk.READ, "files.find": Risk.READ, "files.read": Risk.READ,
    "notes.create": Risk.WRITE, "browser.tabs": Risk.READ, "system.notify": Risk.LOW,
    "media.control": Risk.LOW, "media.search": Risk.LOW, "media.play_track": Risk.LOW,
    "system.status": Risk.READ, "system.control": Risk.LOW, "system.power": Risk.EXECUTE, "terminal.run": Risk.EXECUTE,
    "browser.control": Risk.LOW, "browser.search": Risk.LOW, "browser.media": Risk.LOW, "browser.read_page": Risk.READ, "browser.open_result": Risk.LOW,
}
_ORDER = [Risk.READ, Risk.LOW, Risk.WRITE, Risk.EXECUTE]

TOOL_TIMEOUTS = {"dev.run_script": 920.0, "dev.start_server": 100.0, "process.logs": 70.0, "files.find": 20.0, "browser.tabs": 15.0, "browser.search": 40.0, "terminal.run": 320.0}


class PolicyViolation(Exception):
    pass


def stricter(a: Risk, b: Risk) -> Risk:
    return a if _ORDER.index(a) >= _ORDER.index(b) else b


def plan_digest(plan: Plan) -> str:
    canon = json.dumps([[s.id, s.tool, s.args] for s in plan.steps], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode()).hexdigest()


class PolicyEngine:
    def __init__(self, mode: str = "standard", allowlist: set[str] | None = None):
        self.mode = mode
        self.allowlist = allowlist or set(SERVER_RISK)

    def review(self, plan: Plan, manifest: DesktopManifest) -> Plan:
        if len(plan.steps) > MAX_STEPS:
            raise PolicyViolation(f"Plan has {len(plan.steps)} steps; the limit is {MAX_STEPS}.")
        specs = {t.id: t for t in manifest.tools}
        seen: set[str] = set()
        for step in plan.steps:
            if step.id in seen:
                raise PolicyViolation(f"Duplicate step id {step.id}")
            seen.add(step.id)
            if step.tool not in self.allowlist:
                raise PolicyViolation(f"Tool '{step.tool}' is not on the server allowlist.")
            spec = specs.get(step.tool)
            if spec is None:
                raise PolicyViolation(f"Desktop does not offer tool '{step.tool}'.")
            try:
                jsonschema.validate(step.args, spec.input_schema)
            except jsonschema.ValidationError as e:
                raise PolicyViolation(f"Invalid arguments for {step.tool}: {e.message}") from e
            if step.tool == "terminal.run":
                why = check_command(str(step.args.get("command", "")))
                if why:
                    raise PolicyViolation(f"Perry won't run `{step.args.get('command')}`: {why}.")
            risk = stricter(SERVER_RISK.get(step.tool, Risk.EXECUTE), spec.risk)
            step.risk = risk
            step.requires_approval = risk in (Risk.EXECUTE, Risk.WRITE) or (
                self.mode == "strict" and risk == Risk.LOW
            )
        return plan

    @staticmethod
    def timeout_for(tool: str) -> float:
        return TOOL_TIMEOUTS.get(tool, 45.0)
