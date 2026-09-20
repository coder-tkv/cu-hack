"""Парсер логов Claude Code (JSONL) -> плоский список шагов.

Контракт: НИКОГДА не бросает исключений на данных. Неизвестный тип события ->
kind "other", отсутствующее поле -> None. Все проблемы уходят в meta["warnings"].

Формат сверен с реальными логами, см. docs/log-format.md.
"""

from __future__ import annotations

import json
from typing import Any, Iterable

MAX_TEXT = 4000  # столько символов текста храним в шаге
MAX_ARG_STR = 20000  # отдельная строка внутри args
MAX_RESULT_STR = 2000  # строка внутри результата инструмента
MAX_WARNINGS = 200

# Из toolUseResult берём только то, что нужно детекторам и человеку в отчёте.
# originalFile, file и content — это содержимое файлов целиком: на большом логе
# они дают гигабайты, а для разбора бесполезны (текст результата уже есть в шаге).
RESULT_KEEP = (
    "stdout", "stderr", "interrupted", "is_error", "returnCodeInterpretation",
    "filePath", "oldString", "newString", "replaceAll", "edits",
    "type", "success", "numLines", "numFiles", "mode", "totalLines",
)
RESULT_DROP = ("originalFile", "file", "content", "userModified", "results", "questions")

# Синтетические "реплики пользователя": их пишет харнесс, а не человек.
SYNTHETIC_PREFIXES = (
    "<task-notification>",
    "<system-reminder>",
    "<local-command-stdout>",
    "<local-command-stderr>",
    "<command-name>",
    "<command-message>",
    "<user-memory-input>",
    "<ci-monitor-event>",
    "Caveat: The messages below were generated",
)
INTERRUPT_MARKERS = (
    "[Request interrupted by user",
    "[Request cancelled by user",
)
CONTINUATION_TEXTS = ("Continue from where you left off.",)

KIND_HUMAN = "human"
KIND_ASSISTANT_TEXT = "assistant_text"
KIND_TOOL_CALL = "tool_call"
KIND_TOOL_RESULT = "tool_result"
KIND_OTHER = "other"


def _truncate(s: Any, limit: int) -> Any:
    if not isinstance(s, str) or len(s) <= limit:
        return s
    return s[:limit] + f"\n…[обрезано {len(s) - limit} символов]"


def _shrink(value: Any, depth: int = 0) -> Any:
    """Обрезает длинные строки внутри args/result, чтобы шаг не раздувался."""
    if value is None:
        return None
    if isinstance(value, str):
        return _truncate(value, MAX_ARG_STR)
    if isinstance(value, (int, float, bool)):
        return value
    if depth > 6:
        return None
    if isinstance(value, list):
        return [_shrink(v, depth + 1) for v in value[:200]]
    if isinstance(value, dict):
        return {k: _shrink(value[k], depth + 1) for k in list(value.keys())[:100]}
    return str(value)[:200]


def _patch_summary(patch: Any) -> dict | None:
    """structuredPatch занимает сотни килобайт; в отчёте достаточно сводки."""
    if not isinstance(patch, list):
        return None
    added = removed = 0
    for hunk in patch:
        if not isinstance(hunk, dict):
            continue
        for line in hunk.get("lines") or []:
            if isinstance(line, str):
                if line.startswith("+"):
                    added += 1
                elif line.startswith("-"):
                    removed += 1
    return {"hunks": len(patch), "linesAdded": added, "linesRemoved": removed}


