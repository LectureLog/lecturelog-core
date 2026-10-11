# Independent lecture quality report

- Lecture: compilers-anf (Russian, 01:22:24, 20-slide PDF deck)
- Mode: legacy (no document-slide-alignment.json; slides sit in section galleries)
- task_id: e5c813e0d0384b4a8d91586fbb237958
- Code: tag stage1-baseline @1ad9384
- Judge: claude sonnet, effort medium
- Source hashes (sha256):
  - slides.pdf `a1b4fa5f2c000d23cade866a2a19129fb18cf57493f0fa8223e3ece16f80d6ae`
  - transcript.srt `0941eeb6cf8bd2a8cd8a93dc73fb8b8820f564fa180c8b230cdc9273c66f2c6d`
  - конспект.md `af89da14849ea7cd256fd266ff8e1d5d043cbe3f5639cf4b774931cd4304ef86`
  - structure.json `cac080336c74ae71e28b734154490720dd17d953c96f77d3d2d05f62f9c7f4d3`

## Scope and inventory

- Inputs inspected: result/output/{конспект.md, transcript.srt, structure.json, slides/slide-01..20.png}; source deck slides.pdf (native text via pdftotext, images viewed for slides 5 and 19, the two slides with no/graphic text).
- Sections / blocks / cues / slides: 5 H1, 21 H2 sections (one H3), 17 tangent callouts, 1420 transcript cues (00:00:04 to 01:22:24), 20 slides.
- Missing artifacts: document-slide-alignment.json (expected in legacy), audio cuts (removed for space, not a defect). Verified/probable/unresolved confidence does not exist in legacy: those metrics are n/a, not unknown.

## Sampling method

- The whole transcript was read end to end (all 1420 cues), so every slide was labelled against a full read plus targeted greps (runtime, libc, linker, ELF, GC, Dragon book, references).
- Note: the whole note was read (all 21 sections), not sampled; beginning, middle and end all covered.
- Order of work: slide text and images, then full transcript, then pass-A labels (recorded below), then the note. While inventorying note headings with a grep, the slide image markers were displayed. This happened after the pass-A labels had been fixed and no label was changed afterwards. structure.json (slide_keys/slide_nums per subtopic) was opened only in pass B and merely confirmed the markers in the note.
- Granularity: legacy places slides as a gallery at the top of a section. "Best context hit" therefore means the placed section contains the strongest explanation of the slide; "acceptable" means the section lies in the accepted range.

## Pass-A ground truth

Time ranges are transcript cue times. `S##` = note section (H2) numbers 01..21 in document order.

