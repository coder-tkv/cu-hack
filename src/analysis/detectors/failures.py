"""Падения инструментов и повторные попытки.

Различаем: (1) агент повторяет ровно тот же падающий вызов, (2) одна и та же ошибка
всплывает в разных вызовах, (3) общий фон ошибок, (4) сбои самого API.
"""

from __future__ import annotations

from collections import Counter

from .util import args_key, build_index, describe_args, error_signature, finding, plural, snippet


def detect_failures(steps: list[dict]) -> list[dict]:
    idx = build_index(steps)
    result_by_call = idx["resultByCall"]
    calls = [s for s in steps if s.get("kind") == "tool_call"]

    failed = []
    for c in calls:
        r = result_by_call.get(c["id"])
        if r and r.get("isError"):
            failed.append(
                {"call": c, "result": r, "key": args_key(c), "sig": error_signature(r.get("text"))}
            )

    out: list[dict] = []

    # (1) один и тот же падающий вызов повторяется
    by_key: dict[str, list[dict]] = {}
    for f in failed:
        by_key.setdefault(f["key"], []).append(f)
    for key, lst in by_key.items():
        if len(lst) < 2:
            continue
        same_sig = all(f["sig"] == lst[0]["sig"] for f in lst)
        tool = lst[0]["call"].get("tool") or "Инструмент"
        out.append(
            finding(
                "retry_loop",
                severity=min(0.9, 0.5 + (len(lst) - 2) * 0.1 + (0.15 if same_sig else 0)),
                title=(
                    f"{tool} падал {len(lst)} {plural(len(lst), ('раз', 'раза', 'раз'))}"
                    + (" с той же ошибкой" if same_sig else "")
                    + f": «{snippet(describe_args(lst[0]['call']), 70)}»"
                ),
                step_ids=[i for f in lst for i in (f["call"]["id"], f["result"]["id"])],
                metrics={"attempts": len(lst), "sameError": same_sig},
                evidence={
                    "tool": lst[0]["call"].get("tool"),
                    "key": key,
                    "argsPreview": describe_args(lst[0]["call"]),
                    "errorSnippet": snippet(lst[0]["result"].get("text")),
                    "callStepIds": [f["call"]["id"] for f in lst],
                    "lines": [f["call"].get("line") for f in lst],
                },
                explanation=(
                    "Повторная попытка того же вызова давала ту же ошибку — причина не была "
                    "устранена перед повтором."
                    if same_sig
                    else "Тот же вызов падал несколько раз с разными ошибками."
                ),
            )
        )

    # (2) одна ошибка проходит через разные вызовы
    by_sig: dict[str, list[dict]] = {}
    for f in failed:
        if f["sig"]:
            by_sig.setdefault(f["sig"], []).append(f)
    for sig, lst in by_sig.items():
        if len(lst) < 3:
            continue
        keys = {f["key"] for f in lst}
        if len(keys) < 2:
            continue  # это уже retry_loop
        out.append(
            finding(
                "repeated_error",
                severity=min(0.85, 0.45 + (len(lst) - 3) * 0.08),
                title=(
                    f"Одна и та же ошибка в {len(lst)} разных "
                    f"{plural(len(lst), ('вызове', 'вызовах', 'вызовах'))}: «{snippet(sig, 70)}»"
                ),
                step_ids=[i for f in lst for i in (f["call"]["id"], f["result"]["id"])][:24],
                metrics={"occurrences": len(lst), "distinctCalls": len(keys)},
                evidence={
                    "signature": sig,
                    "errorSnippet": snippet(lst[0]["result"].get("text")),
                    "callStepIds": [f["call"]["id"] for f in lst][:12],
                    "tools": sorted({f["call"].get("tool") or "?" for f in lst}),
                },
                explanation=(
                    "Агент менял подход, но упирался в одно и то же препятствие — "
                    "вероятно, не разобрался в его причине."
                ),
            )
        )

    # (3) общий фон: доля падений
    if len(calls) >= 10 and len(failed) >= 4:
        rate = len(failed) / len(calls)
        if rate >= 0.15:
            out.append(
                finding(
                    "high_failure_rate",
                    severity=min(0.7, 0.3 + rate),
                    title=(
                        f"Каждый {round(1 / rate)}-й вызов инструмента завершался ошибкой "
                        f"({len(failed)} из {len(calls)})"
                    ),
                    step_ids=[i for f in failed[:12] for i in (f["call"]["id"], f["result"]["id"])],
                    metrics={"failures": len(failed), "calls": len(calls), "rate": round(rate, 3)},
                    evidence={
                        "byTool": dict(Counter(f["call"].get("tool") or "?" for f in failed)),
                        "topErrors": [
                            {"error": e, "count": n}
                            for e, n in Counter(f["sig"] for f in failed if f["sig"]).most_common(3)
                        ],
                    },
                    explanation=(
                        "Высокая доля неудачных вызовов: значительная часть работы уходила "
                        "на исправление собственных попыток."
                    ),
                )
            )

    # (4) ошибки самого API — не вина агента, но объясняет потери времени
    api_errors = [s for s in steps if isinstance(s.get("raw"), str) and "api_error" in s["raw"]]
    if len(api_errors) >= 3:
        out.append(
            finding(
                "api_errors",
                severity=min(0.4, 0.15 + len(api_errors) * 0.02),
                title=f"{len(api_errors)} ошибок обращения к API модели",
                step_ids=[s["id"] for s in api_errors[:10]],
                metrics={"count": len(api_errors)},
                evidence={"snippet": snippet(api_errors[0].get("text"))},
                explanation="Сбои на стороне API: время сессии терялось не из-за решений агента.",
            )
        )

    return out
