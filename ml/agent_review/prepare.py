"""Local development helper for Claude Code logs, not the production parser.

Extracts explicit errors, exact repeats and broad file reading. Full token,
edit and timing analysis remains the backend's responsibility. No raw log is sent over the network.
"""

import hashlib
import json
import shlex
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from zipfile import ZipFile

from .redaction import clean_packet, redact
from .schemas import Evidence, ReviewInput
from .detectors import Event, detect

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


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def search_utility(name, arguments) -> str | None:
    if name in ("Grep", "Glob"):
        return name
    if name != "Bash" or not isinstance(arguments, dict):
        return None
    command = arguments.get("command")
    if not isinstance(command, str) or any(c in command for c in (";", "|", "&", "\n", "$", "`", ">", "<")):
        return None
    try:
        parts = shlex.split(command)
    except ValueError:
        return None
    utility = Path(parts[0]).name if parts else None
    return utility if utility in ("rg", "grep", "find") else None


def prepare_stream(source) -> tuple[ReviewInput, dict]:
    digest = hashlib.sha256()
    events: list[Event] = []
    counts = Counter()
    seen_records, sessions = set(), set()
    seen_blocks = set()
    last_uuid, task_by_scope = {}, {}
    warnings = [
        "Detectors cover explicit tool errors, exact consecutive repeats and broad file reading only.",
        "Observed alternatives do not prove an equivalent or optimal solution.",
        "Original token costs, edits and idle time are not calculated by this helper.",
    ]
    known_service = {"mode", "ai-title", "last-prompt", "attachment", "file-history-snapshot",
                     "permission-mode", "system", "queue-operation", "bridge-session", "summary"}
    line_no, total_bytes, segment = 0, 0, 0
    damaged = False
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
            segment += 1
            damaged = True
            continue
        if not raw.strip():
            continue
        try:
            record = json.loads(raw)
        except (ValueError, UnicodeDecodeError, RecursionError):
            counts["invalid_lines"] += 1
            segment += 1
            damaged = True
            continue
        if not isinstance(record, dict):
            counts["unknown_records"] += 1
            segment += 1
            damaged = True
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
        record_type = record.get("type")
        if record_type not in ("assistant", "user") or not isinstance(message, dict):
            counts["service_or_unknown_records"] += 1
            if not isinstance(record_type, str) or record_type not in known_service:
                segment += 1
                damaged = True
            continue
        scope = (session if isinstance(session, str) else "unknown",
                 str(record.get("agentId", "main")), bool(record.get("isSidechain")))
        uuid, parent = record.get("uuid"), record.get("parentUuid")
        if isinstance(uuid, str):
            previous = last_uuid.get(scope)
            if previous and parent != previous and uuid != previous:
                # Forks/reordered parents are boundaries, never accidental retry chains.
                segment += 1
                counts["chain_boundaries"] += 1
            last_uuid[scope] = uuid
        content = message.get("content", [])
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        if not isinstance(content, list):
            counts["unknown_content"] += 1
            segment += 1
            damaged = True
            continue
        text_blocks = [b["text"] for b in content if isinstance(b, dict)
                       and b.get("type") == "text" and isinstance(b.get("text"), str)]
        has_result = any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)
        if record.get("type") == "user" and text_blocks and not has_result:
            segment += 1
            if not record.get("isMeta") and not record.get("isCompactSummary"):
                task_by_scope[scope] = short_text("\n".join(text_blocks))
                counts["user_text_turns"] += 1
            else:
                task_by_scope[scope] = None
        for block_no, block in enumerate(content):
            if not isinstance(block, dict):
                counts["unknown_blocks"] += 1
                damaged = True
                segment += 1
                continue
            kind = block.get("type")
            if not isinstance(kind, str):
                counts["unknown_blocks"] += 1
                damaged = True
                segment += 1
                continue
            if kind == "thinking":
                counts["ignored_blocks"] += 1
                continue
            block_id = block.get("tool_use_id") if kind == "tool_result" else message.get("id")
            block_key = (scope, block_id if isinstance(block_id, str) else None, kind, fingerprint(block))
            if block_key[1] and block_key in seen_blocks:
                counts["duplicate_blocks"] += 1
                continue
            seen_blocks.add(block_key)
            step_id = f"line-{line_no}-block-{block_no}"
            args = {}
            if kind == "tool_use":
                name, arguments = block.get("name"), block.get("input")
                evidence = Evidence(step_id=step_id, kind="tool_call", source_line=line_no,
                    text=short_text({"tool": name, "input": arguments}))
                call_id = block.get("id")
                path = arguments.get("file_path") if isinstance(arguments, dict) else None
                args = dict(call_id=call_id if isinstance(call_id, str) else None,
                            tool_name=name if isinstance(name, str) else None,
                            args_hash=fingerprint(arguments) if isinstance(arguments, dict) else None,
                            file_hash=fingerprint(path) if isinstance(path, str) else None,
                            search_utility=search_utility(name, arguments))
                counts["tool_calls"] += 1
            elif kind == "tool_result":
                evidence = Evidence(step_id=step_id, kind="tool_result", source_line=line_no,
                    text=short_text({"is_error": block.get("is_error"), "content": block.get("content")}))
                call_id = block.get("tool_use_id")
                error = block.get("is_error")
                args = dict(call_id=call_id if isinstance(call_id, str) else None,
                            result_hash=fingerprint(block["content"]) if block.get("content") is not None else None,
                            is_error=error if isinstance(error, bool) else None)
                counts["explicit_error_results"] += error is True
                counts["tool_results"] += 1
            elif kind == "text" and isinstance(block.get("text"), str):
                actor = "assistant_text" if record.get("type") == "assistant" else "user_or_system_text"
                evidence = Evidence(step_id=step_id, kind=actor, source_line=line_no,
                                    text=short_text(block["text"]))
            else:
                counts["ignored_blocks"] += 1
                damaged = True
                segment += 1
                continue
            events.append(Event(evidence=evidence, segment=segment, scope=scope,
                                task_context=task_by_scope.get(scope), **args))
    if len(sessions) > 1:
        raise ValueError("Helper expects one session per file; backend must split multiple sessions")
    candidates = detect(events, damaged=damaged)
    if len(candidates) > 1000:
        warnings.append("Only the first 1000 ranked candidates were retained.")
        candidates = candidates[:1000]
    if damaged:
        warnings.append("Some content was unreadable or unsupported; no complete-context claims are allowed.")
    if not events:
        warnings.append("No supported conversation events found: insufficient data, not a clean session.")
    if not candidates:
        warnings.append("No detector candidates. This is not proof that the session was efficient.")
    packet = ReviewInput(source_id=f"sha256:{digest.hexdigest()}", task=None,
                         candidates=candidates, warnings=warnings)
    counts["lines"] = line_no
    counts["recognized_steps"] = len(events)
    counts["candidates"] = len(candidates)
    for c in candidates:
        counts[f"candidates_{c.kind}"] += 1
    return clean_packet(packet), dict(counts)


def prepare_log(path: Path, member: str | None = None) -> tuple[ReviewInput, dict]:
    with open_log(path, member) as source:
        return prepare_stream(source)
