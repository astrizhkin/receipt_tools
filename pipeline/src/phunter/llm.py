"""Structured LLM client over the llama.cpp OpenAI-compatible API.

Follows the display-digest pattern: raw httpx (not the openai SDK) keeps the
retry-with-validation-feedback loop deterministic and router-agnostic.
Multimodal (image_url data URIs) is supported for the VL endpoint.
"""
from __future__ import annotations

import json
import logging
import re
import threading
from typing import Any

import httpx
from pydantic import TypeAdapter, ValidationError

from .config import LLMEndpoint

log = logging.getLogger("phunter.llm")

# Single-flight: llama.cpp endpoints have fixed slot capacity, so strictly
# one in-flight request per process (shared across both endpoints).
_LLM_LOCK = threading.Lock()


class LLMError(Exception):
    pass


class LLMStructuredFailed(LLMError):
    def __init__(self, msg: str, raws: list[tuple[str, str]]):
        super().__init__(msg)
        self.raws = raws


class LLMTruncated(LLMStructuredFailed):
    """Completion hit max_tokens (finish_reason=length): the JSON is cut off,
    so validation-feedback retries only repeat the same truncated output.
    Callers should fail the request without retrying."""


def extract_json(text: str) -> Any:
    """Pull the first balanced JSON object out of a completion.

    Strips ``` fences, then scans for a balanced brace pair (string/escape
    aware) so trailing prose or thinking text does not break parsing.
    """
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1).strip()
    start = t.find("{")
    if start < 0:
        raise LLMError("no JSON object found in completion")
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(t)):
        c = t[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return json.loads(t[start : i + 1])
    raise LLMError("unbalanced JSON object in completion")


class LLMClient:
    def __init__(self, cfg: LLMEndpoint, transport: httpx.BaseTransport | None = None):
        self.cfg = cfg
        # base_url keeps its path (e.g. /v1); requests use RELATIVE paths so
        # they join UNDER it — a leading slash would RFC-replace and drop /v1.
        self._client = httpx.Client(
            base_url=cfg.base_url.rstrip("/"),
            timeout=cfg.timeout_s,
            transport=transport,
        )
        self._json_ok: bool | None = None  # response_format probe result

    # ---- low level -------------------------------------------------------

    def _body(self, messages: list[dict], *, json_mode: bool, max_tokens: int | None) -> dict:
        body: dict[str, Any] = {
            "model": self.cfg.model,
            "messages": messages,
            "temperature": self.cfg.temperature,
            "max_tokens": max_tokens or self.cfg.max_tokens,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        if self.cfg.disable_thinking:
            body["chat_template_kwargs"] = {"enable_thinking": False}
        return body

    def _post_choice(self, body: dict) -> dict:
        """First choice object: message + finish_reason ('length' = cut off)."""
        with _LLM_LOCK:
            r = self._client.post("chat/completions", json=body)
        r.raise_for_status()
        return r.json()["choices"][0]

    def _post_message(self, body: dict) -> dict:
        return self._post_choice(body).get("message") or {}

    def _post(self, body: dict) -> str:
        return self._post_message(body).get("content") or ""

    def probe_json(self) -> bool:
        """Try response_format=json_object once; fall back to prompt-only."""
        if self._json_ok is None:
            try:
                self._post(
                    self._body(
                        [{"role": "user", "content": 'Reply with exactly {"ok": true}'}],
                        json_mode=True,
                        max_tokens=16,
                    )
                )
                self._json_ok = True
            except Exception:
                self._json_ok = False
        return self._json_ok

    # ---- structured calls -------------------------------------------------

    def call_structured(
        self,
        system: str,
        user: str,
        adapter: TypeAdapter,
        *,
        image_b64: str | None = None,
        image_mime: str = "image/jpeg",
        max_tokens: int | None = None,
        tag: str = "llm",
        slog=None,
        tools: list[dict] | None = None,
        tool_exec: dict[str, callable] | None = None,
        max_tool_rounds: int = 4,
    ) -> tuple[Any, list[tuple[str, str]]]:
        """Call the LLM and validate against `adapter`.

        Optional OpenAI-style `tools` + `tool_exec` (name -> callable): the
        model may call tools (e.g. validate_json) before answering; tool
        results are fed back until it produces a final content message.
        On validation failure the error text is fed back as an extra user
        message (the main reliability lever). Returns (value, raws); raws is
        the list of every raw completion so callers can still log failures.
        """
        messages: list[dict] = [{"role": "system", "content": system}]
        if image_b64:
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{image_mime};base64,{image_b64}"},
                        },
                        {"type": "text", "text": user},
                    ],
                }
            )
        else:
            messages.append({"role": "user", "content": user})

        json_mode = self.probe_json()
        raws: list[tuple[str, str]] = []
        last_err = "no attempts made"

        use_tools = bool(tools)
        for _attempt in range(self.cfg.retries + 1):
            # llama.cpp cannot combine json_object grammar with tool calling:
            # when tools are on, the final answer is plain-text JSON instead.
            body = self._body(messages, json_mode=(json_mode and not use_tools),
                              max_tokens=max_tokens)
            if use_tools:
                body["tools"] = tools
            try:
                choice = self._post_choice(body)
            except (httpx.HTTPError, LLMError) as e:
                detail = getattr(getattr(e, "response", None), "text", "") or str(e)
                if use_tools and "tool" in detail.lower():
                    # endpoint/chat template rejects tools -> run without them
                    log.warning("endpoint rejected tools, continuing without them: %s",
                                detail[:200])
                    use_tools = False
                    continue
                last_err = f"HTTP error: {e}"
                raws.append(("http_error", str(e)))
                if slog:
                    slog.llm_pair(f"{tag}_failed", _render(messages), f"ERROR: {e}")
                continue
            self._check_truncation(choice, body, tag, slog, messages, raws)
            msg = choice.get("message") or {}

            rounds = 0
            while msg.get("tool_calls") and use_tools and rounds < max_tool_rounds:
                rounds += 1
                messages.append({"role": "assistant", **msg})
                for tc in msg["tool_calls"]:
                    fn = tc.get("function", {}).get("name", "")
                    try:
                        args = json.loads(tc.get("function", {}).get("arguments") or "{}")
                    except ValueError:
                        args = {}
                    handler = (tool_exec or {}).get(fn)
                    if handler is None:
                        result: dict = {"error": f"unknown tool {fn!r}"}
                    else:
                        try:
                            result = handler(**args)
                        except Exception as te:  # noqa: BLE001 — tool errors go back to the model
                            result = {"error": str(te)}
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.get("id", fn),
                            "content": json.dumps(result, ensure_ascii=False),
                        }
                    )
                raws.append((f"tool_round{rounds}", json.dumps(msg, ensure_ascii=False)))
                body = self._body(messages, json_mode=(json_mode and not use_tools),
                                  max_tokens=max_tokens)
                if use_tools:
                    body["tools"] = tools
                try:
                    choice = self._post_choice(body)
                except httpx.HTTPStatusError as e:
                    detail = (e.response.text or "")[:500]
                    log.warning("tool follow-up rejected (%s); retrying without tools", detail)
                    use_tools = False
                    break
                self._check_truncation(choice, body, tag, slog, messages, raws)
                msg = choice.get("message") or {}

            content = msg.get("content") or ""
            raws.append(("ok", content))
            if slog:
                slog.llm_pair(tag, _render(messages), content)

            try:
                value = adapter.validate_python(extract_json(content))
                return value, raws
            except (LLMError, ValidationError, ValueError) as e:
                last_err = str(e)
                messages.append({"role": "assistant", "content": content})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Your previous reply failed validation:\n"
                            f"{e}\n"
                            "Return ONLY the corrected JSON object, nothing else."
                        ),
                    }
                )

        raise LLMStructuredFailed(last_err, raws)

    # ---- plain-text calls --------------------------------------------------

    def call_plain(
        self,
        system: str,
        user: str,
        *,
        image_b64: str | None = None,
        image_mime: str = "image/jpeg",
        max_tokens: int | None = None,
        tag: str = "llm",
        slog=None,
    ) -> tuple[str, list[tuple[str, str]]]:
        """Plain-text completion (no JSON schema/grammar): the OCR step's
        output is Markdown. Retries transport errors and empty completions;
        fails fast on truncation like call_structured."""
        messages: list[dict] = [{"role": "system", "content": system}]
        if image_b64:
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{image_mime};base64,{image_b64}"},
                        },
                        {"type": "text", "text": user},
                    ],
                }
            )
        else:
            messages.append({"role": "user", "content": user})

        raws: list[tuple[str, str]] = []
        last_err = "no attempts made"
        for _attempt in range(self.cfg.retries + 1):
            body = self._body(messages, json_mode=False, max_tokens=max_tokens)
            try:
                choice = self._post_choice(body)
            except (httpx.HTTPError, LLMError) as e:
                last_err = f"HTTP error: {e}"
                raws.append(("http_error", str(e)))
                if slog:
                    slog.llm_pair(f"{tag}_failed", _render(messages), f"ERROR: {e}")
                continue
            self._check_truncation(choice, body, tag, slog, messages, raws)
            content = (choice.get("message") or {}).get("content") or ""
            raws.append(("ok", content))
            if slog:
                slog.llm_pair(tag, _render(messages), content)
            if content.strip():
                return content, raws
            last_err = "empty completion"
        raise LLMStructuredFailed(last_err, raws)

    @staticmethod
    def _check_truncation(choice: dict, body: dict, tag: str, slog,
                          messages: list[dict], raws: list[tuple[str, str]]) -> None:
        """finish_reason=length means the completion was cut off mid-JSON:
        retrying just reproduces the same truncation, so fail fast instead."""
        if choice.get("finish_reason") != "length":
            return
        partial = (choice.get("message") or {}).get("content") or ""
        raws.append(("truncated", partial))
        if slog:
            slog.llm_pair(f"{tag}_truncated", _render(messages), partial)
        raise LLMTruncated(
            f"output truncated at max_tokens={body.get('max_tokens')} "
            "(finish_reason=length) — raise the endpoint max_tokens/context "
            "or shrink the input",
            raws,
        )

    def close(self):
        self._client.close()


def _render(messages: list[dict]) -> str:
    """Dump messages to markdown for the debug artifact (images elided)."""
    out: list[str] = []
    for m in messages:
        c = m.get("content")
        if m.get("tool_calls"):
            calls = "; ".join(
                f"{tc.get('function', {}).get('name')}({tc.get('function', {}).get('arguments')})"
                for tc in m["tool_calls"]
            )
            c = f"{c or ''}\n[tool_calls: {calls}]"
        elif m.get("role") == "tool":
            c = f"[tool result] {c}"
        if isinstance(c, list):
            parts = []
            for p in c:
                if p.get("type") == "image_url":
                    url = p["image_url"]["url"]
                    parts.append(f"[image: {len(url)} chars data-uri]")
                else:
                    parts.append(p.get("text", ""))
            c = "\n".join(parts)
        out.append(f"## {m['role']}\n\n{c}\n")
    return "\n".join(out)
