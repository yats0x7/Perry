"""Optional LLM planners. The reasoning provider is pluggable; the policy is not.

* `OpenAICompatPlanner` – any OpenAI-compatible /chat/completions endpoint, e.g. Gnani
  Evon v3.3 (30B-A3B) self-hosted behind SGLang/vLLM, as described on its Hugging Face card.

Both only *propose* a plan. The orchestrator always runs `PolicyEngine.review` on it, and
falls back to the deterministic `RulePlanner` (disclosed in the task timeline) if the
provider errors. Untrusted content (files, logs, web pages) is never sent to the planner:
it plans from the user's command plus the desktop's tool/project manifest only.
"""

from __future__ import annotations

import json
import logging
import re

import httpx

from perry_protocol import Plan, PlanStep

from ..config import Settings
from .planner import Planner, PlanningContext, RulePlanner, normalize

log = logging.getLogger("perry.llm")

SYSTEM = """You are the planning module of Perry, a voice assistant that controls the user's computer.
Users speak English, Hindi or Hinglish (code-mixed, often transcribed in Latin script, sometimes
with recognition errors — e.g. a project name heard as a similar-sounding phrase).

Turn the command into an ordered list of tool calls using ONLY the tools listed. Rules:
- Use the exact tool ids and argument names from the tool schemas. args_json is a JSON object string.
- Refer to projects by their id from the project list; resolve mis-heard names by sound.
- Never invent tools, shell commands, file paths outside projects, or scripts that are not listed.
- If the request cannot be done with these tools, or is ambiguous, return no steps and put a short,
  friendly reply in reply_without_action (in the user's language style, Hinglish if they used Hinglish).
- reason: a short English description of each step shown to the user before approval.
- You do not execute anything and you never decide what needs approval.
- If a command could mean opposite things (e.g. "sleep" vs "don't sleep"), choose the harmless reading or
  ask; never pick a disruptive action (sleep, restart, shutdown, delete) on a guess.
- Commands come from speech recognition, which often mishears: project names become similar-sounding
  words ("the new", "dinu", "denio" for "Dineo"), "kholo"→"holo", "git"→"get", "tab"→"top", "pe"→"pay".
  When exactly one configured project sounds like what was said, use it instead of asking.
- If the user asks whether errors are coming after starting a server, add process.logs after dev.start_server.
- Music: play/resume/pause/next/previous/"what's playing" → media.control. A named song or artist → media.search
  (Spotify) or, if YouTube is mentioned, browser.search with site=youtube and play_first=true. Never use
  app.open / app.focus as a substitute for actually playing or pausing.
- Websites: "open X on/in <browser>" → url.open with that browser. Tabs, back/forward, reload → browser.control.
- Mac settings: volume/mute/brightness/dark mode/keep awake ("don't let the Mac sleep" = system.control keep_awake,
  NOT pmset/sudo)/screenshot → system.control; sleep/lock/restart/shutdown → system.power; battery → system.status.
- terminal.run: only when no dedicated tool fits (e.g. "disk space kitna hai" → `df -h /`, "port 3000 kaun use kar
  raha hai" → `lsof -nP -iTCP:3000 -sTCP:LISTEN`, "ngrok chalao" → background=true). One command per step, read-only
  where possible. Spoken dictation must be converted to real syntax ("minus la" → "-la", "pipe" → "|").
  Never use sudo (Perry can't type passwords) and never destructive commands — reply explaining instead.
  If the user names a project, set cwd to that project's id."""

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "understanding": {"type": "string"},
        "project_id": {"type": "string"},
        "reply_without_action": {"type": "string"},
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "tool": {"type": "string"},
                    "args_json": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["tool", "args_json", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["understanding", "project_id", "reply_without_action", "steps"],
    "additionalProperties": False,
}


def _context_block(text: str, ctx: PlanningContext) -> str:
    m = ctx.manifest
    tools = [{"id": t.id, "description": t.description, "args_schema": t.input_schema.get("properties", {}),
              "required": t.input_schema.get("required", [])} for t in m.tools]
    projects = [{"id": p.id, "name": p.name, "aliases": p.aliases, "scripts": p.scripts, "git": p.has_git}
                for p in m.projects]
    history = [{"user": u, "assistant": a} for u, a in ctx.history[-3:]]
    return json.dumps({
        "desktop": {"os": m.platform, "editor": m.editor, "installed_apps_sample": m.apps[:150]},
        "tools": tools, "projects": projects, "last_project_id": ctx.last_project_id,
        "recent_turns": history, "command": text, "command_after_asr_corrections": normalize(text),
    }, ensure_ascii=False)


