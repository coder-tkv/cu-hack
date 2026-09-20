"""Compact a detected, masked episode without shortening its evidence text.

Keep every step and its order. Exact duplicate texts may refer to an earlier
step; all facts, task context and limitations stay intact. Source locations and
scheduling metadata stay in the original packet/report, outside the model input.
This does not restore content omitted earlier by the development parser.
"""

import json

from .schemas import Candidate, CompressionStats, ReviewInput


def compact_json(value) -> str:
    # Never strip whitespace INSIDE a log string: it is part of the evidence.
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def compress_input(packet: ReviewInput, candidate: Candidate) -> tuple[str, CompressionStats]:
    """Called after detection and redaction; never mutates the source packet."""
    task = candidate.task_context or packet.task
    original = {"source_id": packet.source_id, "task": task,
                "warnings": packet.warnings, "candidate": candidate.model_dump()}
    packed = candidate.model_dump(exclude={"priority", "task_context"})
    first_text_steps: dict[str, str] = {}
    reused = 0
    for step in packed["evidence"]:
        step.pop("source_line")
        text = step["text"]
        first_id = first_text_steps.get(text)
        # A reference points directly to an earlier inline text, never a chain.
        # Keep short duplicates inline if the reference would cost more bytes.
        if first_id is not None and (
            len(compact_json({"text_ref": first_id}).encode("utf-8"))
            < len(compact_json({"text": text}).encode("utf-8"))
        ):
            del step["text"]
            step["text_ref"] = first_id
            reused += 1
        else:
            first_text_steps.setdefault(text, step["step_id"])
    payload = {"task": task, "warnings": packet.warnings, "candidate": packed}
    compressed = compact_json(payload)
    # Compare with the actual JSON representation used before this stage existed.
    before = len(json.dumps(original, ensure_ascii=False).encode("utf-8"))
    after = len(compressed.encode("utf-8"))
    stats = CompressionStats(original_input_bytes=before, compressed_input_bytes=after,
                             saved_input_bytes=before - after,
                             reused_texts=reused, evidence_steps=len(candidate.evidence))
    return compressed, stats