def _shrink_result(tur: dict) -> dict:
    """Чистим результат инструмента: только полезные поля, строки — короткие."""
    out: dict = {}
    for k in RESULT_KEEP:
        if k not in tur:
            continue
        v = tur[k]
        if isinstance(v, str):
            out[k] = _truncate(v, MAX_RESULT_STR)
        elif k == "edits" and isinstance(v, list):
            out[k] = [
                {
                    kk: _truncate(vv, MAX_RESULT_STR) if isinstance(vv, str) else vv
                    for kk, vv in e.items()
                }
                for e in v[:20]
                if isinstance(e, dict)
            ]
        else:
            out[k] = _shrink(v, 4)
    summary = _patch_summary(tur.get("structuredPatch"))
    if summary:
        out["patchSummary"] = summary
    dropped = [k for k in RESULT_DROP if k in tur]
    if dropped:
        out["omitted"] = dropped  # честно говорим, что выбросили
    return out


def _text_of_blocks(blocks: Iterable[Any]) -> str:
    parts: list[str] = []
    for b in blocks:
        if isinstance(b, str):
            parts.append(b)
        elif isinstance(b, dict):
            if isinstance(b.get("text"), str):
                parts.append(b["text"])
            elif b.get("type") == "image":
                parts.append("[image]")
            elif isinstance(b.get("content"), str):
                parts.append(b["content"])
            elif isinstance(b.get("content"), list):
                parts.append(_text_of_blocks(b["content"]))
    return "\n".join(parts)


def _norm_usage(u: Any) -> dict | None:
    if not isinstance(u, dict):
        return None

    def n(x: Any) -> int:
        return x if isinstance(x, (int, float)) and not isinstance(x, bool) else 0

    total_write = int(n(u.get("cache_creation_input_tokens")))
    # Разбивка по TTL: часовой кэш стоит дороже пятиминутного, а Claude Code
    # почти всегда пишет в часовой. Без разбивки считаем весь объём пятиминутным.
    cc = u.get("cache_creation")
    w5 = w1h = 0
    if isinstance(cc, dict):
        w5 = int(n(cc.get("ephemeral_5m_input_tokens")))
        w1h = int(n(cc.get("ephemeral_1h_input_tokens")))
    if w5 + w1h == 0:
        w5 = total_write
    elif w5 + w1h != total_write:
        total_write = w5 + w1h  # доверяем разбивке: она детальнее

    return {
        "in": int(n(u.get("input_tokens"))),
        "out": int(n(u.get("output_tokens"))),
        "cacheRead": int(n(u.get("cache_read_input_tokens"))),
        "cacheWrite": total_write,
        "cacheWrite5m": w5,
        "cacheWrite1h": w1h,
    }


def classify_human_text(text: Any) -> dict:
    """Человек это написал или харнесс. Прерывание — только по началу строки:
    человек может и сам упомянуть маркер в обычной реплике."""
    t = (text or "").strip() if isinstance(text, str) else ""
    if not t:
        return {"synthetic": True, "interrupted": False, "reason": "empty"}
    for m in INTERRUPT_MARKERS:
        if t.startswith(m):
            return {"synthetic": True, "interrupted": True, "reason": "interrupt"}
    for p in SYNTHETIC_PREFIXES:
        if t.startswith(p):
            return {"synthetic": True, "interrupted": False, "reason": "injected"}
    if t in CONTINUATION_TEXTS:
        return {"synthetic": True, "interrupted": False, "reason": "continuation"}
    return {"synthetic": False, "interrupted": False, "reason": None}


def _looks_like_claude_code(obj: Any) -> bool:
    if not isinstance(obj, dict) or not isinstance(obj.get("type"), str):
        return False
    return (
        "uuid" in obj
        or "sessionId" in obj
        or "parentUuid" in obj
        or isinstance(obj.get("message"), dict)
    )


def _parse_ts(obj: dict) -> int | None:
    ts = obj.get("timestamp")
    if isinstance(ts, (int, float)) and not isinstance(ts, bool):
        return int(ts)
    if isinstance(ts, str) and ts:
        try:
            from datetime import datetime

            return int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() * 1000)
        except Exception:
            return None
    return None


