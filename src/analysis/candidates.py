"""Мост к общему контракту: находка детектора -> Candidate из schemas/findings.py.

Контракт (docs/04) требует от Бек-2 именно Candidate: закрытый список kind,
полные step_id, плоский facts, evidence_strength, limitations. severity и rank
детектор не заполняет — это делает ranking.py.

Наши детекторы находят больше видов проблем, чем разрешает закрытый список.
Те, для которых вида нет, возвращаются отдельным списком с предложенным kind —
контракт расширяется по договорённости, молча подменять вид нельзя.
"""

from __future__ import annotations

from typing import Callable

# наш тип находки -> kind из общего контракта
KIND_MAP = {
    "repeated_call": "repeated_tool_call",
    "similar_call": "repeated_tool_call",
    "retry_loop": "repeated_failed_tool",
    "repeated_error": "failure_chain",
    "high_failure_rate": "failure_chain",
    "human_corrections": "human_intervention",
    "interruptions": "human_intervention",
    "repeated_instruction": "human_intervention",
    "edit_revert": "reverted_edit",
    "idle_gaps": "long_gap",
    "slow_tool_calls": "long_gap",
}

# для этих вида в контракте нет — предлагаем добавить
PROPOSED_KINDS = {
    "token_hotspot": "expensive_segment",
    "spend_without_changes": "spend_without_progress",
    "file_churn": "file_churn",
    "rewrite_loop": "file_rewrite_loop",
    "api_errors": "environment_failure",
    "bash_instead_of_tool": "tool_underuse",
    "missing_cli": "missing_tool",
    "tool_permission_denied": "tool_denied",
}

DETECTOR_VERSIONS = {
    "repeated": "repeats-v2",
    "failures": "failures-v2",
    "tokens": "tokens-v1",
    "edits": "edits-v2",
    "human": "interventions-v1",
    "timing": "timing-v1",
    "tools": "tools-v1",
}


def to_candidates(
    findings: list[dict],
    step_id: Callable[[object], str] = str,
) -> tuple[list[dict], list[dict]]:
    """Возвращает (candidates, unmapped).

    step_id — как превратить наш идентификатор шага в полный step_id контракта.
    Пока парсер Бек-1 не подключён, годится str; потом сюда передаётся его карта.
    """
    candidates: list[dict] = []
    unmapped: list[dict] = []

    for f in findings:
        kind = KIND_MAP.get(f.get("type"))
        facts = _facts(f)
        item = {
            "candidate_id": f"c_{len(candidates) + len(unmapped) + 1:03d}",
            "kind": kind or PROPOSED_KINDS.get(f.get("type"), "unknown"),
            "evidence_step_ids": [step_id(i) for i in f.get("stepIds", [])],
            "facts": facts,
            "detector_version": DETECTOR_VERSIONS.get(f.get("detector"), "unknown"),
            "evidence_strength": f.get("evidenceStrength", "indirect"),
            "limitations": list(f.get("limitations") or []),
            # severity и rank проставит ranking.py, не детектор
            "severity": None,
            "rank": None,
        }
        if kind:
            candidates.append(item)
        else:
            item["proposedKind"] = PROPOSED_KINDS.get(f.get("type"))
            item["ourType"] = f.get("type")
            unmapped.append(item)

    return candidates, unmapped


def _facts(f: dict) -> dict:
    """Плоский JSON-совместимый dict: только числа и строки, посчитанные кодом."""
    out: dict = {"fact_text": f.get("fact"), "our_type": f.get("type")}
    for k, v in (f.get("metrics") or {}).items():
        if isinstance(v, (int, float, bool, str)) or v is None:
            out[k] = v
        elif isinstance(v, list) and all(isinstance(x, (int, float, str)) for x in v):
            out[k] = ", ".join(str(x) for x in v[:8])
    ev = f.get("evidence") or {}
    for k in ("tool", "argsPreview", "filePath", "signature", "errorSnippet", "category", "binary"):
        if isinstance(ev.get(k), str):
            out[k] = ev[k]
    if f.get("episodeCount"):
        out["episodes"] = f["episodeCount"]
    return out
