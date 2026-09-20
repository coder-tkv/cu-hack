pi
# Бриф на фронтенд: «Что наделал агент»

Это задание для LLM, которая пишет фронтенд. Читай целиком до начала кода.

Заказчик во фронтенде не разбирается, поэтому:

- не оставляй `TODO` и «допишите сами» — код должен запускаться и работать;
- любую команду, которую нужно выполнить, пиши полностью;
- не предлагай выбор между вариантами, выбирай сам и объясняй одной строкой почему;
- если чего-то не хватает в этом брифе — бери самое простое решение и явно пиши в конце ответа,
  что ты выбрал и где это в коде.

## 1. Что это за продукт

Пользователь загружает лог сессии кодинг-агента (`.jsonl` от Claude Code). Бекенд разбирает
его, ищет признаки неэффективной работы (повторы одной и той же падающей команды, цепочки
ошибок, откаты правок, простои), объясняет находки моделью и выдаёт отчёт с рекомендациями и
скачиваемым файлом правил для проекта.

Фронтенд — это тонкий клиент к готовому API. Он **не** парсит лог, **не** считает метрики,
**не** вызывает LLM, **не** знает никаких ключей. Всё это уже сделано на бекенде.

## 2. Стек и как поднять

- React 18 + TypeScript + Vite
- React Router для трёх экранов
- Обычный `fetch`, без axios/react-query — запросов мало, зависимости не нужны
- CSS-модули или один глобальный CSS. Tailwind можно, если так быстрее повторить дизайн
- Никакого Redux/MobX: состояние локальное, плюс данные в URL

Проект создаётся в папке `frontend/` рядом с `src/` (там бекенд):

```bash
npm create vite@latest frontend -- --template react-ts
cd frontend && npm install && npm install react-router-dom
npm run dev
```

Бекенд слушает `http://localhost:8080`, CORS открыт (`allow_origins=["*"]`), так что можно
обращаться напрямую. Базовый URL вынеси в `src/api/config.ts`:

```ts
export const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8080";
```

Создай `frontend/.env.development` с `VITE_API_BASE=http://localhost:8080` и `.env.example` рядом.

Структура файлов (придерживайся её):

```
frontend/src/
├── main.tsx              # роутер
├── api/
│   ├── config.ts         # API_BASE
│   ├── types.ts          # ВСЕ типы из раздела 4, скопировать дословно
│   └── client.ts         # функции запросов из раздела 5
├── pages/
│   ├── UploadPage.tsx    # экран 1
│   ├── AnalysisPage.tsx  # экран 2
│   └── ReportPage.tsx    # экран 3
├── components/
│   ├── MetricsSummary.tsx
│   ├── FindingCard.tsx
│   ├── EvidenceViewer.tsx
│   ├── StatusBadge.tsx
│   └── StepsList.tsx
└── hooks/
    └── useAnalysisStatus.ts
```

Маршруты:

| Путь | Экран |
|---|---|
| `/` | `UploadPage` |
| `/analyses/:analysisId` | `AnalysisPage` (статус обработки) |
| `/analyses/:analysisId/report` | `ReportPage` |

`session_id` не держи в URL: он есть внутри отчёта и в ответе статуса.

## 3. Дизайн

К заданию приложен PDF с макетами постранично. **Повторить один в один**: сетка, отступы,
размеры и веса шрифтов, цвета, радиусы, состояния кнопок, иконки, порядок блоков на странице.

Правила работы с макетом:

1. Сначала выпиши из PDF токены (цвета, шрифты, отступы, радиусы, тени) в `src/styles/tokens.css`
   как CSS-переменные и используй только их, без «магических» значений по месту.
2. Каждая страница PDF = один экран из таблицы маршрутов. Если в PDF есть состояния (пустое,
   загрузка, ошибка) — реализуй все.
3. Тексты на кнопках и заголовках бери из макета. Если в макете текста нет, бери формулировки
   из этого брифа (они на русском и согласованы с бекендом).
4. Если в макете нарисованы данные, которых API не отдаёт, **не выдумывай поле**: покажи
   ближайшее по смыслу из раздела 4 и напиши об этом в конце ответа.
5. Шрифты подключай из `@fontsource/*` или Google Fonts, если в макете указан конкретный.

Дизайн приоритетнее моих словесных описаний вёрстки ниже: я описываю, *какие данные* должны быть
на экране, а *как они выглядят* — решает PDF.

