"""Правки файлов: откаты и перепахивание одного файла.

Откат — когда более поздняя правка возвращает текст, который прошлая правка убрала
(new_string == прежний old_string). Данные берём из args вызова, а если их нет —
из toolUseResult, где Claude Code хранит oldString/newString/filePath.
"""

from __future__ import annotations

from collections import defaultdict

from .util import build_index, finding, norm, snippet


def _edit_info(call: dict, result: dict | None) -> dict | None:
    a = call.get("args") if isinstance(call.get("args"), dict) else {}
    r = result.get("result") if result and isinstance(result.get("result"), dict) else {}
    path = a.get("file_path") or r.get("filePath")
    old = a.get("old_string") if isinstance(a.get("old_string"), str) else r.get("oldString")
    new = a.get("new_string") if isinstance(a.get("new_string"), str) else r.get("newString")
    if not isinstance(path, str):
        return None
    return {
        "path": path,
        "old": old if isinstance(old, str) else None,
        "new": new if isinstance(new, str) else None,
    }


def detect_edit_churn(steps: list[dict]) -> list[dict]:
    idx = build_index(steps)
    result_by_call = idx["resultByCall"]

    edits = []
    writes: dict[str, list[dict]] = defaultdict(list)
    for s in steps:
        if s.get("kind") != "tool_call":
            continue
        tool = s.get("tool")
        if tool in ("Edit", "MultiEdit"):
            info = _edit_info(s, result_by_call.get(s["id"]))
            if info:
                edits.append({"step": s, **info})
        elif tool == "Write":
            a = s.get("args") if isinstance(s.get("args"), dict) else {}
            p = a.get("file_path")
            if isinstance(p, str):
                writes[p].append(s)

    out: list[dict] = []

    # (1) откат: позже вернули то, что раньше убрали
    for i, later in enumerate(edits):
        if not later["new"]:
            continue
        for earlier in edits[:i]:
            if earlier["path"] != later["path"] or not earlier["old"]:
                continue
            if norm(earlier["old"]) and norm(earlier["old"]) == norm(later["new"]):
                out.append(
                    finding(
                        "edit_revert",
                        severity=0.7,
                        title=f"Правка в {_short(later['path'])} отменена позже в той же сессии",
                        step_ids=[earlier["step"]["id"], later["step"]["id"]],
                        metrics={"filePath": later["path"]},
                        evidence={
                            "filePath": later["path"],
                            "editStepId": earlier["step"]["id"],
                            "revertStepId": later["step"]["id"],
                            "lines": [earlier["step"].get("line"), later["step"].get("line")],
                            "restoredText": snippet(later["new"], 300),
                            "replacedBy": snippet(earlier["new"], 300),
                        },
                        explanation=(
                            "Более поздняя правка вернула прежний текст: работа между этими шагами "
                            "не дала результата. Осознанный откат неудачной гипотезы выглядит так же."
                        ),
                    )
                )
                break

    # (2) один файл правился много раз
    by_path: dict[str, list[dict]] = defaultdict(list)
    for e in edits:
        by_path[e["path"]].append(e["step"])
    for path, lst in by_path.items():
        if len(lst) < 4:
            continue
        out.append(
            finding(
                "file_churn",
                severity=min(0.75, 0.35 + (len(lst) - 4) * 0.05),
                title=f"{_short(path)} правился {len(lst)} раз за сессию",
                step_ids=[s["id"] for s in lst][:14],
                metrics={"edits": len(lst), "filePath": path},
                evidence={
                    "filePath": path,
                    "editStepIds": [s["id"] for s in lst],
                    "lines": [s.get("line") for s in lst],
                },
                explanation=(
                    "Один файл переписывался много раз — обычно признак того, что решение "
                    "подбиралось по частям вместо одного продуманного изменения."
                ),
            )
        )

    # (3) файл перезаписан целиком несколько раз
    for path, lst in writes.items():
        if len(lst) < 2:
            continue
        out.append(
            finding(
                "rewrite_loop",
                severity=min(0.7, 0.4 + (len(lst) - 2) * 0.1),
                title=f"{_short(path)} перезаписан целиком {len(lst)} раза",
                step_ids=[s["id"] for s in lst][:10],
                metrics={"writes": len(lst), "filePath": path},
                evidence={
                    "filePath": path,
                    "writeStepIds": [s["id"] for s in lst],
                    "lines": [s.get("line") for s in lst],
                },
                explanation=(
                    "Полная перезапись файла несколько раз: предыдущая версия отбрасывалась, "
                    "а не правилась."
                ),
            )
        )

    return out


def _short(path: str) -> str:
    parts = path.rstrip("/").split("/")
    return "/".join(parts[-2:]) if len(parts) > 1 else path
