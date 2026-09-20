"""Склейка однотипных находок по одной цели.

Девять отдельных находок «screenshot вызван N раз» — это одна проблема в девяти
местах сессии, а не девять проблем. Склеиваем их в одну находку со списком
эпизодов: человек видит проблему целиком, а ссылки на шаги каждого эпизода
остаются на месте и остаются проверяемыми.

Склеиваем только то, у чего есть общая цель: один и тот же вызов, одна и та же
падающая команда, участки одного вида. Находки уровня сессии (доля падений,
прерывания, простои) и так по одной на сессию.
"""

from __future__ import annotations

from .detectors.util import plural
from .severity import BAND_ORDER, sort_key, rules_for

# тип находки -> как достать её «цель»
MERGE_BY_KEY = ("repeated_call", "similar_call", "retry_loop")
MERGE_BY_TYPE = ("token_hotspot", "spend_without_changes")
# Эти находки по разным целям (разные файлы, разные указания) склеиваем, только
# когда их много: на коротком логе три отдельные строки полезнее одной общей,
# на суточной сессии 34 строки про 34 файла читать невозможно.
MERGE_BY_TYPE_IF_MANY = {
    "file_churn": 4, "rewrite_loop": 4, "repeated_instruction": 4,
    "bash_instead_of_tool": 3, "missing_cli": 3,
}

MAX_STEP_IDS = 30  # столько ссылок держим в самой находке
MAX_EPISODES = 50  # эпизоды несут свои доказательства, поэтому держим почти все


def merge_key(f: dict) -> tuple | None:
    t = f.get("type")
    if t in MERGE_BY_KEY:
        key = (f.get("evidence") or {}).get("key")
        return (t, key) if key else None
    if t in MERGE_BY_TYPE or t in MERGE_BY_TYPE_IF_MANY:
        return (t, "session")
    return None


def merge_findings(findings: list[dict]) -> list[dict]:
    groups: dict[tuple, list[dict]] = {}
    out: list[dict] = []
    for f in findings:
        k = merge_key(f)
        if k is None:
            out.append(f)
        else:
            groups.setdefault(k, []).append(f)

    for (ftype, _), group in groups.items():
        threshold = MERGE_BY_TYPE_IF_MANY.get(ftype)
        if len(group) == 1 or (threshold and len(group) < threshold):
            out.extend(group)
        else:
            out.append(_merge(group))

    out.sort(key=sort_key)
    return out


def _merge(group: list[dict]) -> dict:
    """Самый значимый эпизод становится основой, остальные — его эпизодами."""
    group = sorted(group, key=sort_key)
    lead = dict(group[0])
    episodes = []
    step_ids: list[int] = []

    for f in group:
        ev = f.get("evidence") or {}
        # эпизод хранит собственные доказательства: каждая его строчка
        # остаётся проверяемой по шагам отдельно от остальных
        episodes.append({
            "title": f.get("title"),
            "stepIds": f.get("stepIds", []),
            "callStepIds": ev.get("callStepIds") or f.get("stepIds", [])[:1],
            "lines": ev.get("lines"),
            "severity": f.get("severity"),
            "severityBand": f.get("severityBand"),
            "severityRules": f.get("severityRules", []),
            "metrics": f.get("metrics", {}),
            "evidence": ev,
        })
        step_ids.extend(f.get("stepIds", []))

    lead["episodes"] = episodes[:MAX_EPISODES]
    lead["episodeCount"] = len(episodes)
    lead["episodesTruncated"] = len(episodes) > MAX_EPISODES
    lead["stepIds"] = sorted(set(step_ids))[:MAX_STEP_IDS]
    lead["mergedFrom"] = [f.get("id") for f in group if f.get("id")]

    metrics = dict(lead.get("metrics") or {})
    metrics["episodes"] = len(episodes)
    for field in ("repeats", "attempts", "mutatingBetween", "errors", "backToBack", "compactionsBetween"):
        values = [e["metrics"].get(field) for e in episodes if isinstance(e["metrics"].get(field), int)]
        if values:
            metrics[field] = sum(values)
    for field in ("edits", "writes", "occurrences", "shareOfSession", "billableTokens", "calls", "fileEdits"):
        values = [e["metrics"].get(field) for e in episodes if isinstance(e["metrics"].get(field), (int, float))]
        if values:
            metrics[field] = round(sum(values), 3)
    lead["metrics"] = metrics

    evidence = dict(lead.get("evidence") or {})
    calls = []
    for e in episodes:
        calls.extend(e["callStepIds"] or [])
    evidence["callStepIds"] = sorted(set(calls))
    evidence["episodeStepIds"] = [e["callStepIds"] for e in episodes[:MAX_EPISODES]]
    lead["evidence"] = evidence

    lead["title"] = _title(lead, len(episodes))
    lead["severity"] = min(1.0, max(f["severity"] for f in group) + 0.03 * (len(episodes) - 1))
    lead["severityBand"] = min((f["severityBand"] for f in group), key=lambda b: BAND_ORDER.get(b, 3))
    # правила пересчитываем по суммарным метрикам: иначе заголовок говорит про 142
    # повтора, а объяснение — про девять из сильнейшего эпизода
    rules = rules_for(lead)
    rules.append(f"эпизодов в сессии: {len(episodes)}")
    lead["severityRules"] = rules
    lead["explanation"] = (lead.get("explanation") or "") + (
        f" Такое повторялось в {len(episodes)} местах сессии — ниже перечислены все эпизоды."
    )
    return lead


