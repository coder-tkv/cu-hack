"""Повторяющиеся вызовы инструмента.

Точные повторы (тот же ключ аргументов) и близкие (похожая команда).
Повтор после правки файла может быть законным — за это severity снижаем.
Подряд идущие повторы (между ними вообще ничего не делали) — наоборот, усиливаем.
"""

from __future__ import annotations

from .util import (
    MUTATING_TOOLS,
    plural,
    args_key,
    build_index,
    describe_args,
    error_signature,
    finding,
    jaccard,
    snippet,
    tokens_of,
)

WINDOW_CALLS = 10  # «рядом» = не дальше 10 вызовов инструментов
MIN_REPEATS = 3


def detect_repeated_calls(
    steps: list[dict],
    window: int = WINDOW_CALLS,
    min_repeats: int = MIN_REPEATS,
    similarity: float = 0.7,
) -> list[dict]:
    idx = build_index(steps)
    result_by_call = idx["resultByCall"]
    calls = [s for s in steps if s.get("kind") == "tool_call"]
    if len(calls) < min_repeats:
        return []

    ordinal = {c["id"]: i for i, c in enumerate(calls)}

    groups: dict[str, list[dict]] = {}
    for c in calls:
        groups.setdefault(args_key(c), []).append(c)

    out: list[dict] = []
    covered: set[int] = set()

    for key, lst in groups.items():
        if len(lst) < min_repeats:
            continue
        for cluster in _cluster_by_window(lst, ordinal, window):
            if len(cluster) < min_repeats:
                continue
            covered.update(c["id"] for c in cluster)
            out.append(_make("repeated_call", cluster, key, steps, result_by_call, ordinal))

    # близкие, но не идентичные команды Bash — типичный перебор вариантов
    bash = [c for c in calls if c.get("tool") == "Bash" and c["id"] not in covered]
    for cluster in _cluster_by_similarity(bash, ordinal, window, similarity):
        if len(cluster) < min_repeats:
            continue
        out.append(_make("similar_call", cluster, args_key(cluster[0]), steps, result_by_call, ordinal))

    return out


def _cluster_by_window(lst: list[dict], ordinal: dict[int, int], window: int) -> list[list[dict]]:
    clusters: list[list[dict]] = []
    cur = [lst[0]]
    for step in lst[1:]:
        if ordinal[step["id"]] - ordinal[cur[-1]["id"]] <= window:
            cur.append(step)
        else:
            clusters.append(cur)
            cur = [step]
    clusters.append(cur)
    return clusters


def _cluster_by_similarity(lst: list[dict], ordinal: dict[int, int], window: int, threshold: float) -> list[list[dict]]:
    clusters: list[list[dict]] = []
    used: set[int] = set()
    for i, seed_step in enumerate(lst):
        if seed_step["id"] in used:
            continue
        seed = tokens_of((seed_step.get("args") or {}).get("command", ""))
        if len(seed) < 2:
            continue
        cluster = [seed_step]
        for other in lst[i + 1 :]:
            if other["id"] in used:
                continue
            if ordinal[other["id"]] - ordinal[cluster[-1]["id"]] > window:
                break
            sim = jaccard(seed, tokens_of((other.get("args") or {}).get("command", "")))
            if threshold <= sim < 1:
                cluster.append(other)
        if len(cluster) >= 2:
            used.update(c["id"] for c in cluster)
            clusters.append(cluster)
    return clusters


def _make(ftype: str, cluster: list[dict], key: str, steps: list[dict], result_by_call: dict, ordinal: dict) -> dict:
    first, last = cluster[0], cluster[-1]

    mutating_between = 0
    other_calls_between = 0
    for s in steps:
        if not (first["id"] < s["id"] < last["id"]):
            continue
        if s.get("kind") != "tool_call":
            continue
        if s["id"] in {c["id"] for c in cluster}:
            continue
        other_calls_between += 1
        if s.get("tool") in MUTATING_TOOLS:
            mutating_between += 1

    # повторы «вплотную»: между ними не было ни одного другого вызова
    back_to_back = 0
    for a, b in zip(cluster, cluster[1:]):
        if ordinal[b["id"]] - ordinal[a["id"]] == 1:
            back_to_back += 1

    results = [result_by_call.get(c["id"]) for c in cluster]
    texts = [(r.get("text") or "") if r else "" for r in results]
    sigs = [error_signature(r.get("text")) if r else "" for r in results]
    errors = sum(1 for r in results if r and r.get("isError"))
    results_identical = len(texts) > 1 and all(t == texts[0] != "" for t in texts)
    nonempty_sigs = [s for s in sigs if s]
    errors_identical = errors >= 2 and bool(nonempty_sigs) and all(s == nonempty_sigs[0] for s in nonempty_sigs)

    sev = 0.4 + min(0.25, (len(cluster) - 3) * 0.07)
    if mutating_between == 0:
        sev += 0.15  # ничего не менялось, а вызов повторён
    else:
        sev -= 0.10  # между повторами правились файлы — может быть нормой
    if back_to_back:
        sev += 0.05 * back_to_back
    if results_identical:
        sev += 0.15
    if errors_identical:
        sev += 0.15
    if ftype == "similar_call":
        sev -= 0.10

    what = describe_args(first)
    tool = first.get("tool") or "инструмент"
    if ftype == "repeated_call":
        tail = " без изменений между попытками" if mutating_between == 0 else ""
        times = plural(len(cluster), ("раз", "раза", "раз"))
        title = f"{tool}: «{what}» вызван {len(cluster)} {times}{tail}"
        explanation = (
            "Один и тот же вызов повторён, между попытками агент ничего не менял — "
            "предыдущий результат не был учтён."
            if mutating_between == 0
            else "Вызов повторён несколько раз; между попытками правились файлы, "
            "поэтому часть повторов может быть оправданной."
        )
    else:
        calls_word = plural(len(cluster), ("близкий по смыслу вызов", "близких по смыслу вызова", "близких по смыслу вызовов"))
        title = f"{tool}: {len(cluster)} {calls_word} («{what}»)"
        explanation = (
            "Несколько близких вариантов одной команды подряд — похоже на перебор вариантов "
            "вместо проверки причины."
        )

    step_ids: list[int] = []
    for c in cluster:
        step_ids.append(c["id"])
        r = result_by_call.get(c["id"])
        if r:
            step_ids.append(r["id"])

    evidence = {
        "tool": first.get("tool"),
        "key": key,
        "argsPreview": what,
        "callStepIds": [c["id"] for c in cluster],
        "lines": [c.get("line") for c in cluster],
        "resultsIdentical": results_identical,
        "errorsIdentical": errors_identical,
        "resultSnippet": snippet(next((t for t in texts if t), None)),
    }
    if ftype == "similar_call":
        evidence["variants"] = [describe_args(c) for c in cluster]

    return finding(
        ftype,
        severity=sev,
        title=title,
        step_ids=step_ids,
        metrics={
            "repeats": len(cluster),
            "mutatingBetween": mutating_between,
            "otherCallsBetween": other_calls_between,
            "backToBack": back_to_back,
            "errors": errors,
            "spanCalls": ordinal[last["id"]] - ordinal[first["id"]] + 1,
        },
        evidence=evidence,
        explanation=explanation,
    )
