import pytest

from lecturelog.domain.ports import (
    Exporter,
    MediaCutter,
    MediaIngestor,
    SlideProvider,
    Structurizer,
    TaskRepository,
    Transcriber,
    UsageCallback,
)


def test_usage_callback_is_importable():
    # UsageCallback должен существовать рядом с ProgressCallback (транспорт on_usage)
    assert UsageCallback is not None


def test_transcriber_impl_without_on_usage_still_instantiates():
    # обратная совместимость: реализация без on_usage всё ещё валидна
    from pathlib import Path

    class Legacy(Transcriber):
        async def transcribe(self, audio_path, output_dir, on_progress=None):
            return Path("x.srt")

    assert isinstance(Legacy(), Transcriber)


@pytest.mark.parametrize(
    "port",
    [
        Transcriber,
        SlideProvider,
        Structurizer,
        MediaCutter,
        MediaIngestor,
        Exporter,
        TaskRepository,
    ],
)
def test_ports_are_abstract(port):
    with pytest.raises(TypeError):
        port()  # нельзя инстанцировать абстрактный класс


def test_incomplete_implementation_cannot_instantiate():
    class Bad(Transcriber):
        pass  # не реализует transcribe

    with pytest.raises(TypeError):
        Bad()


def test_complete_implementation_instantiates():
    from pathlib import Path

    class Good(Transcriber):
        async def transcribe(self, audio_path, output_dir, on_progress=None):
            return Path("x.srt")

    assert isinstance(Good(), Transcriber)
