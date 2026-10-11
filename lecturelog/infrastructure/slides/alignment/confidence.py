from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from lecturelog.domain.slides import SlideStatusReason

Confidence = Literal["verified", "probable", "unresolved"]


@dataclass(frozen=True)
class Calibration:
    """Уровень уверенности привязки и, для `unresolved`, его причина.

    Причина заполнена ровно тогда, когда уверенность `unresolved`: такой слайд
    становится непривязанным, и диагностика должна объяснить почему.
    """

    confidence: Confidence
    unbound_reason: SlideStatusReason | None = None


def calibrate(
    *,
    semantic_tier: str,
    margin: float,
    has_grounded_evidence: bool,
    has_competing_context: bool,
    visual_score: float | None = None,
    min_margin: float,
    model_confirmed: bool = False,
) -> Calibration:
    # Margin ниже порога значит, что другой раздел совпадает с речью сильнее
    # выбранного: такой выбор не закрепляется ни на каком уровне, даже если
    # судья подтвердил его цитатой.
    if margin < min_margin:
        return Calibration("unresolved", "stronger_competitor")
    confidence = confidence_from_margin(
        semantic_tier=semantic_tier,
        margin=margin,
        has_grounded_evidence=has_grounded_evidence,
        has_competing_context=has_competing_context,
        visual_score=visual_score,
        model_confirmed=model_confirmed,
    )
    if confidence == "unresolved":
        return Calibration(confidence, "weak_evidence")
    return Calibration(confidence)


def confidence_from_margin(
    *,
    semantic_tier: str,
    margin: float,
    has_grounded_evidence: bool,
    has_competing_context: bool,
    visual_score: float | None = None,
    model_confirmed: bool = False,
) -> Confidence:
    if (
        semantic_tier == "explicit"
        and has_grounded_evidence
        and has_competing_context
        and margin >= 1.5
    ):
        return "verified"
    # Визуальная оценка — совпадение описания картинки с речью, а не вердикт:
    # она усиливает подтверждение модели, но не заменяет его. Без вердикта
    # судьи (лексический путь, восстановление после weak/none) — не выше probable.
    if (
        model_confirmed
        and semantic_tier in {"explicit", "strong"}
        and has_grounded_evidence
        and visual_score is not None
        and visual_score >= 0.85
        and has_competing_context
        and margin >= 1.0
    ):
        return "verified"
    if semantic_tier in {"explicit", "strong"} and has_grounded_evidence:
        return "probable"
    return "unresolved"
