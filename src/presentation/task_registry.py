from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

from src.domain.errors import ensure_app_error
from src.domain.job import JobStatus
from src.utils import timestamp_now


TaskRunner = Callable[[Callable[[JobStatus], None]], Any]


class TaskCancelledError(RuntimeError):
    pass


@dataclass
class TaskHistoryEntry:
    label: str
    detail: str
    updated_at: str
    progress_percent: int

    def to_payload(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "detail": self.detail,
            "updatedAt": self.updated_at,
            "progressPercent": self.progress_percent,
        }


@dataclass
class TaskSnapshot:
    task_id: str
    state: str = "pending"
    phase: str = "input"
    phase_label: str = "已排队"
    progress_percent: int = 0
    message: str = "任务已创建。"
    run_id: str | None = None
    run_dir: str | None = None
    error_code: str | None = None
    error_detail: str | None = None
    result: dict[str, Any] | None = None
    created_at: str = field(default_factory=timestamp_now)
    updated_at: str = field(default_factory=timestamp_now)
    history: list[TaskHistoryEntry] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        return {
            "taskId": self.task_id,
            "state": self.state,
            "phase": self.phase,
            "phaseLabel": self.phase_label,
            "progressPercent": self.progress_percent,
            "message": self.message,
            "runId": self.run_id,
            "runDir": self.run_dir,
            "errorCode": self.error_code,
            "errorDetail": self.error_detail,
            "result": self.result,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "history": [item.to_payload() for item in self.history],
        }


