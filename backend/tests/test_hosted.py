"""HostedClient against a mocked OpenAI-compatible server (no network, no key)."""

import json

import httpx
import pytest

from app.config import Settings
from app.llm import HostedClient, LLMError, from_openai_message, make_client, to_openai_messages
from app.schemas import ArchitectureSummary


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, llm_provider="hosted", hosted_api_key="test-key", **kw)


def test_message_translation_images_and_tool_ids():
    msgs = [
        {"role": "user", "content": "read", "images": ["AAAA"]},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"function": {"name": "a", "arguments": {}}},
                {"function": {"name": "b", "arguments": {"x": 1}}},
            ],
        },
        {"role": "tool", "tool_name": "a", "content": "{}"},
        {"role": "tool", "tool_name": "b", "content": "{}"},
    ]
    out = to_openai_messages(msgs)
    assert out[0]["content"][1] == {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AAAA"}}
    ids = [c["id"] for c in out[1]["tool_calls"]]
    assert [out[2]["tool_call_id"], out[3]["tool_call_id"]] == ids  # each result answers its own call
    assert out[1]["tool_calls"][1]["function"]["arguments"] == '{"x": 1}'


def test_reply_translation_parses_arguments():
    reply = from_openai_message(
        {
            "content": None,
            "tool_calls": [
                {"id": "c1", "function": {"name": "bundle_zip_download", "arguments": "{}"}},
                {"id": "c2", "function": {"name": "x", "arguments": "not json"}},
            ],
        }
    )
    assert reply["content"] == ""
    assert [c["function"]["arguments"] for c in reply["tool_calls"]] == [{}, {}]


async def test_chat_json_sends_key_schema_and_caps():
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-key"
        assert request.url.path == "/v1/chat/completions"
        body = json.loads(request.content)
        seen.append(body)
        content = json.dumps({"title": "Shop", "description": "d", "data_flow": "a → b"})
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": content}}]})

    client = HostedClient(_settings(), transport=httpx.MockTransport(handler))
    out = await client.chat_json("gemma-4-31B-it", [{"role": "user", "content": "hi"}], ArchitectureSummary)
    assert out.title == "Shop"
    body = seen[0]
    assert body["response_format"]["type"] == "json_schema"
    assert body["max_tokens"] == client.settings.json_num_predict and body["temperature"] == 0
    assert "options" not in body and "keep_alive" not in body  # Ollama-only fields never leak


async def test_falls_back_when_json_schema_unsupported():
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        if "response_format" in body:
            return httpx.Response(400, json={"error": "response_format not supported"})
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"title": "X"}'}}]})

    client = HostedClient(_settings(), transport=httpx.MockTransport(handler))
    out = await client.chat_json("m", [{"role": "user", "content": "hi"}], ArchitectureSummary)
    assert out.title == "X" and len(calls) == 2


async def test_errors_are_llm_errors():
    client = HostedClient(
        _settings(), transport=httpx.MockTransport(lambda r: httpx.Response(401, text="bad key"))
    )
    with pytest.raises(LLMError, match="401"):
        await client.chat("m", [{"role": "user", "content": "hi"}])


def test_factory_and_missing_key():
    assert make_client(Settings(_env_file=None)).local is True
    assert make_client(_settings()).local is False
    with pytest.raises(LLMError, match="HOSTED_API_KEY"):
        HostedClient(Settings(_env_file=None, llm_provider="hosted", hosted_api_key=""))


async def test_fallback_retries_on_second_provider_with_mapped_model():
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append((request.url.host, body["model"]))
        if request.url.host == "primary.test":
            return httpx.Response(503, json={"error": "busy"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]})

    s = _settings(
        hosted_base_url="https://primary.test/v1",
        fallback_base_url="https://backup.test/v1",
        fallback_api_key="groq-key",
        agent_model="big",
        fallback_agent_model="small",
    )
    client = make_client(s)
    for c in (client.primary, client.fallback):
        c._transport = httpx.MockTransport(handler)
    reply = await client.chat("big", [{"role": "user", "content": "x"}])
    assert reply["content"] == "hi"
    assert calls == [("primary.test", "big"), ("backup.test", "small")]
