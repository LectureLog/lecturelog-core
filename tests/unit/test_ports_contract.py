import pytest

from lecturelog.domain.enums import TaskStatus
from lecturelog.domain.ports import (
    Exporter,
    MediaCutter,
    MediaIngestor,
    SlideProvider,
    Storage,
    Structurizer,
    TaskRepository,
    Transcriber,
    UsageCallback,
    WebhookNotifier,
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


def test_storage_is_abstract():
    # Порт хранилища нельзя инстанцировать напрямую.
    with pytest.raises(TypeError):
        Storage()


def test_storage_incomplete_impl_cannot_instantiate():
    # Реализация без всех 4 методов остаётся абстрактной.
    class Bad(Storage):
        async def upload_file(self, local_path, key):
            pass

    with pytest.raises(TypeError):
        Bad()


def test_storage_complete_impl_instantiates():
    class Good(Storage):
        async def upload_file(self, local_path, key):
            pass

        async def download_file(self, key, local_path):
            pass

        async def presigned_put(self, key, expires_in=None):
            return None

        async def presigned_get(
            self, key, expires_in=None, download_filename=None, content_type=None
        ):
            return None

        async def delete_prefix(self, prefix):
            return None

        async def list_keys(self, prefix):
            return []

    assert isinstance(Good(), Storage)


def test_storage_incomplete_without_list_keys_cannot_instantiate():
    # Реализация без list_keys остаётся абстрактной.
    class Bad(Storage):
        async def upload_file(self, local_path, key):
            pass

        async def download_file(self, key, local_path):
            pass

        async def presigned_put(self, key, expires_in=None):
            return None

        async def presigned_get(
            self, key, expires_in=None, download_filename=None, content_type=None
        ):
            return None

        async def delete_prefix(self, prefix):
            return None

    with pytest.raises(TypeError):
        Bad()


def test_storage_incomplete_without_delete_prefix_cannot_instantiate():
    # Реализация без delete_prefix остаётся абстрактной.
    class Bad(Storage):
        async def upload_file(self, local_path, key):
            pass

        async def download_file(self, key, local_path):
            pass

        async def presigned_put(self, key, expires_in=None):
            return None

        async def presigned_get(
            self, key, expires_in=None, download_filename=None, content_type=None
        ):
            return None

    with pytest.raises(TypeError):
        Bad()


def test_webhook_notifier_is_abstract():
    # Абстрактный порт нельзя инстанцировать напрямую.
    with pytest.raises(TypeError):
        WebhookNotifier()


@pytest.mark.asyncio
async def test_webhook_notifier_subclass_instantiates_and_notifies():
    # Сабкласс с реализованным notify инстанцируется; сигнатура с default error/error_code=None.
    calls = []

    class Impl(WebhookNotifier):
        async def notify(self, task_id, status, error=None, error_code=None):
            calls.append((task_id, status, error, error_code))

    impl = Impl()
    assert isinstance(impl, WebhookNotifier)
    await impl.notify("t1", TaskStatus.DONE)
    assert calls == [("t1", TaskStatus.DONE, None, None)]
