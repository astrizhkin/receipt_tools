"""Per-call debug artifacts, mirroring display-digest's steplog/journal.

Layout (artifacts_dir/<run_id>/):
    original.<ext>
    journal.log                 ts | run_id | node | event | json
    run_meta.json
    steps/NN_<name>/
        input.md                rendered prompts / params
        output.json             validated step output
        resized.jpg             (resize step)
        llm/NNN_<tag>_input.md  one pair PER LLM call
             NNN_<tag>_output.txt
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from typing import Any


class RunArtifacts:
    def __init__(self, root: str, run_id: str):
        self.run_id = run_id
        self.dir = os.path.join(root, run_id)
        os.makedirs(os.path.join(self.dir, "steps"), exist_ok=True)
        self._journal_path = os.path.join(self.dir, "journal.log")
        self._lock = threading.Lock()
        self._seq = 0

    def next_seq(self) -> int:
        with self._lock:
            self._seq += 1
            return self._seq

    def step(self, index: int, name: str) -> "StepLog":
        return StepLog(self, os.path.join(self.dir, "steps", f"{index:02d}_{name}"))

    def event(self, node: str, event: str, **payload: Any) -> None:
        line = (
            f"{datetime.now().isoformat(timespec='seconds')} | {self.run_id} | "
            f"{node} | {event} | {json.dumps(payload, ensure_ascii=False, default=str)}"
        )
        with self._lock:
            with open(self._journal_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")

    def write_meta(self, obj: Any) -> None:
        with open(os.path.join(self.dir, "run_meta.json"), "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2, default=str)


class StepLog:
    def __init__(self, run: RunArtifacts, dir: str):
        self.run = run
        self.dir = dir
        os.makedirs(dir, exist_ok=True)

    def write_input(self, text: str) -> None:
        with open(os.path.join(self.dir, "input.md"), "w", encoding="utf-8") as f:
            f.write(text)

    def write_output(self, obj: Any) -> None:
        with open(os.path.join(self.dir, "output.json"), "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2, default=str)

    def write_bytes(self, name: str, data: bytes) -> str:
        path = os.path.join(self.dir, name)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def append_raw(self, label: str, text: str) -> None:
        with open(os.path.join(self.dir, "raw.txt"), "a", encoding="utf-8") as f:
            f.write(f"===== {label} =====\n{text}\n")

    def llm_pair(self, tag: str, input_text: str, output_text: str) -> None:
        seq = self.run.next_seq()
        llm_dir = os.path.join(self.dir, "llm")
        os.makedirs(llm_dir, exist_ok=True)
        base = os.path.join(llm_dir, f"{seq:03d}_{tag}")
        with open(base + "_input.md", "w", encoding="utf-8") as f:
            f.write(input_text)
        with open(base + "_output.txt", "w", encoding="utf-8") as f:
            f.write(output_text)
