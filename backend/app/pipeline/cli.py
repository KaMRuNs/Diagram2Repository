"""Run the pipeline without the UI.

python -m app.pipeline.cli path/to/photo.jpg          # full pipeline (needs Ollama)
python -m app.pipeline.cli ../samples/ecommerce.json  # tools only, no models
python -m app.pipeline.cli photo.jpg --no-agent       # models for vision, tools run deterministically
"""

import argparse
import asyncio
import json
from pathlib import Path

from app.jobs import JobStore
from app.llm import make_client
from app.pipeline.run import run_full, run_generate
from app.schemas import ArchitectureSummary, Graph


def _printer(event: dict) -> None:
    t, d = event["type"], event["data"]
    if t == "stage_started":
        print(f"▶ {d['stage']}" + (f" ({d['model']})" if d.get("model") else ""), flush=True)
    elif t == "stage_done":
        print(f"  ✓ {d['stage']} in {d['seconds']}s", flush=True)
    elif t == "progress":
        print(f"    … {d['tokens']} tokens", flush=True)
    elif t == "tool_call":
        mark = "✓" if d["ok"] else "✗"
        print(f"    {mark} [{d['by']}] {d['name']} {d.get('files') or d.get('error') or ''}", flush=True)
    elif t in ("warning", "error"):
        print(f"  ! {d['message']}", flush=True)
    elif t == "summary":
        print(json.dumps(d["summary"], indent=2))
    elif t == "graph" and not d.get("raw"):
        print(json.dumps(d["graph"], indent=1)[:3000])


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path)
    ap.add_argument("--out", type=Path, default=Path("out"))
    ap.add_argument("--no-agent", action="store_true")
    args = ap.parse_args()

    store = JobStore(3600)
    client = make_client()
    if args.input.suffix == ".json":
        data = json.loads(args.input.read_text(encoding="utf-8"))
        job = store.create(
            summary=ArchitectureSummary.model_validate(data["summary"]),
            graph=Graph.model_validate(data["graph"]),
        )
        q = job.subscribe()
        task = asyncio.create_task(run_generate(job, None if args.no_agent else client, not args.no_agent))
    else:
        job = store.create()
        q = job.subscribe()
        task = asyncio.create_task(run_full(job, client, args.input.read_bytes()))

    while not (task.done() and q.empty()):
        try:
            _printer(await asyncio.wait_for(q.get(), timeout=0.5))
        except TimeoutError:
            pass

    if job.zip_bytes:
        args.out.mkdir(parents=True, exist_ok=True)
        dest = args.out / f"{job.project_root}.zip"
        dest.write_bytes(job.zip_bytes)
        print(f"\nWrote {dest} ({len(job.files)} files)")
    else:
        print(f"\nFailed: {job.error}")
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
