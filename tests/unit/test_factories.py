from pathlib import Path

from lecturelog.application.factories import cutter_factory, slide_provider_factory
from lecturelog.domain.media_source import AudioSource, VideoFileSource


class _A:  # маркеры, чтобы различать выбранную реализацию
    pass


class _V:
    pass


def test_cutter_factory_picks_video_for_video_source():
    a, v = _A(), _V()
    chosen = cutter_factory(VideoFileSource(path=Path("/v.mp4")), audio_cutter=a, video_cutter=v)
    assert chosen is v


def test_cutter_factory_picks_audio_for_audio_source():
    a, v = _A(), _V()
    chosen = cutter_factory(AudioSource(path=Path("/a.mp3")), audio_cutter=a, video_cutter=v)
    assert chosen is a


def test_no_slides_flag_wins():
    doc, vid = _A(), _V()
    assert slide_provider_factory(no_slides=True, document_provider=doc, video_provider=vid) is None


def test_document_takes_priority_over_video():
    doc, vid = _A(), _V()
    chosen = slide_provider_factory(no_slides=False, document_provider=doc, video_provider=vid)
    assert chosen is doc


def test_video_auto_when_no_document():
    vid = _V()
    chosen = slide_provider_factory(no_slides=False, document_provider=None, video_provider=vid)
    assert chosen is vid


def test_none_when_nothing_available():
    assert (
        slide_provider_factory(no_slides=False, document_provider=None, video_provider=None) is None
    )
