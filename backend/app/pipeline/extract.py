from app.llm import LLMClient, ProgressFn, b64
from app.pipeline.prompts import render_prompt
from app.schemas import ArchitectureSummary, Graph


async def extract_graph(
    client: LLMClient,
    image_jpeg: bytes,
    summary: ArchitectureSummary | None,
    on_progress: ProgressFn | None = None,
) -> Graph:
    model = client.settings.ocr_model
    hint = f"{summary.title}: {summary.description}\nData flow: {summary.data_flow}" if summary else "(none)"
    messages = [
        {"role": "user", "content": render_prompt("extract", summary=hint), "images": [b64(image_jpeg)]}
    ]
    try:
        return await client.chat_json(model, messages, Graph, on_progress=on_progress)
    finally:
        await client.unload(model)
