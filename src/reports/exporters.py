"""Export seam for the three allowlisted report artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any


ARTIFACT_ALLOWLIST = frozenset(
    {"report.md", "report.json", "CLAUDE.generated.md"}
)


def export_report_md(report: Any, destination: str | Path) -> Path:
    """Write the human-readable report to ``report.md``.

    The final renderer is deferred until the frozen Report model is available.
    """
    raise NotImplementedError("Markdown export is a phase-two implementation.")


def export_report_json(report: Any, destination: str | Path) -> Path:
    """Write the Report JSON contract to ``report.json``."""
    raise NotImplementedError("JSON export is a phase-two implementation.")


def export_claude_generated_md(report: Any, destination: str | Path) -> Path:
    """Write generated recommendations to ``CLAUDE.generated.md``."""
    raise NotImplementedError(
        "CLAUDE.generated.md export is a phase-two implementation."
    )
