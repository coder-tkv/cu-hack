# Формат логов Claude Code — сверено с реальными файлами

13 логов, 26 447 строк, суммарно ~130 МБ (самый большой — 82 МБ, 17 254 строки).

## Что подтвердилось
- JSONL, одна строка = один объект. Битых строк в наших логах 0.
- Поля: `type`, `uuid`, `parentUuid`, `timestamp` (ISO), `sessionId`, `cwd`, `version`, `gitBranch`, `isSidechain`.
- `message.content`: строка **или** массив блоков `text` / `thinking` / `tool_use` / `tool_result` / `image`.
- `message.usage`: `input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens` (+ `service_tier`, `cache_creation`).

## Чего в памяти не было (важно)
1. **Типов событий гораздо больше, чем 4.** Встречены: `assistant`, `user`, `attachment`, `last-prompt`,
   `custom-title`, `mode`, `queue-operation`, `atis-latch`, `system`, `bridge-session`,
   `file-history-snapshot`, `ai-title`, `agent-name`, `file-history-delta`, `frame-link`.
   Типа `summary` в наших логах нет вообще. Вывод: белый список типов писать нельзя, только `kind: "other"`.
2. **Двойной счёт токенов реален и огромен.** 5 485 уникальных `message.id` на 10 116 assistant-строк:
   85 % строк повторяют usage уже посчитанного ответа. Без дедупликации по `message.id` токены завышаются вдвое.
3. **`toolUseResult` (верхний уровень, не внутри content)** — готовая структура результата:
   `stdout`/`stderr`/`interrupted` для Bash, `oldString`/`newString`/`filePath`/`structuredPatch` для Edit.
   Детектор откатов правок можно строить на нём, а не парсить текст.
4. **Не всякая user-строка — человек.** Из 6 068 user-строк: 5 509 — это `tool_result`,
   а среди остальных много служебных: `<task-notification>`, `<system-reminder>`, `[Request interrupted by user]`,
   `Continue from where you left off.`, `isMeta: true`. Парсер помечает такие `synthetic: true`,
   отдельно `interrupted: true`. KPI «вмешательства человека» считаем только по `synthetic: false`.
   Маркер прерывания проверяем **только по началу строки**: человек может упомянуть его и в обычной реплике
   (на этом уже попались — промпт с описанием задачи улетел в «прерывания»).
5. **У 5 726 строк нет `timestamp`** (служебные типы). Время считаем только по шагам, где ts есть.
6. **Span сессии != длительность работы.** В большом логе span 63 516 мин (44 дня), активного времени 1 437 мин:
   сессию возобновляли. В KPI отдаём и `spanMin`, и `activeMin` (простои > 10 мин выкинуты), иначе цифра врёт.
7. `tool_result.content` бывает не строкой, а массивом блоков (1 780 случаев).
8. `is_error` у tool_result — 235 случаев; плюс отдельные строки `type: "system", subtype: "api_error"` (160).
9. Есть подкаталоги `<session>/subagents/agent-*.jsonl` — логи сабагентов лежат отдельными файлами.

## Контракт шага
```json
{ "id": 42, "line": 87, "ts": 1758369600000,
  "kind": "human|assistant_text|tool_call|tool_result|other",
  "tool": "Bash", "args": {"command": "npm test"},
  "resultOf": 41, "isError": false, "text": "…",
  "usage": {"in":1200,"out":300,"cacheRead":9000,"cacheWrite":0},
  "uuid": "…", "raw": "assistant|thinking|attachment|system:api_error|…", "sidechain": false,
  "toolUseId": "tu_1", "textLen": 12345, "result": {},
  "synthetic": false, "interrupted": false, "syntheticReason": null }
```
Любое поле может быть `null`. `id` — сквозной номер шага (на него ссылаются находки), `line` — строка в файле.
`raw` хранит исходный `type[:subtype]` — по нему детекторы ловят `api_error`, `thinking` и прочее,
не завися от списка `kind`.

## API парсера
```js
import { parseLog, createStreamParser, sessionTiming } from './parser/index.js';
const { meta, steps } = parseLog(text);        // весь файл строкой (загрузка через веб)
const p = createStreamParser(); p.line(s); p.finish();  // для файлов в десятки МБ
sessionTiming(steps, 10*60*1000);              // { spanMin, activeMin, idleGaps[] }
```
`parseLog` не бросает исключений ни на каком входе (проверено тестами: пустой файл, `null`,
оборванная строка, не-объекты, чужой формат, отсутствующие поля).

Ограничения по размеру: текст шага 4 000 символов (`textLen` — исходная длина),
строка внутри `args` — 20 000 символов.
