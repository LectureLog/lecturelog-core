import pytest

from lecturelog.domain.media_source import AudioSource, VideoFileSource
from lecturelog.infrastructure.media.video_ingestor import VideoIngestor


@pytest.mark.asyncio
async def test_ingest_local_video_file_copies_into_output(tmp_path):
    src = tmp_path / "lecture.mkv"
    src.write_bytes(b"fake video bytes")
    ingestor = VideoIngestor()
    out = await ingestor.ingest(VideoFileSource(path=src), output_dir=tmp_path / "ingest")
    assert out.exists()
    assert out.suffix == ".mkv"  # известное расширение сохраняется
    assert out.read_bytes() == b"fake video bytes"


@pytest.mark.asyncio
async def test_ingest_unknown_extension_falls_back_to_mp4(tmp_path):
    src = tmp_path / "lecture.bin"
    src.write_bytes(b"x")
    ingestor = VideoIngestor()
    out = await ingestor.ingest(VideoFileSource(path=src), output_dir=tmp_path / "ingest")
    assert out.suffix == ".mp4"  # неизвестное -> .mp4 (паритет с PoC)


@pytest.mark.asyncio
async def test_ingest_missing_file_raises(tmp_path):
    ingestor = VideoIngestor()
    with pytest.raises(FileNotFoundError):
        await ingestor.ingest(
            VideoFileSource(path=tmp_path / "nope.mp4"),
            output_dir=tmp_path / "ingest",
        )


@pytest.mark.asyncio
async def test_ingest_rejects_non_video_source(tmp_path):
    ingestor = VideoIngestor()
    with pytest.raises((ValueError, TypeError)):
        await ingestor.ingest(
            AudioSource(path=tmp_path / "a.mp3"),
            output_dir=tmp_path / "ingest",
        )