## 4. Контракт API: типы

Скопируй в `src/api/types.ts` дословно. Поля именно такие, `snake_case`, переименовывать нельзя.
`null` означает «неизвестно» и **не равно нулю** — это важно для отображения.

```ts
// --- Статусы -------------------------------------------------------------
export type AnalysisStatus =
  | "queued"        // в очереди
  | "parsing"       // чтение файла
  | "analyzing"     // метрики и поиск кандидатов
  | "explaining"    // объяснение моделью
  | "assembling"    // сборка отчёта
  | "complete"      // готово полностью
  | "partial"       // готово частично (например, LLM отвалилась)
  | "insufficient_data" // записей мало для содержательного разбора
  | "failed"        // обработать не удалось
  | "interrupted";  // процесс прервался (рестарт сервера)

// Терминальные: на них прекращаем опрос статуса.
export const TERMINAL_STATUSES: AnalysisStatus[] = [
  "complete", "partial", "insufficient_data", "failed", "interrupted",
];

export type Severity = "high" | "medium" | "low";
export type Assessment = "inefficient" | "reasonable" | "uncertain";
export type ExplanationSource = "llm" | "rule_based" | "not_explained";
export type EvidenceStrength = "direct" | "indirect" | "weak";
export type StepKind =
  | "human_message" | "assistant_text" | "tool_call"
  | "tool_result" | "system_event" | "unknown";
export type Actor = "human" | "assistant" | "tool" | "system" | "unknown";

// --- POST /api/sessions --------------------------------------------------
export interface SessionCreated {
  session_id: string;
  analysis_id: string;
  status_url: string; // например "/api/analyses/a_123"
}

// --- GET /api/analyses/{id} ---------------------------------------------
export interface Progress {
  stage: AnalysisStatus;
  stage_label: string;      // готовая подпись по-русски, показывай её как есть
  percent: number | null;   // null = знаменатель неизвестен, полосу не рисуем
  done: number | null;
  total: number | null;
}

export interface AnalysisState {
  analysis_id: string;
  session_id: string;
  status: AnalysisStatus;
  progress: Progress;
  report_available: boolean; // true -> можно идти на /report
  warnings: string[];
  error: string | null;      // заполнено только при failed
  created_at: string | null; // ISO 8601
  updated_at: string | null;
}

// --- GET /api/analyses/{id}/report --------------------------------------
export interface Metric {
  key: string;
  label: string;                 // подпись для UI, уже по-русски
  value: number | null;          // null -> показать «неизвестно», НЕ 0
  unit: string | null;           // "count" | "ratio" | "tokens" | "seconds"
  denominator: number | null;    // знаменатель доли
  coverage: string | null;       // на каких данных посчитано
  limitations: string[];
}

export interface Coverage {
  total_lines: number;
  recognized_steps: number;
  invalid_lines: number;
  unknown_events: number;
  candidates_total: number;
  candidates_explained: number;
  llm_enabled: boolean;
  incomplete_reasons: string[];
}

export interface Provenance {
  parser_version: string | null;
  detector_version: string | null;
  prompt_version: string | null;
  model: string | null; // null = модель не вызывалась
}

export interface Finding {
  finding_id: string;
  candidate_id: string;
  kind: string;            // "repeated_failed_tool" | "failure_chain" | ...
  title: string;           // готовый заголовок карточки
  severity: Severity;
  rank: number;            // 0 = самое важное
  facts: Record<string, unknown>; // числа, посчитанные кодом
  evidence_step_ids: string[];    // ссылки на шаги-доказательства
  evidence_strength: EvidenceStrength;
  assessment: Assessment | null;  // null = объяснения нет
  explanation: string | null;
  likely_cause: string | null;    // всегда предположение, подавай как гипотезу
  explanation_source: ExplanationSource;
  limitations: string[];
  detector_version: string | null;
}

export interface Recommendation {
  recommendation_id: string;
  finding_id: string;          // связь с находкой
  action: string;
  rationale: string;
  verification: string | null;
  rule_text: string | null;
  source: ExplanationSource;
}

export interface Report {
  schema_version: string;
  analysis_id: string;
  session_id: string;
  status: AnalysisStatus;
  summary: string;
  coverage: Coverage;
  metrics: Metric[];
  findings: Finding[];          // УЖЕ отсортированы по rank, не сортируй заново
  recommendations: Recommendation[];
  warnings: string[];
  provenance: Provenance;
  artifacts: string[];          // "report.md" | "report.json" | "CLAUDE.generated.md"
  created_at: string | null;
}

// --- Шаги ---------------------------------------------------------------
export interface SourceRef {
  source_line: number;      // номер строки в исходном файле
  block_index: number;
  source_event_id: string | null;
  source_message_id: string | null;
}

export interface Step {
  step_id: string;          // "s_7d9:line_42:block_0"
  session_id: string;
  ordinal: number;          // сквозная нумерация с 0
  source: SourceRef;
  parent_event_id: string | null;
  branch_id: string;
  timestamp: string | null;
  kind: StepKind;
  actor: Actor;
  tool_call_id: string | null;
  tool_name: string | null;
  arguments: Record<string, unknown> | null;
  text: string | null;
  text_truncated: boolean;
  is_error: boolean | null; // null = статус неизвестен, НЕ «успех»
  usage_ref: string | null;
  warnings: string[];
}

export interface StepDetail {
  step: Step;
  tool_call: unknown | null;
  neighbors_before: Step[];
  neighbors_after: Step[];
}

export interface StepsPage {
  items: Step[];
  next_cursor: string | null; // null = страниц больше нет
  total: number | null;
}

// --- Ошибки -------------------------------------------------------------
// Приходит в теле как { "detail": ApiError }
export interface ApiError {
  code: string;      // "file_too_large" | "empty_file" | "report_not_ready" | "not_found" | ...
  message: string;   // готовый текст по-русски, показывай его пользователю
  status: AnalysisStatus | null;
  status_url: string | null;
}
```

