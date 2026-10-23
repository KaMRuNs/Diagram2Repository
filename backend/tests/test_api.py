import asyncio
import io
import zipfile

import httpx

from app.main import app


async def _wait_done(client: httpx.AsyncClient, job_id: str) -> dict:
    for _ in range(100):
        job = (await client.get(f"/api/jobs/{job_id}")).json()
        if job["status"] in ("done", "failed"):
            return job
        await asyncio.sleep(0.05)
    raise AssertionError("job did not finish")


async def test_sample_job_end_to_end():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        samples = (await client.get("/api/samples")).json()
        assert {"name": "ecommerce", "title": "Online Bookstore"} in samples

        job_id = (await client.post("/api/samples/ecommerce")).json()["job_id"]
        job = await _wait_done(client, job_id)
        assert job["status"] == "done", job["error"]
        assert "docker-compose.yml" in job["files"]

        resp = await client.get(job["download_url"])
        assert resp.headers["content-type"] == "application/zip"
        names = zipfile.ZipFile(io.BytesIO(resp.content)).namelist()
        assert "online-bookstore/prisma/schema.prisma" in names

        # Edit the graph (rename + port change) and regenerate without models.
        graph = job["graph"]
        api = next(n for n in graph["nodes"] if n["id"] == "orders-api")
        api["ports"] = [4000]
        resp = await client.put(f"/api/jobs/{job_id}/graph", json={"graph": graph, "use_agent": False})
        assert resp.status_code == 200
        job = await _wait_done(client, job_id)
        assert "ORDERS_API_PORT:-4000" in job["files"]["docker-compose.yml"]


async def test_unknown_job_404():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/api/jobs/nope")).status_code == 404
        assert (await client.post("/api/samples/..%2Fsecret")).status_code == 404