def _to_plan(data: dict, planner: str) -> Plan:
    steps = []
    for i, s in enumerate(data.get("steps") or []):
        try:
            args = json.loads(s.get("args_json") or "{}")
        except json.JSONDecodeError:
            args = {"__invalid__": s.get("args_json")}  # policy will reject it
        steps.append(PlanStep(id=f"s{i + 1}", tool=str(s.get("tool", "")), args=args if isinstance(args, dict) else {},
                              reason=str(s.get("reason", ""))[:200]))
    return Plan(steps=steps, understanding=str(data.get("understanding", ""))[:400], planner=planner,
                project_id=data.get("project_id") or None,
                reply_without_action=(data.get("reply_without_action") or None) if not steps else None)


class OpenAICompatPlanner(Planner):
    def __init__(self, base_url: str, api_key: str, model: str, reasoning_effort: str = "low"):
        self.base = base_url.rstrip("/")
        self.key = api_key
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.name = f"openai-compat:{model}"
        self.http = httpx.AsyncClient(timeout=30)

    async def plan(self, text: str, ctx: PlanningContext) -> Plan:
        headers = {"Authorization": f"Bearer {self.key}"} if self.key else {}
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM + "\nReply with ONLY a JSON object matching this schema: "
                 + json.dumps(PLAN_SCHEMA)},
                {"role": "user", "content": _context_block(text, ctx)},
            ],
            "response_format": {"type": "json_object"},
        }
        # Reasoning models (o-series, GPT-5.x) reject temperature; give them a low effort instead.
        if re.match(r"^(o\d|gpt-5)", self.model.split("/")[-1]):
            payload["reasoning_effort"] = self.reasoning_effort
        else:
            payload["temperature"] = 0
        for _ in range(3):
            r = await self.http.post(f"{self.base}/chat/completions", headers=headers, json=payload)
            if r.status_code == 400:
                msg = r.text
                dropped = [k for k in ("reasoning_effort", "temperature", "response_format") if k in payload and k in msg]
                if dropped:
                    for k in dropped:
                        payload.pop(k)
                    continue
            break
        if r.status_code >= 400:
            raise RuntimeError(f"LLM HTTP {r.status_code}: {r.text[:200]}")
        content = r.json()["choices"][0]["message"]["content"]
        content = re.sub(r"^```(?:json)?|```$", "", content.strip(), flags=re.M).strip()
        # reasoning models may emit <think>…</think> before the JSON
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()
        return _to_plan(json.loads(content), self.name)


class HybridPlanner(Planner):
    """Rules first (instant, tuned on real Prisma output); the LLM only when the rules can't
    fully handle the command. Either way the result still goes through the PolicyEngine."""

    def __init__(self, rules: RulePlanner, llm: Planner):
        self.rules, self.llm = rules, llm
        self.name = f"rules+{llm.name}"

    async def plan(self, text: str, ctx: PlanningContext) -> Plan:
        p = await self.rules.plan(text, ctx)
        if p.steps and "(ignored:" not in p.understanding:
            p.planner = self.rules.name
            return p
        try:
            q = await self.llm.plan(text, ctx)
        except Exception as e:  # noqa: BLE001 — LLM outage: keep the rule result (disclosed by planner name)
            log.warning("LLM planner failed (%s); using rules", e)
            return p
        if not q.steps and not q.reply_without_action:
            return p
        return q


def build_planner(s: Settings) -> Planner:
    choice = s.planner
    if choice == "auto":
        choice = "openai_compat" if s.llm_base_url else "rules"
    if choice == "openai_compat" and s.llm_base_url:
        return HybridPlanner(RulePlanner(), OpenAICompatPlanner(s.llm_base_url, s.llm_api_key, s.llm_model,
                                                                s.llm_reasoning_effort))
    return RulePlanner()
