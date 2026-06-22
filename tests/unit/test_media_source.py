from pathlib import Path

from lecturelog.domain.media_source import (
    AudioSource,
    MediaSource,
    S3ObjectSource,
    VideoFileSource,
    VideoUrlSource,
    is_video_source,
)


def test_audio_source_kind():
    src = AudioSource(path=Path("/tmp/a.mp3"))
    assert src.kind == "audio"
    assert is_video_source(src) is False


def test_video_file_source_kind():
    src = VideoFileSource(path=Path("/tmp/v.mp4"))
    assert src.kind == "video_file"
    assert is_video_source(src) is True


def test_video_url_source_kind():
    src = VideoUrlSource(url="https://youtu.be/x")
    assert src.kind == "video_url"
    assert is_video_source(src) is True


def test_s3_object_source_kind():
    s = S3ObjectSource(key="uploads/abc/lecture.mp3", media="audio")
    assert s.kind == "s3_object"
    assert s.key == "uploads/abc/lecture.mp3"


def test_s3_object_video_flag_follows_media():
    assert is_video_source(S3ObjectSource(key="k", media="video")) is True
    assert is_video_source(S3ObjectSource(key="k", media="audio")) is False


def test_media_source_is_union_accepting_all_three():
    sources: list[MediaSource] = [
        AudioSource(path=Path("a")),
        VideoFileSource(path=Path("v")),
        VideoUrlSource(url="u"),
    ]
    assert {s.kind for s in sources} == {"audio", "video_file", "video_url"}
