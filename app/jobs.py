"""תור עבודות רקע + דיווח התקדמות חי לדפדפן.

HeyGen לוקח דקות, FFmpeg לוקח דקות. הדפדפן לא מחכה — הוא פותח עבודה,
מקבל מזהה, ומאזין לעדכונים. אפשר לסגור את הלשונית ולחזור.
"""
from __future__ import annotations

import asyncio
import time
import traceback
from typing import Any, Awaitable, Callable

from .storage import new_id


class Job:
    def __init__(self, kind: str, project_id: str, label: str) -> None:
        self.id = new_id("j_")
        self.kind = kind
        self.project_id = project_id
        self.label = label
        self.status = "queued"          # queued | running | done | error | cancelled
        self.progress = 0.0             # 0..1
        self.message = "ממתין בתור"
        self.result: Any = None
        self.error: str | None = None
        self.created_at = time.time()
        self.finished_at: float | None = None
        self._waiters: list[asyncio.Queue] = []

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "project_id": self.project_id,
            "label": self.label,
            "status": self.status,
            "progress": round(self.progress, 4),
            "message": self.message,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }

    def update(self, progress: float | None = None, message: str | None = None) -> None:
        if progress is not None:
            self.progress = max(0.0, min(1.0, progress))
        if message is not None:
            self.message = message
        self._broadcast()

    def _broadcast(self) -> None:
        snap = self.snapshot()
        for q in list(self._waiters):
            try:
                q.put_nowait(snap)
            except asyncio.QueueFull:
                pass

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=64)
        self._waiters.append(q)
        q.put_nowait(self.snapshot())
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._waiters:
            self._waiters.remove(q)


class JobManager:
    """מריץ עבודות ושומר אותן בזיכרון. ניקוי אוטומטי של ישנות."""

    MAX_KEEP_SECONDS = 60 * 60 * 6

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def for_project(self, project_id: str) -> list[dict[str, Any]]:
        return [
            j.snapshot()
            for j in sorted(self._jobs.values(), key=lambda x: x.created_at, reverse=True)
            if j.project_id == project_id
        ]

    def start(
        self,
        kind: str,
        project_id: str,
        label: str,
        coro_factory: Callable[[Job], Awaitable[Any]],
    ) -> Job:
        self._sweep()
        job = Job(kind, project_id, label)
        self._jobs[job.id] = job

        async def runner() -> None:
            job.status = "running"
            job.update(0.01, "מתחיל")
            try:
                job.result = await coro_factory(job)
                job.status = "done"
                job.progress = 1.0
                job.message = "הסתיים"
            except asyncio.CancelledError:
                job.status = "cancelled"
                job.message = "בוטל"
                raise
            except Exception as exc:  # noqa: BLE001 — כל כשל נכנס לדוח למשתמש
                job.status = "error"
                job.error = str(exc) or exc.__class__.__name__
                job.message = "נכשל"
                traceback.print_exc()
            finally:
                job.finished_at = time.time()
                job._broadcast()

        self._tasks[job.id] = asyncio.create_task(runner())
        return job

    def cancel(self, job_id: str) -> bool:
        task = self._tasks.get(job_id)
        if task and not task.done():
            task.cancel()
            return True
        return False

    def _sweep(self) -> None:
        cutoff = time.time() - self.MAX_KEEP_SECONDS
        for jid, job in list(self._jobs.items()):
            if job.finished_at and job.finished_at < cutoff:
                self._jobs.pop(jid, None)
                self._tasks.pop(jid, None)


jobs = JobManager()
