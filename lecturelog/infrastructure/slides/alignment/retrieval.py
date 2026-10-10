from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Set

from lecturelog.domain.slides import SectionRef, SlideCandidate, SlideCatalogEntry, TranscriptBlock
from lecturelog.infrastructure.slides.alignment.transcript import blocks_for_section

_TOKEN_RE = re.compile(r"[\w+-]+", re.UNICODE)
_BM25_K1 = 1.2
_BM25_B = 0.75
_MAX_EVIDENCE_BLOCKS = 6
# Визуальное описание — связная проза, а не список терминов: служебные слова
# короче четырёх букв отбрасываются, а словоформы сводятся к основе по первым
# пяти буквам («серверу» и «сервер» — одна основа).
_VISUAL_MIN_TOKEN = 4
_VISUAL_STEM = 5
# Сколько разных основ описания должно встретиться в речи раздела, чтобы
# визуальная оценка была полной: одно общее слово — ещё не описание схемы.
_VISUAL_SATURATION_TERMS = 3


def normalize_tokens(text: str) -> tuple[str, ...]:
    return tuple(token.casefold() for token in _TOKEN_RE.findall(text) if len(token) > 1)


def _char_ngrams(text: str, size: int = 3) -> set[str]:
    normalized = re.sub(r"\s+", " ", text.casefold()).strip()
    return {normalized[i : i + size] for i in range(max(0, len(normalized) - size + 1))}


def generate_candidates(
    entry: SlideCatalogEntry,
    sections: tuple[SectionRef, ...],
    blocks: list[TranscriptBlock],
    *,
    limit: int = 5,
    neighbor_radius: int = 1,
    visual_weight: float = 0.0,
) -> tuple[SlideCandidate, ...]:
    """Кандидаты разделов для слайда: лексическая и визуальная оценки.

    `lexical_score` — совпадение видимого текста и терминов страницы с речью
    раздела. `visual_score` — совпадение описания картинки (`visual_summary`):
    только основ, которых нет в тексте страницы, иначе одно и то же слово
    считалось бы дважды. Ранжирование разделов идёт по
    `lexical_score + visual_score * visual_weight` — той же силе доказательства,
    что и в выборе пути (`AlignmentWeights.visual_weight`).
    """
    query_parts = tuple(
        filter(
            None,
            (
                entry.title or "",
                *entry.source_concepts,
                *entry.transcript_language_terms,
                *entry.formulas,
                *(
                    part.strip()
                    for part in re.split(r"[\n•;]+", entry.visible_text)
                    if part.strip()
                ),
            ),
        )
    )
    query_tokens = set(normalize_tokens(" ".join(query_parts)))
    textual_stems = _stems(" ".join(query_parts))
    visual_stems = _stems(entry.visual_summary) - textual_stems
    # Доля описания в содержании страницы: у схемы без текста описание —
    # единственное доказательство, у страницы с богатым текстом — добавка,
    # которая не должна перебивать текст и рождать ложных конкурентов.
    visual_share = len(visual_stems) / max(len(visual_stems) + len(textual_stems), 1)
    section_documents = [(section, blocks_for_section(blocks, section)) for section in sections]
    section_counters = [
        Counter(normalize_tokens(" ".join(block.text for block in evidence)))
        for _, evidence in section_documents
    ]
    document_count = max(len(section_counters), 1)
    average_length = sum(sum(counter.values()) for counter in section_counters) / document_count
    document_frequency = {
        token: sum(token in counter for counter in section_counters) for token in query_tokens
    }
    idf = {
        token: math.log(1.0 + (document_count - frequency + 0.5) / (frequency + 0.5))
        for token, frequency in document_frequency.items()
    }
    section_stems = [
        _stems(" ".join(block.text for block in evidence)) for _, evidence in section_documents
    ]
    visual_idf = {
        stem: math.log(1.0 + (document_count - frequency + 0.5) / (frequency + 0.5))
        for stem in visual_stems
        if (frequency := sum(stem in stems for stems in section_stems))
    }
    scored: list[tuple[float, float, float | None, SectionRef, tuple[TranscriptBlock, ...]]] = []
    for (section, evidence), doc_tokens, doc_stems in zip(
        section_documents, section_counters, section_stems, strict=True
    ):
        text = " ".join(block.text for block in evidence)
        lexical = _bm25_score(
            doc_tokens,
            query_tokens,
            idf,
            average_length,
        )
        char_score = max(
            (_ngram_overlap(part, text) for part in query_parts),
            default=0.0,
        )
        score = lexical + char_score * 2.0
        visual = _visual_score(visual_idf, doc_stems) * visual_share if visual_stems else None
        strength = score + (visual or 0.0) * visual_weight
        scored.append((strength, score, visual, section, evidence))
    ranked = sorted(scored, key=lambda item: (item[0], -item[3].global_section_id), reverse=True)
    top_ids = {section.global_section_id for _, _, _, section, _ in ranked[:limit]}
    expanded = {
        section.global_section_id
        for section in sections
        if any(abs(section.global_section_id - top) <= neighbor_radius for top in top_ids)
    }
    result = []
    for _, score, visual, section, evidence in ranked:
        if section.global_section_id not in expanded:
            continue
        selected_evidence = _best_evidence_blocks(
            evidence,
            query_tokens,
            query_parts,
            idf,
            average_length,
            visual_stems,
            visual_share,
        )
        ids = tuple(block.block_id for block in selected_evidence)
        result.append(
            SlideCandidate(
                slide_num=entry.slide_num,
                global_section_id=section.global_section_id,
                evidence_block_ids=ids,
                evidence_quote=None,
                anchor_start_s=(
                    selected_evidence[0].start_s if selected_evidence else section.start_s
                ),
                anchor_end_s=(selected_evidence[-1].end_s if selected_evidence else section.end_s),
                lexical_score=score,
                visual_score=visual,
            )
        )
    return tuple(result[: limit + 2 * neighbor_radius])


