# Контракты бекенда (v1) — читать всем

Это описание кода, который уже лежит в `src/schemas/`. Контракт заморожен: если нужно
поле, которого нет, пишешь в чат и правим вместе. Молча менять нельзя — от этих моделей
зависят парсер, детекторы, ML и фронт.

Импорт всегда из пакета, не из файла-модуля:

```python
from schemas import Step, Candidate, Judgment, Finding, Report, AnalysisStatus
```

## Кто владеет чем

| Файл | Что описывает | Владелец | Кто читает |
|---|---|---|---|
| `schemas/common.py` | все enum-ы и `SCHEMA_VERSION` | Бек-3 | все |
| `schemas/events.py` | `Step`, `ToolCall`, `UsageRecord`, `SessionInfo` | Бек-1 (парсер) | Бек-2, ML, API |
| `schemas/findings.py` | `Candidate`, `Judgment`, `Finding`, `Recommendation` | Бек-2 + ML | сборщик отчёта, фронт |
| `schemas/reports.py` | `Report` и все ответы API | Бек-3 | фронт, сборщик отчёта |

Поток данных: парсер → `Step` → детекторы → `Candidate` → ML → `Judgment` → builder →
`Finding` + `Recommendation` → `Report` → API → фронт.

## Общие правила (нарушение = баг)

1. `None` ≠ `0` и ≠ `False`. Нет данных — ставим `None` и пишем причину в `limitations`.
2. Все модели с `extra="forbid"`: лишнее поле упадёт на валидации, а не молча пролезет.
3. Числа в отчёт попадают только из `Candidate.facts` / `Metric`. Текст модели не источник чисел.
4. Ссылка на доказательство — всегда полный `step_id`, формат
   `<session_id>:line_<номер строки>:block_<индекс блока>`. Никаких `step-2`.
5. Каждое из направлений анализа возвращает явный результат, в том числе пустой.

## `schemas/common.py`

- `StepKind`: `human_message | assistant_text | tool_call | tool_result | system_event | unknown`.
- `Actor`: `human | assistant | tool | system | unknown`. Запись `type=user` с `tool_result` — это `tool`, не `human`.
- `ToolCallStatus`: `success | error | unknown`. Нет результата → `unknown`.
- `AnalysisStatus`: `queued | parsing | analyzing | explaining | assembling | complete | partial | insufficient_data | failed | interrupted`.
  - `TERMINAL_STATUSES` — на них фронт прекращает опрос.
  - `RUNNING_STATUSES` — их при старте сервиса переводим в `interrupted`.
- `Severity`: `high | medium | low` — ставит только `ranking.py`.
- `LogFormat`: пока только `claude_code`.

## `schemas/events.py` — данные парсера

`Step` — единица истории. Одна строка JSONL может дать несколько шагов (по блокам `content`).

Ключевые поля: `step_id`, `session_id`, `ordinal` (сквозная нумерация с 0, по ней пагинация),
`source: SourceRef` (`source_line`, `block_index`, `source_event_id`, `source_message_id`),
`branch_id` (по умолчанию `"main"`), `timestamp` (может быть `None`), `kind`, `actor`,
`tool_call_id`, `tool_name`, `arguments`, `text`, `text_truncated`, `is_error`, `usage_ref`,
`warnings`.

`is_error` ставим только из `is_error=true` или ненулевого exit code. Слово «error» в тексте —
не основание, остаётся `None`.

`ToolCall` — пара вызов/результат, связанная по `tool_use.id` ↔ `tool_result.tool_use_id`, а не
по соседним строкам. `unfinished=True`, если результата нет.

`UsageRecord` — расход **исходного** агента на один запрос, дедуп по `request_id`. Наш расход на
LLM-анализ здесь не хранится и с ним не складывается. Категории токенов — `None`, если в логе их нет.

`ParseStats` / `SessionInfo` — итоги чтения файла, откуда берётся `coverage` отчёта.

`StepDetail` — ответ на запрос одного шага: шаг + его `ToolCall` + соседи до/после.

## `schemas/findings.py` — анализ

`Candidate` (Бек-2) — «это стоит рассмотреть», ещё не вывод о неэффективности.

```python
Candidate(
    candidate_id="c_001",
    kind="repeated_failed_tool",
    evidence_step_ids=["s_7d9:line_42:block_0", ...],   # минимум 1, полные step_id
    facts={"tool_name": "Bash", "command": "npm test", "attempt_count": 3},
    detector_version="repeats-v1",
    evidence_strength="direct",      # direct | indirect | weak
    limitations=["между попытками не найдено релевантного изменения"],
)
```

Допустимые `kind` (список закрыт, расширяем только договорившись):
`repeated_tool_call`, `repeated_failed_tool`, `failure_chain`, `human_intervention`,
`reverted_edit`, `long_gap`.

`severity` и `rank` детектор **не** заполняет — это делает `ranking.py`.

`Judgment` (ML) — ровно та форма, которую отдаёт модель через Structured Outputs:
`candidate_id`, `assessment` (`inefficient | reasonable | uncertain`), `evidence_step_ids`
(подмножество разрешённых для этого кандидата), `explanation`, `likely_cause`, `action`,
`verification`, `rule_text`, `limitations`. Для `reasonable`/`uncertain` поля `action`,
`verification`, `rule_text` могут быть `None`. Для `inefficient` они обязательны — это проверяет
`validator.py`, а не модель.

`Finding` — то, что видит человек: копия фактов кода + `title`, `severity`, `rank` от бекенда +
объяснение, если оно есть. `explanation_source`: `llm | rule_based | not_explained`.
`not_explained` означает «не объяснено», а не «проблемы нет».

`Recommendation` — всегда с `finding_id`. Без связи с находкой рекомендаций не создаём.

