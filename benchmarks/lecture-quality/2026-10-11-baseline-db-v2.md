# Independent lecture quality report

- Lecture: db-2026-09-24 (Databases, lecture 1, ~59 min, Russian), mode v2, baseline of stage 1
- task_id: 7509c2afb0c14026a24d3ec37743d42b
- Code: tag stage1-baseline @1ad9384
- Judge: claude sonnet, effort medium
- Date: 2026-10-11

## Scope and inventory

- Inputs inspected: extracted result `test-data/document-slide-alignment/runs/2026-10-11-baseline-db-v2/result/output/` (конспект.md, transcript.srt, structure.json, slides/slide-01..41.png, document-slide-alignment.json); source deck `test-data/document-slide-alignment/db-2026-09-24/slides.pptx` (native text extracted from the slide XML for all 41 slides; slide images viewed for 18, 25, 32, 38 only).
- Source hashes (sha256):
  - конспект.md `9d168296f6c6425122c5c53ad651993796e8de981e3cdbe263e5a7f634cb460e`
  - transcript.srt `444a014f32ad0c57da68eda5c206707ccaecd642cc15a7a5a8af00cdd6e5c8da`
  - structure.json `0bf30df3f3349669174d9c01b6a6fc4d27b8c85580f699551089b6782cad6f67`
  - document-slide-alignment.json `8af9867c9239c08ef27c9d1b62df3e37c44b068f8afe5e7ade9a44a4d60e3d47`
  - slides.pptx `dae893ec850ec6e6ede84807fbbdca8ca7b900e76d1d86fc3e4801e4dc6a540e`
- Sections / transcript cues / slides: 21 sections (5 top-level groups), 1357 SRT cues (00:00:01 - 00:59:20), 41 slides; 41 slide markers in the note (37 inline/gallery + 4 in "Непривязанные слайды").
- Missing artifacts: audio clips (removed deliberately, not a defect). Nothing else missing.

## Sampling method

- Full transcript read end to end (all 1357 cues, with timestamps). Full note read with slide markers stripped. All 41 slides' native text read; images of 18, 25, 32, 38 inspected. Image-only content of picture slides (12-16, 21, 28, 30, 31, 33) was judged from native title text plus transcript, not from the pixels (limit).
- Every slide was searched globally in the transcript, including paraphrases.
- Note quality was sampled across the whole lecture (all sections read), not a subset.
- Pass-A labels (table below) were completed before document-slide-alignment.json was opened. Note: the note file itself contains slide markers; they were stripped (grep -v) while reading in pass A.
- Section numbering used below: S1 Введение/лектор, S2 Содержание курса, S3 Литература, S4 Понятие ИС, S5 Этапы эволюции (00:14:38-00:17:13), S6 История выч. техники 50-70 (-00:19:04), S7 Эпоха ПК (-00:21:54), S8 Появление СУБД и 3-уровневой арх. (-00:23:36), S9 Понятие БД, S10 СУБД (00:25:03-00:27:43), S11 Файлы -> СУБД, независимость, S12 Трёхуровневая арх. БД, S13 История СУБД, S14 Распределённые БД/облака, S15 Причины/статистика, S16 Архитектура решений/игроки, S17 Функции СУБД (00:52:49-00:54:01), S18 Слои арх., S19 Роли, S20 Проектировщик/аналитик, S21 Завершение.
  (matcher global_section_id N = this S(N+1).)

## Pass-A ground truth

Times are transcript times (hh:mm:ss). "Sec" = note section that covers that time range. Status of partial slides: see slide 7 and 31.

