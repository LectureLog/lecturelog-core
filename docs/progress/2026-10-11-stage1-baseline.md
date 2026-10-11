# Этап 1 матчера слайдов: базовая линия «до» на validation (11.10.2026)

Точка отсчёта для всех изменений этапа 1 (`.scratch/slide-matcher-fixes`, тикет 04).
Замер «после» (тикет 10) делается на той же конфигурации стенда и сравнивается с этой
таблицей.

## Что прогнано

Код — тег `stage1-baseline` (`1ad9384`): тикеты 01 (кеш транскриптов) и 02 (нарезка
подтем по границе реплики), без 05–09. Прогоны шли из отдельного worktree на этом теге,
строго последовательно, на изолированном стенде `lecturelog-matcher-v2` (порт 18082).

Validation-лекции — по роадмапу `benchmarks/lecture-quality/generalization-roadmap.md`:
`db-2026-09-24` (базы данных, аудио из видео + PPTX, 41 слайд, ~59 мин) и
`compilers-anf` (компиляторы, аудио + PDF, 20 слайдов, ~82 мин).

| Лекция | Режим | Задача | Отчёт |
| --- | --- | --- | --- |
| db-2026-09-24 | v2 | `7509c2afb0c14026a24d3ec37743d42b` | `benchmarks/lecture-quality/2026-10-11-baseline-db-v2.md` |
| db-2026-09-24 | legacy | `fb7ceeefca2a482eb94dfbba64c29a3e` | нет — задача упала, см. ниже |
| compilers-anf | v2 | `fbd3a7f99c1d4827aae1a8899685ecb9` | `benchmarks/lecture-quality/2026-10-11-baseline-anf-v2.md` |
| compilers-anf | legacy | `e5c813e0d0384b4a8d91586fbb237958` | `benchmarks/lecture-quality/2026-10-11-baseline-anf-legacy.md` |

Результаты лежат в `test-data/document-slide-alignment/runs/2026-10-11-baseline-*`
(в git не входят, аудио-нарезки удалены ради места на диске).

Конфигурация стенда: override вне git, `/root/.cache/lecturelog-orch/stage1/stand.override.yml`.
Режим задаётся `DOCUMENT_SLIDE_ALIGNMENT_MODE`, остальное общее для обоих режимов:
транскрипция `deepgram nova-3, ru`; `LLM_MAX_TOKENS=65536`;
`LLM_EFFORT_SPLIT/SUBSPLIT/RENDER=medium`, `LLM_EFFORT_SLIDE_MATCH=low`;
`LLM_MODELS_SLIDE_MATCH=google/gemini-3.6-flash,google/gemini-3.5-flash-lite` (без gemma,
см. опровергнутую гипотезу в `2026-07-27-matcher-model-experiments.md`); модели
split/subsplit/render — из `.env` стенда; вебхуки и публичный S3 выключены;
`MAX_CONCURRENT_TASKS=1`. Кеш транскриптов — в отдельном томе: Deepgram оплачен по разу
на лекцию, второй режим брал транскрипт из кеша (`audio_seconds: 0`).

Судьи — независимые сабагенты Claude (sonnet, effort medium, скилл
`skills/lecture-quality-judge/`), по одному на прогон, без доступа к прошлым отчётам.

## Сводная таблица «до»

| Метрика | db v2 | anf v2 | anf legacy |
| --- | ---: | ---: | ---: |
| Discussed precision | 100% (37/37) | 100% (13/13) | 95.0% (19/20) |
| Discussed recall | 90.2% (37/41) | 68.4% (13/19) | 100% (19/19)¹ |
| Ложные `unmentioned` | 9.8% (4/41) | 31.6% (6/19) | 0%¹ |
| Acceptable topic accuracy | 91.9% (34/37) | 84.6% (11/13) | 52.6% (10/19) |
| Preferred topic accuracy | 89.2% (33/37) | 53.8% (7/13) | 42.1% (8/19) |
| Wrong-topic rate | 8.1% (3/37) | 15.4% (2/13) | 47.4% (9/19) |
| Best-context hit | 54.1% (20/37) | 23.1% (3/13) | 42.1% (8/19) |
| Acceptable-context hit | 91.9% (34/37) | 76.9% (10/13) | — |
| Verified precision | 100% (18/18)² | 50% (1/2) | n/a |
| High-confidence error rate | 8.1% (3/37) | 23.1% (3/13) | n/a |
| Collapsed-slide rate | 4.9% (2/41) | 10% (2/20) | 30% (6/20) |
| Rendering correctness | 100% (41/41) | 100% (13/13) | 100% (20/20) |
| Вердикт | `usable_with_alignment_issues` | `usable_with_alignment_issues` | `usable_with_alignment_issues` |

¹ Вырожденно: legacy никогда не объявляет слайд необсуждённым, все слайды попадают в
какой-то раздел. ² 16/18 строго; два `reasonable_range` засчитаны как верные.

Знаменатели разные, unknown нет ни в одном прогоне. Каждый прогон оценивал свой судья,
поэтому различия меньше ~5 п.п. не интерпретируются.

## Что видно уже на базовой линии

1. **Legacy падает на тяжёлой колоде.** На `db-2026-09-24` грубый матч legacy (шаг 3a)
   отправляет все 41 PNG одним запросом: 23 080 080 байт при лимите Google AI Studio
   20 000 000. Ошибка 413 детерминирована, повтор её не снимет. Поэтому пары v2/legacy
   на этой лекции нет. Это вероятный баг прода: там режим по умолчанию — legacy.
2. **На `compilers-anf` legacy уступает v2 по размещению с большим запасом**: wrong-topic
   47.4% против 15.4%, collapsed 30% против 10%. Legacy свалил слайды 11–20 в галерею
   последнего раздела.
3. **Главная слабость v2 — ложные `unmentioned`.** 4 из 41 на db и 6 из 19 на anf ушли в
   приложение с `no_supported_evidence`, хотя судья нашёл их обсуждение в транскрипте.
   Это тот же класс, что на старых лекциях.
4. **Отрицательный margin снова не понижает уверенность.** db: все три неверных
   `probable` (слайды 14, 16, 34) имеют margin < 0. Это предмет тикета 06.
5. **Неверный `verified` впервые с начала замеров.** anf, слайд 15 (вложенные функции и
   продолжения): якорь стоит на 1:18:39 в разделе лямбда-лифтинга, а обсуждался слайд
   около 1:05–1:08. До этого `verified` был безупречен (26/26 на трёх старых лекциях).