## `schemas/reports.py` — контракт для фронта

`Report` (он же JSON-блоб в БД и `report.json`):

```
schema_version, analysis_id, session_id, status, summary,
coverage, metrics[], findings[], recommendations[], warnings[],
provenance, artifacts[], created_at
```

- `findings` приходят уже отсортированными по `rank` — фронт не сортирует.
- `Metric`: `key, label, value, unit, denominator, coverage, limitations`. Для доли ошибок
  обязательно `denominator` = число вызовов с известным статусом. `value=None` = неизвестно.
- `Coverage`: `total_lines, recognized_steps, invalid_lines, unknown_events,
  candidates_total, candidates_explained, llm_enabled, incomplete_reasons`.
- `Provenance`: `parser_version, detector_version, prompt_version, model`.
- `artifacts` — только имена из `ARTIFACT_ALLOWLIST`: `report.md`, `report.json`,
  `CLAUDE.generated.md`.

Ответы API: `SessionCreated`, `AnalysisState` (+`Progress`), `SessionSummary`, `StepsPage`,
`ApiError`. `Progress.percent` — `None`, если измеримого знаменателя нет; выдумывать проценты нельзя.

## Таблицы БД (3 штуки, Postgres + alembic)

| Таблица | Модель | Смысл |
|---|---|---|
| `sessions` | `models/session.py:SessionModel` | загрузка: файл, sha256, путь, `meta` = `SessionInfo` |
| `steps` | `models/session.py:StepModel` | шаги; поля для поиска колонками, полный `Step` в `payload` |
| `analyses` | `models/analysis.py:AnalysisModel` | задача + `progress` + `report` (JSONB) + `heartbeat_at` |

Индексы: `(session_id, ordinal)`, `(session_id, tool_call_id)`, `analyses.session_id`, `analyses.status`.
`tool_calls`, `usage_records`, `findings`, `reports`, `artifacts` отдельными таблицами в MVP **не** делаем.

## API и общий пайплайн

API работает на загруженных JSONL Claude Code. Маршруты: `POST /api/sessions`,
`GET /api/sessions/{id}`, `GET /api/sessions/{id}/steps`,
`GET /api/sessions/{id}/steps/{step_id}`, `GET /api/analyses/{id}`,
`GET /api/analyses/{id}/report`, `GET /api/analyses/{id}/artifacts/{name}` и `/api/health`.
Точные схемы доступны в `/docs` и `/openapi.json`; пагинация шагов ограничена 200 элементами.

`jobs/runner.py` читает настоящий файл через `analysis.parse_file`, запускает
`analysis.analyze_parsed` и сохраняет шаги. `reports/builder.py` переводит внутренний
отчёт детекторов в HTTP-отчёт и ML-пакет версии 2. ML получает наблюдения типа
`detector_observation`, факты с доказательствами и контекст; затем автоматически
выполняются маскирование, сжатие, лимит размера, вызов модели и проверка цитат.
Сигнал детектора не становится доказанной неэффективностью автоматически.

В `POST /api/sessions` параметр `llm_enabled` по умолчанию **false**. При включённом
ML и отсутствии ключа либо ошибке модели факты сохраняются, отчёт получает
`partial`. Файл неизвестного формата получает `insufficient_data`, а не чистый отчёт.
Несколько исходных сессий в одном файле нужно загрузить отдельно.

HTTP-контракт сохраняет `schema_version=1`; это не версия ML-контракта.
В `Finding` добавлены `citations` и виды кандидатов для всех детекторов.
В `Step` сохраняются `usage` и `result_metadata`, когда они есть в логе.
В `Report` добавлены `directions`, `analysis_usage`, `ml_details` (сжатие и причины
пропусков). Расход на ML-анализ отделён от расхода исходной сессии. Старый
дублирующий `schemas.Judgment` удалён: актуальная схема находится в `agent_review.schemas`.

Моки `src/mocks/` удалены. Артефакты собираются из того же `Report`, что хранится в БД.
Все изменения статуса проходят через `crud.analyses`; незавершённые задачи после
перезапуска отмечаются `interrupted`. Используем один процесс backend и одну очередь
в памяти; PostgreSQL хранит результаты и состояние.

## Запуск и проверка

Из корня репозитория: `docker compose up -d --build --wait`.
Swagger: http://localhost:8080/docs. Проверка: `python3 scripts/check_api.py`.
Инструкция, параметры ML и команды тестов — в [README](../README.md).

PostgreSQL доступен на localhost:5433; Redis и демонстрационные users-модули не нужны.
Для локального Python можно использовать `.env` по образцу `src/.env.template`,
установить зависимости через `uv sync`, затем запускать из `src/`:
`../.venv/bin/alembic upgrade head` и `../.venv/bin/uvicorn main:app --port 8080`.

### Дополнение после объединения Grisha

`parsers.parse_claude_code_log/lines` — типизированный интерфейс поверх общего `analysis.parser`, а не второй разбор для сервера. Сохраняются исходные номера строк/блоков и ID сообщений. Синтетические прерывания отмечаются как системные; внутренний thinking не выводится. `link_tool_calls` связывает только однозначный предшествующий вызов в той же сессии и ветке.

`UsageCollector` получает уже разобранные события в том же проходе. Финальное usage запроса имеет приоритет над промежуточным, повторы не суммируются. `UsageRecord` использует исходные названия `cache_read_input_tokens` и `cache_creation_input_tokens`; отсутствующее значение — `null`. Метрики отчёта показывают ограничения неполных сумм. Расход нашего анализа остаётся отдельно в `analysis_usage`.

Публичные функции `export_report_json`, `export_report_md`, `export_claude_generated_md` принимают готовый `Report` и путь назначения. HTTP продолжает выдавать только три разрешённых артефакта.
