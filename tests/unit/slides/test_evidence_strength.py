"""Одна формула силы доказательства для пути DP и для competition_margin."""

from __future__ import annotations

import pytest

from lecturelog.domain.slides import SlideCandidate
from lecturelog.infrastructure.slides.alignment.sequence import AlignmentWeights, align_sequence
from lecturelog.infrastructure.slides.alignment.service import DocumentAlignmentService


def _cand(section: int, lexical: float, tier: str, visual: float | None = None) -> SlideCandidate:
    return SlideCandidate(
        1, section, (section + 1,), "цитата", 0.0, 1.0, lexical, tier, visual_score=visual
    )


@pytest.mark.parametrize(
    ("tier", "bonus"), [("explicit", 4.0), ("strong", 2.0), ("weak", 0.0), ("none", -1.0)]
)
def test_score_пути_это_лексика_плюс_бонус_вердикта_плюс_визуал(tier, bonus):
    """Фиксируем текущее поведение DP: score слайда = lexical·w + бонус tier + visual·w_visual."""
    weights = AlignmentWeights()
    item = align_sequence([1], {1: (_cand(1, 6.0, tier, visual=0.5),)}, (), weights)[0]
    assert item.score == pytest.approx(6.0 + bonus + 0.5 * weights.visual_weight)


def test_score_пути_учитывает_lexical_weight():
    weights = AlignmentWeights(lexical_weight=2.0)
    item = align_sequence([1], {1: (_cand(1, 6.0, "explicit"),)}, (), weights)[0]
    assert item.score == pytest.approx(6.0 * 2.0 + weights.explicit_bonus)


def test_competition_margin_считается_той_же_формулой_без_бонуса_вердикта():
    weights = AlignmentWeights(lexical_weight=2.0)
    mine = _cand(1, 5.0, "strong", visual=0.5)
    rival = _cand(2, 4.0, "none", visual=1.0)
    out = DocumentAlignmentService._with_competition(mine, (mine, rival), weights)
    expected = (5.0 * 2.0 + 0.5 * weights.visual_weight) - (4.0 * 2.0 + 1.0 * weights.visual_weight)
    assert out.competition_margin == pytest.approx(expected)
