"""Слова-описатели картинки сравниваются по целым словам, а не по коротким началам."""

from __future__ import annotations

import pytest

from lecturelog.infrastructure.slides.alignment.grounding import is_visual_filler


@pytest.mark.parametrize(
    "word",
    [
        "фон",
        "фоне",
        "фоновый",
        "Цвет",
        "цветов",
        "цветной",
        "текст",
        "тексте",
        "схема",
        "схемы",
        "show",
        "shows",
        "виден",
        "видна",
        "слайдов",
        "изображение",
    ],
)
def test_описатель_картинки_отфильтровывается(word):
    assert is_visual_filler(word)


@pytest.mark.parametrize(
    "word",
    [
        "фонд",
        "фонарь",
        "фондовый",
        "цветок",
        "цветение",
        "текстиль",
        "текстура",
        "контекст",
        "схемотехника",
        "showcase",
        "видный",
        "виднеться",
    ],
)
def test_обычное_слово_с_общим_началом_не_описатель(word):
    assert not is_visual_filler(word)
