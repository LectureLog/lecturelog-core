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

# (start, end) глобального прогресса для видео-пути (ingest/extract в начале)
_VIDEO_BANDS: dict[PipelineStage, tuple[int, int]] = {
    PipelineStage.VIDEO_INGEST: (0, 5),
    PipelineStage.AUDIO_EXTRACT: (5, 10),
    PipelineStage.TRANSCRIBE: (10, 25),
    PipelineStage.SLIDES: (25, 40),
    PipelineStage.VIDEO_SLIDES: (25, 40),
    PipelineStage.STRUCTURIZE: (40, 80),
    PipelineStage.VIDEO_CUT: (80, 90),
    PipelineStage.EXPORT: (90, 100),
}


@dataclass
class ProgressPlan:
    bands: dict[PipelineStage, tuple[int, int]]

    @classmethod
    def for_audio(cls) -> ProgressPlan:
        return cls(bands=dict(_AUDIO_BANDS))

    @classmethod
    def for_video(cls) -> ProgressPlan:
        return cls(bands=dict(_VIDEO_BANDS))

    def stage_start(self, stage: PipelineStage) -> int:
        return self.bands[stage][0]

    def scale(self, stage: PipelineStage, inner_pct: int) -> int:
        start, end = self.bands[stage]
        inner = max(0, min(100, inner_pct))
        return min(100, start + int((end - start) * inner / 100))
