import pytest
from lecturelog.domain.ports import (
    Transcriber, SlideProvider, Structurizer, MediaCutter, MediaIngestor, Exporter, TaskRepository,
)


@pytest.mark.parametrize("port", [
    Transcriber, SlideProvider, Structurizer, MediaCutter, MediaIngestor, Exporter, TaskRepository,
])
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