| Slide | Role | Discussion status | Central concepts | Preferred context | Acceptable range | Evidence |
| ---: | --- | --- | --- | --- | --- | --- |
| 1 | title | discussed | course title, lecturer | 00:00-00:19 (S1 start) | S1 | cue 9 "курс у нас называется База данных" |
| 2 | content | discussed | about the lecturer, career, e-mail | 00:49-02:12 (S1) | S1 | cues 19-47 "старшим преподавателем кафедры системного программирования", "Ростелекома", "Газпромнефть" |
| 3 | content | discussed | organisational: oral exam, 1 pair/week, admission, Telegram/personal message | 02:15-02:29 (S1 end) | S1 | cue 49 "В конце устный экзамен, ... 1 пара лекций в неделю" |
| 4 | content | discussed | course topics (terminology, models, SQL, transactions, indexing, design, NoSQL, DBMS overview, cloud) | 02:29-04:13 (S2) | S2 | cues 52-93 |
| 5 | content | discussed | know/able after the course | 04:13-05:37 (S2) | S2 | cues 94-128 |
| 6 | reference_or_table | discussed | DB literature, Date | 05:42-06:29 (S3) | S3 | cues 129-146 "книга Data ... классика по модели" |
| 7 | reference_or_table | partially_discussed | SQL literature list; only generic mention + Postgres emphasis | 06:31-07:17 (S3) | S3 gallery | cues 147-163 |
| 8 | content | discussed | IS = storage + processing + UI | 07:42-09:34 (S4) | S4 | cues 188-207 "хранение, обработка и представление" |
| 9 | content | discussed | Silver 1995 IS definition (hardware, software, data, people, procedures) | 09:38-10:30 (S4) | S4 | cues 209-230 "аппаратное обеспечение, программное обеспечение, данные, людей и процедуры" |
| 10 | content | discussed | ACM definition, IT + business symbiosis | 10:30-11:28 (S4; tangent to 12:20) | S4 | cues 231-274 |
| 11 | content | discussed | IS examples: DWH, ERP, expert, search, EDMS, BI+OLAP, ecosystems | 12:24-14:36 (S4) | S4 | cues 275-323 |
| 12 | section_divider | discussed | "Evolution of computing 1950s-1980s" | beginning of 14:38 (S5 start) | S5 start; S5-S7 span | cues 324-329 "Пройдемся по этапам эволюции вычислительной техники" |
| 13 | visual_example | discussed | first IS (statistics, banking), first computers, mainframes + terminals | 14:42-16:28 (S5) | S5 | cues 329-363 |
| 14 | visual_example | discussed | IBM 305 RAMAC 1956, 5 MB | 16:30-18:05 (S5 end / S6 start) | S5, S6 | cues 364-403 "жесткий диск от IBM ... 1956", "5 мегабайт" |
| 15 | visual_example | discussed | centralisation in 1950-70, IBM 360 | 18:08-19:02 (S6) | S6 | cues 408-421 "склонность к централизации" |
| 16 | content | discussed | PCs, BI boom, many users, decentralisation, DB/DBMS as separate class | 19:04-21:54 (S7) | S7 (and S8 for the last bullet) | cues 423-490 |
| 17 | content | discussed | business logic can be separated from storage logic | 22:52-23:02 (S8) | S8 | cue 512 "с концептуальной точки зрения бизнес-логику можно отделить от логики хранения" |
| 18 | visual_example | discussed | three-tier pyramid UI / business logic / data storage | 23:17-23:33 (S8 end) | S8 | cues 524-527 "трехуровневая архитектура, бизнес-логика и хранилище данных" |
| 19 | content | discussed | DB definition (Wikipedia, conceptual, technical, file) | 23:36-24:55 (S9) | S9 | cues 530-554 |
| 20 | content | discussed | DBMS definition + 3 functions | 25:05-26:20 (S10); repeated at 52:50 (S17) | S10, S17 | cue 560-565 definition; cue 1208-1219 "мы его видели ... в начале презентации" |
| 21 | visual_example | discussed | DB = storage, DBMS = management | 26:22-27:35 (S10) | S10 | cues 587-616 |
| 22 | content | discussed | "first there were DBs, no DBMS", file formats per program | 27:38-28:57 (S11) | S11 | cues 617-643 |
| 23 | content | discussed | physical independence | 28:57-29:42 (S11) | S11 | cues 644-657 |
| 24 | content | discussed | logical independence | 29:42-31:03 (S11) | S11 | cues 658-686 |
| 25 | visual_example | discussed | ANSI_SPARC diagram (external/conceptual/internal) | 31:06-32:20 (S12 start) | S12 | cues 687-715 |
| 26 | content | discussed | three levels in detail (external / logical / physical) | 32:20-34:29 (S12) | S12 whole | cues 716-763 |
| 27 | summary | discussed | DBMS history timeline, System R 1974, SQL, standards, SQL:2023 | 34:33-37:45 (S13) | S13 | cues 764-838 |
| 28 | visual_example | discussed | 2000+: distributed, cloud, NoSQL | 38:13-41:06 (S14) | S14 | cues 846-931 |
| 29 | content | discussed | reasons for DB development | 41:11-44:40 (S15) | S15 | cues 932-1013 |
| 30 | visual_example | discussed | data volume statistics, video content half | 44:40-45:50 (S15) | S15 | cues 1014-1042 |
| 31 | visual_example | partially_discussed | Big Data market size forecast, technologies in demand (only a vague pass over the charts) | 45:50-47:20 (S15) | S15 | cues 1043-1089 |
| 32 | visual_example | discussed | data-processing architecture (batch, stream, analytical store) | 47:35-49:50 (S16) | S16 | cues 1090-1147 |
| 33 | visual_example | discussed | main DBMS vendors, Oracle, MS SQL, market share, SQLite tangent | 50:09-52:26 (S16) | S16 | cues 1153-1207 |
| 34 | content | discussed | "What is a DBMS": 1st build of function list (storage, creation, schema, backup, consistency, queries) | 52:50-53:09 (S17) | S17 | cues 1208-1219 |
| 35 | content | discussed | build 2: + integrity constraints | 53:25-53:35 (S17) | S17 | cues 1224-1228 |
| 36 | content | discussed | build 3: + query processing, concurrent access, scaling | 53:35-53:50 (S17) | S17 | cues 1229-1234 |
| 37 | content | discussed | build 4: + business logic in DBMS | 53:52-54:00 (S17 end) | S17 | cues 1235-1238 |
| 38 | visual_example | discussed | layers penetrating components (UI, business, storage, OOP, stored procedures) | 54:01-55:07 (S18) | S18 | cues 1239-1267 |
| 39 | reference_or_table | discussed | DB IT roles | 55:10-57:30 (S19) | S19 | cues 1268-1323 |
| 40 | content | discussed | DB designer: infological model, ER | 57:32-58:01 (S20) | S20 | cues 1324-1331 |
| 41 | content | discussed | data analyst: validation, processing, reports, data mining | 58:01-58:15 (S20) | S20 | cues 1332-1340 |

