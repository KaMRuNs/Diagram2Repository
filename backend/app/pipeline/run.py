"""Orchestrates the stages for a job and reports progress as job events."""

import asyncio
import contextlib
import logging
import time

from app.jobs import Job
from app.llm import LLMClient, LLMError, preprocess_image
from app.pipeline.agent import run_agent, run_deterministic
from app.pipeline.extract import extract_graph
from app.pipeline.normalize import normalize_graph
from app.pipeline.summarize import summarize
from app.schemas import ArchitectureSummary, Graph
from app.tools.registry import ToolContext
from app.tools.stack import apply_stack

log = logging.getLogger(__name__)

# One model in RAM at a time on the dev box, so jobs never run local model stages concurrently.
MODEL_LOCK = asyncio.Lock()


def model_lock(client: LLMClient) -> contextlib.AbstractAsyncContextManager:
    """Serialize local inference; hosted inference has no shared RAM, so jobs may overlap."""
    return MODEL_LOCK if client.local else contextlib.nullcontext()


class _Stage:
    def __init__(self, job: Job, name: str, status, model: str | None = None):
        self.job, self.name, self.status, self.model = job, name, status, model

    async def __aenter__(self):
        self.t0 = time.monotonic()
        self.job.set_status(self.status)
        self.job.publish("stage_started", {"stage": self.name, "model": self.model})
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if exc is None:
            self.job.publish(
                "stage_done", {"stage": self.name, "seconds": round(time.monotonic() - self.t0, 1)}
            )
        return False

    async def progress(self, tokens: int) -> None:
        self.job.publish("progress", {"stage": self.name, "tokens": tokens})


def fallback_summary(graph: Graph) -> ArchitectureSummary:
    names = [n.label for n in graph.nodes]
    return ArchitectureSummary(
        title="Whiteboard Project",
        description="Starter repository generated from a whiteboard diagram with "
        + (", ".join(names[:6]) or "a database schema")
        + ".",
        data_flow=" → ".join(names[:6]),
    )


async def _generate(job: Job, client: LLMClient | None, use_agent: bool) -> None:
    async with _Stage(job, "normalize", "normalizing"):
        graph, warnings = normalize_graph(job.graph)
        job.graph = graph
        job.warnings.extend(warnings)
        for w in warnings:
            job.publish("warning", {"message": w})
        job.publish("graph", {"graph": graph.model_dump()})

    ctx = ToolContext(
        # The chosen stack only shapes the generated files; the canvas keeps the graph as drawn.
        graph=apply_stack(graph, job.options.stack),
        summary=job.summary or fallback_summary(graph),
        options=job.options,
        download_url=f"/api/jobs/{job.id}/download",
    )

    async def emit(type_: str, data: dict) -> None:
        job.publish(type_, data)

    model = client.settings.agent_model if (client and use_agent) else None
    async with _Stage(job, "generate", "generating", model):
        if client and use_agent:
            async with model_lock(client):
                await run_agent(client, ctx, emit)
        else:
            await run_deterministic(ctx, emit)

    job.files, job.zip_bytes, job.project_root = ctx.files, ctx.zip_bytes, ctx.project_root
    job.warnings.extend(w for w in ctx.warnings if w not in job.warnings)
    job.set_status("done")
    job.publish("done", {"download_url": f"/api/jobs/{job.id}/download", "files": sorted(job.files)})


async def _guard(job: Job, coro) -> None:
    try:
        await coro
    except (LLMError, ValueError) as exc:
        job.error = str(exc)
        job.set_status("failed")
        job.publish("error", {"message": str(exc)})
    except Exception as exc:  # never leave a job hanging in a running state
        log.exception("job %s crashed", job.id)
        job.error = f"Internal error: {exc}"
        job.set_status("failed")
        job.publish("error", {"message": job.error})


async def run_full(job: Job, client: LLMClient, raw_image: bytes) -> None:
    async def body():
        s = client.settings
        async with _Stage(job, "preprocess", "preprocessing"):
            job.image = await asyncio.to_thread(preprocess_image, raw_image, s.image_max_side)

        async with model_lock(client):
            async with _Stage(job, "summarize", "summarizing", s.vision_model) as st:
                try:
                    job.summary = await summarize(client, job.image, on_progress=st.progress)
                    job.publish("summary", {"summary": job.summary.model_dump()})
                except LLMError as exc:
                    msg = f"Summary stage failed ({exc}); continuing without it."
                    job.warnings.append(msg)
                    job.publish("warning", {"message": msg})

            async with _Stage(job, "extract", "extracting", s.ocr_model) as st:
                job.graph = await extract_graph(client, job.image, job.summary, on_progress=st.progress)
                job.publish("graph", {"graph": job.graph.model_dump(), "raw": True})

        await _generate(job, client, use_agent=True)

    await _guard(job, body())


async def run_generate(job: Job, client: LLMClient | None, use_agent: bool) -> None:
    job.error = None
    job.warnings = []
    await _guard(job, _generate(job, client, use_agent))
