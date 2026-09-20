"""Conservative detectors: exact consecutive repeats and broad file reading."""

from dataclasses import dataclass
from itertools import groupby

from .schemas import Candidate, Evidence, Fact, ObservedAlternative


@dataclass
class Event:
    evidence: Evidence
    segment: int
    scope: tuple
    task_context: str | None = None
    call_id: str | None = None
    tool_name: str | None = None
    args_hash: str | None = None
    result_hash: str | None = None
    is_error: bool | None = None
    file_hash: str | None = None
    search_utility: str | None = None


def detect(events: list[Event], *, damaged: bool = False) -> list[Candidate]:
    positions = {e.evidence.step_id: i for i, e in enumerate(events)}
    calls = [event for event in events if event.evidence.kind == "tool_call"]
    results = {}
    conflicting_results = set()
    call_counts = {}
    for call in calls:
        if call.call_id:
            key = (call.scope, call.call_id)
            call_counts[key] = call_counts.get(key, 0) + 1
    for event in events:
        if event.evidence.kind == "tool_result" and event.call_id:
            key = (event.scope, event.call_id)
            if key in results:
                conflicting_results.add(key)
            results[key] = event

    def result_for(call):
        key = (call.scope, call.call_id)
        result = results.get(key)
        if (not call.call_id or key in conflicting_results or call_counts.get(key) != 1 or
                not result or result.evidence.source_line < call.evidence.source_line):
            return None
        return result

    def candidate(kind, selected_calls, extra=(), group_size=None):
        evidence = []
        for call in [*selected_calls, *extra]:
            evidence.append(call.evidence)
            result = result_for(call)
            if result:
                evidence.append(result.evidence)
        evidence = list({step.step_id: step for step in evidence}.values())
        # Keep the agent's local rationale, e.g. why polling/retrying is expected.
        first_pos = positions[selected_calls[0].evidence.step_id]
        last_pos = positions[result_for(selected_calls[-1]).evidence.step_id]
        start, end = first_pos, last_pos + 1
        while start > 0 and events[start - 1].evidence.kind == "assistant_text":
            start -= 1
        while end < len(events) and events[end].evidence.kind == "assistant_text":
            end += 1
        context = [e.evidence for e in events[start:end]
                   if e.evidence.kind == "assistant_text" and e.scope == selected_calls[0].scope
                   and e.segment == selected_calls[0].segment]
        omitted_context = len(context) > 20
        evidence.extend(context[:20])
        evidence.sort(key=lambda e: positions[e.step_id])
        refs = [e.step_id for c in selected_calls for e in [c.evidence, result_for(c).evidence]]
        truncated = (any("[TRUNCATED]" in step.text for step in evidence) or
                     "[TRUNCATED]" in (selected_calls[0].task_context or ""))
        limits = ["Доступен фрагмент истории; скрытое состояние проекта неизвестно."]
        if damaged:
            limits.append("Часть входных данных не разобрана или неоднозначна.")
        if truncated:
            limits.append("Некоторые тексты усечены; полное содержание не видно.")
        if omitted_context:
            limits.append("Часть пояснений агента не поместилась в эпизод.")
        if group_size and group_size > len(selected_calls):
            limits.append("Длинная серия разбита на перекрывающиеся окна; число ниже относится только к этому окну.")
        n = len(selected_calls)
        if kind == "repeated_tool_call":
            facts = [Fact(fact_id="same_calls", text=f"В этом фрагменте {n} последовательных вызовов одного инструмента имеют одинаковые аргументы.", evidence_step_ids=[c.evidence.step_id for c in selected_calls]),
                     Fact(fact_id="same_results", text=f"Для этих {n} вызовов в логе записаны одинаковые результаты.", evidence_step_ids=[result_for(c).evidence.step_id for c in selected_calls])]
            failures = all(result_for(c).is_error is True for c in selected_calls)
            if failures:
                facts.append(Fact(fact_id="explicit_errors", text=f"Все {n} результатов явно помечены is_error=true.", evidence_step_ids=[result_for(c).evidence.step_id for c in selected_calls]))
            limits.append("Повторы могут быть оправданы опросом статуса или временным сбоем; одинаковый результат сам по себе не доказывает отсутствие прогресса.")
            priority = "high" if failures else "medium"
        else:
            facts = [Fact(fact_id="multiple_reads", text=f"В этом фрагменте выполнено {n} последовательных вызовов Read для нескольких разных файлов.", evidence_step_ids=refs)]
            limits.append("Не установлено, были ли эти чтения лишними или могла ли одна утилита дать эквивалентный результат.")
            priority = "low"
        alternatives = [ObservedAlternative(alternative_id=f"observed-{c.evidence.step_id}",
                            tool_name=c.search_utility,
                            evidence_step_ids=[c.evidence.step_id, result_for(c).evidence.step_id]) for c in extra]
        return Candidate(candidate_id=f"{kind}-{selected_calls[0].evidence.step_id}",
            kind=kind, priority=priority, task_context=selected_calls[0].task_context,
            facts=facts, evidence=evidence,
            alternatives=alternatives,
            context_complete=not damaged and not truncated and not omitted_context
                             and selected_calls[0].task_context is not None,
            limitations=limits)

    candidates, grouped_error_steps = [], set()
    # Every intervening tool call breaks the run, including a write or diagnostic.
    def repeat_key(call):
        result = result_for(call)
        if (not result or call.segment != result.segment or not call.args_hash or
                not call.tool_name or not result.result_hash):
            return ("unpaired", call.evidence.step_id)
        return (call.scope, call.segment, call.tool_name, call.args_hash,
                result.result_hash, result.is_error)

    for _, run in groupby(calls, key=repeat_key):
        run = list(run)
        if len(run) < 3:
            continue
        # Only completed sequential attempts; concurrent calls aren't retries.
        if any(result_for(a).evidence.source_line >= b.evidence.source_line for a, b in zip(run, run[1:])):
            continue
        for start in range(0, len(run) - 2, 6):
            window = run[start:start + 8]
            candidates.append(candidate("repeated_tool_call", window, group_size=len(run)))
            grouped_error_steps.update(result_for(c).evidence.step_id for c in window)

    for _, run in groupby(calls, key=lambda c: (c.scope, c.segment, "Read")
                         if c.tool_name == "Read" and c.file_hash and result_for(c)
                         and result_for(c).is_error is not True and result_for(c).segment == c.segment
                         else ("other", c.evidence.step_id)):
        run = list(run)
        if len(run) < 3 or any(c.tool_name != "Read" for c in run):
            continue
        for start in range(0, len(run) - 2, 6):
            window = run[start:start + 8]
            if len({c.file_hash for c in window}) < 3:
                continue
            first = window[0]
            prior = [c for c in calls if c.search_utility and c.scope == first.scope and
                     c.segment == first.segment and
                     c.evidence.source_line < first.evidence.source_line and result_for(c) and
                     result_for(c).is_error is False and
                     result_for(c).evidence.source_line < first.evidence.source_line][-2:]
            candidates.append(candidate("read_many_files", window, prior, len(run)))

    call_for_result = {id(result_for(c)): c for c in calls if result_for(c)}
    for result in events:
        if result.evidence.kind != "tool_result" or result.is_error is not True:
            continue
        if result.evidence.step_id in grouped_error_steps:
            continue
        call = call_for_result.get(id(result))
        index = positions[result.evidence.step_id]
        context = [e.evidence for e in events[max(0, index - 2):index + 3]
                   if e.scope == result.scope and e.segment == result.segment]
        evidence = list({e.step_id: e for e in ([call.evidence] if call else []) + context}.values())
        limits = ["Одиночная ошибка не доказывает неэффективность агента."]
        if not call:
            limits.append("Связанный вызов инструмента отсутствует или неоднозначен.")
        if damaged:
            limits.append("Часть входных данных не разобрана или неоднозначна.")
        if any("[TRUNCATED]" in e.text for e in evidence):
            limits.append("Часть контекста усечена.")
        candidates.append(Candidate(candidate_id=f"error-{result.evidence.step_id}",
            kind="explicit_tool_error", task_context=result.task_context,
            facts=[Fact(fact_id="explicit_error",
            text="Результат инструмента явно помечен is_error=true.",
            evidence_step_ids=[result.evidence.step_id])], evidence=evidence, limitations=limits))
    rank = {"high": 0, "medium": 1, "low": 2}
    return sorted(candidates, key=lambda c: rank[c.priority])
