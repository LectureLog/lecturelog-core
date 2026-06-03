from lecturelog.domain.enums import PipelineStage, TaskStatus
from lecturelog.domain.models import Section, Task, Topic


def test_section_holds_content_and_slides():
    s = Section(title="Введение", start="0:00", end="3:00", content="текст", slide_indices=[1, 2])
    assert s.slide_indices == [1, 2]
    assert s.content == "текст"


def test_topic_aggregates_sections():
    s = Section(title="t", start="0:00", end="1:00", content="c", slide_indices=[1])
    topic = Topic(title="Тема", start="0:00", end="5:00", sections=[s], slide_indices=[1])
    assert topic.sections[0].title == "t"


def test_task_defaults_to_pending_zero_progress():
    task = Task(task_id="abc", source_kind="audio")
    assert task.status == TaskStatus.PENDING
    assert task.progress_pct == 0
    assert task.stage is None
    assert task.error is None
    assert task.result_path is None


def test_task_accepts_stage_and_progress():
    task = Task(
        task_id="abc",
        source_kind="video_file",
        status=TaskStatus.PROCESSING,
        stage=PipelineStage.TRANSCRIBE,
        progress_pct=15,
    )
    assert task.stage == PipelineStage.TRANSCRIBE
    assert task.progress_pct == 15
