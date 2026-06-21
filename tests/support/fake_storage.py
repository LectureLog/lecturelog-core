from __future__ import annotations

from pathlib import Path

from lecturelog.domain.ports import Storage


class FakeStorage(Storage):
    """In-memory реализация порта Storage для тестов без MinIO.

    Объекты хранятся в dict по ключу. Флаг public имитирует наличие
    публичного endpoint: при public=False presigned возвращают None
    (как реальный адаптер без S3_PUBLIC_ENDPOINT).
    """

    def __init__(self, public: bool = False):
        self.public = public
        self.objects: dict[str, bytes] = {}

    async def upload_file(self, local_path: Path, key: str) -> None:
        self.objects[key] = Path(local_path).read_bytes()

    async def download_file(self, key: str, local_path: Path) -> None:
        local_path = Path(local_path)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(self.objects[key])

    async def presigned_put(self, key: str, expires_in: int | None = None) -> str | None:
        if not self.public:
            return None
        return f"https://fake/{key}?op=put"

    async def presigned_get(
        self,
        key: str,
        expires_in: int | None = None,
        download_filename: str | None = None,
        content_type: str | None = None,
    ) -> str | None:
        if not self.public:
            return None
        url = f"https://fake/{key}?op=get"
        if download_filename is not None:
            url += f"&filename={download_filename}.zip"
        return url
