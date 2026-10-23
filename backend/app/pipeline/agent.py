"""Stage 3: the tool-calling agent, plus a deterministic fallback so a run always finishes."""

import json
from collections.abc import Awaitable, Callable

from app.llm import LLMClient, LLMError, strip_think
from app.pipeline.prompts import render_prompt
from app.tools.registry import ToolContext, dispatch, ollama_tool_specs, required_tools

Emit = Callable[[str, dict], Awaitable[None]]


def _system_prompt(ctx: ToolContext) -> str:
    # Kept short on purpose: on CPU every prompt token costs ~50 ms, and the tools hold the real graph.
    order = "\n".join(f"{i}. {name}" for i, name in enumerate(required_tools(ctx), 1))
    components = ", ".join(
        f"{n.label} ({n.kind}{', :' + str(n.ports[0]) if n.ports else ''})" for n in ctx.graph.nodes
    )
    return render_prompt(
        "agent",
        tool_order=order,
        license_type=ctx.options.license_type,
        summary=f"{ctx.summary.title}: {ctx.summary.description}".strip(": "),
        components=components or "none",
        tables=", ".join(t.name for t in ctx.graph.tables) or "none",
    )


def _parse_args(raw: object) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


async def _run_tool(ctx: ToolContext, name: str, args: dict, emit: Emit, by: str) -> dict:
    result = dispatch(ctx, name, args)
    await emit(
        "tool_call",
        {
            "name": name,
            "args": args,
            "ok": result.get("ok", False),
            "by": by,
            "files": result.get("files_written", []),
            "error": result.get("error"),
        },
    )
    return result


async def run_agent(client: LLMClient, ctx: ToolContext, emit: Emit) -> None:
    settings = client.settings
    model = settings.agent_model
    messages: list[dict] = [
        {"role": "system", "content": _system_prompt(ctx)},
        {"role": "user", "content": "Build the repository now. /no_think"},
    ]
    tools = ollama_tool_specs()
    call_counts: dict[str, int] = {}
    bad_turns = 0

    try:
        for _turn in range(settings.agent_max_turns):
            if "bundle_zip_download" in ctx.completed:
                break
            try:
                # No temperature override: greedy decoding makes Qwen3 repeat itself endlessly.
                msg = await client.chat(
                    model,
                    messages,
                    tools=tools,
                    think=settings.agent_think,
                    keep_alive="5m",
                    options={"num_ctx": 4096, "num_predict": settings.agent_num_predict},
                )
            except LLMError as exc:
                await emit(
                    "warning", {"message": f"Agent model failed ({exc}); finishing deterministically."}
                )
                break

            calls = msg.get("tool_calls") or []
            messages.append({"role": "assistant", "content": msg.get("content", ""), "tool_calls": calls})
            if not calls:
                text = strip_think(msg.get("content", "")).strip()
                if text:
                    await emit("agent_message", {"text": text[:500]})
                if "bundle_zip_download" in ctx.completed:
                    break
                bad_turns += 1
                if bad_turns >= 2:
                    break
                missing = [t for t in required_tools(ctx) if t not in ctx.completed]
                messages.append({"role": "user", "content": f"Not done yet. Call {missing[0]} next."})
                continue

            for call in calls:
                fn = call.get("function", {})
                name = fn.get("name", "")
                call_counts[name] = call_counts.get(name, 0) + 1
                if call_counts[name] > 2:
                    result = {"ok": False, "error": f"{name} already ran. Call the next tool in the list."}
                else:
                    result = await _run_tool(ctx, name, _parse_args(fn.get("arguments")), emit, by="agent")
                messages.append({"role": "tool", "tool_name": name, "content": json.dumps(result)[:2000]})
            if max(call_counts.values(), default=0) > 3:
                await emit("warning", {"message": "Agent is looping; finishing deterministically."})
                break
    finally:
        await client.unload(model)

    missing = [t for t in required_tools(ctx) if t not in ctx.completed]
    if missing:
        await emit("warning", {"message": f"Agent skipped {', '.join(missing)}; running them automatically."})
    for name in missing:
        await _run_tool(ctx, name, {}, emit, by="fallback")


async def run_deterministic(ctx: ToolContext, emit: Emit) -> None:
    """Same tools, no model: used for samples and for re-generation after graph edits when asked."""
    for name in required_tools(ctx):
        if name not in ctx.completed:
            await _run_tool(ctx, name, {}, emit, by="fallback")
