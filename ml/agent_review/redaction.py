"""Best-effort text masking. It cannot guarantee removal of all secrets."""

import re

from .schemas import ReviewInput


def redact(text: str) -> str:
    text = re.sub(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        "[REDACTED_PRIVATE_KEY]", text, flags=re.S,
    )
    text = re.sub(r"\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{12,})\b",
                  "[REDACTED_TOKEN]", text)
    text = re.sub(r"(?i)(\bbearer\s+)[A-Za-z0-9._~+/-]+=*", r"\1[REDACTED]", text)
    text = re.sub(
        r'''(?i)(["']?\b(?:[a-z0-9_-]{0,64}api[_-]?key|[a-z0-9_-]{0,64}password|[a-z0-9_-]{0,64}secret|[a-z0-9_-]{0,64}token)["']?\s*[:=]\s*)("[^"\n]*"|'[^'\n]*'|[^\s,;}]+)''',
        r'\1"[REDACTED]"', text,
    )
    text = re.sub(r"(https?://)[^/@\s]+:[^/@\s]+@", r"\1[REDACTED]@", text)
    return re.sub(r"/(?:Users|home)/[^/\s\"']+", "/home/USER", text)


def clean_packet(packet: ReviewInput) -> ReviewInput:
    clean = packet.model_copy(deep=True)
    clean.task = redact(clean.task) if clean.task else None
    clean.warnings = [redact(t) for t in clean.warnings]
    for candidate in clean.candidates:
        candidate.task_context = redact(candidate.task_context) if candidate.task_context else None
        for fact in candidate.facts:
            fact.text = redact(fact.text)
        candidate.limitations = [redact(t) for t in candidate.limitations]
        for step in candidate.evidence:
            step.text = redact(step.text)
    return clean
