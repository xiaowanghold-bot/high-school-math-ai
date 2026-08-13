from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from threading import Lock, Thread
from typing import Callable, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class BackgroundJobView(BaseModel):
    job_id: str
    kind: str
    subject_id: str
    status: Literal["queued", "running", "succeeded", "failed"]
    current: int = 0
    total: int = 0
    message: str = ""
    error: str = ""
    result: dict = Field(default_factory=dict)
    created_at: str
    updated_at: str


Progress = Callable[[int, int, str], None]
Runner = Callable[[Progress], dict]


class BackgroundJobRegistry:
    """Small process-local registry for slow OCR/model operations.

    The source data remains durable in each domain database. Jobs are deliberately
    transient: after an API restart the UI can simply start the operation again.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._jobs: dict[str, dict] = {}

    def start(self, *, kind: str, subject_id: str, runner: Runner) -> BackgroundJobView:
        now = datetime.now(UTC).isoformat()
        job_id = f"job_{uuid4().hex[:16]}"
        with self._lock:
            self._jobs[job_id] = {
                "job_id": job_id, "kind": kind, "subject_id": subject_id,
                "status": "queued", "current": 0, "total": 0,
                "message": "任务已排队", "error": "", "result": {},
                "created_at": now, "updated_at": now,
            }
        Thread(target=self._run, args=(job_id, runner), daemon=True).start()
        return self.get(job_id)

    def get(self, job_id: str) -> BackgroundJobView:
        with self._lock:
            value = self._jobs.get(job_id)
            if value is None:
                raise KeyError(job_id)
            return BackgroundJobView.model_validate(deepcopy(value))

    def _update(self, job_id: str, **values) -> None:
        with self._lock:
            self._jobs[job_id].update(values)
            self._jobs[job_id]["updated_at"] = datetime.now(UTC).isoformat()

    def _run(self, job_id: str, runner: Runner) -> None:
        self._update(job_id, status="running", message="正在处理")

        def progress(current: int, total: int, message: str) -> None:
            self._update(job_id, current=current, total=total, message=message)

        try:
            result = runner(progress)
            self._update(job_id, status="succeeded", message="处理完成", result=result)
        except Exception as exc:  # boundary: the API reports the domain error to the UI
            self._update(job_id, status="failed", message="处理失败", error=str(exc))
