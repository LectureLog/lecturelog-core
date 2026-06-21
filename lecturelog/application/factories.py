from __future__ import annotations

from lecturelog.domain.media_source import MediaSource, is_video_source
from lecturelog.domain.ports import MediaCutter, SlideProvider, WebhookNotifier
from lecturelog.infrastructure.webhook.http_notifier import HttpWebhookNotifier


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


def webhook_notifier_factory(
    callback_url: str | None, secret: str | None
) -> WebhookNotifier | None:
    """Нотификатор только при заданных callback_url и секрете; иначе None (автономный режим)."""
    if not callback_url:
        return None
    if not secret:
        # Секрет обязателен для подписи; без него вебхук не включаем (логируем выше по стеку).
        return None
    return HttpWebhookNotifier(callback_url=callback_url, secret=secret)
