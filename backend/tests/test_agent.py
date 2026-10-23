"""Agent loop against a scripted fake model: happy path, skipped tools, and model failure."""

from app.config import Settings
from app.llm import LLMError
from app.pipeline.agent import run_agent
from app.tools.registry import ToolContext, required_tools


def _call(name: str, **args) -> dict:
    return {"function": {"name": name, "arguments": args}}


class FakeClient:
    def __init__(self, replies: list):
        self.settings = Settings(agent_max_turns=8)
        self.replies = list(replies)
        self.calls = 0

    async def chat(self, model, messages, **kwargs):
        self.calls += 1
        if not self.replies:
            return {"role": "assistant", "content": "Done."}
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return {"role": "assistant", "content": "", "tool_calls": reply}

    async def unload(self, model):
        pass


async def _collect(client, ctx):
    events = []

    async def emit(t, d):
        events.append((t, d))

    await run_agent(client, ctx, emit)
    return events


async def test_agent_happy_path(ecommerce):
    summary, graph = ecommerce
    ctx = ToolContext(graph=graph, summary=summary)
    script = [[_call(n)] for n in required_tools(ctx)]
    script[3] = [_call("generate_readme_and_license", license_type="BSD-3-Clause", project_name="Bookshop")]
    events = await _collect(FakeClient(script), ctx)
    assert ctx.zip_bytes and set(ctx.completed) == set(required_tools(ctx))
    assert all(d["by"] == "agent" for t, d in events if t == "tool_call")
    assert "BSD 3-Clause" in ctx.files["LICENSE"]
    # the vision summary's title beats the model's invented name
    assert ctx.files["README.md"].startswith("# Online Bookstore")


async def test_model_names_untitled_project_but_not_with_placeholders(ecommerce):
    from app.schemas import ArchitectureSummary

    _, graph = ecommerce
    for name, expected in [("Bookshop", "# Bookshop"), ("your-project-name", "# Whiteboard Project")]:
        ctx = ToolContext(graph=graph, summary=ArchitectureSummary())
        script = [[_call("generate_readme_and_license", project_name=name, author="YourName")]]
        await _collect(FakeClient(script), ctx)
        assert ctx.files["README.md"].startswith(expected)
        assert "YourName" not in ctx.files["LICENSE"]


async def test_user_license_choice_beats_model(ecommerce):
    from app.schemas import GenerateOptions

    summary, graph = ecommerce
    ctx = ToolContext(graph=graph, summary=summary, options=GenerateOptions(license_type="Apache-2.0"))
    await _collect(FakeClient([[_call("generate_readme_and_license", license_type="MIT")]]), ctx)
    assert "Apache License" in ctx.files["LICENSE"]


async def test_fallback_finishes_when_model_stops_early(ecommerce):
    summary, graph = ecommerce
    ctx = ToolContext(graph=graph, summary=summary)
    events = await _collect(FakeClient([[_call("validate_port_conflicts")]]), ctx)
    assert ctx.zip_bytes is not None
    assert any(t == "tool_call" and d["by"] == "fallback" for t, d in events)
    assert any(t == "warning" for t, _ in events)


async def test_fallback_when_model_errors(chat):
    summary, graph = chat
    ctx = ToolContext(graph=graph, summary=summary)
    await _collect(FakeClient([LLMError("boom")]), ctx)
    assert ctx.zip_bytes is not None and "docker-compose.yml" in ctx.files
    assert "generate_db_schema" not in ctx.completed  # no tables in this sample


async def test_bad_tool_name_and_early_bundle_are_reported(ecommerce):
    summary, graph = ecommerce
    ctx = ToolContext(graph=graph, summary=summary)
    events = await _collect(FakeClient([[_call("rm_rf")], [_call("bundle_zip_download")]]), ctx)
    errors = [d["error"] for t, d in events if t == "tool_call" and not d["ok"]]
    assert any("Unknown tool" in e for e in errors)
    assert any("first" in e for e in errors)
    assert ctx.zip_bytes is not None