Pass-A totals: discussed 39, partially_discussed 2 (slides 7, 31), unmentioned 0, unknown 0.

## Scorecard

| Dimension | Score or unknown | Confidence | Evidence summary |
| --- | ---: | --- | --- |
| Faithfulness | 78-85 | medium | Content tracks the transcript closely across all sections. Defects: "batch-обработка запросов на языках высокого уровня" (S17) - transcript cue 1229 "бета-обработка запросов на языках высокого уровня", slide 36 "Обработка запросов на языках высокого уровня": "batch" is an invented gloss. "В 1980-е годы произошло появление персональных компьютеров" (S7): the transcript cue 423 is garbled ("140000-ые годы"), slide 16 says 1970-2000, so "1980-е" is unsupported. S3 closing sentence "Если на предыдущем слайде рассматривался ответ на один вопрос..." is a reworded slide-reference artefact. |
| Content coverage | 88-92 | medium | All topics from 00:00 to 00:59 represented, including the tail (S20, S21); no temporal gaps. Closing remarks (next lecture tomorrow 19:30, shortened format) only inside a tangent block. |
| Block quality | 65-72 | medium | Several sections are near-verbatim spoken transcript instead of summarised prose (S6, the second half of S5, the S15 reasons paragraph) with "вот", "да", "ну", and the quiz dialogue ("Килобайт 16? 16 килобайт. Да.") kept raw. Unresolved ASR leaks "[неясный фрагмент]" (S5-S10). Contrast: S9-S12, S19-S20 are well summarised. |
| Document structure | 62-70 | medium | Top-level group "Введение в курс" swallows the IS definition and the start of computing history (S4, S5). Boundary at 00:17:13 cuts the RAMAC Q&A mid-dialogue (S5 ends with "Я думаю, что побольше.", S6 starts "Что еще? По-моему, там было 4 мегабайта."). S21 consists only of a tangent. Otherwise headings reflect content and progress coherently. |
| Language consistency | 90-95 | high | Russian prose throughout; English only for terms/slide labels (external, conceptual schema, stream processing, Software as a Service), all legitimate. |
| Slide semantic relevance | 85-90 | medium | 34/37 placed slides sit in an accepted range; 3 wrong-topic placements. Image content for picture slides inferred from title text. |
| Slide anchor precision | 70-78 | medium | 20/37 at the best context, 34/37 acceptable; recurring small regrets (slide placed before its explanation, galleries at section end, inverted order of gallery vs inline slides). |
| Confidence calibration | 72-80 | medium | No incorrect `verified` (0/18). 3 incorrect `probable` (3/19). All 4 `unresolved` slides are discussed ones (precision 0/4). Weakest verified slide scores (6: raw 13.7) are still correct. |

