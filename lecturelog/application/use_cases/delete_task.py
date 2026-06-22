from __future__ import annotations

from pathlib import PurePosixPath

from lecturelog.domain.ports import Storage, TaskRepository


class DeleteTaskUseCase:
    """Идемпотентное удаление задачи: объекты MinIO ядра + строка БД.

    Платформа ретраит DELETE при обрыве, поэтому повтор на уже удалённую
    задачу обязан завершаться успешно (никаких 404/500). Все шаги — no-op
    при отсутствии данных.
    """

    def __init__(self, repository: TaskRepository, storage: Storage):
        self._repo = repository
        self._storage = storage

    async def execute(self, task_id: str) -> None:
        # Сначала читаем задачу, чтобы достать ключ исходника (uploads/...).
        # Если задачи нет — uploads-ключ неизвестен, но results/<id>/ всё равно
        # чистим по префиксу (исходник из uuid-папки выведать нельзя — он умер
        # вместе со строкой; это допустимо: при штатном порядке строку удаляем
        # последней).
        task = await self._repo.get(task_id)

        # results/<task_id>/ всегда выводится из task_id (см. pipeline_service).
        await self._storage.delete_prefix(f"results/{task_id}/")

        # results-tmp/<task_id>/ — временные zip от /result-url; чистим немедленно
        # (lifecycle MinIO на префикс results-tmp/ — страховка от orphan вне DELETE).
        await self._storage.delete_prefix(f"results-tmp/{task_id}/")

        # uploads-исходник чистим только если ключ сохранён; удаляем всю
        # папку загрузки uploads/<uuid>/, а не единственный объект.
        if task is not None and task.source_key:
            parent = str(PurePosixPath(task.source_key).parent)
            await self._storage.delete_prefix(f"{parent}/")

        # Строку удаляем последней и идемпотентно.
        await self._repo.delete(task_id)
