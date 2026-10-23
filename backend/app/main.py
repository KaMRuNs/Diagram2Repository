import asyncio
import json
import logging

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import get_settings
from app.jobs import Job, JobStore
from app.llm import make_client
from app.pipeline.run import run_full, run_generate
from app.schemas import ArchitectureSummary, GenerateOptions, Graph, LicenseType

logging.basicConfig(level=logging.INFO)
settings = get_settings()
app = FastAPI(title="Diagram2Repo")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
store = JobStore(settings.job_ttl_seconds)
client = make_client(settings)  # local Ollama, or the hosted provider when LLM_PROVIDER=hosted
_tasks: set[asyncio.Task] = set()
MAX_UPLOAD = 15 * 1024 * 1024


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def _job(job_id: str) -> Job:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found or expired")
    return job


def _busy(job: Job) -> bool:
    return job.status not in ("done", "failed")


@app.get("/api/health")
async def health() -> dict:
    """`reachable`: Ollama or the hosted provider answered. `installed`: the model is available there."""
    provider = settings.llm_provider
    roles = {"vision": settings.vision_model, "ocr": settings.ocr_model, "agent": settings.agent_model}
    try:
        available = await client.list_models()
    except httpx.HTTPError:
        models = {r: {"name": m, "installed": False} for r, m in roles.items()}
        return {"provider": provider, "reachable": False, "models": models}

    def has(name: str) -> bool:
        return name in available or f"{name}:latest" in available

    models = {r: {"name": m, "installed": has(m)} for r, m in roles.items()}
    return {"provider": provider, "reachable": True, "models": models}


@app.get("/api/samples")
async def list_samples() -> list[dict]:
    out = []
    for path in sorted(settings.samples_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        out.append({"name": path.stem, "title": data.get("summary", {}).get("title", path.stem)})
    return out


@app.post("/api/samples/{name}")
async def start_sample(name: str) -> dict:
    path = settings.samples_dir / f"{name}.json"
    if not name.replace("-", "").replace("_", "").isalnum() or not path.exists():
        raise HTTPException(404, "Unknown sample")
    data = json.loads(path.read_text(encoding="utf-8"))
    job = store.create(
        source="sample",
        summary=ArchitectureSummary.model_validate(data["summary"]),
        graph=Graph.model_validate(data["graph"]),
    )
    job.publish("summary", {"summary": job.summary.model_dump()})
    _spawn(run_generate(job, None, use_agent=False))
    return {"job_id": job.id}


@app.post("/api/jobs")
async def create_job(
    image: UploadFile = File(...),
    license_type: LicenseType = Form("MIT"),
    author: str = Form("Your Name"),
) -> dict:
    data = await image.read()
    if not data:
        raise HTTPException(400, "Empty upload")
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "Image larger than 15 MB")
    job = store.create(options=GenerateOptions(license_type=license_type, author=author))
    _spawn(run_full(job, client, data))
    return {"job_id": job.id}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str) -> dict:
    return _job(job_id).view()


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str, request: Request, after: int = 0) -> StreamingResponse:
    job = _job(job_id)
    last_id = request.headers.get("last-event-id")
    start = int(last_id) if last_id and last_id.isdigit() else after

    async def stream():
        q = job.subscribe()
        try:
            for event in job.events[start:]:
                yield f"id: {event['seq']}\ndata: {json.dumps(event)}\n\n"
            seen = len(job.events)
            while not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15)
                except TimeoutError:
                    yield ": ping\n\n"
                    continue
                if event["seq"] <= max(seen, start):
                    continue
                yield f"id: {event['seq']}\ndata: {json.dumps(event)}\n\n"
        finally:
            job.unsubscribe(q)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


class RegenerateBody(BaseModel):
    graph: Graph
    options: GenerateOptions | None = None
    use_agent: bool = True


@app.put("/api/jobs/{job_id}/graph")
async def regenerate(job_id: str, body: RegenerateBody) -> dict:
    job = _job(job_id)
    if _busy(job):
        raise HTTPException(409, "Job is still running")
    job.graph = body.graph
    if body.options:
        job.options = body.options
    job.set_status("queued")
    _spawn(run_generate(job, client, use_agent=body.use_agent))
    return {"job_id": job.id}


@app.get("/api/jobs/{job_id}/download")
async def download(job_id: str) -> Response:
    job = _job(job_id)
    if not job.zip_bytes:
        raise HTTPException(404, "Repository not generated yet")
    return Response(
        job.zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{job.project_root}.zip"'},
    )


@app.get("/api/jobs/{job_id}/image")
async def job_image(job_id: str) -> Response:
    job = _job(job_id)
    if not job.image:
        raise HTTPException(404, "No image for this job")
    return Response(job.image, media_type="image/jpeg")


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE"], include_in_schema=False)
async def api_not_found(path: str) -> None:
    # Keep unknown /api paths as JSON 404s instead of falling through to the static frontend.
    raise HTTPException(404, "Not found")


if settings.frontend_dist.exists():
    app.mount("/", StaticFiles(directory=settings.frontend_dist, html=True), name="frontend")
