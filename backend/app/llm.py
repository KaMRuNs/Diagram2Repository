"""The only place that talks to Ollama (native /api endpoints)."""

import base64
import copy
import io
import json
import re
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import httpx
from PIL import Image, ImageOps
from pydantic import BaseModel, ValidationError

from app.config import Settings, get_settings

T = TypeVar("T", bound=BaseModel)
ProgressFn = Callable[[int], Awaitable[None]]


class LLMError(RuntimeError):
    pass


# ---------- text helpers ----------

_THINK = re.compile(r"<think>.*?</think>", re.S)
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def strip_think(text: str) -> str:
    text = _THINK.sub("", text)
    return text.split("</think>", 1)[1] if "</think>" in text else text


def extract_json(text: str) -> Any:
    """Pull the first JSON object out of a model reply (handles <think>, fences and prose)."""
    text = strip_think(text).strip()
    fenced = _FENCE.search(text)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    raise ValueError("no JSON object found in model output")


def inline_schema(model: type[BaseModel]) -> dict:
    """JSON schema with $defs inlined (simpler for Ollama's grammar converter)."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return resolve(copy.deepcopy(defs[node["$ref"].split("/")[-1]]))
            # drop "title" annotations (strings), but keep a *property* named "title" (a dict)
            return {k: resolve(v) for k, v in node.items() if not (k == "title" and isinstance(v, str))}
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    return resolve(schema)


# ---------- images ----------


def preprocess_image(data: bytes, max_side: int) -> bytes:
    """EXIF-rotate, downscale and boost contrast so small VL models read the board better."""
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((max_side, max_side))
    img = ImageOps.autocontrast(img, cutoff=1)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=90)
    return out.getvalue()


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


# ---------- clients ----------


class LLMClient:
    """Shared interface. Pipeline code only uses: settings, local, chat, chat_json, unload, list_models.

    Messages and replies use Ollama's shape everywhere (images in `messages[].images`, tool calls as
    `{"function": {"name", "arguments": dict}}`, tool results as `{"role": "tool", "tool_name"}`);
    other clients translate at the edge.
    """

    local = True  # models share this machine's RAM -> run one at a time

    def __init__(self, base_url: str, settings: Settings | None, transport: httpx.AsyncBaseTransport | None):
        self.settings = settings or get_settings()
        self.base = base_url.rstrip("/")
        self._transport = transport  # tests inject httpx.MockTransport

    def _client(self, timeout: float | None = None, headers: dict | None = None) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base,
            headers=headers,
            transport=self._transport,
            timeout=httpx.Timeout(timeout or self.settings.llm_timeout, connect=10),
        )

    async def chat(self, model: str, messages: list[dict], **kwargs: Any) -> dict:
        raise NotImplementedError

    async def unload(self, model: str) -> None:
        pass

    async def list_models(self) -> list[str]:
        raise NotImplementedError

    async def chat_json(
        self,
        model: str,
        messages: list[dict],
        schema: type[T],
        *,
        on_progress: ProgressFn | None = None,
    ) -> T:
        """Schema-constrained call, validated with pydantic, with one repair retry."""
        fmt = inline_schema(schema)
        # Greedy is fine for constrained JSON; the cap stops a runaway generation on CPU.
        opts = {"temperature": 0, "num_predict": self.settings.json_num_predict}
        msg = await self.chat(model, messages, format=fmt, options=opts, on_progress=on_progress)
        try:
            return schema.model_validate(extract_json(msg["content"]))
        except (ValueError, ValidationError) as exc:
            repair = messages + [
                {"role": "assistant", "content": msg["content"]},
                {
                    "role": "user",
                    "content": f"That output was invalid ({str(exc)[:400]}). "
                    "Reply with ONLY the corrected JSON object.",
                },
            ]
            msg = await self.chat(model, repair, format=fmt, options=opts, on_progress=on_progress)
            try:
                return schema.model_validate(extract_json(msg["content"]))
            except (ValueError, ValidationError) as exc2:
                raise LLMError(f"{model} returned invalid JSON twice: {str(exc2)[:300]}") from exc2


class OllamaClient(LLMClient):
    def __init__(self, settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None):
        s = settings or get_settings()
        super().__init__(s.ollama_base_url, s, transport)

    async def chat(
        self,
        model: str,
        messages: list[dict],
        *,
        format: dict | None = None,
        tools: list[dict] | None = None,
        think: bool | None = None,
        keep_alive: str | int = "5m",
        options: dict | None = None,
        on_progress: ProgressFn | None = None,
    ) -> dict:
        """Return the assistant message dict ({role, content, tool_calls?})."""
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "keep_alive": keep_alive,
            "options": {"num_ctx": 8192, **(options or {})},
            "stream": on_progress is not None and not tools,
        }
        if format is not None:
            body["format"] = format
        if tools:
            body["tools"] = tools
        if think is not None:
            body["think"] = think

        async with self._client() as client:
            try:
                return await self._send(client, body, on_progress)
            except LLMError as exc:
                if "think" in body and "think" in str(exc).lower():
                    body.pop("think")  # model doesn't support the think flag
                    return await self._send(client, body, on_progress)
                raise
            except httpx.ConnectError as exc:
                raise LLMError(f"Cannot reach Ollama at {self.base}. Is it running?") from exc
            except httpx.TimeoutException as exc:
                raise LLMError(f"{model} timed out after {self.settings.llm_timeout:.0f}s") from exc

    async def _send(self, client: httpx.AsyncClient, body: dict, on_progress: ProgressFn | None) -> dict:
        if not body["stream"]:
            resp = await client.post("/api/chat", json=body)
            if resp.status_code >= 400:
                raise LLMError(f"Ollama {resp.status_code}: {resp.text[:300]}")
            return resp.json()["message"]

        parts: list[str] = []
        tokens = 0
        async with client.stream("POST", "/api/chat", json=body) as resp:
            if resp.status_code >= 400:
                raise LLMError(f"Ollama {resp.status_code}: {(await resp.aread()).decode()[:300]}")
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                chunk = json.loads(line)
                if "error" in chunk:
                    raise LLMError(f"Ollama: {chunk['error']}")
                parts.append(chunk.get("message", {}).get("content", ""))
                tokens += 1
                if on_progress and tokens % 25 == 0:
                    await on_progress(tokens)
        return {"role": "assistant", "content": "".join(parts)}

    async def unload(self, model: str) -> None:
        """Free RAM: the dev box can only hold one model at a time."""
        try:
            async with self._client() as client:
                await client.post("/api/generate", json={"model": model, "keep_alive": 0})
        except httpx.HTTPError:
            pass

    async def list_models(self) -> list[str]:
        async with self._client(timeout=5) as client:
            resp = await client.get("/api/tags")
            resp.raise_for_status()
            return [m["name"] for m in resp.json().get("models", [])]


# ---------- hosted (OpenAI-compatible) ----------


def to_openai_messages(messages: list[dict]) -> list[dict]:
    """Ollama-shaped messages -> OpenAI chat format (image parts, tool-call ids)."""
    out: list[dict] = []
    pending_ids: list[str] = []  # ids of the last assistant tool calls, consumed by tool results
    for i, m in enumerate(messages):
        role = m["role"]
        if role == "tool":
            call_id = pending_ids.pop(0) if pending_ids else f"call_{i}"
            out.append({"role": "tool", "tool_call_id": call_id, "content": m.get("content", "")})
            continue
        msg: dict[str, Any] = {"role": role}
        images = m.get("images") or []
        if images:
            msg["content"] = [{"type": "text", "text": m.get("content", "")}] + [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img}"}} for img in images
            ]
        else:
            msg["content"] = m.get("content", "")
        if role == "assistant" and m.get("tool_calls"):
            calls = []
            for j, call in enumerate(m["tool_calls"]):
                fn = call.get("function", {})
                call_id = call.get("id") or f"call_{i}_{j}"
                args = fn.get("arguments", {})
                calls.append(
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": fn.get("name", ""),
                            "arguments": args if isinstance(args, str) else json.dumps(args),
                        },
                    }
                )
            msg["tool_calls"] = calls
            pending_ids = [c["id"] for c in calls]
        out.append(msg)
    return out


def from_openai_message(msg: dict) -> dict:
    """OpenAI assistant message -> Ollama shape (tool-call arguments parsed to dicts)."""
    calls = []
    for call in msg.get("tool_calls") or []:
        fn = call.get("function", {})
        raw = fn.get("arguments") or "{}"
        try:
            args = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError:
            args = {}
        calls.append({"id": call.get("id"), "function": {"name": fn.get("name", ""), "arguments": args}})
    reply: dict[str, Any] = {"role": "assistant", "content": msg.get("content") or ""}
    if calls:
        reply["tool_calls"] = calls
    return reply


class HostedClient(LLMClient):
    """Open-weight models served by an OpenAI-compatible provider, for deployments without a GPU.

    Same models and prompts as local Ollama; only transport differs. No streaming (hosted inference
    answers in seconds), no unloading, and stages may run concurrently.
    """

    local = False

    def __init__(
        self,
        settings: Settings | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
    ):
        s = settings or get_settings()
        super().__init__(base_url or s.hosted_base_url, s, transport)
        key = s.hosted_api_key if api_key is None else api_key
        if not key:
            raise LLMError("LLM_PROVIDER=hosted needs HOSTED_API_KEY")
        self._headers = {"Authorization": f"Bearer {key}"}

    async def chat(
        self,
        model: str,
        messages: list[dict],
        *,
        format: dict | None = None,
        tools: list[dict] | None = None,
        options: dict | None = None,
        **_ignored: Any,  # think / keep_alive / on_progress are Ollama-only
    ) -> dict:
        opts = options or {}
        body: dict[str, Any] = {"model": model, "messages": to_openai_messages(messages)}
        if "temperature" in opts:
            body["temperature"] = opts["temperature"]
        if "num_predict" in opts:
            body["max_tokens"] = opts["num_predict"]
        if tools:
            body["tools"] = tools
        if format is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "output", "schema": format, "strict": False},
            }

        async with self._client(headers=self._headers) as client:
            try:
                resp = await client.post("/chat/completions", json=body)
                if resp.status_code == 400 and "response_format" in body:
                    # Not every provider/model supports JSON schema; extract_json + repair still guard us.
                    body.pop("response_format")
                    resp = await client.post("/chat/completions", json=body)
            except httpx.ConnectError as exc:
                raise LLMError(f"Cannot reach the inference provider at {self.base}") from exc
            except httpx.TimeoutException as exc:
                raise LLMError(f"{model} timed out after {self.settings.llm_timeout:.0f}s") from exc
        if resp.status_code >= 400:
            raise LLMError(f"Provider {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        if not data.get("choices"):
            raise LLMError(f"Provider returned no choices: {str(data)[:300]}")
        return from_openai_message(data["choices"][0]["message"])

    async def list_models(self) -> list[str]:
        async with self._client(timeout=10, headers=self._headers) as client:
            resp = await client.get("/models")
            resp.raise_for_status()
            return [m["id"] for m in resp.json().get("data", [])]


class FallbackClient(LLMClient):
    """Tries the primary client; on LLMError retries the same call on a second provider.

    Each stage's model is mapped to that provider's equivalent (vision/ocr/agent).
    """

    def __init__(self, primary: LLMClient, fallback: LLMClient, models: dict[str, str]):
        super().__init__(primary.base, primary.settings, None)
        self.primary, self.fallback, self.models = primary, fallback, models
        self.local = primary.local

    async def chat(self, model: str, messages: list[dict], **kwargs: Any) -> dict:
        try:
            return await self.primary.chat(model, messages, **kwargs)
        except LLMError as exc:
            try:
                return await self.fallback.chat(self.models.get(model, model), messages, **kwargs)
            except LLMError as exc2:
                raise LLMError(f"{exc} | fallback: {exc2}") from exc2

    async def unload(self, model: str) -> None:
        await self.primary.unload(model)

    async def list_models(self) -> list[str]:
        return await self.primary.list_models()


def make_client(settings: Settings | None = None) -> LLMClient:
    s = settings or get_settings()
    primary: LLMClient = HostedClient(s) if s.llm_provider == "hosted" else OllamaClient(s)
    if not s.fallback_api_key:
        return primary
    fallback = HostedClient(s, base_url=s.fallback_base_url, api_key=s.fallback_api_key)
    models = {
        s.vision_model: s.fallback_vision_model,
        s.ocr_model: s.fallback_ocr_model,
        s.agent_model: s.fallback_agent_model,
    }
    return FallbackClient(primary, fallback, models)
