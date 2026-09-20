"""Инструменты: что агенту стоит подключить, разрешить или чем перестать
пользоваться вручную.

Кейс просит рекомендовать в том числе «какие инструменты подключить». Из лога
это видно по трём признакам:

1. агент делает через Bash то, для чего в сессии есть готовый инструмент
   (cat вместо Read, grep вместо Grep) — лишние шаги и лишние токены;
2. команда не найдена в системе — инструмента не хватает физически;
3. вызов отклонён по разрешениям — инструмент есть, но доступа нет.
"""

from __future__ import annotations

import re
from collections import defaultdict

from .util import build_index, finding, plural, snippet

# Bash-команда -> готовый инструмент, который делает то же самое
BASH_SUBSTITUTES = (
    ("чтение файлов", re.compile(r"^\s*(cat|head|tail|less|more)\s+[^|]*$", re.M), "Read"),
    ("поиск по содержимому", re.compile(r"^\s*(grep|rg|ag)\s", re.M), "Grep"),
    ("поиск файлов", re.compile(r"^\s*(find\s|ls\s+-R)", re.M), "Glob"),
    ("запись файлов", re.compile(r"(>\s*[^|&>\s]+\.(?:py|js|ts|tsx|json|md|txt|ya?ml|css|html)|<<\s*['\"]?EOF)", re.M), "Write"),
    ("правка файлов", re.compile(r"^\s*(sed\s+-i|perl\s+-i)", re.M), "Edit"),
)

MISSING_CLI = re.compile(
    r"(?:command not found:\s*|:\s*command not found|zsh:\s*command not found:\s*)([A-Za-z0-9_.-]{2,})"
)
DENIED = re.compile(
    r"user doesn'?t want to proceed|was rejected|permission for this action was denied|"
    r"denied by the claude code auto mode classifier|not allowed to use",
    re.I,
)

MIN_SUBSTITUTIONS = 5   # единичный cat — не проблема, это привычка
MIN_MISSING = 2         # одна опечатка в имени команды тоже бывает
MIN_DENIALS = 2


def detect_tool_gaps(steps: list[dict]) -> list[dict]:
    idx = build_index(steps)
    result_by_call = idx["resultByCall"]
    out: list[dict] = []

    available = {s.get("tool") for s in steps if s.get("kind") == "tool_call" and s.get("tool")}

    # (1) Bash вместо готового инструмента
    hits: dict[str, list[dict]] = defaultdict(list)
    for s in steps:
        if s.get("kind") != "tool_call" or s.get("tool") != "Bash":
            continue
        cmd = (s.get("args") or {}).get("command")
        if not isinstance(cmd, str):
            continue
        for label, pattern, tool in BASH_SUBSTITUTES:
            if pattern.search(cmd):
                hits[label].append({"step": s, "tool": tool, "command": cmd})
                break

    for label, group in hits.items():
        if len(group) < MIN_SUBSTITUTIONS:
            continue
        tool = group[0]["tool"]
        used_before = tool in available
        out.append(
            finding(
                "bash_instead_of_tool",
                severity=min(0.65, 0.3 + len(group) * 0.01),
                title=(
                    f"{label.capitalize()} через Bash {len(group)} "
                    f"{plural(len(group), ('раз', 'раза', 'раз'))} — для этого есть {tool}"
                ),
                step_ids=[h["step"]["id"] for h in group][:20],
                metrics={"occurrences": len(group), "tool": tool, "toolUsedInSession": used_before},
                evidence={
                    "category": label,
                    "tool": tool,
                    "toolUsedInSession": used_before,
                    "examples": [
                        {"stepId": h["step"]["id"], "line": h["step"].get("line"),
                         "command": snippet(h["command"], 120)}
                        for h in group[:5]
                    ],
                },
                explanation=(
                    f"Агент {len(group)} раз делал через Bash то, что делает {tool}: "
                    "каждый такой вызов дороже по токенам и не даёт инструменту показать структуру. "
                    + ("Инструмент в сессии доступен." if used_before
                       else f"{tool} в этой сессии ни разу не вызывался — возможно, он не подключён.")
                ),
            )
        )

    # (2) команды нет в системе
    missing: dict[str, list[dict]] = defaultdict(list)
    for s in steps:
        if s.get("kind") != "tool_result":
            continue
        for binary in dict.fromkeys(m.group(1) for m in MISSING_CLI.finditer(s.get("text") or "")):
            missing[binary].append(s)
    for binary, group in missing.items():
        if len(group) < MIN_MISSING:
            continue
        out.append(
            finding(
                "missing_cli",
                severity=min(0.6, 0.35 + len(group) * 0.02),
                title=(
                    f"Команда «{binary}» не найдена: сообщение в {len(group)} результатах инструментов"
                ),
                step_ids=[s["id"] for s in group][:12],
                metrics={"binary": binary, "occurrences": len(group)},
                evidence={
                    "binary": binary,
                    "resultStepIds": [s["id"] for s in group][:12],
                    "lines": [s.get("line") for s in group][:12],
                    "errorSnippet": snippet(group[0].get("text")),
                },
                explanation=(
                    f"Агент рассчитывал на «{binary}», но команды нет в окружении. "
                    "Шаги уходили в ошибку из-за отсутствующего инструмента, а не из-за неверного решения."
                ),
            )
        )

    # (3) вызов отклонён по разрешениям
    denied = []
    for s in steps:
        if s.get("kind") != "tool_result" or not DENIED.search(s.get("text") or ""):
            continue
        call = None
        if s.get("resultOf"):
            call = next((x for x in steps if x["id"] == s["resultOf"]), None)
        denied.append({"result": s, "call": call})
    if len(denied) >= MIN_DENIALS:
        tools = sorted({d["call"].get("tool") for d in denied if d["call"] and d["call"].get("tool")})
        out.append(
            finding(
                "tool_permission_denied",
                severity=min(0.65, 0.35 + len(denied) * 0.05),
                title=(
                    f"{len(denied)} {plural(len(denied), ('вызов', 'вызова', 'вызовов'))} "
                    f"отклонено по разрешениям"
                ),
                step_ids=[d["result"]["id"] for d in denied][:12]
                + [d["call"]["id"] for d in denied if d["call"]][:12],
                metrics={"denials": len(denied), "tools": tools},
                evidence={
                    "tools": tools,
                    "resultStepIds": [d["result"]["id"] for d in denied][:12],
                    "lines": [d["result"].get("line") for d in denied][:12],
                    "snippet": snippet(denied[0]["result"].get("text")),
                    "commands": [
                        snippet((d["call"].get("args") or {}).get("command"), 90)
                        for d in denied[:5] if d["call"] and isinstance(d["call"].get("args"), dict)
                    ],
                },
                explanation=(
                    "Инструмент был нужен, но доступ к нему не разрешён: агент терял шаги на "
                    "попытках, которые не могли выполниться."
                ),
            )
        )

    return out