class Parser:
    """Потоковый парсер: кормим строками через .line(), забираем .finish()."""

    def __init__(self) -> None:
        self.steps: list[dict] = []
        self.warnings: list[str] = []
        self.stats = {"lines": 0, "blank": 0, "badJson": 0, "claudeCodeLines": 0}
        self._seen_usage_msg_ids: set[str] = set()  # защита от двойного счёта usage
        self._tool_use_to_step: dict[str, int] = {}
        self._line_no = 0
        self._meta = {
            "sessionIds": set(),
            "cwd": None,
            "gitBranch": None,
            "versions": set(),
            "models": set(),
        }

    # --- служебное -----------------------------------------------------
    def warn(self, msg: str) -> None:
        if len(self.warnings) < MAX_WARNINGS:
            self.warnings.append(msg)
        elif len(self.warnings) == MAX_WARNINGS:
            self.warnings.append("…предупреждения дальше не показываем")

    def _push(self, step: dict) -> dict:
        step["id"] = len(self.steps) + 1
        self.steps.append(step)
        return step

    def _base(self, line: int, obj: dict) -> dict:
        return {
            "id": 0,
            "line": line,
            "ts": _parse_ts(obj),
            "kind": KIND_OTHER,
            "tool": None,
            "args": None,
            "resultOf": None,
            "isError": False,
            "text": None,
            "usage": None,
            "uuid": obj.get("uuid") if isinstance(obj.get("uuid"), str) else None,
            "raw": obj.get("type") if isinstance(obj.get("type"), str) else None,
            "sidechain": bool(obj.get("isSidechain")),
        }

    # --- разбор --------------------------------------------------------
    def line(self, text: Any) -> None:
        self._line_no += 1
        self.add_line(self._line_no, text)

    def add_line(self, line_no: int, text: Any) -> None:
        trimmed = text.strip() if isinstance(text, str) else ""
        if not trimmed:
            self.stats["blank"] += 1  # пустые строки в конце файла — норма
            return
        self.stats["lines"] += 1

        try:
            obj = json.loads(trimmed)
        except Exception:
            self.stats["badJson"] += 1
            self.warn(f"строка {line_no}: не разобрался JSON (возможно, файл оборван)")
            return
        if not isinstance(obj, dict):
            self.stats["badJson"] += 1
            self.warn(f"строка {line_no}: ожидался объект, пришло {type(obj).__name__}")
            return

        if _looks_like_claude_code(obj):
            self.stats["claudeCodeLines"] += 1
        self._collect_meta(obj)

        kind = obj.get("type")
        try:
            if kind == "assistant":
                self._add_assistant(line_no, obj)
            elif kind == "user":
                self._add_user(line_no, obj)
            else:
                self._add_other(line_no, obj)
        except Exception as e:  # сюда в норме не попадаем, но лог судей важнее нашей гордости
            self.warn(f"строка {line_no}: внутренняя ошибка разбора ({e})")
            s = self._base(line_no, obj)
            s["text"] = "не удалось разобрать шаг"
            self._push(s)

    def _collect_meta(self, obj: dict) -> None:
        m = self._meta
        if isinstance(obj.get("sessionId"), str):
            m["sessionIds"].add(obj["sessionId"])
        if m["cwd"] is None and isinstance(obj.get("cwd"), str):
            m["cwd"] = obj["cwd"]
        if m["gitBranch"] is None and isinstance(obj.get("gitBranch"), str) and obj["gitBranch"]:
            m["gitBranch"] = obj["gitBranch"]
        if isinstance(obj.get("version"), str):
            m["versions"].add(obj["version"])
        msg = obj.get("message")
        if isinstance(msg, dict) and isinstance(msg.get("model"), str):
            m["models"].add(msg["model"])

    def _add_assistant(self, line_no: int, obj: dict) -> None:
        msg = obj.get("message") if isinstance(obj.get("message"), dict) else {}
        msg_id = msg.get("id") if isinstance(msg.get("id"), str) else None

        # usage дублируется в каждой строке одного ответа -> считаем один раз
        usage = None
        if msg_id is None or msg_id not in self._seen_usage_msg_ids:
            usage = _norm_usage(msg.get("usage"))
            if msg_id:
                self._seen_usage_msg_ids.add(msg_id)

        model = msg.get("model") if isinstance(msg.get("model"), str) else None
        content = msg.get("content")
        if isinstance(content, list):
            blocks = content
        elif isinstance(content, str):
            blocks = [{"type": "text", "text": content}]
        else:
            blocks = []

        made: list[dict] = []
        for b in blocks:
            if not isinstance(b, dict):
                continue
            btype = b.get("type")
            if btype == "tool_use":
                s = self._base(line_no, obj)
                s["kind"] = KIND_TOOL_CALL
                s["tool"] = b.get("name") if isinstance(b.get("name"), str) else None
                s["args"] = _shrink(b.get("input"))
                s["toolUseId"] = b.get("id") if isinstance(b.get("id"), str) else None
                self._push(s)
                if s["toolUseId"]:
                    self._tool_use_to_step[s["toolUseId"]] = s["id"]
                made.append(s)
            elif btype in ("text", "thinking"):
                t = b.get("text") if isinstance(b.get("text"), str) else b.get("thinking")
                if not isinstance(t, str) or not t.strip():
                    continue
                s = self._base(line_no, obj)
                s["kind"] = KIND_OTHER if btype == "thinking" else KIND_ASSISTANT_TEXT
                if btype == "thinking":
                    s["raw"] = "thinking"
                s["text"] = _truncate(t, MAX_TEXT)
                s["textLen"] = len(t)
                self._push(s)
                made.append(s)

        if not made:
            # пустой ответ (только usage) — шаг всё равно нужен, чтобы токены не потерялись
            s = self._base(line_no, obj)
            s["raw"] = "assistant_empty"
            self._push(s)
            made.append(s)

        for st in made:
            st["model"] = model  # нужен для оценки стоимости шага
        if usage:
            made[0]["usage"] = usage
        if obj.get("subtype") == "api_error" or obj.get("isApiErrorMessage"):
            made[0]["isError"] = True

    def _add_user(self, line_no: int, obj: dict) -> None:
        msg = obj.get("message") if isinstance(obj.get("message"), dict) else {}
        tur = obj.get("toolUseResult") if isinstance(obj.get("toolUseResult"), dict) else None
        content = msg.get("content")
        if isinstance(content, list):
            blocks = content
        elif isinstance(content, str):
            blocks = [{"type": "text", "text": content}]
        else:
            blocks = []

        made = 0
        for b in blocks:
            if not isinstance(b, dict):
                continue
            btype = b.get("type")
            if btype == "tool_result":
                s = self._base(line_no, obj)
                s["kind"] = KIND_TOOL_RESULT
                s["toolUseId"] = b.get("tool_use_id") if isinstance(b.get("tool_use_id"), str) else None
                s["resultOf"] = self._tool_use_to_step.get(s["toolUseId"]) if s["toolUseId"] else None
                if s["resultOf"]:
                    call = self.steps[s["resultOf"] - 1]
                    s["tool"] = call.get("tool")
                body = b.get("content")
                body_text = body if isinstance(body, str) else (_text_of_blocks(body) if isinstance(body, list) else "")
                s["text"] = _truncate(body_text, MAX_TEXT)
                s["textLen"] = len(body_text)
                s["isError"] = bool(b.get("is_error")) or bool(
                    tur and (tur.get("interrupted") is True or tur.get("is_error") is True)
                )
                if tur:
                    s["result"] = _shrink_result(tur)
                self._push(s)
                made += 1
            elif btype in ("text", "image"):
                t = "[image]" if btype == "image" else (b.get("text") if isinstance(b.get("text"), str) else "")
                cls = classify_human_text(t)
                s = self._base(line_no, obj)
                s["kind"] = KIND_HUMAN
                s["text"] = _truncate(t, MAX_TEXT)
                s["textLen"] = len(t)
                s["synthetic"] = bool(cls["synthetic"] or obj.get("isMeta"))
                s["interrupted"] = bool(cls["interrupted"])
                s["syntheticReason"] = "meta" if obj.get("isMeta") else cls["reason"]
                self._push(s)
                made += 1

        if made == 0:
            s = self._base(line_no, obj)
            s["raw"] = "user_empty"
            self._push(s)

    def _add_other(self, line_no: int, obj: dict) -> None:
        s = self._base(line_no, obj)
        s["raw"] = obj["type"] if isinstance(obj.get("type"), str) else "unknown"
        if obj.get("subtype"):
            s["raw"] += ":" + str(obj["subtype"])
        if obj.get("subtype") == "api_error" or obj.get("level") == "error":
            s["isError"] = True
        t = obj.get("content") if isinstance(obj.get("content"), str) else obj.get("error")
        if isinstance(t, str):
            s["text"] = _truncate(t, MAX_TEXT)
            s["textLen"] = len(t)
        self._push(s)

    # --- итог ----------------------------------------------------------
    def finish(self) -> dict:
        st = self.stats
        fmt = "unknown"
        if st["lines"] == 0:
            fmt = "empty"
        elif st["claudeCodeLines"] > 0 and st["claudeCodeLines"] >= max(1, (st["lines"] - st["badJson"]) * 0.3):
            fmt = "claude-code"
        if fmt == "unknown" and st["lines"] > 0:
            self.warn("формат не похож на лог Claude Code: разбираем как можем")
        if st["badJson"]:
            self.warn(f"{st['badJson']} строк(и) пропущено из-за битого JSON")

        tss = [s["ts"] for s in self.steps if s["ts"] is not None]
        if not tss and self.steps:
            self.warn("в логе нет пригодных timestamp: время и простои не считаем")

        return {
            "meta": {
                "format": fmt,
                "steps": len(self.steps),
                "lines": st["lines"],
                "badJson": st["badJson"],
                "sessionIds": sorted(self._meta["sessionIds"]),
                "cwd": self._meta["cwd"],
                "gitBranch": self._meta["gitBranch"],
                "versions": sorted(self._meta["versions"]),
                "models": sorted(self._meta["models"]),
                "tsFrom": min(tss) if tss else None,
                "tsTo": max(tss) if tss else None,
                "warnings": self.warnings,
            },
            "steps": self.steps,
        }


