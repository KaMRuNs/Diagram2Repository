from app.llm import LLMClient, ProgressFn, b64
from app.pipeline.prompts import render_prompt
from app.schemas import ArchitectureSummary


async def summarize(
    client: LLMClient, image_jpeg: bytes, on_progress: ProgressFn | None = None
) -> ArchitectureSummary:
    model = client.settings.vision_model
    messages = [{"role": "user", "content": render_prompt("summarize"), "images": [b64(image_jpeg)]}]
    try:
        return await client.chat_json(model, messages, ArchitectureSummary, on_progress=on_progress)
    finally:
        await client.unload(model)