| Slide | Role | Discussion status | Central concepts | Preferred context | Acceptable range | Evidence |
| ---: | --- | --- | --- | --- | --- | --- |
| 1 | title | discussed (role-based) | lecture title "Компиляторы. ANF" | lecture start 00:03:54 | 00:00:04-00:06:35 | cue 35 "сегодня некоторые поверхностные темы..." (title slide, start of covered span) |
| 2 | content | discussed | goal RISC-V asm; f(x+y), nested functions, anonymous, partial application, tuples; middle-end | 00:03:54-00:06:25 | same | cues 36-60 "никак вы не можете в ассемблер написать f от x плюс y"; "Функции можно возвращать из функций, анонимные функции бывают, частичное применение" |
| 3 | section_divider | discussed (role) | divider "ANF" | just before 00:06:25 | 00:05:00-00:06:40 | cue 82 "И 1-ое, что нам стоит сделать, это прикрутить... специальное представление программ" |
| 4 | content | discussed | ANF def; immexpr/cexpr/aexpr; atomic args | 00:06:40-00:10:35 | same | "Простыми аргументами считаются переменные и ... константы", "разваливается на 3 вида конструкций" |
| 5 | visual_example | discussed | example `(5+4)-2` | 00:10:39-00:10:58 | 00:10:39-00:11:27 | "5 плюс 4 минус 2 это довольно простое выражение" (image-only slide, viewed) |
| 6 | content | discussed | example 1 -> `let v1 = 5+4 in v1-2`; example 2 `let x = 5 in x`; types recap | 00:10:39-00:11:30 | 00:10:39-00:13:20 | "v 1 равно 5 плюс 4 минус v 1 минус 2"; "Wet x равно 5 n x это уже выражение в ANF" |
| 7 | content | discussed | wrapper constructors CImmExpr/ACExpr | 00:11:31-00:13:20 | same | "приходится добавлять такие вот фейковые конструкторы ... заворачивать" |
| 8 | content | discussed | anf with hole, Num/Id/Plus, why `(* bad *)` | 00:13:25-00:16:05 | 00:13:25-00:17:37 | "трюк ... напоминает contination passing style ... выражение типа с дыркой" |
| 9 | content | discussed | `ALet("result_of_plus", CPlus, hole (ImmId ...))`, fresh name | 00:16:07-00:17:50 | 00:15:20-00:17:50 | "заводим специальное новое имя ... затыкаем дырку новым именем ... свежее во всей программе" |
| 10 | summary | discussed | conclusions: let/if hard; trivial lets; curried temp1; arity info; inline `A<B` into if; typecheck first | 00:20:06-00:22:24 and 00:51:53-00:54:30 | 00:20:06-00:54:30 (S08, S09, S13) | "let x равно игрек in x, который можно просто записать как игрек"; "мусорная INF требует большого ассемблера"; "если у вас в условии стоит целочисленное меньше... оставить внутри" |
| 11 | content | discussed | `1+(if x then y else z)+2`; variant 1 fresh; variant 2 duplicate; blow-up | 00:54:45-00:56:42 | same (S13 end) | "1-ый вариант ... led fresh равно ... if"; "2-ой вариант ... запихиваете вовнутрь в обе ветки ... Код взрывается" |
| 12 | content | discussed | variant 3: local function `fresh`; resembles CPS | 00:56:54-00:58:00 | 00:56:54-00:59:30 | "протаскивается только вызов функции ... Это вам напоминает ... ЦПС" |
| 13 | summary | discussed | pros/cons: simple, code blow-up, not closed under beta/inline, CPS alternative | 00:59:32-01:01:57 | 00:56:54-01:02:02 (S14) | "незамкнутость относительно операции инлайн"; "с CPS-представлением другие проблемы" |
| 14 | section_divider | discussed (role) | divider "closure conversion" | 01:05:07-01:06:24 | 01:02:05-01:06:40 | "Дальше нам нужно повозиться с замыканиями"; "делают преобразования замыканий" |
| 15 | visual_example | discussed | nested `fack` with continuation lambda; OCaml has nested/anon functions, asm doesn't | 01:06:24-01:07:57 | 01:06:24-01:08:01 | "запускается анонимная функция как продолжение. И в нее попадают через замыкания к и н" |
| 16 | content | discussed | closure conversion options (explicit args / tuple / chain links, displays); free-variable search | 01:08:01-01:13:46 | same | "собираете все свободные переменные"; "складывать в ncle"; "В DragonBook ... дисплеи и чейн-ринги" |
| 17 | content | discussed | pass free names explicitly; extracted `fack1 k n m` | 01:13:50-01:15:13 | 01:13:50-01:15:13; short recap 01:18:31-01:18:45 | "я сделал для анонимной функции 2 дополнительных аргумента ... Получилась функция трех аргументов" |
| 18 | content | discussed | lambda lifting; one partial application left | 01:18:35-01:19:30 | 01:15:01-01:19:30 | "лямбда-лифтинг и все вложенные LET-ы ... сделать верхнеуровневыми LET-ами" |
| 19 | visual_example | partially_discussed | runtime incl. closure creation/call, GC, IO; libc/linker diagram; arity calls | 01:20:51-01:21:36 | same | only partial-application runtime, code pointer, calling convention discussed; no libc/linker/ELF/GC/IO in any cue (greps empty); lecturer: "Короче, слайды дальше неинтересно" (01:22:20) |
| 20 | reference_or_table (appendix-like) | unmentioned | bibliography [1]-[5] | n/a | end of lecture or appendix | only a spoken "DragonBook" (01:12:53) and "статья ... 85-ом" (01:07:03); no references read |

Counts: discussed 18, partially_discussed 1 (slide 19), unmentioned 1 (slide 20), unknown 0. Slides 1, 3, 14 are role-based labels (title/divider).

## Scorecard

