from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from lecturelog.domain.enums import PipelineStage, TaskStatus
from lecturelog.domain.exceptions import TaskNotFound, TranscribeFailed
from lecturelog.domain.ports import TaskRepository


@dataclass
class TranscriptResult:
    ready: bool
    path: Path | None = None
    stage: PipelineStage | None = None
    progress_pct: int = 0


class GetTranscriptUseCase:
    def __init__(self, repository: TaskRepository, srt_path_for: Callable[[str], Path]):
        self._repo = repository
        self._srt_path_for = srt_path_for

    async def execute(self, task_id: str) -> TranscriptResult:
        task = await self._repo.get(task_id)
        if task is None:
            raise TaskNotFound(task_id)

        # Pipeline упал именно на транскрипции — сырого текста не будет.
        if task.status == TaskStatus.FAILED and task.stage == PipelineStage.TRANSCRIBE:
            raise TranscribeFailed(task.error or "")

        srt_path = self._srt_path_for(task_id)
        if not srt_path.exists():
            return TranscriptResult(ready=False, stage=task.stage, progress_pct=task.progress_pct)
        return TranscriptResult(
            ready=True, path=srt_path, stage=task.stage, progress_pct=task.progress_pct
        )