class TaskRegistry:
    def __init__(self, *, max_workers: int = 4) -> None:
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="synpture-task")
        self._tasks: dict[str, TaskSnapshot] = {}
        self._cancel_events: dict[str, threading.Event] = {}

    def start(self, runner: TaskRunner) -> str:
        task_id = uuid.uuid4().hex
        snapshot = TaskSnapshot(task_id=task_id)
        snapshot.history.append(
            TaskHistoryEntry(
                label=snapshot.phase_label,
                detail=snapshot.message,
                updated_at=snapshot.updated_at,
                progress_percent=snapshot.progress_percent,
            )
        )
        with self._lock:
            self._tasks[task_id] = snapshot
            self._cancel_events[task_id] = threading.Event()
        self._executor.submit(self._run_task, task_id, runner)
        return task_id

    def cancel(self, task_id: str) -> TaskSnapshot | None:
        with self._lock:
            snapshot = self._tasks.get(task_id)
            event = self._cancel_events.get(task_id)
            if snapshot is None or event is None:
                return None
            if snapshot.state in {"succeeded", "failed"}:
                return TaskSnapshot(
                    task_id=snapshot.task_id,
                    state=snapshot.state,
                    phase=snapshot.phase,
                    phase_label=snapshot.phase_label,
                    progress_percent=snapshot.progress_percent,
                    message=snapshot.message,
                    run_id=snapshot.run_id,
                    run_dir=snapshot.run_dir,
                    error_code=snapshot.error_code,
                    error_detail=snapshot.error_detail,
                    result=snapshot.result,
                    created_at=snapshot.created_at,
                    updated_at=snapshot.updated_at,
                    history=list(snapshot.history),
                )
            event.set()
            updated_at = timestamp_now()
            snapshot.phase_label = "中止中"
            snapshot.message = "已发送中止请求，等待当前步骤结束。"
            snapshot.updated_at = updated_at
            self._append_history(
                snapshot,
                TaskHistoryEntry(
                    label="中止中",
                    detail="已发送中止请求，等待当前步骤结束。",
                    updated_at=updated_at,
                    progress_percent=snapshot.progress_percent,
                ),
            )
            return TaskSnapshot(
                task_id=snapshot.task_id,
                state=snapshot.state,
                phase=snapshot.phase,
                phase_label=snapshot.phase_label,
                progress_percent=snapshot.progress_percent,
                message=snapshot.message,
                run_id=snapshot.run_id,
                run_dir=snapshot.run_dir,
                error_code=snapshot.error_code,
                error_detail=snapshot.error_detail,
                result=snapshot.result,
                created_at=snapshot.created_at,
                updated_at=snapshot.updated_at,
                history=list(snapshot.history),
            )

    def get(self, task_id: str) -> TaskSnapshot | None:
        with self._lock:
            snapshot = self._tasks.get(task_id)
            if snapshot is None:
                return None
            return TaskSnapshot(
                task_id=snapshot.task_id,
                state=snapshot.state,
                phase=snapshot.phase,
                phase_label=snapshot.phase_label,
                progress_percent=snapshot.progress_percent,
                message=snapshot.message,
                run_id=snapshot.run_id,
                run_dir=snapshot.run_dir,
                error_code=snapshot.error_code,
                error_detail=snapshot.error_detail,
                result=snapshot.result,
                created_at=snapshot.created_at,
                updated_at=snapshot.updated_at,
                history=[
                    TaskHistoryEntry(
                        label=item.label,
                        detail=item.detail,
                        updated_at=item.updated_at,
                        progress_percent=item.progress_percent,
                    )
                    for item in snapshot.history
                ],
            )

    def _run_task(self, task_id: str, runner: TaskRunner) -> None:
        try:
            result = runner(lambda status: self._update_from_status(task_id, status))
        except TaskCancelledError:
            updated_at = timestamp_now()
            self._merge(
                task_id,
                state="failed",
                phase_label="已中止",
                message="任务已中止。",
                error_code="task.cancelled",
                error_detail="任务被用户中止。",
                updated_at=updated_at,
                history_entry=TaskHistoryEntry(
                    label="已中止",
                    detail="任务被用户中止。",
                    updated_at=updated_at,
                    progress_percent=100,
                ),
            )
            return
        except Exception as exc:
            app_error = ensure_app_error(
                exc,
                default_code="system.unexpected",
                default_message="任务执行失败。",
            )
            self._merge(
                task_id,
                state="failed",
                phase="artifact_write",
                phase_label="执行失败",
                progress_percent=100,
                message=app_error.message,
                error_code=app_error.error_code,
                error_detail=app_error.detail or str(exc),
                updated_at=timestamp_now(),
                history_entry=TaskHistoryEntry(
                    label="执行失败",
                    detail=app_error.message,
                    updated_at=timestamp_now(),
                    progress_percent=100,
                ),
            )
            return

        if isinstance(result, dict):
            run_id = result.get("runId")
            run_dir = result.get("runDir")
            payload = result
        else:
            run_id = None
            run_dir = None
            payload = None

        snapshot = self.get(task_id)
        if snapshot is None:
            return
        if self._is_cancel_requested(task_id):
            updated_at = timestamp_now()
            self._merge(
                task_id,
                state="failed",
                phase_label="已中止",
                message="任务已中止。",
                error_code="task.cancelled",
                error_detail="任务被用户中止。",
                updated_at=updated_at,
                history_entry=TaskHistoryEntry(
                    label="已中止",
                    detail="任务被用户中止。",
                    updated_at=updated_at,
                    progress_percent=snapshot.progress_percent or 100,
                ),
            )
            return

        terminal_state = snapshot.state if snapshot.state in {"succeeded", "failed"} else "succeeded"
        terminal_phase = snapshot.phase or "artifact_write"
        terminal_label = snapshot.phase_label or "已完成"
        terminal_progress = snapshot.progress_percent or 100
        terminal_message = snapshot.message if snapshot.message and snapshot.message != "任务已创建。" else "任务已完成。"
        updated_at = timestamp_now()

        self._merge(
            task_id,
            state=terminal_state,
            phase=terminal_phase,
            phase_label=terminal_label,
            progress_percent=terminal_progress,
            message=terminal_message,
            run_id=run_id or snapshot.run_id,
            run_dir=run_dir or snapshot.run_dir,
            result=payload,
            updated_at=updated_at,
            history_entry=TaskHistoryEntry(
                label=terminal_label,
                detail=terminal_message,
                updated_at=updated_at,
                progress_percent=terminal_progress,
            ),
        )

    def _update_from_status(self, task_id: str, status: JobStatus) -> None:
        if self._is_cancel_requested(task_id):
            raise TaskCancelledError(task_id)
        label = status.phase_label or status.phase
        detail = status.message or label
        self._merge(
            task_id,
            state=status.state,
            phase=status.phase,
            phase_label=label,
            progress_percent=status.progress_percent,
            message=detail,
            error_code=status.error_code,
            error_detail=status.error_detail,
            updated_at=status.updated_at,
            history_entry=TaskHistoryEntry(
                label=label,
                detail=detail,
                updated_at=status.updated_at,
                progress_percent=status.progress_percent,
            ),
        )

    def _merge(self, task_id: str, history_entry: TaskHistoryEntry | None = None, **changes: Any) -> None:
        with self._lock:
            snapshot = self._tasks.get(task_id)
            if snapshot is None:
                return
            for key, value in changes.items():
                if value is not None:
                    setattr(snapshot, key, value)
            if history_entry is not None:
                self._append_history(snapshot, history_entry)

    def _append_history(self, snapshot: TaskSnapshot, entry: TaskHistoryEntry) -> None:
        if snapshot.history:
            previous = snapshot.history[-1]
            if (
                previous.label == entry.label
                and previous.detail == entry.detail
                and previous.progress_percent == entry.progress_percent
            ):
                previous.updated_at = entry.updated_at
                return
        snapshot.history.append(entry)

    def _is_cancel_requested(self, task_id: str) -> bool:
        with self._lock:
            event = self._cancel_events.get(task_id)
            return bool(event and event.is_set())