| Dimension | Score or unknown | Confidence | Evidence summary |
| --- | ---: | --- | --- |
| Faithfulness | 70 (range 62-78) | medium | Most blocks track the transcript closely; defects: slide code and text injected into unrelated sections (S12, S14), "Administrative Normal Form" invented (slide says "A Normal Form"), "Код... нужно писать на C" not in transcript (cue 1406), 6 `[неясный фрагмент]` holes and several truncated sentences |
| Content coverage | 88 | high | Contiguous 00:00:04-01:22:24 in 21 sections; tail (lambda lifting, C codegen, partial-application runtime) present; the classroom Q&A about arity (18 min) is compressed but represented |
| Block quality | 70 | medium | Readable and structured; truncations mid-sentence (S02 end, S07, S08, S10, S14 end) and 17 tangent callouts, some containing technical content (S19 callouts) |
| Document structure | 74 | medium | Sensible 5-part arc; S12 "Частичное применение и арность" (00:49:03) sits under the "условные операторы" H1 although it continues the arity discussion of H1 3; S01-S02 organizational material correctly isolated |
| Language consistency | 85 | medium | Russian prose throughout; terms bold; ASR leftovers kept: "INFO", "энкли", "на сэмпле", "Kabla/комбле" (S15, S17, S18) |
| Slide semantic relevance | 53 (10/19 acceptable) | high | see metrics; 9 of 19 discussed slides sit in a topically wrong section |
| Slide anchor precision | 42 (8/19 best-context) | high | section-gallery granularity; 10 slides collapsed into one gallery |
| Confidence calibration | n/a | n/a | legacy has no verified/probable/unresolved |

## Critical and major defects

1. major, `slide_collapse_tail`: slides 11-16 (and 17-20) are all dumped into the gallery of the last section S21 `Лямбда-лифтинг, трансляция в C и завершение лекции` (structure.json subtopic [4].5 slide_nums 11..20).
   - Better contexts: slides 11-12 -> S13/S14 (00:54:45-00:58:00, "1-ый вариант... 2-ой вариант... Код взрывается"); slide 13 -> S14 (00:59:32-01:01:57, "незамкнутость относительно операции инлайн"); slide 14 -> S16 (01:05:07, "повозиться с замыканиями"); slide 15 -> S16/S17 (01:06:24-01:07:57); slide 16 -> S17/S18 (01:08:01-01:13:46).
   - Impact: the reader sees 10 slides after the last paragraph, 25-50 minutes after their discussion; the closure-conversion divider (14) appears after the closure-conversion text.
2. major, `wrong_section`: slide 9 (`ALet("result_of_plus", ...)`) placed in S12 [00:49:03-00:51:53] about arity of a function passed as argument. Better: S06 [00:13:38-00:17:37], cue 00:16:17 "Мы заводим специальное новое имя ... затыкаем дырку новым именем".
3. major, `unsupported_claim_from_slide`: S12 note text re-types slide 9's code and states "функция имеет тип, принимающий функцию в качестве продолжения (`immexpr -> aexpr`)". Cues 00:49:03-00:51:53 discuss only arity of a function that arrived as an argument; the immexpr->aexpr link is not made there. Slide content was folded into a paragraph about a different subject.
4. major, `wrong_section`: slide 2 (goal: RISC-V asm, f(x+y), nested functions) placed in S01 (homework chatter, 00:00:04-00:03:20); the content is explained in S03 (00:03:54-00:06:25), "никак вы не можете в ассемблер написать f от x плюс y".
5. major, `wrong_section` (ambiguous): slide 10 ("Заключение про ANF", summary of six distinct bullets) placed in S14 [00:56:43-01:02:02] (ANF vs CPS, inlining). Its bullets are spoken at 00:20:06-00:22:24 (S08, S09) and 00:51:53-00:54:30 (S13); none of them in S14 except the broad ANF theme. S14's paragraph 1 re-types the slide 10 text (incl. LLVM/RISC-V, `temp1`) although those words are not in cues 00:56:43-01:02:02.
6. warning, `invented_expansion`: S14 "Administrative Normal Form" vs slide 4 "A Normal Form" and the lecturer's "A-normal form" (S04 heading).
7. warning, `unresolved_text`: 6 `[неясный фрагмент]` markers and several truncated sentences (e.g. S06 end "...берет и [неясный фрагмент]", S14 para 1 ends "чтобы ").
8. warning, `appendix_false_positive`: slide 20 (references, unmentioned) is shown inline in the last gallery; harmless for navigation but a reference list is presented as discussed content.

