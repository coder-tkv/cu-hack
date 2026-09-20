"""Общие утилиты детекторов. Чистый код, без LLM."""

from __future__ import annotations

import json
import re
from typing import Any

# Инструменты, которые меняют проект: после них повтор команды — законное дело.
MUTATING_TOOLS = {"Edit", "Write", "NotebookEdit", "MultiEdit"}
VOLATILE_ARG_KEYS = {"description", "timeout", "run_in_background", "limit", "offset"}

_WS = re.compile(r"\s+")
_TOKEN_SPLIT = re.compile(r"[^a-zа-я0-9_./:-]+")


def norm(s: Any) -> str:
    return _WS.sub(" ", str(s)).strip()


def norm_command(cmd: Any) -> str:
    """Команду сравниваем без мусора: кавычки, лишние пробелы, регистр.

    Каталог из `cd X && ...` НЕ выбрасываем: одна и та же команда в разных
    каталогах — разные действия, и склеивать их в «повтор» нельзя.
    """
    t = norm(cmd).replace('"', "").replace("'", "").lower()
    m = re.match(r"^cd\s+(\S+)\s*(?:&&|;)\s*(.*)$", t)
    return f"cd={m.group(1)} {m.group(2)}" if m else t


def args_key(step: dict) -> str:
    """Нормализованный ключ вызова: одинаковый ключ = то же самое действие."""
    tool = step.get("tool") or "?"
    a = step.get("args") if isinstance(step.get("args"), dict) else {}

    def pick(k: str) -> str | None:
        v = a.get(k)
        return v if isinstance(v, str) else None

    if tool == "Bash":
        return f"{tool}|{norm_command(pick('command') or '')}"
    if tool in ("Read", "Write"):
        return f"{tool}|{pick('file_path') or ''}"
    if tool in ("Edit", "MultiEdit"):
        path = pick("file_path") or ""
        edits = a.get("edits")
        if isinstance(edits, list):
            # у MultiEdit правки лежат в массиве; без него ключ был бы одинаков
            # для любых правок одного файла
            parts = [
                f"{norm(e.get('old_string') or e.get('oldString') or '')}=>"
                f"{norm(e.get('new_string') or e.get('newString') or '')}"
                for e in edits
                if isinstance(e, dict)
            ]
            return f"{tool}|{path}|" + "|".join(parts)[:500]
        # разный new_string при одном old_string — разные правки, не повтор
        return f"{tool}|{path}|{norm(pick('old_string') or '')}=>{norm(pick('new_string') or '')}"
    if tool in ("Grep", "Glob"):
        return f"{tool}|{pick('pattern') or ''}|{pick('path') or ''}"
    if tool in ("WebFetch", "WebSearch"):
        return f"{tool}|{norm(pick('url') or pick('query') or '')}"

    parts = []
    for k in sorted(a.keys()):
        if k in VOLATILE_ARG_KEYS:
            continue
        v = a[k]
        parts.append(f"{k}={json.dumps(v, ensure_ascii=False, sort_keys=True) if isinstance(v, (dict, list)) else v}")
    return f"{tool}|{norm('&'.join(parts))[:500]}"


def has_identity(step: dict) -> bool:
    """Есть ли у вызова хоть что-то отличающее его от другого вызова.

    Без имени инструмента и без аргументов все такие шаги схлопываются в один ключ,
    и детектор повторов начинает видеть «три одинаковых вызова» там, где их нет.
    """
    if step.get("tool"):
        return True
    a = step.get("args")
    return isinstance(a, (dict, list, str)) and bool(a)


def group_key(step: dict) -> str:
    """Ключ группировки повторов. Сабагент — отдельный исполнитель: его вызовы
    нельзя складывать в одну серию с вызовами главного потока."""
    return ("sub|" if step.get("sidechain") else "") + args_key(step)


def is_compact_boundary(step: dict) -> bool:
    """Шаг сжатия контекста: после него агент заново читает то, что уже читал."""
    raw = step.get("raw")
    return isinstance(raw, str) and "compact_boundary" in raw


def tokens_of(s: Any) -> set[str]:
    return {t for t in _TOKEN_SPLIT.split(str(s).lower()) if len(t) > 1}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / (len(a) + len(b) - inter)


def snippet(s: Any, limit: int = 200) -> str | None:
    if not isinstance(s, str):
        return None
    t = norm(s)
    return t if len(t) <= limit else t[:limit] + "…"


