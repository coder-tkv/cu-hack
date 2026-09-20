# analysis — разбор лога кодинг-агента кодом (без LLM)

```python
from analysis import analyze_log, analyze_file

report = analyze_log(uploaded_text)   # для загрузки через API
report = analyze_file(path)           # построчное чтение, логи бывают под 100 МБ
```

`report` — это контракт с фронтом:

```python
{
  "meta": {"format": "claude-code", "steps": 812, "lines": 800, "badJson": 0,
           "cwd": "...", "models": [...], "warnings": ["12 строк пропущено"]},
  "kpi":  {"tokensIn": 0, "tokensOut": 0, "cacheRead": 0, "cacheWrite": 0,
           "cost": 12.34, "costPartial": False, "durationMin": 73, "spanMin": 400,
           "toolCalls": 195, "failures": 9, "humanMessages": 5, "interruptions": 2},
  "findings": [{"id": "f1", "type": "repeated_call", "severity": 0.87, "title": "…",
                "stepIds": [120, 124, 131], "evidence": {...}, "metrics": {...},
                "explanation": "…", "source": "code", "detector": "repeated"}],
  "recommendations": [],   # заполняет LLM-этап
  "steps": [...]
}
```

## Что считает код

| type | когда срабатывает |
|---|---|
| `repeated_call` | 3+ одинаковых вызова в окне 10 вызовов; severity выше, если между ними ничего не правили и результат тот же |
| `similar_call` | 3+ близких по смыслу команды Bash (Жаккар ≥ 0.7) — перебор вариантов |
| `retry_loop` | один и тот же вызов падал 2+ раза |
| `repeated_error` | одна ошибка в 3+ разных вызовах |
| `high_failure_rate` | доля падений ≥ 15% при 10+ вызовах |
| `api_errors` | 3+ сбоя самого API модели |
| `token_hotspot` | участок съел ≥ 20% расхода и вдвое больше медианы |
| `spend_without_changes` | ≥ 15% расхода на участке, где не изменён ни один файл |
| `edit_revert` | поздняя правка вернула текст, который убрала прошлая |
| `file_churn` | один файл правился 4+ раз |
| `rewrite_loop` | файл перезаписан целиком 2+ раза |
| `human_corrections` | 2+ коротких реплики-разворота («нет», «не то», «стоп») |
| `interruptions` | 2+ прерывания агента человеком |
| `repeated_instruction` | человек повторил одно указание 2+ раза |
| `idle_gaps` | паузы дольше 10 минут |
| `slow_tool_calls` | 3+ вызова дольше минуты |

Порог и формулы severity — в коде детекторов, каждый в своём файле.

## Правила, которые нельзя ломать

1. **Парсер не бросает исключений.** Любой вход: пустой файл, оборванная строка,
   неизвестный тип события, чужой формат. Проблемы уходят в `meta.warnings`.
2. **Каждая находка ссылается на существующие шаги.** `run_all` выбрасывает
   несуществующие `stepIds`, а находку без ссылок отбрасывает целиком.
3. **Упавший детектор не роняет отчёт** — его ошибка попадает в `meta.warnings`.
4. **«Значимых проблем не найдено» — нормальный результат.** Придумывать находки нельзя.
5. **Цену не выдумываем.** Неизвестная модель -> `cost: None` и `costPartial`.

## Проверка

```bash
python3 -m unittest discover -s tests -q          # 47 тестов
python3 -m analysis.cli ~/.claude/projects/<проект>/<uuid>.jsonl --top 10
```

Тест `TestRealLogs` прогоняет разбор по всем настоящим логам на машине и по
их обрезанным половинам — это защита от падения на логе судей.
