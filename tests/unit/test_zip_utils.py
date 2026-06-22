from __future__ import annotations

from zipfile import ZipFile

from lecturelog.infrastructure.export.zip_utils import zip_dir


def test_zip_dir_packs_with_relative_arcnames(tmp_path):
    # Раскладка: src_root/output/<...>; base=src_root -> arcname начинается с output/.
    src_root = tmp_path / "work"
    output = src_root / "output"
    (output / "audio").mkdir(parents=True)
    (output / "конспект.md").write_text("hello", encoding="utf-8")
    (output / "audio" / "01-a.mp3").write_bytes(b"\x00\x01")

    zip_path = tmp_path / "result.zip"
    zip_dir(output, zip_path, base=src_root)

    with ZipFile(zip_path) as zf:
        names = sorted(zf.namelist())
        assert names == ["output/audio/01-a.mp3", "output/конспект.md"]
        assert zf.read("output/конспект.md") == b"hello"


def test_zip_dir_overwrites_existing(tmp_path):
    src_root = tmp_path / "work"
    output = src_root / "output"
    output.mkdir(parents=True)
    (output / "a.txt").write_text("a", encoding="utf-8")

    zip_path = tmp_path / "result.zip"
    zip_path.write_bytes(b"stale-not-a-zip")  # старый файл должен быть перезаписан
    zip_dir(output, zip_path, base=src_root)

    with ZipFile(zip_path) as zf:
        assert zf.namelist() == ["output/a.txt"]
