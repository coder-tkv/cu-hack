"""Local CLI: prepare evidence, preview requests, then explicitly call the API."""

import argparse
import json
import sys
from pathlib import Path
from zipfile import BadZipFile

from pydantic import ValidationError

from .prepare import list_logs, prepare_log
from .reviewer import MAX_CALLS, preview, review
from .schemas import ReviewInput


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare and explain coding-agent evidence")
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list-logs", help="List JSONL members of a ZIP, without extraction")
    listing.add_argument("archive", type=Path)
    prepare = commands.add_parser("prepare", help="Read one Claude Code log locally; no API call")
    prepare.add_argument("source", type=Path)
    prepare.add_argument("--member", help="Exact member name if source is a ZIP")
    prepare.add_argument("--out", type=Path, required=True)
    for name in ("preview", "explain"):
        command = commands.add_parser(name, help="No network" if name == "preview" else "Call the paid model API")
        command.add_argument("packet", type=Path)
        command.add_argument("--out", type=Path, required=True)
        command.add_argument("--model")
        command.add_argument("--max-calls", type=int, default=MAX_CALLS)
    args = parser.parse_args()
    try:
        if args.command == "list-logs":
            print(json.dumps(list_logs(args.archive), ensure_ascii=False, indent=2))
            return 0
        source = args.source if args.command == "prepare" else args.packet
        if source.resolve() == args.out.resolve():
            raise ValueError("Output path must not overwrite the input")
        if args.command == "prepare":
            packet, counts = prepare_log(args.source, args.member)
            write_json(args.out, packet.model_dump())
            print(json.dumps({"mode": "local_prepare", "summary": counts}, ensure_ascii=False))
            return 0
        if args.packet.stat().st_size > 10 * 1024 * 1024:
            raise ValueError("Prepared packet exceeds 10 MiB; split it in the backend")
        packet = ReviewInput.model_validate_json(args.packet.read_text(encoding="utf-8"))
        options = {"model": args.model, "max_calls": args.max_calls}
        if args.command == "preview":
            result = preview(packet, **options)
            write_json(args.out, result)
            print(f"Preview only: {len(result['requests'])} requests, no API calls")
            return 0
        report = review(packet, **options)
        write_json(args.out, report.model_dump())
        print(f"{report.status}: {report.candidates_reviewed}/{report.candidates_total} explained")
        # Saved partial result is useful, but automation must see non-success.
        return 2 if report.status == "partial" else 0
    except ValidationError as exc:
        print(json.dumps({"error": "invalid_packet", "details": exc.errors(
            include_input=False, include_context=False, include_url=False)}, ensure_ascii=False), file=sys.stderr)
        print("Expected schema_version=2. Re-run prepare for older packets.", file=sys.stderr)
    except (OSError, ValueError, KeyError, BadZipFile) as exc:
        # Do not print provider responses or log content in CLI errors.
        print(f"Input/configuration error: {type(exc).__name__}: {exc}", file=sys.stderr)
    return 1
