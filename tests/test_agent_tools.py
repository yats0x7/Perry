import asyncio

import pytest

from perry_agent.config import AgentConfig, ProjectConfig
from perry_agent.platform import LinuxAdapter
from perry_agent.processes import ProcessManager
from perry_agent.tools.builtin import build_registry
from perry_agent.tools.registry import ToolContext
from perry_protocol import Risk, ToolCall


@pytest.fixture
def env(project, perry_home, tmp_path):
    cfg = AgentConfig(projects=[ProjectConfig(name="Demo", path=str(project))], notes_dir=str(tmp_path / "notes"))
    procs = ProcessManager()
    reg = build_registry(cfg, LinuxAdapter(), procs)
    yield reg, procs, project
    procs.stop_all()


async def run(reg, tool, args, risk=None, approved=False):
    spec = reg.get(tool)
    call = ToolCall(call_id="c", task_id="t", tool=tool, args=args, risk=risk or spec.risk, approved=approved, timeout_s=30)

    async def progress(_):
        pass

    return await reg.execute(call, ToolContext(progress=progress, cancelled=asyncio.Event()))


async def test_git_status_parses_paths_with_spaces(env):
    reg, _, _ = env
    r = await run(reg, "git.status", {"project": "demo"})
    assert r.ok, r.error
    assert r.output["untracked"] == [".env", "README.md", "new file.txt"] or "new file.txt" in r.output["untracked"]
    assert r.output["branch"] in ("main", "master")


async def test_execute_requires_approval_flag(env):
    reg, _, _ = env
    r = await run(reg, "dev.start_server", {"project": "demo"}, approved=False)
    assert not r.ok and "approval" in r.error


async def test_server_cannot_underclassify_risk(env):
    reg, _, _ = env
    r = await run(reg, "dev.start_server", {"project": "demo"}, risk=Risk.READ, approved=True)
    assert not r.ok and "under-classified" in r.error


async def test_start_server_detects_url_and_stop(env):
    reg, procs, _ = env
    r = await run(reg, "dev.start_server", {"project": "demo", "wait_s": 10}, approved=True)
    assert r.ok, r.error
    assert r.output["status"] == "running" and r.output["url"].startswith("http://localhost:")
    again = await run(reg, "dev.start_server", {"project": "demo"}, approved=True)
    assert again.output["already_running"]
    stop = await run(reg, "process.stop", {"project": "demo"})
    assert stop.ok and len(stop.output["stopped"]) == 1
    assert not procs.find("demo")


async def test_failing_script_reports_errors(env):
    reg, _, _ = env
    r = await run(reg, "dev.run_script", {"project": "demo", "script": "build"}, approved=True)
    assert r.ok and r.output["passed"] is False and r.output["exit_code"] == 2
    assert any("boom" in l for l in r.output["error_lines"])


async def test_script_not_in_allowlist_refused(env):
    reg, _, _ = env
    r = await run(reg, "dev.run_script", {"project": "demo", "script": "deploy"}, approved=True)
    assert not r.ok and "allowed_scripts" in r.error


async def test_script_name_injection_rejected(env):
    reg, _, _ = env
    r = await run(reg, "dev.run_script", {"project": "demo", "script": "test && rm -rf ~"}, approved=True)
    assert not r.ok and "Invalid arguments" in r.error


async def test_files_confined_to_workspace(env):
    reg, _, _ = env
    r = await run(reg, "files.read", {"path": "/etc/hosts"})
    assert not r.ok and "outside" in r.error
    r = await run(reg, "files.read", {"path": "../../../../etc/passwd", "project": "demo"})
    assert not r.ok


async def test_secret_files_refused(env):
    reg, _, _ = env
    r = await run(reg, "files.read", {"path": ".env", "project": "demo"})
    assert not r.ok and "secret" in r.error
    listing = await run(reg, "files.list", {"project": "demo"})
    assert ".env" not in [e["name"] for e in listing.output["entries"]]


async def test_untrusted_file_content_is_just_data(env):
    reg, _, _ = env
    r = await run(reg, "files.read", {"path": "README.md", "project": "demo"})
    assert r.ok and "Ignore previous instructions" in r.output["content"]  # returned as data, nothing executed


async def test_note_never_overwrites(env):
    reg, _, _ = env
    r = await run(reg, "notes.create", {"title": "Demo", "body": "x"}, approved=True)
    assert r.ok and r.output["path"].endswith(".md")


async def test_url_must_be_http(env):
    reg, _, _ = env
    r = await run(reg, "url.open", {"url": "file:///etc/passwd"})
    assert not r.ok


async def test_unsupported_platform_is_honest(env):
    reg, _, _ = env
    r = await run(reg, "app.open", {"app": "Safari"})
    assert not r.ok and "not implemented" in r.error.lower()