## 5. Контракт API: запросы

Реализуй `src/api/client.ts` ровно этими функциями.

| Функция | Запрос | Ответ |
|---|---|---|
| `createSession(file, llmEnabled)` | `POST /api/sessions`, multipart | `SessionCreated`, код 202 |
| `getAnalysisState(analysisId)` | `GET /api/analyses/{id}` | `AnalysisState` |
| `getReport(analysisId)` | `GET /api/analyses/{id}/report` | `Report`, либо 409 |
| `getSteps(sessionId, cursor, limit)` | `GET /api/sessions/{id}/steps?cursor=&limit=` | `StepsPage` |
| `getStep(sessionId, stepId)` | `GET /api/sessions/{id}/steps/{step_id}` | `StepDetail` |
| `artifactUrl(analysisId, name)` | строит URL для скачивания | строка |

Загрузка файла (поля формы именно такие):

```ts
export async function createSession(file: File, llmEnabled: boolean): Promise<SessionCreated> {
  const form = new FormData();
  form.append("file", file);
  form.append("format", "claude_code");
  form.append("llm_enabled", String(llmEnabled));
  const res = await fetch(`${API_BASE}/api/sessions`, { method: "POST", body: form });
  if (!res.ok) throw await toApiError(res);
  return res.json();
}
```

Не ставь `Content-Type` руками для FormData — браузер сам добавит boundary.

Разбор ошибок: бекенд кладёт объект в `detail`. Сделай хелпер, который достаёт
`body.detail.message`, а если формат неожиданный — отдаёт текст вида
`Ошибка ${res.status}`. Никогда не показывай пользователю сырой JSON.

**`step_id` содержит двоеточия** (`s_7d9:line_42:block_0`) и обязательно кодируется:

```ts
const url = `${API_BASE}/api/sessions/${sessionId}/steps/${encodeURIComponent(stepId)}`;
```

Скачивание артефактов — просто ссылка, без fetch и без blob:

```tsx
<a href={`${API_BASE}/api/analyses/${analysisId}/artifacts/report.md`} download>
  Скачать report.md
</a>
```

Имена артефактов бери **только** из `report.artifacts`. Если массив пуст — кнопок нет.

## 6. Экран 1: загрузка (`/`)

Содержимое:

- выбор файла `.jsonl` (`<input type="file" accept=".jsonl">`) + drag-and-drop, если он есть в макете;
- имя и размер выбранного файла после выбора;
- чекбокс «Объяснять находки моделью» → уходит в `llm_enabled`, по умолчанию включён.
  Подпись рядом: без него анализ будет только на правилах, зато ничего не уйдёт в облако;
