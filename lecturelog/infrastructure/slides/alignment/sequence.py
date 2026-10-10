from __future__ import annotations

from dataclasses import dataclass

from lecturelog.domain.slides import (
    SlideAssignment,
    SlideCandidate,
    SlideRelation,
    SlideStatusReason,
)
from lecturelog.infrastructure.slides.alignment.confidence import calibrate


@dataclass(frozen=True)
class AlignmentWeights:
    unmatched_score: float = 0.0
    backtrack_penalty: float = 1.5
    jump_penalty: float = 0.08
    explicit_bonus: float = 4.0
    strong_bonus: float = 2.0
    lexical_weight: float = 1.0
    visual_weight: float = 3.0
    progressive_same_section_bonus: float = 0.75
    # Порог margin выбора: ниже него слайд непривязанный с причиной
    # `stronger_competitor` на любом уровне уверенности. Margin выбора пути
    # неотрицателен, поэтому при пороге 0 срабатывает только отрицательный
    # competition_margin — конкурент из другого раздела лексически сильнее.
    min_margin: float = 0.0


def align_sequence(
    slide_nums: list[int],
    candidates: dict[int, tuple[SlideCandidate, ...]],
    relations: tuple[SlideRelation, ...] = (),
    weights: AlignmentWeights = AlignmentWeights(),
) -> tuple[SlideAssignment, ...]:
    duplicate_of = {
        relation.slide_num: relation.canonical_slide_num
        for relation in relations
        if relation.kind == "exact_duplicate"
    }
    progressive_of = {
        relation.slide_num: relation.canonical_slide_num
        for relation in relations
        if relation.kind == "progressive_build"
    }
    best_total, best_path = _solve(
        slide_nums,
        candidates,
        duplicate_of,
        progressive_of,
        weights,
    )
    assignments: list[SlideAssignment] = []
    for index, (slide_num, chosen) in enumerate(zip(slide_nums, best_path, strict=True)):
        if slide_num in duplicate_of:
            assignments.append(
                SlideAssignment(
                    slide_num,
                    "duplicate",
                    None,
                    (),
                    None,
                    "verified",
                    0.0,
                    f"duplicate_of:{duplicate_of[slide_num]}",
                )
            )
            continue
        if chosen is None:
            # Путь пропустил слайд. Если у него всё же есть кандидат с
            # доказательством, пропуск — цена порядка колоды, а не признак того,
            # что лектор слайд не обсуждал.
            assignments.append(
                _unbound_or_unmentioned(
                    slide_num,
                    candidates.get(slide_num, ()),
                    None,
                    "deck_order_conflict",
                    None,
                    weights,
                )
            )
            continue
        constrained_total, _ = _solve(
            slide_nums,
            candidates,
            duplicate_of,
            progressive_of,
            weights,
            forbidden=(index, chosen.global_section_id),
        )
        path_margin = best_total - constrained_total
        margin = (
            min(path_margin, chosen.competition_margin)
            if chosen.competition_margin is not None
            else path_margin
        )
        best_score = _candidate_score(chosen, weights)
        calibration = calibrate(
            semantic_tier=chosen.semantic_tier,
            margin=margin,
            has_grounded_evidence=bool(chosen.evidence_block_ids and chosen.evidence_quote),
            has_competing_context=chosen.competition_margin is not None,
            visual_score=chosen.visual_score,
            min_margin=weights.min_margin,
        )
        if calibration.unbound_reason is None:
            assignments.append(
                SlideAssignment(
                    slide_num=slide_num,
                    match_status="discussed",
                    global_section_id=chosen.global_section_id,
                    evidence_block_ids=chosen.evidence_block_ids,
                    anchor_s=(chosen.anchor_start_s + chosen.anchor_end_s) / 2,
                    assignment_confidence=calibration.confidence,
                    score=best_score,
                    reason_code=_reason_code(chosen, margin),
                )
            )
            continue
        pool = candidates.get(slide_num, ())
        if calibration.unbound_reason == "stronger_competitor":
            # Конкуренты в выбор пути не входят, но галерея должна достаться
            # разделу с самым сильным доказательством — возможно, конкуренту.
            pool = (*pool, *chosen.competitors)
        assignments.append(
            _unbound_or_unmentioned(
                slide_num,
                pool,
                chosen,
                calibration.unbound_reason,
                margin,
                weights,
            )
        )
    return tuple(assignments)


