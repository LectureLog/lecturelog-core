from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def zip_dir(src_root: Path, zip_path: Path, base: Path) -> Path:
    """Упаковать все файлы из src_root в zip_path.

    arcname внутри архива считается относительно base, поэтому при base=src_root.parent
    пути в архиве начинаются с имени src_root (например, output/...). Старый файл архива
    перезаписывается. DRY: используется и автономной веткой pipeline, и сборкой /result.
    """
    zip_path = Path(zip_path)
    if zip_path.exists():
        zip_path.unlink()
    with ZipFile(zip_path, "w", compression=ZIP_DEFLATED) as zip_file:
        for path in sorted(Path(src_root).rglob("*")):
            if path.is_file():
                zip_file.write(path, arcname=path.relative_to(base).as_posix())
    return zip_path