## Critical and major defects

No critical defects. Major defects (all proven against transcript cues):

1. major / false-negative unmentioned: slide 2 ("О лекторе") placed in appendix (`no_supported_evidence`). Native text: "Виктор Александрович Андриенко, ст. преподаватель кафедры системного программирования матмеха СПбГУ ... Руководитель направления «Искусственный интеллект» в «Ростелеком-Корпоративные системы»". Transcript 00:00:49-00:02:12 (cues 19-47): "старшим преподавателем кафедры системного программирования", "руководителем направления искусственного интеллекта в 1 из дочек Ростелекома", "Газпромнефть". Expected: S1, after the paragraph "Лекции ведёт Андриенко...". Reader sees a lecturer slide detached from the lecturer paragraph.
2. major / false-negative unmentioned: slide 4 ("Что будет в курсе") in appendix. Transcript 00:02:29-00:04:13 (cues 52-93): "терминологией баз данных и системой управления базами данных ... транзакции блокировки ... индексирования, оптимизации запросов ... нереляционными базами данных". Expected: S2, para 1-2 (note already paraphrases every bullet).
3. major / false-negative unmentioned: slide 9 (Silver et al. 1995 definition) in appendix. Transcript cues 209-230: "система включает аппаратное обеспечение, программное обеспечение, данные, людей и процедуры", "95-го года". Expected: S4, 2nd paragraph ("Согласно модели взаимодействия информационных технологий (базовый курс 1995 года)...").
4. major / false-negative unmentioned: slide 15 (centralisation, IBM 360, 1964) in appendix. Transcript cues 408-421: "отличительной особенностью тех времен была склонность к централизации ... вычисления все производились на 1 машине". Expected: S6 (note: "склонность к централизации" paragraph).
5. major / incorrect probable placement: slide 14 (IBM 305 RAMAC, "5 мегабайт"): placed as section_gallery (fallback no_safe_semantic_block) at the end of S15 "Причины развития и статистика" after the Big Data paragraph (anchor 00:42:01, evidence cues 952, 959). The only match there is the aside "несчастные 5 мегабайт" (cue 959, a call-back, `broad_topic_only`). The actual discussion is 00:16:30-00:18:05: "появился жесткий диск от IBM ... 1956-ом году", "5 мегабайт" (S5/S6, RAMAC Q&A). Better context exists: S5 end / S6 start.
6. major / incorrect probable placement: slide 16 ("История: 1970-2000", PCs, decentralisation) placed as gallery at the end of S16 after the SQLite tangent (anchor 00:52:50, evidence cue 1208 "Что-то у меня такое ощущение, что где-то этот слайд мы уже видели"). `unrelated`. The explanation is 00:19:04-00:21:54 "появились персональные компьютеры ... Децентрализация ... выделение баз данных и системы управления базами в отдельный класс технологий" (S7).
7. major / incorrect probable placement: slide 34 ("Что такое СУБД?", build 1 with "Создание БД, Описание её схемы, Резервирование данных") placed inline at the start of S10 (anchor 00:27:41, evidence cue 617 "Сначала были БД, но не было СУБД"). `broad_topic_only`: S10 never lists create/schema/backup. The matching explanation is 00:52:50-00:53:09 ("Это и создание БД, и описание ее схемы, и резервирование данных") in S17. Notably slides 20 and 34 look swapped: slide 20 (the definition + 3 functions) is in S17, slide 34 in S10.
8. warning / faithfulness: "batch-обработка запросов" (S17) and "В 1980-е годы" (S7), see scorecard.
9. warning / structure: S5/S6 boundary mid-dialogue; evolution history under "Введение в курс".
10. info / calibration: slide 10 is `verified` but rendered as a `fallback` gallery (`no_safe_semantic_block`); assignment and rendering state disagree.

## Slide audit

Predicted status/confidence and placement from document-slide-alignment.json (opened only after pass A). "disc"=discussed, "unm"=unmentioned. Topic/anchor: C=correct, RR=reasonable_range, I=incorrect. Evidence strength per rubric. Rendering: where the marker actually appears in конспект.md versus the placement record.

