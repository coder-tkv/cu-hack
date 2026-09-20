"""Правки файлов: откаты и перепахивание одного файла.

Откат — когда более поздняя правка возвращает текст, который прошлая правка убрала
(new_string == прежний old_string). Данные берём из args вызова, а если их нет —
из toolUseResult, где Claude Code хранит oldString/newString/filePath.
MultiEdit держит правки в массиве edits — разбираем и его.

Поиск откатов идёт за один проход по индексу: наивное сравнение всех пар
на логе с тысячами правок одного файла занимало секунды.
"""

from __future__ import annotations

from collections import defaultdict

from .util import build_index, finding, norm, snippet

MIN_EDITS_FOR_CHURN = 4
MIN_WRITES_FOR_REWRITE = 2


def _edit_pairs(call: dict, result: dict | None) -> list[dict]:
    """Все пары (old, new) одного вызова. Для Edit — одна, для MultiEdit — сколько есть."""
    a = call.get("args") if isinstance(call.get("args"), dict) else {}
    r = result.get("result") if result and isinstance(result.get("result"), dict) else {}
    path = a.get("file_path") or r.get("filePath")
    if not isinstance(path, str):
        return []

    raw_edits = a.get("edits") if isinstance(a.get("edits"), list) else r.get("edits")
    pairs: list[dict] = []
    if isinstance(raw_edits, list):
        for e in raw_edits:
            if isinstance(e, dict):
                pairs.append({"old": e.get("old_string") or e.get("oldString"),
                              "new": e.get("new_string") or e.get("newString")})
    if not pairs:
        pairs.append({
            "old": a.get("old_string") if isinstance(a.get("old_string"), str) else r.get("oldString"),
            "new": a.get("new_string") if isinstance(a.get("new_string"), str) else r.get("newString"),
        })

    out = []
    for p in pairs:
        old = p["old"] if isinstance(p["old"], str) else None
        new = p["new"] if isinstance(p["new"], str) else None
        out.append({
            "path": path,
            "old": old,
            "new": new,
            "oldNorm": norm(old) if old else "",
            "newNorm": norm(new) if new else "",
        })
    return out


def detect_edit_churn(steps: list[dict]) -> list[dict]:
    idx = build_index(steps)
    result_by_call = idx["resultByCall"]

    edits: list[dict] = []
    writes: dict[str, list[dict]] = defaultdict(list)
    for s in steps:
        if s.get("kind") != "tool_call":
            continue
        tool = s.get("tool")
        if tool in ("Edit", "MultiEdit"):
            for pair in _edit_pairs(s, result_by_call.get(s["id"])):
                edits.append({"step": s, **pair})
        elif tool == "Write":
            a = s.get("args") if isinstance(s.get("args"), dict) else {}
            p = a.get("file_path")
            if isinstance(p, str):
                writes[p].append(s)

    out: list[dict] = []

    # (1) откат: позже вернули то, что раньше убрали.
    # Индекс (файл, убранный текст) -> первая такая правка; один проход вместо сравнения всех пар.
    removed: dict[tuple[str, str], dict] = {}
    reported: set[tuple[int, int]] = set()
    for e in edits:
        if e["newNorm"]:
            earlier = removed.get((e["path"], e["newNorm"]))
            if earlier and earlier["step"]["id"] != e["step"]["id"]:
                key = (earlier["step"]["id"], e["step"]["id"])
                if key not in reported:
                    reported.add(key)
                    out.append(
                        finding(
                            "edit_revert",
                            severity=0.7,
                            title=f"Правка в {_short(e['path'])} отменена позже в той же сессии",
                            step_ids=[earlier["step"]["id"], e["step"]["id"]],
                            metrics={"filePath": e["path"]},
                            evidence={
                                "filePath": e["path"],
                                "editStepId": earlier["step"]["id"],
                                "revertStepId": e["step"]["id"],
                                "lines": [earlier["step"].get("line"), e["step"].get("line")],
                                "restoredText": snippet(e["new"], 300),
                                "replacedBy": snippet(earlier["new"], 300),
                            },
                            explanation=(
                                "Более поздняя правка вернула прежний текст: работа между этими шагами "
                                "не дала результата. Осознанный откат неудачной гипотезы выглядит так же."
                            ),
                        )
                    )
        if e["oldNorm"]:
            removed.setdefault((e["path"], e["oldNorm"]), e)

    # (2) один файл правился много раз (считаем вызовы, а не отдельные куски MultiEdit)
    by_path: dict[str, list[dict]] = defaultdict(list)
    for e in edits:
        lst = by_path[e["path"]]
        if not lst or lst[-1]["id"] != e["step"]["id"]:
            lst.append(e["step"])
    for path, lst in by_path.items():
        if len(lst) < MIN_EDITS_FOR_CHURN:
            continue
        out.append(
            finding(
                "file_churn",
                severity=min(0.75, 0.35 + (len(lst) - MIN_EDITS_FOR_CHURN) * 0.05),
                title=f"{_short(path)} правился {len(lst)} раз за сессию",
                step_ids=[s["id"] for s in lst][:14],
                metrics={"edits": len(lst), "filePath": path},
                evidence={
                    "filePath": path,
                    "editStepIds": [s["id"] for s in lst][:40],
                    "lines": [s.get("line") for s in lst][:40],
                },
                explanation=(
                    "Один файл переписывался много раз — обычно признак того, что решение "
                    "подбиралось по частям вместо одного продуманного изменения."
                ),
            )
        )

    # (3) файл перезаписан целиком несколько раз
    for path, lst in writes.items():
        if len(lst) < MIN_WRITES_FOR_REWRITE:
            continue
        out.append(
            finding(
                "rewrite_loop",
                severity=min(0.7, 0.4 + (len(lst) - MIN_WRITES_FOR_REWRITE) * 0.1),
                title=f"{_short(path)} перезаписан целиком {len(lst)} раза",
                step_ids=[s["id"] for s in lst][:10],
                metrics={"writes": len(lst), "filePath": path},
                evidence={
                    "filePath": path,
                    "writeStepIds": [s["id"] for s in lst][:20],
                    "lines": [s.get("line") for s in lst][:20],
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
