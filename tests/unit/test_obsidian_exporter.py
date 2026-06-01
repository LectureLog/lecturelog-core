import zipfile

import pytest

from lecturelog.domain.models import Topic, Section
from lecturelog.infrastructure.export.obsidian_exporter import ObsidianExporter, _slugify


def test_slugify_cyrillic_and_spaces():
    assert _slugify("Введение в тему") == "введение-в-тему"


def test_slugify_strips_punctuation():
    out = _slugify("Раздел #1: основы!")
    assert " " not in out and "#" not in out and ":" not in out


def test_slugify_empty_falls_back():
    assert _slugify("!!!") == "section"


@pytest.mark.asyncio
async def test_export_produces_zip_with_expected_structure(tmp_path):
    # подготовим фейковые фрагменты и слайды
    frag = tmp_path / "f1.mp3"; frag.write_bytes(b"audio")
    slide = tmp_path / "s1.png"; slide.write_bytes(b"png")
    sec = Section(title="Введение", start="0:00", end="5:00", content="текст", slide_indices=[1])
    topic = Topic(title="Тема", start="0:00", end="5:00", sections=[sec], slide_indices=[1])

    exporter = ObsidianExporter()
    zip_path = await exporter.export(
        topics=[topic], media_fragments=[frag], slide_images=[slide],
        output_dir=tmp_path / "export", media_kind="audio",
    )
    assert zip_path.exists() and zip_path.suffix == ".zip"
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
    assert any(n.endswith("конспект.md") for n in names)
    assert any("/audio/" in n or "audio/" in n for n in names)
    assert any("slide" in n for n in names)