| Slide | Predicted status | Topic verdict | Anchor verdict | Evidence strength | Regret | Rendering | Confidence | Evidence |
| ---: | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | disc, S1 | C | C | direct | none | inline, after para 1 (as recorded) | probable | cue 9 course title; title slide at start |
| 2 | unm (appendix) | I (false negative) | - | - | major | appendix | unresolved | see defect 1 |
| 3 | disc, S1 | C | C | direct | small | inline, after para 1; org text is in tangent after "Лекции ведёт" paragraph, so marker sits ahead of its explanation | verified | cue 49 exam / 1 pair per week (anchor 140 s) |
| 4 | unm (appendix) | I (false negative) | - | - | major | appendix | unresolved | defect 2 |
| 5 | disc, S2 | C | C | direct | small | inline, after para 1 (course program), before the know/able paragraph | verified | cues 99-102 "Нужно знать принцип проектирования баз данных" |
| 6 | disc, S3 | C | C | direct | small | inline, after last para of S3 | verified | cue 133 "книга Data ... классика" (raw 13.7, lowest verified; still direct) |
| 7 | disc, S3 | C | C | composite | none | gallery at section end | probable | reference slide; partially discussed |
| 8 | disc, S4 | C | C | direct | none | inline, after para 1 | verified | cues 188-207 |
| 9 | unm (appendix) | I (false negative) | - | - | major | appendix | unresolved | defect 3 |
| 10 | disc, S4 | C | RR | direct | small | gallery fallback (no_safe_semantic_block) at section end, placed after slide 11 although ACM para precedes examples | verified | cues 231-238 ACM definition |
| 11 | disc, S4 | C | C | direct | none | inline, after last para | verified | cues 276-318 |
| 12 | disc, S5 | C | RR | composite | small | gallery at S5 end (divider should be at section start) | probable | cue 324-329 |
| 13 | disc, S5 | C | C | direct | none | inline, after para 2 (mainframes + terminals) | probable | cue 338 "статистические обработки ... банковских операций" |
| 14 | disc, S15 | I | I | broad_topic_only | major | gallery at end of S15 | probable | defect 5 |
| 15 | unm (appendix) | I (false negative) | - | - | major | appendix | unresolved | defect 4 |
| 16 | disc, S16 | I | I | unrelated | major | gallery at end of S16 | probable | defect 6 |
| 17 | disc, S8 | C | C | direct | none | inline, after para 2 | verified | cues 512-513 |
| 18 | disc, S8 | C | C | direct | none | gallery after slide 17 | probable | cues 525-527 "трехуровневая архитектура, бизнес-логика и хранилище" |
| 19 | disc, S9 | C | C | direct | none | inline, after para 1 | probable | cue 551 Wikipedia definition |
| 20 | disc, S17 | C | RR | composite | small | inline at S17 start | probable | cues 1208-1228 "слайд мы уже видели в начале презентации"; preferred anchor S10 (cue 560-565 definition) |
| 21 | disc, S10 | C | C | direct | none | inline, after last para | verified | cues 614-616 "БД это хранение ... СУБД это управление" |
| 22 | disc, S11 | C | C | direct | none | inline, after para 1 | probable | cues 617-628 |
| 23 | disc, S11 | C | C | direct | none | inline, after para 2 | verified | cues 646-650 |
| 24 | disc, S11 | C | C | direct | none | inline, after para 4 | verified | cues 658-675 |
| 25 | disc, S12 | C | RR | direct | small | gallery at S12 end, after slide 26 (reverse of narrative order) | probable | cue 688-715 diagram explanation is the first paragraph |
| 26 | disc, S12 | C | RR | composite | small | inline, after last para (physical level) | probable | cue 717 "внешний пользовательский уровень"; slide covers three paras |
| 27 | disc, S13 | C | C | direct | small | inline, after para with added periods; the SQL-standards bullet follows | verified | cues 795-831 |
| 28 | disc, S14 | C | RR | composite | small | gallery at S14 end | probable | cues 850-881 |
| 29 | disc, S15 | C | C | direct | none | inline, after the last reason | probable | cue 937 |
| 30 | disc, S15 | C | C | direct | none | inline, after statistics para | verified | cue 1014 "Статистика по использованию данных" |
| 31 | disc (partial), S15 | C | C | direct | none | inline, after Big Data para | verified | cues 1046, 1068 "размер международного рынка больших данных" |
| 32 | disc, S16 | C | C | direct | small | inline, after para 2 (para 1 is the architecture explanation) | verified | cues 1127, 1143 |
| 33 | disc, S16 | C | C | direct | none | inline, after vendors para | probable | cue 1153 "Основные игроки на рынке" |
| 34 | disc, S10 | I | I | broad_topic_only | major | inline at S10 start | probable | defect 7 |
| 35 | disc, S17 | C | RR | composite | small | inline at S17 block 0 (before "ограничения целостности" paragraph) | probable | cues 1211-1212; build slide |
| 36 | disc, S17 | C | RR | composite | small | inline at S17 block 0 (query processing/concurrency/scaling are in the later paragraph) | verified | cues 1212, 1216, 1223 |
| 37 | disc, S17 | C | C | direct | none | inline, after the last paragraph | probable | cues 1208, 1212 (note: evidence cue 1208 is shared with slides 16, 20) |
| 38 | disc, S18 | C | C | direct | none | inline, after para 1 | verified | cue 1239 |
| 39 | disc, S19 | C | RR | direct | small | gallery at S19 end | probable | cue 1305 roles |
| 40 | disc, S20 | C | C | direct | none | inline, after para 1 | verified | cues 1324-1330 |
| 41 | disc, S20 | C | C | direct | none | inline, after para 2 | verified | cues 1332-1334 |

