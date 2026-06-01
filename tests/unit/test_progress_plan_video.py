from lecturelog.application.progress_plan import ProgressPlan
from lecturelog.domain.enums import PipelineStage


def test_video_plan_has_ingest_and_extract_bands():
    plan = ProgressPlan.for_video()
    assert plan.stage_start(PipelineStage.VIDEO_INGEST) == 0
    assert plan.stage_start(PipelineStage.AUDIO_EXTRACT) == 5
    assert plan.stage_start(PipelineStage.TRANSCRIBE) == 10


def test_video_transcribe_band_differs_from_audio():
    assert ProgressPlan.for_video().stage_start(PipelineStage.TRANSCRIBE) == 10
    assert ProgressPlan.for_audio().stage_start(PipelineStage.TRANSCRIBE) == 0


def test_video_slides_and_structurize_bands():
    plan = ProgressPlan.for_video()
    assert plan.stage_start(PipelineStage.VIDEO_SLIDES) == 25
    assert plan.stage_start(PipelineStage.STRUCTURIZE) == 40
    assert plan.stage_start(PipelineStage.VIDEO_CUT) == 80
    assert plan.stage_start(PipelineStage.EXPORT) == 90


def test_video_scale_within_transcribe_band():
    plan = ProgressPlan.for_video()
    assert plan.scale(PipelineStage.TRANSCRIBE, 100) == 25
    assert plan.scale(PipelineStage.TRANSCRIBE, 0) == 10
