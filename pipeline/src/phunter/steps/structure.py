"""Step 3: convert OCR Markdown into structured receipt JSON (text LLM)."""
from __future__ import annotations

import json

from pydantic import ValidationError

from ..artifacts import StepLog
from ..config import LLMEndpoint, PromptsConfig
from ..llm import LLMClient
from ..schemas import STRUCTURED_ADAPTER

# Tool the model must use to self-validate its JSON before answering.
VALIDATE_TOOL = {
    "type": "function",
    "function": {
        "name": "validate_json",
        "description": (
            "Validate the candidate receipt JSON against the required schema. "
            "You MUST call this tool with your complete JSON before returning the final answer."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "candidate": {
                    "type": "string",
                    "description": "The complete candidate JSON as one string.",
                }
            },
            "required": ["candidate"],
        },
    },
}


_TOL = 0.011


def _arith_errors(model) -> list[str]:
    """Recompute the receipt arithmetic on the schema-validated model.

    Errors carry the COMPUTED values so the model fixes its field mapping
    instead of re-guessing. Deliberately layout-tolerant: line sums are
    pre-discount on r-keeper receipts but post-discount on e.g. Perekriostok,
    so there is no sum(items.sum) == subtotal check.
    """
    errs: list[str] = []
    m = lambda x: f"{x:.2f}"

    for i, it in enumerate(model.items, start=1):
        if it.qty is None or it.price is None or it.sum is None:
            continue
        want = it.qty * it.price
        ok = abs(want - it.sum) <= _TOL or (
            it.discount is not None and abs(want - it.discount - it.sum) <= _TOL
        )
        if not ok:
            errs.append(
                f"item {i} ({it.name!r}): qty {it.qty} x price {m(it.price)} = "
                f"{m(want)}, but sum is {m(it.sum)}; keep the printed line "
                "amounts and put any line discount in 'discount'"
            )

    discs = [it.discount for it in model.items if it.discount is not None]
    if model.discount_total is not None and discs:
        want = sum(discs)
        if abs(want - model.discount_total) > _TOL:
            errs.append(
                f"sum of item discounts = {m(want)}, but discount_total is "
                f"{m(model.discount_total)}"
            )

    # total must reconcile with the items under SOME consistent layout:
    # lines already post-discount (r-keeper: sum(items) == ИТОГ), lines
    # pre-discount (sum - discount_total), or a printed pre-discount
    # subtotal (Perekriostok: ПОДИТОГ - discount_total). Never force a
    # subtraction: that invented a wrong total on r-keeper receipts.
    sums = [it.sum for it in model.items if it.sum is not None]
    if model.total is not None and sums:
        line_sum = sum(sums)
        ok = abs(line_sum - model.total) <= _TOL or (
            model.discount_total is not None
            and (
                abs(line_sum - model.discount_total - model.total) <= _TOL
                or (
                    model.subtotal is not None
                    and abs(model.subtotal - model.discount_total - model.total) <= _TOL
                )
            )
        )
        if not ok:
            detail = f"sum of item sums = {m(line_sum)}"
            if model.discount_total is not None:
                detail += (
                    f", discount_total = {m(model.discount_total)}, "
                    f"sum - discount_total = {m(line_sum - model.discount_total)}"
                )
            errs.append(
                f"total {m(model.total)} does not reconcile: {detail}; "
                "total must be the final printed amount (ИТОГ/К ОПЛАТЕ) - "
                "do not add or subtract discounts yourself"
            )
    return errs


def _validate_candidate(candidate: str) -> dict:
    try:
        data = json.loads(candidate)
    except ValueError as e:
        return {"valid": False, "errors": f"not parseable JSON: {e}"}
    try:
        model = STRUCTURED_ADAPTER.validate_python(data)
    except ValidationError as e:
        return {"valid": False, "errors": e.json()}
    errs = _arith_errors(model)
    if errs:
        return {"valid": False, "errors": "; ".join(errs)}
    return {"valid": True}

def run_structure(
    state: dict,
    cfg: LLMEndpoint,
    prompts: PromptsConfig,
    client: LLMClient,
    slog: StepLog,
) -> dict:
    ocr = state["ocr"]
    # replace (not str.format): the prompt templates may contain literal braces
    user = prompts.structure_user.replace("{ocr_text}", ocr["text"])

    slog.write_input(
        f"# structure\n\nmodel: {cfg.model}\nbase_url: {cfg.base_url}\n\n"
        f"## system\n\n{prompts.structure_system}\n\n## user\n\n{user}\n"
    )

    tools = [VALIDATE_TOOL] if cfg.use_tools else None
    tool_exec = {"validate_json": _validate_candidate} if cfg.use_tools else None

    result, raws = client.call_structured(
        SYSTEM_PROMPT,
        user,
        STRUCTURED_ADAPTER,
        max_tokens=cfg.max_tokens,
        tag="structure",
        slog=slog,
        tools=tools,
        tool_exec=tool_exec,
    )

    for label, raw in raws:
        slog.append_raw(label, raw)
    slog.write_output(result.model_dump())
    return {"structured": result.model_dump()}
