from lecturelog.application.progress_plan import ProgressPlan
from lecturelog.domain.enums import PipelineStage


def test_audio_plan_stage_start_values():
    plan = ProgressPlan.for_audio()
    assert plan.stage_start(PipelineStage.TRANSCRIBE) == 0
    assert plan.stage_start(PipelineStage.STRUCTURIZE) == 40
    assert plan.stage_start(PipelineStage.EXPORT) == 90


def test_scale_maps_inner_progress_into_stage_band():
    plan = ProgressPlan.for_audio()
    # structurize занимает 40..80; внутренний прогресс 50% -> 40 + 0.5*40 = 60
    assert plan.scale(PipelineStage.STRUCTURIZE, 50) == 60


def test_scale_clamps_to_band_bounds():
    plan = ProgressPlan.for_audio()
    assert plan.scale(PipelineStage.STRUCTURIZE, 0) == 40
    assert plan.scale(PipelineStage.STRUCTURIZE, 100) == 80


def test_scale_never_exceeds_100():
    plan = ProgressPlan.for_audio()
    assert plan.scale(PipelineStage.EXPORT, 100) == 100