def _stems(text: str) -> set[str]:
    return {
        token[:_VISUAL_STEM] for token in normalize_tokens(text) if len(token) >= _VISUAL_MIN_TOKEN
    }


def _visual_score(visual_idf: dict[str, float], document_stems: set[str]) -> float:
    """Насколько речь раздела покрывает описание картинки, 0..1.

    Покрытие взвешено по idf среди основ, которые звучат хоть в одном разделе:
    слова описания, которых лектор не произносит нигде («изображение»,
    «стрелка»), ни один раздел не различают и в знаменатель не входят.
    Полная оценка требует не меньше `_VISUAL_SATURATION_TERMS` общих основ.
    """
    total = sum(visual_idf.values())
    if not total:
        return 0.0
    shared = [stem for stem in visual_idf if stem in document_stems]
    coverage = sum(visual_idf[stem] for stem in shared) / total
    return coverage * min(1.0, len(shared) / _VISUAL_SATURATION_TERMS)


def _bm25_score(
    document: Counter[str],
    query_tokens: set[str],
    idf: dict[str, float],
    average_length: float,
) -> float:
    length = sum(document.values())
    normalization = _BM25_K1 * (1.0 - _BM25_B + _BM25_B * length / max(average_length, 1.0))
    return sum(
        idf[token] * document[token] * (_BM25_K1 + 1.0) / (document[token] + normalization)
        for token in query_tokens
        if document[token]
    )


def _ngram_overlap(query: str, document: str) -> float:
    query_ngrams = _char_ngrams(query)
    if not query_ngrams:
        return 0.0
    return len(query_ngrams & _char_ngrams(document)) / len(query_ngrams)


def _best_evidence_blocks(
    evidence: tuple[TranscriptBlock, ...],
    query_tokens: set[str],
    query_parts: tuple[str, ...],
    idf: dict[str, float],
    average_length: float,
    visual_stems: Set[str] = frozenset(),
    visual_share: float = 0.0,
) -> tuple[TranscriptBlock, ...]:
    ranked = sorted(
        evidence,
        key=lambda block: (
            _bm25_score(
                Counter(normalize_tokens(block.text)),
                query_tokens,
                idf,
                average_length,
            )
            + max(
                (_ngram_overlap(part, block.text) for part in query_parts),
                default=0.0,
            )
            + (
                len(visual_stems & _stems(block.text)) / len(visual_stems) * visual_share
                if visual_stems
                else 0.0
            ),
            -block.start_s,
        ),
        reverse=True,
    )
    selected = ranked[:_MAX_EVIDENCE_BLOCKS]
    return tuple(sorted(selected, key=lambda block: (block.start_s, block.block_id)))
