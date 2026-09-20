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

## API — работает уже сейчас (на мок-данных)

| Метод | Путь | Ответ |
|---|---|---|
| POST | `/api/sessions` | 202 `SessionCreated`; multipart: `file`, `format`, `llm_enabled` |
| GET | `/api/sessions/{session_id}` | `SessionSummary` |
| GET | `/api/sessions/{session_id}/steps?cursor=&limit=` | `StepsPage` (`limit` ≤ 200) |
| GET | `/api/sessions/{session_id}/steps/{step_id}` | `StepDetail` (шаг + 3 соседа с каждой стороны) |
| GET | `/api/analyses/{analysis_id}` | `AnalysisState` — опрашивать раз в 2 с |
| GET | `/api/analyses/{analysis_id}/report` | `Report`; 409 `report_not_ready`, пока не собран |
| GET | `/api/analyses/{analysis_id}/artifacts/{name}` | файл, только из allowlist |
| GET | `/api/health` | `{"status":"ok"}` |

Фронт берёт типы из OpenAPI (`/docs`, `/openapi.json`) и не угадывает поля.
Ошибки приходят в `detail` в формате `ApiError` (`code`, `message`, `status`, `status_url`).

Загрузка уже настоящая: файл пишется потоково в `data/uploads/<session_id>.jsonl`,
считается sha256 и размер, лимит 50 МБ, пустой файл → 400. Но **разбора файла ещё нет**:
`jobs/runner.py` проходит стадии `parsing → analyzing → explaining → assembling` и кладёт
мок-шаги и мок-отчёт из `src/mocks/fixture.py`. В `warnings` про это честно написано.

Артефакты (`report.md`, `report.json`, `CLAUDE.generated.md`) уже генерируются из `Report`
в `reports/exporters.py` и лежат в `data/exports/<analysis_id>/`.

## Куда подключать свою часть

Все точки помечены `TODO` в `src/jobs/runner.py`:

- **Бек-1** — стадия `parsing`: вместо `build_mock_steps()` вернуть настоящие `Step` из
  `parsers/claude_code.py` (путь к файлу лежит в `sessions.file_path`), заполнить
  `SessionInfo` и записать его в `sessions.meta` через `crud.sessions.set_session_meta`.
  Сохранение шагов уже есть: `crud.sessions.save_steps(db, steps)`.
- **Бек-2** — стадия `analyzing`: получить шаги из БД/парсера, вернуть `list[Candidate]`.
- **ML** — стадия `explaining`: `context_builder` → `llm.explain(packet)` → `validator`,
  вернуть `list[Judgment]`. При падении LLM — `rule_based`-объяснения и статус `partial`.
- **Сборка** — `reports/builder.py`: `Candidate` + `Judgment` → `Report`, дальше уже
  работает `write_artifacts()` и `crud.analyses.save_report()`.

Статусы и прогресс пишутся только через `crud.analyses.set_stage(...)`. Руками таблицу
не обновляем.

Мок удаляется целиком (`src/mocks/`) в момент, когда сквозная цепочка пойдёт на реальном логе.

## Локальный запуск

Хостовые порты сдвинуты, потому что 5432/6379 часто заняты другим проектом:
Postgres → `5433`, Redis → `6380`.

```bash
cp src/.env.template src/.env     # уже содержит порт 5433
docker compose up -d db
cd src && uv run alembic upgrade head
uv run uvicorn main:app --reload --port 8080
# проверка сквозного сценария:
curl -X POST localhost:8080/api/sessions -F file=@session.jsonl -F format=claude_code
```

Redis и примеры из шаблона (users, redis_example, crud/users) удалены — не нужны.
Порт Postgres на хосте — **5433**, внутри docker-сети по-прежнему 5432.

Новая миграция после правки моделей:

```bash
cd src && uv run alembic revision --autogenerate -m "что изменили" && uv run alembic upgrade head
```
