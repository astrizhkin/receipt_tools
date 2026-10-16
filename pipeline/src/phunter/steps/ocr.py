"""Step 2: Qwen VL OCR on the resized photo (VL endpoint).

Plain-Markdown output: the earlier JSON wrapper with `codes` + `hocr`
coordinate blocks was dropped — nothing downstream consumed them, and hocr
doubled the VL output tokens, which truncated big receipts at max_tokens.
Prompts live in pipeline.yaml (`prompts.ocr_system` / `prompts.ocr_user`).
"""
from __future__ import annotations

import base64

from ..artifacts import StepLog
from ..config import LLMEndpoint, PromptsConfig
from ..llm import LLMClient


def run_ocr(
    state: dict,
    cfg: LLMEndpoint,
    prompts: PromptsConfig,
    client: LLMClient,
    slog: StepLog,
) -> dict:
    with open(state["resized_path"], "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("ascii")

    slog.write_input(
        f"# ocr\n\nmodel: {cfg.model}\nbase_url: {cfg.base_url}\n"
        f"image: {state['resized_path']} ({state['resize_info']['resized_size']})\n\n"
        f"## system\n\n{prompts.ocr_system}\n\n## user\n\n{prompts.ocr_user}\n"
    )

    text, raws = client.call_plain(
        prompts.ocr_system,
        prompts.ocr_user,
        image_b64=img_b64,
        max_tokens=cfg.max_tokens,
        tag="vl_ocr",
        slog=slog,
    )

    for label, raw in raws:
        slog.append_raw(label, raw)
    ocr = {"text": text}
    slog.write_output(ocr)
    return {"ocr": ocr}