Overall placement verdict per slide (correct / reasonable_range / incorrect), 37 placed slides: correct 25 (1, 3, 5, 6, 7, 8, 11, 13, 17, 18, 19, 21, 22, 23, 24, 27, 29, 30, 31, 32, 33, 37, 38, 40, 41), reasonable_range 9 (10, 12, 20, 25, 26, 28, 35, 36, 39), incorrect 3 (14, 16, 34). Plus 4 appendix slides, all false negatives (2, 4, 9, 15). Unknown 0.

## Slide metrics

Pass-A positives: 41 (39 discussed + 2 partially_discussed; both treated as positive). Strict variant (partial excluded from positives): 39. Predicted discussed: 37, all truly (at least partially) discussed. Unknown/excluded: 0 everywhere.

| Metric | Value | Count | Unknown/excluded |
| --- | ---: | ---: | ---: |
| Discussed precision (partial = positive) | 100.0% | 37/37 | 0 |
| Discussed precision (strict: partial = not discussed) | 94.6% | 35/37 | 0 |
| Discussed recall (partial = positive) | 90.2% | 37/41 | 0 |
| Discussed recall (strict) | 89.7% | 35/39 | 0 |
| Unmentioned false-negative rate (partial = positive) | 9.8% | 4/41 | 0 |
| Unmentioned false-negative rate (strict) | 10.3% | 4/39 | 0 |
| Acceptable topic accuracy (placed slides) | 91.9% | 34/37 | 0 |
| Preferred topic accuracy | 89.2% | 33/37 (all correct 25 + RR slides 10, 12, 25, 26, 28, 35, 36, 39; slide 20 acceptable but not preferred) | 0 |
| Wrong-topic rate | 8.1% | 3/37 (14, 16, 34) | 0 |
| Best-context hit (regret none) | 54.1% | 20/37 | 0 |
| Acceptable-context hit (regret none or small) | 91.9% | 34/37 | 0 |
| Materially-better-context rate (regret major) | 8.1% | 3/37 | 0 |
| Verified precision (strict: correct only) | 88.9% | 16/18 | 0 |
| Verified precision (correct + reasonable_range) | 100.0% | 18/18 | 0 |
| High-confidence error rate (incorrect verified or probable / all verified or probable) | 8.1% | 3/37 (0 verified of 18, 3 probable of 19) | 0 |
| Unresolved precision | 0.0% | 0/4 | 0 |
| Collapsed-slide rate | 4.9% | 2/41 (16 onto cue 1208 and 34 onto cue 617 are semantically unrelated to the other slides sharing that cue) | 0 |
| Rendering correctness (marker present once, in the recorded section) | 100% | 41/41 | 0 |

Additional:

