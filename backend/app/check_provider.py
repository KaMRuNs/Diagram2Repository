"""Check that the configured provider really offers what the pipeline needs.

    python -m app.check_provider            # uses .env (LLM_PROVIDER, models, keys)
    python -m app.check_provider photo.jpg  # vision check on your own image

Runs three small calls: (1) the vision model reads text from an image, (2) it returns JSON,
(3) the agent model makes a tool call. Prints PASS/FAIL per check.
"""

import asyncio
import io
import sys
import time

from PIL import Image, ImageDraw, ImageFont

from app.llm import LLMError, b64, extract_json, make_client, preprocess_image
from app.tools.registry import ollama_tool_specs


def _test_image() -> bytes:
    img = Image.new("RGB", (640, 240), "white")
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 34)
    except OSError:
        font = ImageFont.load_default()
    d.rectangle([30, 60, 270, 170], outline="black", width=4)
    d.text((55, 95), "Orders API", font=font, fill="black")
    d.rectangle([380, 60, 610, 170], outline="black", width=4)
    d.text((410, 95), "Postgres", font=font, fill="black")
    d.line([270, 115, 380, 115], fill="black", width=4)
    out = io.BytesIO()
    img.save(out, format="JPEG")
    return out.getvalue()


async def main() -> int:
    client = make_client()
    s = client.settings
    image = preprocess_image(open(sys.argv[1], "rb").read(), 1024) if len(sys.argv) > 1 else _test_image()
    print(f"provider={s.llm_provider} base={client.base}")
    ok = True

    async def check(name: str, coro) -> None:
        nonlocal ok
        t0 = time.monotonic()
        try:
            detail = await coro
            print(f"PASS {name} ({time.monotonic() - t0:.1f}s): {detail}")
        except (LLMError, ValueError, KeyError) as exc:
            ok = False
            print(f"FAIL {name}: {exc}")

    async def vision() -> str:
        msg = await client.chat(
            s.vision_model,
            [{"role": "user", "content": "List every word in this image.", "images": [b64(image)]}],
            options={"num_predict": 100},
        )
        text = msg["content"]
        if "orders" not in text.lower() and len(sys.argv) == 1:
            raise ValueError(f"model did not read the image: {text[:120]!r}")
        return text[:120].replace("\n", " ")

    async def json_out() -> str:
        msg = await client.chat(
            s.ocr_model,
            [
                {
                    "role": "user",
                    "content": 'Return JSON {"boxes": [labels of each box]}.',
                    "images": [b64(image)],
                }
            ],
            format={
                "type": "object",
                "properties": {"boxes": {"type": "array", "items": {"type": "string"}}},
            },
            options={"temperature": 0, "num_predict": 200},
        )
        return str(extract_json(msg["content"]))

    async def tools() -> str:
        msg = await client.chat(
            s.agent_model,
            [{"role": "user", "content": "Call validate_port_conflicts now. It takes no arguments."}],
            tools=ollama_tool_specs(),
            think=False,
            options={"num_predict": s.agent_num_predict},
        )
        calls = [c["function"]["name"] for c in msg.get("tool_calls") or []]
        if not calls:
            raise ValueError(f"no tool call; replied {msg['content'][:120]!r}")
        return ", ".join(calls)

    print(f"models: vision={s.vision_model} ocr={s.ocr_model} agent={s.agent_model}")
    await check("vision reads image", vision())
    await check("JSON output", json_out())
    await check("agent tool call", tools())
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
