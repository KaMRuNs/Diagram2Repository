"""In-memory job store with an event log that feeds SSE (no database: jobs expire after an hour)."""

import asyncio
import time
import uuid
from dataclasses import dataclass, field

from app.schemas import ArchitectureSummary, GenerateOptions, Graph, JobStatus


@dataclass
class Job:
    id: str
    created_at: float = field(default_factory=time.time)
    status: JobStatus = "queued"
    source: str = "upload"
    image: bytes | None = None
    summary: ArchitectureSummary | None = None
    graph: Graph | None = None
    options: GenerateOptions = field(default_factory=GenerateOptions)
    files: dict[str, str] = field(default_factory=dict)
    zip_bytes: bytes | None = None
    project_root: str = "project"
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    events: list[dict] = field(default_factory=list)
    _listeners: list[asyncio.Queue] = field(default_factory=list, repr=False)

    def publish(self, type_: str, data: dict | None = None) -> dict:
        event = {"seq": len(self.events) + 1, "type": type_, "data": data or {}, "ts": time.time()}
        self.events.append(event)
        for q in self._listeners:
            q.put_nowait(event)
        return event

    def set_status(self, status: JobStatus) -> None:
        self.status = status
        self.publish("status", {"status": status})

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._listeners.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._listeners:
            self._listeners.remove(q)

    def view(self) -> dict:
        return {
            "id": self.id,
            "status": self.status,
            "source": self.source,
            "has_image": self.image is not None,
            "summary": self.summary.model_dump() if self.summary else None,
            "graph": self.graph.model_dump() if self.graph else None,
            "options": self.options.model_dump(),
            "files": self.files,
            "warnings": self.warnings,
            "error": self.error,
            "download_url": f"/api/jobs/{self.id}/download" if self.zip_bytes else None,
            "last_seq": len(self.events),
        }


class JobStore:
    def __init__(self, ttl_seconds: int):
        self.ttl = ttl_seconds
        self._jobs: dict[str, Job] = {}

    def create(self, **kwargs) -> Job:
        self._purge()
        job = Job(id=uuid.uuid4().hex[:12], **kwargs)
        self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def _purge(self) -> None:
        cutoff = time.time() - self.ttl
        for jid in [j.id for j in self._jobs.values() if j.created_at < cutoff]:
            del self._jobs[jid]