## Slide audit

Predicted status in legacy = shown inline in a section gallery (no appendix, no unmentioned). Section numbering S01..S21. Confidence column is n/a for all rows. Rendering: all 20 markers present, once each, image files exist (20 of 20), gallery above the prose as designed.

| Slide | Predicted status | Topic verdict | Anchor verdict | Evidence strength | Regret | Rendering | Confidence | Evidence |
| ---: | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | placed (S01) | correct | best context | composite (title, start of lecture) | none | ok | n/a | S01 starts the note at 00:00:04 |
| 2 | placed (S01) | incorrect | not hit | broad_topic_only/unrelated (S01 = homework) | major | ok | n/a | better S03 [00:03:54-00:06:35] |
| 3 | placed (S03) | reasonable_range | acceptable | composite (ANF intro, before ANF section S04) | small | ok | n/a | S03 closes with "Первым шагом ... ANF"; divider sits ~3 min before the ANF content |
| 4 | placed (S04) | correct | best context | direct | none | ok | n/a | S04 "три типа данных: immexpr, cexpr, aexpr" |
| 5 | placed (S05) | correct | best context | direct | none | ok | n/a | S05 `5 + 4 - 2` |
| 6 | placed (S05) | correct | best context | direct | none | ok | n/a | S05 `let v1 = 5 + 4 in v1 - 2`, `let x = 5 in x` |
| 7 | placed (S05) | correct | best context | direct | none | ok | n/a | S05 "фейковые конструкторы ... immexpr в cexpr, cexpr в aexpr" |
| 8 | placed (S06) | correct | best context | direct | none | ok | n/a | S06 "дырка", `ImmNum`/`ImmId` |
| 9 | placed (S12) | incorrect | not hit | unrelated (arity) | major | ok | n/a | better S06 (00:16:17); S12 repeats slide code (defect 3) |
| 10 | placed (S14) | incorrect (ambiguous) | not hit | broad_topic_only | major | ok | n/a | better S08/S09/S13; see defect 5 |
| 11 | placed (S21) | incorrect | not hit | unrelated | major | ok | n/a | better S13 [00:54:45-00:56:42] |
| 12 | placed (S21) | incorrect | not hit | unrelated | major | ok | n/a | better S14 [00:56:54-00:58:00] |
| 13 | placed (S21) | incorrect | not hit | unrelated | major | ok | n/a | better S14 [00:59:32-01:02:02] |
| 14 | placed (S21) | incorrect | not hit | unrelated | major | ok | n/a | divider; better S16 start [01:05:07] |
| 15 | placed (S21) | incorrect | not hit | unrelated | major | ok | n/a | better S16/S17 [01:06:24-01:07:57] |
| 16 | placed (S21) | incorrect | not hit | unrelated | major | ok | n/a | better S17/S18 [01:08:01-01:13:46] |
| 17 | placed (S21) | reasonable_range | acceptable (recap) | composite (S21 opens with "дописывается множество аргументов") | small | ok | n/a | direct explanation is in S19 [01:13:50-01:15:13] |
| 18 | placed (S21) | correct | best context | direct | none | ok | n/a | S21 "лямбда-лифтинг ... верхнеуровневые let-выражения" |
| 19 | placed (S21) | reasonable_range | best context (partial) | composite, weak (partial-application runtime only) | none | ok | n/a | S21 last paragraph: code pointer, formal arity, calling convention; no libc/linker in any cue |
| 20 | placed (S21), truly unmentioned | reasonable_range (end-of-lecture reference) | acceptable | n/a | none | ok | n/a | appendix-like; inline placement is a false positive |

## Slide metrics

Denominator rule: unknown labels excluded (0 unknown in this audit). Partially_discussed (slide 19) is counted as positive wherever noted; slide 20 (truly unmentioned) is excluded from the placement metrics and reported separately.