def _title(lead: dict, episodes: int) -> str:
    t = lead.get("type")
    m = lead.get("metrics") or {}
    ev = lead.get("evidence") or {}
    what = ev.get("argsPreview") or ev.get("signature") or ""
    tool = ev.get("tool") or "инструмент"

    eps = f"{episodes} {plural(episodes, ('эпизоде', 'эпизодах', 'эпизодах'))} сессии"
    files = plural(episodes, ("файл", "файла", "файлов"))

    if t in ("repeated_call", "similar_call"):
        n = m.get("repeats") or 0
        tail = " без изменений между попытками" if m.get("mutatingBetween") == 0 else ""
        return (f"{tool}: «{what}» — {n} {plural(n, ('повтор', 'повтора', 'повторов'))} "
                f"в {eps}{tail}")
    if t == "retry_loop":
        n = m.get("attempts") or 0
        return f"{tool}: «{what}» падал {n} {plural(n, ('раз', 'раза', 'раз'))} в {eps}"
    if t == "token_hotspot":
        return (f"{episodes} {plural(episodes, ('участок', 'участка', 'участков'))} сессии съели "
                f"{round((m.get('shareOfSession') or 0) * 100)}% расхода токенов")
    if t == "spend_without_changes":
        return (f"{round((m.get('shareOfSession') or 0) * 100)}% расхода токенов на {episodes} "
                f"{plural(episodes, ('участке', 'участках', 'участках'))}, где не изменён ни один файл")
    if t == "file_churn":
        n = m.get("edits") or 0
        return (f"{episodes} {files} правились по четыре и более раз "
                f"(всего {n} {plural(n, ('правка', 'правки', 'правок'))})")
    if t == "rewrite_loop":
        n = m.get("writes") or 0
        return (f"{episodes} {files} перезаписаны целиком по нескольку раз "
                f"(всего {n} {plural(n, ('перезапись', 'перезаписи', 'перезаписей'))})")
    if t == "bash_instead_of_tool":
        n = m.get("occurrences") or 0
        tools = sorted({(e.get("evidence") or {}).get("tool") for e in lead.get("episodes") or []} - {None})
        return (f"{n} {plural(n, ('обращение', 'обращения', 'обращений'))} через Bash к тому, "
                f"для чего есть готовые инструменты ({', '.join(tools)})")
    if t == "missing_cli":
        bins = [(e.get("evidence") or {}).get("binary") for e in lead.get("episodes") or []]
        bins = [b for b in bins if b]
        return f"В окружении не хватает команд: {', '.join(bins[:6])}"
    if t == "repeated_instruction":
        return (f"Человеку приходилось повторять указания: {episodes} "
                f"{plural(episodes, ('случай', 'случая', 'случаев'))} за сессию")
    return lead.get("title") or ""