- Maximum slides per evidence cue: 3 (cue 1208: slides 16, 20, 37; cue 1212: slides 35, 36, 37). Per rendered anchor: 3 (S17 block 0: slides 20, 35, 36; defensible as progressive builds of one slide).
- Duplicate markers: 0. Missing markers/images: 0 (41 markers, 41 PNG).
- Appendix false positives (a discussed slide sent to the appendix): 4 (slides 2, 4, 9, 15); appendix correct omissions: 0 (no real appendix slides in the deck).
- Assignment-correct but rendering-imperfect: 4 (slide 10 verified but rendered as fallback gallery; slides 10/11 and 25/26 appear in reversed narrative order because galleries are appended after inline slides; slide 3 placed before the paragraph carrying its content). None of these misleads on topic.
- Role-aware semantic accuracy (acceptable topic, appendix false negatives counted as failures):
  - title/divider/closing: 2/2 (slides 1, 12; 12 is reasonable_range, gallery at section end);
  - ordinary content: 18/23 (failures: 2, 4, 9 appendix; 16, 34 wrong topic);
  - summary/reference/table: 4/4 (6, 7, 27, 39);
  - visual examples: 10/12 (failures: 14 wrong topic, 15 appendix);
  - appendix/blank: no real appendix slides in the deck; 0 correct omissions, 4 false omissions;
  - total 34/41 = 82.9%.
  - Rendering accuracy is not role-dependent here: 41/41 markers present once; gallery-vs-inline order inversions only affect galleries (7, 10, 12, 18, 25, 28, 39, 14, 16).

## Strong evidence-backed aspects

- Verified placements are precise on narrated, distinctive slides: slide 8 (IS = хранение, обработка, представление: cues 188-207 right under para 1 of S4), slides 23/24 (physical and logical independence, each directly beside its own paragraph), slides 30/31 (statistics charts beside the paragraphs that read them), slide 38 (stored-procedures layer example), slides 40/41 (designer/analyst).
- Slide 18 (pyramid) correctly tied to "трехуровневая архитектура, бизнес-логика и хранилище" at the end of S8, and slide 25 correctly not confused with it (the lecturer explicitly says "это не трехслойная архитектура ... это уровни представления данных").
- Appendix section is not used as a dumping ground (4 of 41).
- Language: faithful Russian; tangents (SQLite story, SQL:2023 check, course-inheritance remark, "ERP/OLAP" aside) correctly isolated into tangent callouts; the lecture tail is present.

## Confidence calibration

- Incorrect `verified`: 0 of 18.
- Incorrect `probable`: 3 (slides 14, 16, 34), all gallery/inline placements driven by `broad_topic_only` or a call-back cue; slides 14 and 16 are `section_gallery` fallbacks with `no_safe_semantic_block` that still carry `probable`.
- Weak high-confidence matches that happen to be right: slide 6 (verified, raw 13.7, correct), slide 3 (verified, anchor ahead of the explanation), slides 10 and 36 (verified but reasonable_range).
- False-negative `unresolved`/unmentioned: 4 (slides 2, 4, 9, 15); `unresolved` precision 0/4. These are slides with no lexical overlap in the matcher but with clear paraphrased or spoken-explanation matches (slide 15 "централизация" appears in the transcript as a standalone key word).
- Appropriate fallbacks: slides 7, 12, 25, 28, 39 (gallery at an acceptable section).
- Slides 20 and 34 are effectively swapped: the near-duplicate "What is DBMS" slides were assigned in the opposite order of their discussion.

## Uncertainty and limitations

- Checked and correct scope: all 25 `correct` slides were verified against transcript cues; all 4 false negatives and 3 incorrect placements were verified against transcript text with cue numbers.
- Unchecked: picture content of slides 12-16, 21, 28, 30, 31, 33 was inferred from native title/text and the transcript, not from the images; slide 31's partial status is a judgment call (the lecturer only names the two charts). Slides 7, 20, 34-37 are ambiguous (reference slide, near-duplicate build slides); they are labelled `reasonable_range` or `incorrect` with the reasoning above, and a stricter judge might treat 20 as incorrect.
- Note-text faithfulness was read end to end, but a line-by-line diff against the transcript was not done; numeric faithfulness scores are ranges.
- Scores use my sampling; no overall arithmetic score computed.

## Verdict

`usable_with_alignment_issues`

Rationale: the note covers the whole lecture and is faithful, in good Russian, but 7 of 41 slides are mishandled: four discussed slides (2, 4, 9, 15) were dropped to the appendix as unmentioned (false-negative rate 4/41 = 9.8%), and three slides (14, 16, 34) sit in unrelated or merely topical sections with `probable` confidence (slide 14 RAMAC is in the Big-Data statistics section, slide 16 PCs after the SQLite tangent). There are no incorrect `verified` placements (0/18), which prevents a `poor` verdict, but the structure and block-quality defects (raw dialogue, mid-dialogue section cut, history under the introduction group) and the false negatives mislead navigation.