- предупреждение, что фрагменты лога будут отправлены облачному провайдеру модели
  (если чекбокс включён), и где обычно лежит лог: `~/.claude/projects/<проект>/<uuid>.jsonl`;
- кнопка «Проанализировать»: заблокирована, пока файл не выбран; во время запроса —
  состояние загрузки и повторные клики не отправляют второй запрос;
- текст «Поддерживается формат Claude Code JSONL, до 50 МБ».

Клиентские проверки перед отправкой: файл выбран, размер > 0 и ≤ 50 МБ, расширение `.jsonl`
(при другом расширении не блокируй, а предупреди — судья может принести файл без расширения).

После успеха: `navigate(`/analyses/${data.analysis_id}`)`.

При ошибке: показать `message` из `ApiError` рядом с кнопкой, файл не сбрасывать.

## 7. Экран 2: статус (`/analyses/:analysisId`)

Здесь живёт опрос. Сделай хук `useAnalysisStatus(analysisId)`:

1. сразу запрашивает `getAnalysisState`;
2. затем повторяет каждые **2000 мс**;
3. останавливается, когда `TERMINAL_STATUSES.includes(state.status)`;
4. чистит таймер в `useEffect` cleanup (иначе после ухода со страницы запросы продолжатся);
5. используй `setTimeout` рекурсивно, а не `setInterval` — так следующий запрос уходит только
   после ответа предыдущего и они не наслаиваются;
6. сетевая ошибка одного опроса не ломает экран: показываем «соединение потеряно, пробуем ещё»
   и продолжаем попытки. Три неудачи подряд — показать кнопку «Повторить».

Почему опрос, а не WebSocket: обработка идёт в фоне на сервере и может занять до двух минут,
а HTTP не умеет сам присылать обновления. Состояние лежит в БД, поэтому опрос переживает
перезагрузку страницы. Это осознанное решение, не переделывай.

Что на экране:

- текущая стадия: показывай `progress.stage_label` как есть, он уже по-русски;
- полоса прогресса **только** если `progress.percent !== null`. Если `null` —
  неопределённый индикатор (спиннер), проценты не выдумывай;
- если есть `progress.done` и `progress.total` — покажи «12 из 180»;
- список стадий с отметкой пройденных, если так в макете. Порядок:
  `parsing → analyzing → explaining → assembling`;
- `warnings` показывай по мере поступления, они приходят ещё до конца обработки;
- как только `report_available === true` → `navigate` на `/analyses/:id/report`.

Терминальные состояния, кроме `complete`/`partial`, обрабатывай отдельно:

| Статус | Что показать |
|---|---|
| `complete` | сразу переход на отчёт |
| `partial` | переход на отчёт + плашка «часть данных не удалось объяснить» |
| `insufficient_data` | «В файле недостаточно записей для содержательного разбора» + кнопка на `/`. Отчёт может быть доступен — если `report_available`, дай ссылку на него |
| `failed` | текст из `error` + кнопка «Загрузить другой файл» |
| `interrupted` | «Обработка прервалась, запустите анализ заново» + кнопка на `/` |

## 8. Экран 3: отчёт (`/analyses/:analysisId/report`)

Запрашивает `getReport`. Если пришёл **409** — значит пользователь попал сюда слишком рано:
редиректни назад на `/analyses/:analysisId`, не показывай ошибку.

Блоки сверху вниз (если в макете другой порядок — слушай макет):

**1. Шапка.** `summary`, бейдж статуса (`StatusBadge`), дата `created_at`.
Для `partial` — плашка с причинами из `coverage.incomplete_reasons`.

**2. Полнота анализа.** Из `coverage`: распознано шагов, битых строк, неизвестных событий,
объяснено кандидатов `candidates_explained` из `candidates_total`. Если
`llm_enabled === false` — подпись «анализ выполнен без модели, только по правилам».

**3. Метрики** (`MetricsSummary`). Карточки по `metrics`:

- `value === null` → «неизвестно» серым + `coverage` как подпись причины. Не пиши «0»;
- `unit === "ratio"` → проценты, и рядом обязательно знаменатель: «100% (3 из 3)»;
- `unit === "seconds"` → человеческий формат («2 мин 5 с»);
- `limitations` — мелким текстом под значением или в тултипе.

**4. Находки** (`FindingCard` в цикле по `findings`, порядок не менять):

