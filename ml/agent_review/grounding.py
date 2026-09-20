"""Validate literal evidence; render factual prose from backend facts only."""

from .schemas import Candidate, Judgment, ModelDecision


class GroundingError(ValueError):
    """Stable, non-sensitive rejection reason."""


def validate_decision(candidate: Candidate, decision: ModelDecision) -> None:
    if decision.candidate_id != candidate.candidate_id:
        raise GroundingError("unknown_candidate_id")
    facts = {f.fact_id: f for f in candidate.facts}
    ids = decision.fact_ids
    if not ids or len(ids) != len(set(ids)) or not set(ids) <= facts.keys():
        raise GroundingError("invalid_fact_ids")
    steps = {s.step_id: s for s in candidate.evidence}
    cited = set()
    for citation in decision.citations:
        if citation.step_id not in steps or citation.step_id in cited:
            raise GroundingError("invalid_evidence_step_ids")
        text, quote = steps[citation.step_id].text, citation.quote
        if (not quote.strip() or len(quote) > 600 or
                len(quote.strip()) < min(12, len(text.strip())) or quote not in text or
                "[TRUNCATED]" in quote or "[REDACTED" in quote):
            raise GroundingError("quote_not_supported")
        cited.add(citation.step_id)
    required = {step for fid in ids for step in facts[fid].evidence_step_ids}
    if not required <= cited:
        raise GroundingError("missing_fact_evidence")
    if decision.assessment == "inefficient":
        if candidate.kind != "repeated_tool_call" or not candidate.context_complete:
            raise GroundingError("insufficient_basis_for_inefficiency")
        if set(ids) != facts.keys():
            raise GroundingError("incomplete_cycle_evidence")
        if decision.advice != "change_approach":
            raise GroundingError("missing_cycle_recommendation")
    if decision.assessment == "reasonable" and decision.advice != "none":
        raise GroundingError("recommendation_for_reasonable_episode")
    allowed = {
        "explicit_tool_error": {"none", "inspect_failure"},
        "repeated_tool_call": {"none", "change_approach", "inspect_failure"},
        "read_many_files": {"none", "narrow_read_scope", "reuse_observed_tool"},
    }
    if decision.advice not in allowed[candidate.kind]:
        raise GroundingError("advice_not_applicable")
    if decision.advice == "reuse_observed_tool":
        alternative = next((a for a in candidate.alternatives
                            if a.alternative_id == decision.alternative_id), None)
        if alternative is None:
            raise GroundingError("unobserved_alternative")
        if not set(alternative.evidence_step_ids) <= cited:
            raise GroundingError("missing_alternative_evidence")
    elif decision.alternative_id is not None:
        raise GroundingError("unexpected_alternative")


def render_judgment(candidate: Candidate, decision: ModelDecision) -> Judgment:
    """No unrestricted model-authored prose is copied into the public report."""
    validate_decision(candidate, decision)
    facts = {f.fact_id: f for f in candidate.facts}
    action = verification = rule = None
    if decision.advice == "inspect_failure":
        action = "Проверить причину указанной ошибки по результату инструмента перед повторным запуском."
        verification = "Убедиться, что диагностический шаг объясняет ошибку; сама ошибка не доказывает плохую работу агента."
    elif decision.advice == "change_approach":
        action = "Проверить, дают ли одинаковые повторения новый результат. Если прогресса нет, остановить повторы и проверить причину либо сменить подход."
        verification = "В следующей сессии проверить, что после одинакового результата есть диагностика или обоснование очередного повтора."
        if decision.assessment == "inefficient":
            rule = "После повторения одинакового результата проверь причину и условия. Не продолжай неизменённые попытки без основания ожидать новый результат."
    elif decision.advice == "narrow_read_scope":
        action = "Проверить, нужны ли полные тексты всех прочитанных файлов. Если достаточно отдельных сведений, сузить область чтения."
        verification = "Сравнить полноту найденной информации и число обращений на той же задаче. Меньше вызовов само по себе не означает лучшее решение."
    elif decision.advice == "reuse_observed_tool":
        alternative = next(a for a in candidate.alternatives if a.alternative_id == decision.alternative_id)
        action = f"Проверить, можно ли применить уже встречавшийся инструмент {alternative.tool_name} для отбора нужных сведений перед чтением файлов. Его применимость к этому эпизоду не доказана."
        verification = "Сравнить результат с исходным способом на той же задаче: корректность, полноту и число вызовов. Не обещать эквивалентность без проверки."
    limitations = [*candidate.limitations,
        "Факты взяты из входных доказательств; оценка полезности выбрана моделью и требует проверки человеком."]
    if candidate.kind == "read_many_files":
        limitations.append("Глобальная оптимальность и возможность заменить всё одной утилитой по этим данным не установлены.")
    return Judgment(
        candidate_id=candidate.candidate_id, assessment=decision.assessment,
        fact_ids=decision.fact_ids, evidence_step_ids=[c.step_id for c in decision.citations],
        citations=decision.citations,
        explanation="\n".join(facts[fid].text for fid in decision.fact_ids),
        action=action, verification=verification, rule_text=rule,
        advice=decision.advice, alternative_id=decision.alternative_id, limitations=limitations,
    )
