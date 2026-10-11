from lecturelog.domain.slides import SlideCandidate, SlideRelation
from lecturelog.infrastructure.slides.alignment.sequence import align_sequence


def _candidate(
    slide: int,
    section: int,
    score: float,
    tier: str = "explicit",
    competition_margin: float | None = None,
) -> SlideCandidate:
    return SlideCandidate(
        slide,
        section,
        (section + 1,),
        "grounded",
        section * 10,
        section * 10 + 5,
        score,
        tier,
        competition_margin=competition_margin,
    )


def test_sequence_allows_unmatched_and_does_not_force_weak_slide() -> None:
    result = align_sequence(
        [1, 2],
        {
            1: (_candidate(1, 0, 5),),
            2: (_candidate(2, 1, -2, "none"),),
        },
    )
    assert result[0].match_status == "discussed"
    assert result[1].match_status == "unmentioned"


def test_single_candidate_cannot_be_verified_without_real_competition() -> None:
    result = align_sequence([1], {1: (_candidate(1, 0, 50),)})

    assert result[0].match_status == "discussed"
    assert result[0].assignment_confidence == "probable"


def test_real_runner_up_margin_can_verify_explicit_evidence() -> None:
    result = align_sequence(
        [1],
        {1: (_candidate(1, 0, 10, competition_margin=3.0),)},
    )

    assert result[0].assignment_confidence == "verified"


def test_sequence_softly_allows_strong_backtrack() -> None:
    result = align_sequence(
        [1, 2],
        {1: (_candidate(1, 2, 8),), 2: (_candidate(2, 0, 12),)},
    )
    assert [item.global_section_id for item in result] == [2, 0]


def test_progressive_build_is_not_suppressed_as_duplicate() -> None:
    result = align_sequence(
        [1, 2],
        {1: (_candidate(1, 0, 5),), 2: (_candidate(2, 0, 5),)},
        (SlideRelation(2, "progressive_build", "g", 1),),
    )
    assert [item.match_status for item in result] == ["discussed", "discussed"]


def test_unbound_slide_goes_to_section_with_strongest_evidence_not_path_choice() -> None:
    """Сила доказательства = lexical·1.0 + бонус tier (explicit 4, strong 2) + visual·2.25.

    Слайд 2: раздел 1 — strong без цитаты, 3·1 + 2 = 5.0 (путь выбирает его: раздел 0
    после раздела 1 стоит штрафа возврата 1.5); раздел 0 — explicit,
    0.5·1 + 4 + 0.5·2.25 = 5.625. Уверенность выбора unresolved (нет цитаты), значит
    слайд непривязанный и идёт в раздел 0 — самое сильное доказательство.
    """
    anchor = _candidate(1, 1, 20, competition_margin=10.0)
    path_choice = SlideCandidate(2, 1, (2,), None, 10, 15, 3.0, "strong")
    strongest = SlideCandidate(2, 0, (1,), None, 0, 5, 0.5, "explicit", visual_score=0.5)

    result = align_sequence([1, 2], {1: (anchor,), 2: (path_choice, strongest)})

    assert result[1].match_status == "unbound"
    assert result[1].global_section_id == 0
    assert result[1].status_reason == "weak_evidence"
    assert result[1].score == 5.625
