from __future__ import annotations

from dataclasses import dataclass

from lecturelog.domain.enums import PipelineStage

# (start, end) глобального прогресса для каждой стадии аудио-пути
_AUDIO_BANDS: dict[PipelineStage, tuple[int, int]] = {
    PipelineStage.TRANSCRIBE: (0, 20),
    PipelineStage.SLIDES: (20, 35),
    PipelineStage.STRUCTURIZE: (40, 80),
    PipelineStage.AUDIO_CUT: (80, 90),
    PipelineStage.EXPORT: (90, 100),
}


@dataclass
class ProgressPlan:
    bands: dict[PipelineStage, tuple[int, int]]

    @classmethod
    def for_audio(cls) -> "ProgressPlan":
        return cls(bands=dict(_AUDIO_BANDS))

    def stage_start(self, stage: PipelineStage) -> int:
        return self.bands[stage][0]

    def scale(self, stage: PipelineStage, inner_pct: int) -> int:
        start, end = self.bands[stage]
        inner = max(0, min(100, inner_pct))
        return min(100, start + int((end - start) * inner / 100))