_POSITIONAL_NUM = re.compile(
    r"\b(?:lines?|col(?:umn)?s?|char|row|offset|position|pos|port)\b\s*[:=#]?\s*\d+",
    re.IGNORECASE,
)

_ERR_HINT = re.compile(
    r"error|exception|fail|not found|cannot|no such|denied|refused|traceback|нет|ошибк",
    re.IGNORECASE,
)


def error_signature(text: Any) -> str:
    """Первая осмысленная строка ошибки: по ней группируем «одинаковые падения»."""
    if not isinstance(text, str):
        return ""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if not lines:
        return ""
    meaningful = next((l for l in lines if _ERR_HINT.search(l)), lines[0])
    # Затирать все числа нельзя: HTTP 404 и HTTP 500 — разные ошибки, а
    # «line 42» и «line 99» — одна. Нормализуем только позиционные числа.
    out = _POSITIONAL_NUM.sub(lambda m: re.sub(r"\d+", "N", m.group(0)), meaningful)
    out = re.sub(r"[0-9a-f]{8,}", "HASH", out, flags=re.IGNORECASE)
    return norm(out)[:160].lower()


def describe_args(step: dict) -> str:
    a = step.get("args") if isinstance(step.get("args"), dict) else {}
    for k in ("command", "file_path", "pattern", "url", "query"):
        if isinstance(a.get(k), str):
            return snippet(a[k], 90) or ""
    return snippet(json.dumps(a, ensure_ascii=False), 90) if a else "(без аргументов)"


def describe_tool_call(step: dict) -> str:
    return f"{step.get('tool') or 'инструмент'}: {describe_args(step)}"


def build_index(steps: list[dict]) -> dict:
    """Индексы: вызов -> результат, шаг -> его «ход» (между репликами человека)."""
    result_by_call: dict[int, dict] = {}
    for s in steps:
        if s.get("kind") == "tool_result" and s.get("resultOf"):
            result_by_call[s["resultOf"]] = s

    turns: list[dict] = []
    turn_of_step: dict[int, int] = {}
    cur: dict | None = None
    for s in steps:
        is_human = s.get("kind") == "human" and not s.get("synthetic")
        if is_human or cur is None:
            cur = {
                "index": len(turns),
                "promptStepId": s["id"] if is_human else None,
                "promptText": s.get("text") if is_human else None,
                "stepIds": [],
            }
            turns.append(cur)
        cur["stepIds"].append(s["id"])
        turn_of_step[s["id"]] = cur["index"]
    return {"resultByCall": result_by_call, "turns": turns, "turnOfStep": turn_of_step}


def by_id(steps: list[dict]) -> dict[int, dict]:
    return {s["id"]: s for s in steps}


def call_duration_ms(call: dict | None, result: dict | None) -> int | None:
    if not call or not result:
        return None
    a, b = call.get("ts"), result.get("ts")
    if not isinstance(a, int) or not isinstance(b, int):
        return None
    return b - a if b >= a else None


def plural(n: int, forms: tuple[str, str, str]) -> str:
    """Русские окончания: plural(3, ("раз", "раза", "раз")) -> "раза"."""
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return forms[0]
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return forms[1]
    return forms[2]


def fmt_minutes(m: int) -> str:
    """Крупные интервалы читаемо: 7853 -> "5 дн 11 ч"."""
    m = int(m)
    if m >= 1440:
        return f"{m // 1440} дн {(m % 1440) // 60} ч"
    if m >= 60:
        return f"{m // 60} ч {m % 60} мин"
    return f"{m} мин"


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def finding(
    ftype: str,
    *,
    severity: float,
    title: str,
    step_ids: list[int],
    evidence: dict | None = None,
    metrics: dict | None = None,
    explanation: str | None = None,
) -> dict:
    """Единый формат находки: {type, severity, stepIds, evidence, ...}."""
    # id шага не обязан быть числом: у общего контракта это строка
    # "<session>:line_<N>:block_<M>". Порядок сохраняем, дубли убираем.
    seen = []
    for i in step_ids:
        if i is not None and i not in seen:
            seen.append(i)
    ordered = sorted(seen) if all(isinstance(i, int) for i in seen) else seen
    return {
        "type": ftype,
        "severity": round(clamp01(severity), 3),
        "title": title,
        "stepIds": ordered,
        "evidence": evidence or {},
        "metrics": metrics or {},
        "explanation": explanation,
        "source": "code",
    }
