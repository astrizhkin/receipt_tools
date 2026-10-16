"""Single-threaded background worker: claims the oldest queued request and
runs the LangGraph pipeline; each graph node updates the request stage."""
from __future__ import annotations

import glob
import logging
import os
import threading
import time

log = logging.getLogger("phunter.worker")

from .artifacts import RunArtifacts
from .config import PipelineConfig
from .db import ReceiptDB
from .graph import RunContext, build_graph
from .llm import LLMClient, LLMTruncated


class Worker(threading.Thread):
    def __init__(self, cfg: PipelineConfig, db: ReceiptDB):
        super().__init__(daemon=True, name="pipeline-worker")
        self.cfg = cfg
        self.db = db
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        recovered = self.db.recover_interrupted()
        if recovered:
            log.info("worker: startup recovery, re-queued interrupted requests: %s", recovered)
        vl = LLMClient(self.cfg.vl)
        text = LLMClient(self.cfg.text)
        while not self._stop.is_set():
            try:
                req = self.db.claim_next_queued()
                if req is None:
                    # queue drained: retry the failed request that waited longest
                    requeued = self.db.requeue_failed(self.cfg.max_request_retries)
                    if requeued is None:
                        self._stop.wait(2.0)
                        continue
                    log.info(
                        "worker: queue empty, requeued failed request id=%s "
                        "(retry %d/%d)",
                        requeued["id"], requeued["retry_count"],
                        self.cfg.max_request_retries,
                    )
                    continue
                self._process(req, vl, text)
            except Exception:  # noqa: BLE001 — worker must survive DB/schema errors
                log.exception("worker: queue poll failed; retrying in 5s "
                              "(is a db/init migration missing?)")
                self._stop.wait(5.0)
        vl.close()
        text.close()

    def _process(self, req: dict, vl: LLMClient, text: LLMClient) -> None:
        request_id = req["id"]
        run_id = req["artifacts_dir"]  # folder name == run id
        log.info("worker: claimed request id=%s (run=%s, account=%s)",
                 request_id, run_id, req.get("account_id"))
        folder = os.path.join(self.cfg.artifacts_dir, run_id)
        originals = glob.glob(os.path.join(folder, "original.*"))
        if not originals:
            log.error("worker: request id=%s failed: no original photo in %s", request_id, folder)
            self.db.finish_request(request_id, "failed", error=f"no original photo in {folder}")
            return

        arts = RunArtifacts(self.cfg.artifacts_dir, run_id)
        arts.event("worker", "start", request_id=request_id)
        ctx = RunContext(
            cfg=self.cfg, vl=vl, text=text, db=self.db, arts=arts, request_id=request_id
        )
        try:
            build_graph(ctx).invoke(
                {"run_id": run_id, "original_path": originals[0], "request_id": request_id}
            )
        except LLMTruncated as e:
            # deterministic (output longer than max_tokens): retrying would
            # loop forever, so exhaust retries and move to the next task
            log.error("worker: request id=%s failed, NOT retryable: %s", request_id, e)
            arts.event("worker", "failed", error=str(e), retryable=False)
            self.db.finish_request(request_id, "failed", error=str(e)[:2000],
                                   exhaust_retries=self.cfg.max_request_retries)
            return
        except Exception as e:  # noqa: BLE001 — worker must survive any failure
            log.exception("worker: request id=%s failed", request_id)
            arts.event("worker", "failed", error=str(e))
            self.db.finish_request(request_id, "failed", error=str(e)[:2000])
            return
        arts.event("worker", "done")
        self.db.finish_request(request_id, "completed")
        log.info("worker: request id=%s completed", request_id)
