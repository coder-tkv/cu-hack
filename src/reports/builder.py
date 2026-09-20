"""Report assembly seam.

The real implementation will combine parser output, detector candidates and
validated ML judgments. This module intentionally exposes the seam early so
other backend parts can depend on one import path now.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def build_report(
    *,
    analysis_id: str,
    session_id: str,
    status: Any,
    session_info: Any,
    steps: Iterable[Any] = (),
    candidates: Iterable[Any] = (),
    judgments: Iterable[Any] = (),
    usage: Any = None,
) -> Any:
    """Build the frozen ``Report`` contract from pipeline outputs.

    ``Report`` and finding schemas belong to the platform/detector phase and
    are not implemented in this first seam. Keeping the arguments explicit
    prevents callers from inventing incompatible ad-hoc report shapes.
    """
    raise NotImplementedError(
        "Report builder is a phase-two implementation; the interface is ready."
    )