- `title` как заголовок;
- бейдж `severity`: `high` красный, `medium` жёлтый, `low` серый (точные цвета из макета);
- бейдж `assessment`: `inefficient` «неэффективно», `reasonable` «обоснованно»,
  `uncertain` «недостаточно данных», `null` → «не объяснено»;
- `explanation` — основной текст;
- `likely_cause` — отдельным блоком с подписью «Возможная причина», формулировка как гипотеза;
- `facts` — небольшая таблица ключ/значение. Ключи переведи по словарю, неизвестный ключ
  показывай как есть, не падай на нём;
- `limitations` — блок «Ограничения», если непустой;
- если `explanation_source === "rule_based"` — пометка «шаблонное объяснение»,
  если `"not_explained"` — «модель не объясняла этот эпизод». Это важно: отсутствие
  объяснения не значит отсутствие проблемы;
- связанные рекомендации: фильтруй `recommendations` по `finding_id === finding.finding_id`
  и показывай внутри карточки (`action`, `rationale`, `verification`, `rule_text`);
- кнопка «Показать доказательства» раскрывает `EvidenceViewer` по `evidence_step_ids`.

**5. Доказательства** (`EvidenceViewer`). По клику грузит шаги через `getStep` (по одному
на `step_id`, максимум первые 8, остальные по кнопке «Показать ещё»). Для каждого шага:

- `ordinal`, `kind`, `actor`, время `timestamp` (или «время неизвестно»);
- номер строки исходного файла из `source.source_line` — это важный элемент доверия,
  показывай его явно: «строка 42»;
- для `tool_call`: `tool_name` и `arguments.command` (или весь `arguments` как JSON)
  в моноширинном блоке;
- для `tool_result`: `text` в моноширинном блоке; если `is_error === true` — красная рамка;
  `is_error === null` → нейтрально, не зелёным;
- если `text_truncated === true` — подпись «вывод обрезан»;
- соседние шаги из `neighbors_before` / `neighbors_after` — приглушённо, для контекста.

Весь текст из лога выводи **как текст**, никогда не через `innerHTML`/`dangerouslySetInnerHTML`.
Лог — недоверенные данные: там может быть HTML, скрипты и инструкции, адресованные модели.
Если рендеришь markdown — включай санитайзер.

**6. Скачивание.** Кнопки по `report.artifacts`. Подписи:
`report.md` — «Отчёт в Markdown», `report.json` — «Данные отчёта (JSON)»,
`CLAUDE.generated.md` — «Предлагаемые правила для проекта».
Рядом одна строка: правила нужно просмотреть и перенести в свой `CLAUDE.md` вручную.

**7. Предупреждения.** `warnings` списком, приглушённо, внизу.

**8. Происхождение.** Мелким шрифтом: версии парсера и детекторов, модель из `provenance`.
Если `provenance.model === null` — «модель не вызывалась».

**9. История шагов** (`StepsList`, опционально, если есть в макете). `getSteps` с `limit=50`,
кнопка «Загрузить ещё» пока `next_cursor !== null`. Передавай его как `?cursor=`.
Полезно на защите: доказывает, что файл реально разобран.

## 9. Общие требования

- **Пустые состояния.** `findings: []` при `status === "complete"` — это нормальный
  содержательный результат: «Значимых проблем не найдено». Не рисуй ошибку и не пиши «пусто».
- **Загрузка.** Скелетоны или спиннер на каждом экране, никаких белых вспышек.
- **Ошибки.** Любой экран умеет показать сообщение и кнопку «Повторить».
- **Мобильная вёрстка** — если в PDF есть мобильные макеты. Иначе достаточно, чтобы на 1280px
  всё совпадало с макетом и не ломалось на 768px.
- **Доступность по минимуму:** у инпутов `label`, у иконок-кнопок `aria-label`,
  фокус видимый, контраст из макета.
- **Русский язык** во всём интерфейсе, тексты с бекенда не переводи.
- **Никаких моков в коде.** Данные только из API. Бекенд уже отдаёт заполненный демо-отчёт,
  так что верстать есть на чём.

## 10. Пример реального ответа `/report`

Это настоящий ответ бекенда, проверяй вёрстку на нём (сокращён по метрикам и находкам):

