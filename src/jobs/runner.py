"""Real background pipeline: parse once -> detectors -> compact ML -> report."""

import asyncio
import logging
import os

from agent_review import review_async
from analysis import analyze_parsed, parse_file
from config import settings
from crud import analyses as analyses_crud
from crud import sessions as sessions_crud
from database.db_helper import db_helper
from reports.builder import build_ml_packet, build_report, clean, to_steps
from reports.exporters import write_artifacts
from schemas import AnalysisStatus

log = logging.getLogger(__name__)
_ANALYSIS_LOCK = asyncio.Lock()
_BACKGROUND_TASKS: set[asyncio.Task] = set()


async def _pipeline(analysis_id: str, session_id: str, llm_enabled: bool) -> None:
    async with db_helper.session_factory() as db:
        session = await sessions_crud.get_session(db, session_id)
        if session is None:
            raise ValueError("Session does not exist")
        await analyses_crud.set_stage(db, analysis_id, AnalysisStatus.parsing)
        parsed = await asyncio.to_thread(parse_file, session.file_path, settings.storage.max_line_bytes)
        steps = to_steps(parsed, session_id)
        await sessions_crud.save_steps(db, steps)
        await sessions_crud.set_session_meta(db, session_id, {
            "source_session_ids": parsed["meta"].get("sessionIds", []),
            "stats": {"warnings": clean(parsed["meta"].get("warnings", []))},
        })
        await analyses_crud.set_stage(db, analysis_id, AnalysisStatus.analyzing)
        raw = await asyncio.to_thread(analyze_parsed, parsed)
        if len(parsed["meta"].get("sessionIds", [])) > 1:
            raw["findings"] = []
            raw["summary"]["dataStatus"] = "insufficient_data"
            raw["meta"]["warnings"].append("В файле несколько сессий. Загрузите каждую отдельно: находки между сессиями не объединяются.")
            for direction in raw["coverage"]:
                direction.update(status="insufficient_data", findings=0, findingIds=[], note="Нужна одна сессия в файле.")
        ml, warnings = None, []
        await analyses_crud.set_stage(db, analysis_id, AnalysisStatus.explaining)
        if llm_enabled and raw["summary"].get("dataStatus") != "insufficient_data":
            packet, warnings = build_ml_packet(raw, steps, session.sha256)
            if packet.candidates:
                if os.getenv("OPENAI_API_KEY"):
                    ml = await review_async(packet)
                else:
                    warnings.append("ML запрошен, но OPENAI_API_KEY не настроен. Сохранены факты и рекомендации кода.")
        await analyses_crud.set_stage(db, analysis_id, AnalysisStatus.assembling)
        report = build_report(raw, analysis_id=analysis_id, session_id=session_id,
                              llm_enabled=llm_enabled, ml=ml, warnings=warnings)
        await asyncio.to_thread(write_artifacts, report)
        await analyses_crud.add_warnings(db, analysis_id, report.warnings)
        await analyses_crud.save_report(db, analysis_id, report)
        log.info("Analysis %s: %s, %s findings", analysis_id, report.status, len(report.findings))


async def run_analysis(analysis_id: str, session_id: str, *, llm_enabled: bool = False) -> None:
    try:
        async with _ANALYSIS_LOCK:
            await _pipeline(analysis_id, session_id, llm_enabled)
    except asyncio.CancelledError:
        async with db_helper.session_factory() as db:
            await analyses_crud.set_stage(db, analysis_id, AnalysisStatus.interrupted)
        raise
    except Exception as exc:
        log.error("Analysis %s failed: %s", analysis_id, type(exc).__name__)
        async with db_helper.session_factory() as db:
            await analyses_crud.fail_analysis(db, analysis_id, f"Ошибка обработки: {type(exc).__name__}")


def schedule_analysis(analysis_id: str, session_id: str, *, llm_enabled: bool = False) -> None:
    task = asyncio.create_task(run_analysis(analysis_id, session_id, llm_enabled=llm_enabled),
                               name=f"analysis:{analysis_id}")
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


async def shutdown_tasks() -> None:
    tasks = list(_BACKGROUND_TASKS)
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
