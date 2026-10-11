from __future__ import annotations

import logging
import re

from lecturelog.domain.slides import SlideAssignment, SlideCatalogEntry, SlidePlacement
from lecturelog.infrastructure.slides.alignment.grounding import (
    evidence_matches_entry,
    evidence_specificity,
)
from lecturelog.infrastructure.slides.alignment.markers import (
    inject_marker,
    parse_markdown_blocks,
    strip_slide_markers,
)

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r"[^\W\d_]{4,}", re.UNICODE)
# Конспект пересказывает речь не дословно: словоформы меняются, поэтому слова
# сравниваются по началу. Пяти букв хватает, чтобы «слоев»/«слоёв» не путались
# с «словами», и мало, чтобы «архитектуры» совпала с «архитектурой».
_STEM_LENGTH = 5
# Одно общее слово («который», «можно») случайно; место речи подтверждают два.
_MIN_SHARED_STEMS = 2


def _stems(text: str) -> set[str]:
    return {word.casefold().replace("ё", "е")[:_STEM_LENGTH] for word in _WORD_RE.findall(text)}


def anchor_assignment(
    assignment: SlideAssignment,
    entry: SlideCatalogEntry | None,
    markdown: str,
    evidence_text: str = "",
) -> tuple[str, SlidePlacement]:
    """Поставить маркер слайда после абзаца, где он обсуждается.

    ``evidence_text`` — текст реплик-доказательств назначения. Слайд подтверждает,
    что абзац о нём; реплика — какой из таких абзацев пересказывает момент показа.
    Без неё лексика слайда тянет маркер к первому абзацу с его термином, даже если
    слайд показан в конце раздела.
    """
    if assignment.match_status == "unbound" and assignment.global_section_id is not None:
        # Непривязанный слайд обсуждали, но место в речи не установлено надёжно:
        # он стоит в галерее раздела с самым сильным доказательством, а не в
        # приложении и не внутри абзаца.
        return markdown, SlidePlacement(
            assignment.slide_num,
            "section_gallery",
            assignment.global_section_id,
            gallery_position="after_content",
            anchor_confidence="fallback",
            fallback_reason=f"unbound:{assignment.status_reason}",
        )
    if assignment.match_status != "discussed" or assignment.global_section_id is None:
        return markdown, SlidePlacement(
            assignment.slide_num,
            "appendix",
            None,
            anchor_confidence="none",
            fallback_reason=assignment.reason_code,
        )
    if entry is None:
        return markdown, SlidePlacement(
            assignment.slide_num,
            "section_gallery",
            assignment.global_section_id,
            gallery_position="after_content",
            anchor_confidence="probable",
            fallback_reason="catalog_entry_missing",
        )
    # Existing markers are not semantic content and must not shift the stable
    # content-block index expected by inject_marker.
    blocks = parse_markdown_blocks(strip_slide_markers(markdown))
    ranked = [
        (evidence_specificity(block.text, entry), index)
        for index, block in enumerate(blocks)
        if not block.atomic and evidence_matches_entry(block.text, entry)
    ]
    if not ranked:
        return markdown, SlidePlacement(
            assignment.slide_num,
            "section_gallery",
            assignment.global_section_id,
            gallery_position="after_content",
            anchor_confidence="fallback",
            fallback_reason="no_safe_semantic_block",
        )
    specificity = max(ranked)[0]
    evidence_stems = _stems(evidence_text)
    # При равных совпадениях — более ранний абзац: слайд показывают, когда о нём
    # заговорили впервые, а не на последнем упоминании.
    shared_stems, _, negated_index = max(
        (len(evidence_stems & _stems(blocks[index].text)), block_specificity, -index)
        for block_specificity, index in ranked
    )
    block_index = -negated_index if shared_stems >= _MIN_SHARED_STEMS else max(ranked)[1]
    verified = assignment.assignment_confidence == "verified"
    # Для неверифицированного назначения одного лишь пересечения слов мало: слайд
    # рядом со случайно похожим абзацем вводит в заблуждение сильнее, чем галерея.
    # Дословная фраза слайда или совпавший редкий токен — достаточное основание.
    if not verified and specificity[0] < 1:
        return markdown, SlidePlacement(
            assignment.slide_num,
            "section_gallery",
            assignment.global_section_id,
            gallery_position="after_content",
            anchor_confidence="probable",
            fallback_reason="weak_evidence_only",
        )
    try:
        anchored_markdown = inject_marker(
            markdown,
            slide_num=assignment.slide_num,
            block_index=block_index,
            side="after",
        )
    except Exception as error:  # noqa: BLE001 - anchoring is a post-render fail-safe boundary
        logger.warning("slide %d marker injection failed: %s", assignment.slide_num, error)
        return markdown, SlidePlacement(
            assignment.slide_num,
            "section_gallery",
            assignment.global_section_id,
            gallery_position="after_content",
            anchor_confidence="fallback",
            fallback_reason="anchor_injection_failed",
        )
    marker = f"<!-- slide:{assignment.slide_num} -->"
    if anchored_markdown.count(marker) != 1:
        logger.warning("slide %d marker verification failed", assignment.slide_num)
        return markdown, SlidePlacement(
            assignment.slide_num,
            "section_gallery",
            assignment.global_section_id,
            gallery_position="after_content",
            anchor_confidence="fallback",
            fallback_reason="anchor_injection_failed",
        )
    return (
        anchored_markdown,
        SlidePlacement(
            assignment.slide_num,
            "inline",
            assignment.global_section_id,
            block_index=block_index,
            side="after",
            anchor_confidence="verified" if verified else "probable",
        ),
    )
