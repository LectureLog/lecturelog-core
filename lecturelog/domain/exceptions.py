from __future__ import annotations


class DomainError(Exception):
    """Базовое доменное исключение."""


class TaskNotFound(DomainError):
    def __init__(self, task_id: str):
        super().__init__(f"Задача не найдена: {task_id}")
        self.task_id = task_id


class ResultNotReady(DomainError):
    def __init__(self, task_id: str):
        super().__init__(f"Результат ещё не готов: {task_id}")
        self.task_id = task_id


class TranscribeFailed(DomainError):
    def __init__(self, detail: str):
        super().__init__(f"Транскрибация упала: {detail}")
        self.detail = detail


class InvalidFormat(DomainError):
    def __init__(self, allowed: list[str]):
        super().__init__(f"Недопустимый формат. Разрешены: {allowed}")
        self.allowed = allowed


class InvalidSource(DomainError):
    def __init__(self, message: str = "Передайте ровно один источник: audio, video или video_url"):
        super().__init__(message)