def strongest_candidate(
    pool: tuple[SlideCandidate, ...],
    weights: AlignmentWeights,
    *,
    preferred: SlideCandidate | None = None,
) -> SlideCandidate | None:
    """Кандидат с самым сильным доказательством — его раздел получает непривязанный слайд.

    Сила доказательства — та же оценка `_candidate_score`, что и в выборе пути:
    `lexical_score * lexical_weight + бонус semantic_tier + visual_score * visual_weight`.
    Порядок колоды в неё не входит: он подсказка для пути, а не свойство
    доказательства. Доказательством считается только кандидат, который сам по
    себе сильнее пропуска слайда (`unmatched_score`). При равной силе выигрывает
    `preferred` (выбор пути), затем более ранний раздел.
    """
    evidence = [
        candidate
        for candidate in pool
        if _candidate_score(candidate, weights) > weights.unmatched_score
    ]
    if not evidence:
        return None
    return max(
        evidence,
        key=lambda candidate: (
            _candidate_score(candidate, weights),
            candidate is preferred,
            -candidate.global_section_id,
        ),
    )


def _unbound_or_unmentioned(
    slide_num: int,
    pool: tuple[SlideCandidate, ...],
    chosen: SlideCandidate | None,
    unbound_reason: SlideStatusReason,
    margin: float | None,
    weights: AlignmentWeights,
) -> SlideAssignment:
    """Слайд без уверенной привязки: галерея раздела с сильнейшим доказательством или приложение."""
    strongest = strongest_candidate(pool, weights, preferred=chosen)
    if strongest is None:
        return SlideAssignment(
            slide_num,
            "unmentioned",
            None,
            (),
            None,
            "unresolved",
            0.0,
            "no_supported_evidence",
            status_reason="no_candidates",
        )
    return SlideAssignment(
        slide_num,
        "unbound",
        strongest.global_section_id,
        strongest.evidence_block_ids,
        # Галерея не привязана к месту речи — якоря нет.
        None,
        "unresolved",
        _candidate_score(strongest, weights),
        _unbound_reason_code(strongest, chosen, margin),
        status_reason=unbound_reason,
    )


def _unbound_reason_code(
    strongest: SlideCandidate, chosen: SlideCandidate | None, margin: float | None
) -> str:
    """reason_code описывает сильнейшего кандидата, куда ушёл слайд.

    Margin посчитан для выбора пути, поэтому у сильнейшего он указан, только
    если это и есть выбор; иначе выбор пути и его margin записаны отдельно.
    """
    if chosen is None or strongest is chosen:
        return _reason_code(strongest, margin)
    return (
        f"{_reason_code(strongest, None)}"
        f":path_section={chosen.global_section_id}"
        f":path_margin={'none' if margin is None else f'{margin:.3f}'}"
    )


def _reason_code(candidate: SlideCandidate, margin: float | None) -> str:
    # margin=none — путь пропустил слайд, и margin выбора для него не считался.
    return (
        f"semantic_{candidate.semantic_tier}"
        f":lexical={candidate.lexical_score:.3f}"
        f":visual={(candidate.visual_score or 0.0):.3f}"
        f":margin={'none' if margin is None else f'{margin:.3f}'}"
    )


def _solve(
    slide_nums: list[int],
    candidates: dict[int, tuple[SlideCandidate, ...]],
    duplicate_of: dict[int, int],
    progressive_of: dict[int, int],
    weights: AlignmentWeights,
    forbidden: tuple[int, int] | None = None,
) -> tuple[float, list[SlideCandidate | None]]:
    states: dict[int | None, tuple[float, list[SlideCandidate | None]]] = {None: (0.0, [])}
    for slide_index, slide_num in enumerate(slide_nums):
        if slide_num in duplicate_of:
            states = {
                previous: (score, path + [None]) for previous, (score, path) in states.items()
            }
            continue
        options: tuple[SlideCandidate | None, ...] = (
            *(
                candidate
                for candidate in candidates.get(slide_num, ())
                if forbidden != (slide_index, candidate.global_section_id)
            ),
            None,
        )
        next_states: dict[int | None, tuple[float, list[SlideCandidate | None]]] = {}
        for previous_section, (base_score, path) in states.items():
            for option in options:
                section = option.global_section_id if option else previous_section
                score = base_score + _candidate_score(option, weights)
                if option is not None and previous_section is not None:
                    delta = option.global_section_id - previous_section
                    if delta < 0:
                        score -= weights.backtrack_penalty * abs(delta)
                    elif delta > 1:
                        score -= weights.jump_penalty * (delta - 1)
                    if slide_num in progressive_of and option.global_section_id == previous_section:
                        score += weights.progressive_same_section_bonus
                existing = next_states.get(section)
                if existing is None or score > existing[0]:
                    next_states[section] = (score, path + [option])
        states = next_states
    return max(states.values(), key=lambda state: state[0])


def _candidate_score(candidate: SlideCandidate | None, weights: AlignmentWeights) -> float:
    if candidate is None:
        return weights.unmatched_score
    bonus = {
        "explicit": weights.explicit_bonus,
        "strong": weights.strong_bonus,
        "weak": 0.0,
        "none": -1.0,
    }[candidate.semantic_tier]
    return (
        candidate.lexical_score * weights.lexical_weight
        + bonus
        + (candidate.visual_score or 0.0) * weights.visual_weight
    )