def parse_log(text: Any) -> dict:
    """Весь текст лога -> {"meta": ..., "steps": [...]}. Не бросает исключений."""
    p = Parser()
    src = text if isinstance(text, str) else ("" if text is None else str(text))
    for i, line in enumerate(src.split("\n"), start=1):
        p.add_line(i, line)
    return p.finish()


def parse_file(path: str) -> dict:
    """Построчное чтение: логи бывают под 100 МБ."""
    p = Parser()
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            p.line(line.rstrip("\n"))
    return p.finish()


def session_timing(steps: list[dict], gap_ms: int = 10 * 60 * 1000) -> dict:
    """span — от первого до последнего шага, active — без простоев длиннее gap_ms.
    Сессию часто возобновляют через сутки, span тогда врёт."""
    tss = sorted(s["ts"] for s in steps if isinstance(s.get("ts"), int))
    if len(tss) < 2:
        return {"spanMin": 0, "activeMin": 0, "idleGaps": []}
    active = 0
    gaps = []
    for prev, cur in zip(tss, tss[1:]):
        d = cur - prev
        if d <= gap_ms:
            active += d
        else:
            gaps.append({"fromTs": prev, "toTs": cur, "minutes": round(d / 60000)})
    return {
        "spanMin": round((tss[-1] - tss[0]) / 60000),
        "activeMin": round(active / 60000),
        "idleGaps": gaps,
    }