```json
{
  "schema_version": "1",
  "analysis_id": "a_e7a1374c27b9",
  "session_id": "s_cc8ef562e4f1",
  "status": "complete",
  "summary": "Найден один значимый эпизод: команда `npm test` повторена три раза с одинаковой ошибкой.",
  "coverage": {
    "total_lines": 9, "recognized_steps": 9, "invalid_lines": 0, "unknown_events": 0,
    "candidates_total": 2, "candidates_explained": 2, "llm_enabled": true, "incomplete_reasons": []
  },
  "metrics": [
    {"key": "tool_error_rate", "label": "Доля ошибок инструментов", "value": 1.0,
     "unit": "ratio", "denominator": 3, "coverage": "вызовы с известным статусом",
     "limitations": ["вызовов мало, доля нестабильна"]},
    {"key": "source_total_tokens", "label": "Токены исходной сессии", "value": null,
     "unit": "tokens", "denominator": null, "coverage": "usage в логе отсутствует",
     "limitations": ["в мок-данных нет usage, значение неизвестно"]}
  ],
  "findings": [
    {
      "finding_id": "f_001", "candidate_id": "c_001", "kind": "repeated_failed_tool",
      "title": "Команда `npm test` повторена 3 раза с одинаковой ошибкой",
      "severity": "high", "rank": 0,
      "facts": {"tool_name": "Bash", "command": "npm test", "attempt_count": 3,
                "explicit_error_count": 3, "identical_errors": true},
      "evidence_step_ids": ["s_cc8ef562e4f1:line_3:block_0", "s_cc8ef562e4f1:line_4:block_0"],
      "evidence_strength": "direct",
      "assessment": "inefficient",
      "explanation": "Команда повторялась после одинакового сообщения об отсутствии test-скрипта.",
      "likely_cause": "Вероятно, агент не проверил доступные команды проекта.",
      "explanation_source": "llm",
      "limitations": ["в доступных событиях не обнаружено релевантного изменения"],
      "detector_version": "mock-v0"
    }
  ],
  "recommendations": [
    {"recommendation_id": "r_001", "finding_id": "f_001",
     "action": "Перед запуском тестов проверь scripts в package.json.",
     "rationale": "Находка f_001: три одинаковые ошибки без изменений между попытками.",
     "verification": "В следующей сессии после одинаковой ошибки появляется диагностический шаг.",
     "rule_text": "Перед первым запуском тестов проверь scripts в package.json.",
     "source": "llm"}
  ],
  "warnings": ["Последняя строка файла оборвана"],
  "provenance": {"parser_version": "mock-v0", "detector_version": "mock-v0",
                 "prompt_version": "mock-v0", "model": "gpt-4.1-mini-2025-04-14"},
  "artifacts": ["report.md", "report.json", "CLAUDE.generated.md"],
  "created_at": "2026-09-20T09:55:21Z"
}
```

Живой OpenAPI: `http://localhost:8080/docs` и `http://localhost:8080/openapi.json` — если
сомневаешься в поле, смотри туда, а не догадывайся.

## 11. Частые ошибки, которых не делай

1. Ставить `Content-Type: multipart/form-data` руками — сломается boundary.
2. Не кодировать `step_id` в URL — двоеточия ломают путь.
3. Показывать `0` там, где `null`. Это искажает смысл: «неизвестно» ≠ «ноль».
4. Считать `is_error: null` успехом. Это «статус неизвестен».
5. Сортировать или фильтровать `findings` на клиенте. Порядок задан бекендом (`rank`).
6. Продолжать опрос после терминального статуса или не чистить таймер при размонтировании.
7. Показывать ошибку на 409 от `/report` вместо возврата на экран статуса.
8. Считать пустой список находок ошибкой.
9. Рендерить текст лога как HTML.
10. Придумывать поля, которых нет в разделе 4.

## 12. Что считать готовым

Сценарий проходится целиком в браузере:

1. Открыл `/`, выбрал `.jsonl`, нажал «Проанализировать».
2. Попал на экран статуса, видел смену стадий с подписями.
3. Автоматически оказался на отчёте.
4. Видит метрики (включая «неизвестно» там, где `null`), находки по приоритету,
   рекомендации внутри находок.
5. Раскрыл доказательства — видит шаги с номерами строк исходного файла и текстом ошибки.
6. Скачал `CLAUDE.generated.md` — файл открывается и содержит правила.
7. Перезагрузил страницу отчёта — всё на месте (данные из API, не из памяти).
8. `npm run build` проходит без ошибок TypeScript.

Вёрстка каждой страницы совпадает с PDF: сетка, отступы, типографика, цвета, состояния.
