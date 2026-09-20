"""Local development helper for Claude Code logs, not the production parser.

Only explicit tool errors become candidates. Token costs, retries, edits and
timing are the backend's responsibility. No raw log is sent over the network.
"""

import hashlib
import json
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from zipfile import ZipFile

from .redaction import clean_packet, redact
from .schemas import Candidate, Evidence, ReviewInput

MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_LINE_BYTES = 5 * 1024 * 1024


def list_logs(path: Path) -> list[dict]:
    with ZipFile(path) as archive:
        return [{"member": i.filename, "bytes": i.file_size}
                for i in archive.infolist() if i.filename.endswith(".jsonl") and not i.is_dir()]


@contextmanager
def open_log(path: Path, member: str | None = None):
    if path.suffix.lower() == ".zip":
        if not member:
            raise ValueError("Select a .jsonl member with --member; use list-logs first")
        with ZipFile(path) as archive:
            info = archive.getinfo(member)
            if info.is_dir() or not info.filename.endswith(".jsonl"):
                raise ValueError("Selected ZIP member must be a .jsonl file")
            if info.file_size > MAX_FILE_BYTES:
                raise ValueError("Log exceeds 50 MiB")
            # Reading a member directly avoids archive extraction/path traversal.
            with archive.open(info) as source:
                yield source
    else:
        if member:
            raise ValueError("--member is only used with ZIP")
        if path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("Log exceeds 50 MiB")
        with path.open("rb") as source:
            yield source


def short_text(value, limit=1800) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    # Redact before shortening, so a cut-off private key cannot defeat masking.
    text = redact(text)
    if len(text) <= limit:
        return text
    return text[:limit // 2] + "\n[TRUNCATED]\n" + text[-limit // 2:]


def prepare_stream(source) -> tuple[ReviewInput, dict]:
    digest = hashlib.sha256()
    events: list[Evidence] = []
    calls: dict[str, Evidence] = {}
    error_results: list[tuple[int, str | None]] = []
    counts = Counter()
    task = None
    seen_records = set()
    sessions = set()
    warnings = [
        "Development helper: candidates cover only explicit tool_result.is_error=true.",
        "Only limited neighbouring events are provided; no conclusions about the whole session.",
        "Original token costs, retries, edits and idle time are not calculated by this helper.",
    ]
    line_no, total_bytes = 0, 0
    while raw := source.readline(MAX_LINE_BYTES + 1):
        line_no += 1
        total_bytes += len(raw)
        digest.update(raw)
        if total_bytes > MAX_FILE_BYTES:
            raise ValueError("Log exceeds 50 MiB")
        if len(raw) > MAX_LINE_BYTES:
            while not raw.endswith(b"\n"):
                raw = source.readline(MAX_LINE_BYTES + 1)
                if not raw:
                    break
                digest.update(raw)
                total_bytes += len(raw)
                if total_bytes > MAX_FILE_BYTES:
                    raise ValueError("Log exceeds 50 MiB")
            counts["oversized_lines"] += 1
            continue
        if not raw.strip():
            continue
        try:
            record = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            counts["invalid_lines"] += 1
            continue
        if not isinstance(record, dict):
            counts["unknown_records"] += 1
            continue
        record_hash = hashlib.sha256(raw).hexdigest()
        if record.get("uuid") and record_hash in seen_records:
            counts["duplicate_records"] += 1
            continue
        seen_records.add(record_hash)
        session = record.get("sessionId")
        if isinstance(session, str):
            sessions.add(session)
        message = record.get("message")
        if record.get("type") not in ("assistant", "user") or not isinstance(message, dict):
            counts["service_or_unknown_records"] += 1
            continue
        content = message.get("content", [])
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        if not isinstance(content, list):
            counts["unknown_content"] += 1
            continue
        for block_no, block in enumerate(content):
            if not isinstance(block, dict):
                counts["unknown_blocks"] += 1
                continue
            kind = block.get("type")
            step_id = f"line-{line_no}-block-{block_no}"
            if kind == "tool_use":
                evidence = Evidence(step_id=step_id, kind="tool_call", source_line=line_no,
                    text=short_text({"tool": block.get("name"), "input": block.get("input")}))
                call_id = block.get("id")
                if isinstance(call_id, str):
                    calls[call_id] = evidence
                counts["tool_calls"] += 1
            elif kind == "tool_result":
                evidence = Evidence(step_id=step_id, kind="tool_result", source_line=line_no,
                    text=short_text({"is_error": block.get("is_error"), "content": block.get("content")}))
                if block.get("is_error") is True:
                    call_id = block.get("tool_use_id")
                    error_results.append((len(events), call_id if isinstance(call_id, str) else None))
                    counts["explicit_error_results"] += 1
                counts["tool_results"] += 1
            elif kind == "text" and isinstance(block.get("text"), str):
                actor = "assistant_text" if record.get("type") == "assistant" else "user_or_system_text"
                evidence = Evidence(step_id=step_id, kind=actor, source_line=line_no,
                                    text=short_text(block["text"]))
                if task is None and record.get("type") == "user" and not record.get("isMeta"):
                    task = evidence.text
            else:
                # Exclude hidden reasoning, images and unsupported blocks.
                counts["ignored_blocks"] += 1
                continue
            events.append(evidence)
    if len(sessions) > 1:
        raise ValueError("Helper expects one session per file; backend must split multiple sessions")
    candidates = []
    for index, call_id in error_results[:1000]:
        result = events[index]
        call = calls.get(call_id) if call_id else None
        context = events[max(0, index - 2): index + 3]
        relevant = ([call] if call else []) + context
        evidence = list({step.step_id: step for step in relevant}.values())
        limitations = ["A tool error alone does not prove inefficient agent behaviour."]
        if not call:
            limitations.append("The matching tool call is missing from this log.")
        if any("[TRUNCATED]" in step.text for step in evidence):
            limitations.append("Some evidence text was truncated; full details are not visible.")
        candidates.append(Candidate(
            candidate_id=f"error-{result.step_id}", kind="explicit_tool_error",
            facts=[f"At {result.step_id}, the tool result explicitly has is_error=true."],
            evidence=evidence, limitations=limitations,
        ))
    if len(error_results) > 1000:
        warnings.append("Only the first 1000 explicit error candidates were retained.")
    if counts["invalid_lines"] or counts["oversized_lines"]:
        warnings.append("Some lines were invalid or oversized; see preparation summary.")
    if not events:
        warnings.append("No supported conversation events found: insufficient data, not a clean session.")
    if not candidates:
        warnings.append("No explicit error candidates. This is not proof that the session was efficient.")
    packet = ReviewInput(source_id=f"sha256:{digest.hexdigest()}", task=task,
                         candidates=candidates, warnings=warnings)
    counts["lines"] = line_no
    counts["recognized_steps"] = len(events)
    counts["candidates"] = len(candidates)
    return clean_packet(packet), dict(counts)


def prepare_log(path: Path, member: str | None = None) -> tuple[ReviewInput, dict]:
    with open_log(path, member) as source:
        return prepare_stream(source)
