from __future__ import annotations

from lecturelog.domain.media_source import MediaSource, is_video_source
from lecturelog.domain.ports import MediaCutter, SlideProvider


def cutter_factory(
    source: MediaSource, *, audio_cutter: MediaCutter, video_cutter: MediaCutter
) -> MediaCutter:
    """Видеоисточник режется видео-cutter'ом, аудио — аудио-cutter'ом."""
    return video_cutter if is_video_source(source) else audio_cutter


def slide_provider_factory(
    *,
    no_slides: bool,
    document_provider: SlideProvider | None,
    video_provider: SlideProvider | None,
) -> SlideProvider | None:
    """Выбор источника слайдов по приоритету:
    1. no_slides → None;
    2. документ (PDF/PPTX) приоритетнее;
    3. иначе авто-извлечение из видео;
    4. иначе None.
    """
    if no_slides:
        return None
    if document_provider is not None:
        return document_provider
    return video_provider
