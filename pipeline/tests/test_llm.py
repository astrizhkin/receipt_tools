"""Offline LLM client tests via httpx.MockTransport (display-digest pattern)."""
import json

import httpx
import pytest
from pydantic import BaseModel, TypeAdapter

from phunter.config import LLMEndpoint
from phunter.llm import LLMClient, LLMStructuredFailed, LLMTruncated, extract_json


class Doc(BaseModel):
    text: str


CFG = LLMEndpoint(base_url="http://fake/v1", model="m", retries=1)
ADAPTER: TypeAdapter = TypeAdapter(Doc)


def _completion(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


def test_extract_json_strips_fences_and_trailing_prose():
    assert extract_json('```json\n{"a": 1}\n```\nsome trailing prose') == {"a": 1}
    assert extract_json('thinking...\n{"a": {"b": "}"}} done') == {"a": {"b": "}"}}


def test_relative_path_keeps_v1_and_validation_succeeds():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, json.loads(request.content)))
        if seen[-1][1].get("max_tokens") == 16:  # probe call
            return httpx.Response(200, json=_completion('{"ok": true}'))
        return httpx.Response(200, json=_completion('{"text": "hi"}'))

    client = LLMClient(CFG, transport=httpx.MockTransport(handler))
    value, raws = client.call_structured("sys", "user", ADAPTER)
    assert value.model_dump() == {"text": "hi"}
    # relative join: /v1 from base_url must survive
    assert all(path == "/v1/chat/completions" for path, _ in seen)
    # probe succeeded -> json_mode used on the real call
    assert seen[-1][1]["response_format"] == {"type": "json_object"}


def test_probe_failure_falls_back_to_prompt_mode():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        if "response_format" in body:
            return httpx.Response(400, json={"error": "unsupported"})
        return httpx.Response(200, json=_completion('{"text": "ok"}'))

    client = LLMClient(CFG, transport=httpx.MockTransport(handler))
    value, _ = client.call_structured("sys", "user", ADAPTER)
    assert value.model_dump() == {"text": "ok"}
    assert "response_format" not in seen[-1]


def test_validation_feedback_retry_then_succeed():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body.get("max_tokens") == 16:
            return httpx.Response(200, json=_completion('{"ok": true}'))
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, json=_completion('{"text": 123}'))  # invalid type
        # feedback message must be present in the retry
        assert any("failed validation" in str(m.get("content")) for m in body["messages"])
        return httpx.Response(200, json=_completion('{"text": "good"}'))

    client = LLMClient(CFG, transport=httpx.MockTransport(handler))
    value, raws = client.call_structured("sys", "user", ADAPTER)
    assert value.model_dump() == {"text": "good"}
    assert len(raws) == 2


def test_tool_roundtrip_validate_json():
    """Model calls validate_json once (invalid), gets the error back, then answers valid."""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        if body.get("max_tokens") == 16:
            return httpx.Response(200, json=_completion('{"ok": true}'))
        roles = [m["role"] for m in body["messages"]]
        if "tool" not in roles:
            assert "tools" in body  # tools offered on the first call
            return httpx.Response(200, json={
                "choices": [{
                    "message": {
                        "content": None,
                        "tool_calls": [{
                            "id": "call1",
                            "function": {
                                "name": "validate_json",
                                "arguments": '{"candidate": "{\\"text\\": 5}"}',
                            },
                        }],
                    }
                }]
            })
        # the tool result must carry the validation error
        tool_msg = [m for m in body["messages"] if m["role"] == "tool"][0]
        assert '"valid": false' in tool_msg["content"]
        return httpx.Response(200, json=_completion('{"text": "fixed"}'))

    client = LLMClient(CFG, transport=httpx.MockTransport(handler))
    value, raws = client.call_structured(
        "sys", "user", ADAPTER,
        tools=[{"type": "function", "function": {"name": "validate_json"}}],
        tool_exec={"validate_json": lambda candidate: {"valid": False, "errors": "text must be str"}},
    )
    assert value.model_dump() == {"text": "fixed"}
    assert any(label.startswith("tool_round") for label, _ in raws)


def test_tools_rejected_falls_back_to_plain():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body.get("max_tokens") == 16:
            return httpx.Response(200, json=_completion('{"ok": true}'))
        calls["n"] += 1
        if "tools" in body:
            return httpx.Response(400, json={"error": "template does not support tools"})
        return httpx.Response(200, json=_completion('{"text": "no tools needed"}'))

    client = LLMClient(CFG, transport=httpx.MockTransport(handler))
    value, _ = client.call_structured(
        "sys", "user", ADAPTER,
        tools=[{"type": "function", "function": {"name": "validate_json"}}],
        tool_exec={"validate_json": lambda **k: {"valid": True}},
    )
    assert value.model_dump() == {"text": "no tools needed"}


def test_truncation_fails_fast_without_retry_loop():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        if body.get("max_tokens") == 16:  # probe call
            return httpx.Response(200, json=_completion('{"ok": true}'))
        return httpx.Response(200, json={"choices": [
            {"message": {"content": '{"text": "cut off mid'},
            "finish_reason": "length",
        }]})

    client = LLMClient(CFG, transport=httpx.MockTransport(handler))
    with pytest.raises(LLMTruncated) as ei:
        client.call_structured("sys", "user", ADAPTER)
    assert "truncated" in str(ei.value)
    # probe + exactly one real call: no validation-feedback retry rounds
    assert len(seen) == 2


def test_retry_exhaustion_raises_with_raws():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body.get("max_tokens") == 16:
            return httpx.Response(200, json=_completion('{"ok": true}'))
        return httpx.Response(200, json=_completion("not json at all"))

    client = LLMClient(CFG, transport=httpx.MockTransport(handler))
    try:
        client.call_structured("sys", "user", ADAPTER)
        assert False, "expected LLMStructuredFailed"
    except LLMStructuredFailed as e:
        assert len(e.raws) == CFG.retries + 1


def test_call_plain_returns_markdown_without_json_mode():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=_completion("sigma\nкасса\nИТОГ 100.00"))

    client = LLMClient(CFG, transport=httpx.MockTransport(handler))
    text, raws = client.call_plain("sys", "user", image_b64="aGk=")
    assert text.startswith("sigma")
    assert all("response_format" not in b for b in seen)
    assert seen[0]["messages"][1]["content"][0]["type"] == "image_url"


def test_call_plain_truncation_fails_fast():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [
            {"message": {"content": "partial..."}, "finish_reason": "length"},
        ]})

    client = LLMClient(CFG, transport=httpx.MockTransport(handler))
    with pytest.raises(LLMTruncated):
        client.call_plain("sys", "user")
