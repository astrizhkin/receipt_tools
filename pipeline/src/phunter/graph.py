"""LangGraph pipeline: resize -> ocr -> structure -> persist (linear chain)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from .artifacts import RunArtifacts
from .config import PipelineConfig
from .db import ReceiptDB
from .llm import LLMClient
from .steps.ocr import run_ocr
from .steps.persist import run_persist
from .steps.resize import run_resize
from .steps.structure import run_structure


def merge_dict(a: dict, b: dict) -> dict:
    return {**a, **b}


class RunState(TypedDict, total=False):
    run_id: str
    original_path: str
    request_id: int
    resized_path: str
    resize_info: Annotated[dict, merge_dict]
    ocr: Annotated[dict, merge_dict]
    structured: Annotated[dict, merge_dict]
    receipt_id: int


@dataclass
class RunContext:
    cfg: PipelineConfig
    vl: LLMClient
    text: LLMClient
    db: ReceiptDB
    arts: RunArtifacts
    request_id: int | None = None

    def set_stage(self, stage: str) -> None:
        """Request status bookkeeping (async flow); no-op for direct runs."""
        if self.request_id is not None:
            self.db.set_request_stage(self.request_id, stage)


def build_graph(ctx: RunContext):
    sg = StateGraph(RunState)

    def n_resize(state: RunState) -> dict:
        slog = ctx.arts.step(1, "resize")
        ctx.arts.event("resize", "start", src=state["original_path"])
        ctx.set_stage("resize")
        out = run_resize(state, ctx.cfg.resize, slog)
        ctx.arts.event("resize", "done", **out["resize_info"])
        return out

    def n_ocr(state: RunState) -> dict:
        slog = ctx.arts.step(2, "ocr")
        ctx.arts.event("ocr", "start", model=ctx.cfg.vl.model)
        ctx.set_stage("ocr")
        out = run_ocr(state, ctx.cfg.vl, ctx.cfg.prompts, ctx.vl, slog)
        ctx.arts.event("ocr", "done", text_len=len(out["ocr"]["text"]))
        return out

    def n_structure(state: RunState) -> dict:
        slog = ctx.arts.step(3, "structure")
        ctx.arts.event("structure", "start", model=ctx.cfg.text.model)
        ctx.set_stage("structure")
        out = run_structure(state, ctx.cfg.text, ctx.cfg.prompts, ctx.text, slog)
        ctx.arts.event("structure", "done", items=len(out["structured"]["items"]))
        return out

    def n_persist(state: RunState) -> dict:
        slog = ctx.arts.step(4, "persist")
        ctx.arts.event("persist", "start")
        ctx.set_stage("persist")
        out = run_persist(state, ctx.db, slog)
        ctx.arts.event("persist", "done", **out)
        return out

    sg.add_node("resize", n_resize)
    sg.add_node("ocr", n_ocr)
    sg.add_node("structure", n_structure)
    sg.add_node("persist", n_persist)
    sg.add_edge(START, "resize")
    sg.add_edge("resize", "ocr")
    sg.add_edge("ocr", "structure")
    sg.add_edge("structure", "persist")
    sg.add_edge("persist", END)
    return sg.compile()