| Metric | Value | Count | Unknown/excluded |
| --- | ---: | ---: | ---: |
| Discussed precision (partial = positive) | 95.0% | 19/20 | 0 |
| Discussed precision (strict: 18 discussed over 19 non-partial predictions) | 94.7% | 18/19 | 0 (slide 19 partial excluded) |
| Discussed recall (partial = positive) | 100% | 19/19 | 0 |
| Unmentioned false-negative rate | 0% | 0/19 | 0; degenerate, legacy never predicts "unmentioned" |
| Acceptable topic accuracy | 52.6% | 10/19 | 0 (slide 20 excluded) |
| Preferred topic accuracy | 42.1% | 8/19 | 0 |
| Wrong-topic rate | 47.4% | 9/19 | 0 |
| Best-context hit | 42.1% | 8/19 | 0 |
| Acceptable-context hit | 52.6% | 10/19 | 0 |
| Materially-better-context rate | 47.4% | 9/19 | 0 |
| Anchor regret none / small / major | 8 / 2 / 9 | of 19 | 0 |
| Verified precision | n/a | n/a | legacy has no verified |
| High-confidence error rate | n/a | n/a | legacy has no verified/probable |
| Unresolved precision | n/a | n/a | no unresolved |
| Collapsed-slide rate (strict: 11-16 collapsed on S21 with unrelated content) | 30.0% | 6/20 | 0 |
| Rendering correctness (marker + file, once each) | 100% | 20/20 | 0 |

- Max slides per rendered anchor: 10 (S21 gallery, slides 11-20); per evidence cue: n/a (legacy has no cue evidence). Next largest: 3 (S05, correct), 2 (S01).
- Duplicate markers: 0. Missing marker/image: 0. Appendix false positives (discussed slide put in appendix): 0 (no appendix exists). Inline false positive of an unmentioned slide: 1 (slide 20).
- Assignment-correct but rendering-wrong: 0 by the legacy gallery convention (galleries precede prose by design; for slides 5-7 and 11-20 the image is not adjacent to the explaining sentence).
- Role-aware (acceptable topic / total): title/divider/closing slides 1, 3, 14: 2/3; ordinary content slides 2, 4, 6, 7, 8, 9, 11, 12, 15, 16, 17, 18: 6/12; summary/reference slides 10, 13, 20: 1/3 (slide 20 only); visual examples 5, 19: 2/2; appendix/blank: none. Totals 11/20 including slide 20.
- Sensitivity: if slide 10 is judged reasonable_range, acceptable topic accuracy would be 11/19 (57.9%).

## Strong evidence-backed aspects

- S04-S06 (00:06:35-00:17:37): ANF definition, the three types, the hole/continuation trick and the fresh-name `let` are accurately paraphrased; slides 4, 5, 6, 7, 8 sit in exactly these sections.
- S17 free-variable algorithm and S18 heap vs arguments ("это утюг", 6/8 registers) track cues 01:08:47-01:12:50 faithfully.
- S21 correctly places slide 18 with the lambda-lifting explanation, and the final paragraph on partial application at runtime matches cues 01:21:00-01:21:33.
- The lecture tail up to 01:22:24 is represented, including the closing remark.

## Confidence calibration

Not applicable in legacy: no verified/probable/fallback/unresolved labels. Counts: incorrect high-confidence placements n/a; false-negative unmentioned 0 (none predicted); weak high-confidence matches n/a. The user-visible effect is instead silent mislocation: 9 of 19 discussed slides stand in a wrong section with no signal of uncertainty.

## Uncertainty and limitations

- Checked in full: all 20 slides (native text; images for 5 and 19 only, the rest have complete native text), all 1420 cues, all 21 note sections.
- Ambiguous: slide 10 (multi-range summary, wrong-topic verdict is arguable), slide 3 (divider off by one section), slide 17 (recap context), slide 19 (partial), slide 20 (reference).
- Slides 1, 3, 14 labelled discussed by role; if excluded, denominators shrink by 3 (precision/recall unchanged in direction).
- Faithfulness was checked on every section by reading, but not every sentence was line-aligned to cues; the 70 score carries a range.
- Slide images were not compared pixel-wise to the PDF.

## Verdict

`usable_with_alignment_issues`

The note itself is complete and mostly faithful (contiguous coverage, readable, sensible structure), but slide placement materially misleads: 9 of 19 discussed slides are in a wrong section, six of them collapsed at the end of the document, and one wrong placement came with slide text injected into an unrelated paragraph (S12). Legacy gives no confidence signal, so the reader cannot tell the good placements (slides 1, 4-8, 18) from the bad ones.
