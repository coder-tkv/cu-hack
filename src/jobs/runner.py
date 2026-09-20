"""Последовательный пайплайн анализа: parsing -> analyzing -> explaining -> assembling.

Сейчас каждая стадия — заглушка на мок-данных. Точки подключения помечены TODO:
- parsing: Бек-1, parsers/claude_code.py
- analyzing: Бек-2, analysis/*.py + ranking.py
- explaining: ML, llm/client.py + validator.py
- assembling: reports/builder.py + exporters.py

Один анализ за раз. Состояние всегда в БД, чтобы статус был виден после рестарта.
"""

import asyncio
import logging

from database.db_helper import db_helper
from crud import analyses as analyses_crud
from crud import sessions as sessions_crud
from mocks import build_mock_report, build_mock_steps
from reports.exporters import write_artifacts
from schemas import AnalysisStatus

log = logging.getLogger(__name__)

# Пауза между стадиями, чтобы фронт успел увидеть прогресс на демо-логе.
STAGE_DELAY_SECONDS = 1.0


async def run_analysis(analysis_id: str, session_id: str, *, llm_enabled: bool = True) -> None:
    """Выполняет пайплайн. Любая ошибка -> статус failed с текстом причины."""
    async with db_helper.session_factory() as db:
        try:
            # --- parsing -------------------------------------------------
            await analyses_crud.set_stage(db, analysis_id, AnalysisStatus.parsing, percent=0.0)
            await asyncio.sleep(STAGE_DELAY_SECONDS)

            # TODO(Бек-1): заменить на потоковый парсер загруженного файла.
            steps = build_mock_steps(session_id)
            saved = await sessions_crud.save_steps(db, steps)
            await analyses_crud.set_stage(
                db,
                analysis_id,
                AnalysisStatus.parsing,
                percent=100.0,
                done=saved,
                total=saved,
            )
            await analyses_crud.add_warnings(
                db, analysis_id, ["Шаги взяты из мок-фикстуры, файл ещё не разбирается"]
            )

            # --- analyzing -----------------------------------------------
            await analyses_crud.set_stage(db, analysis_id, AnalysisStatus.analyzing)
            await asyncio.sleep(STAGE_DELAY_SECONDS)
            # TODO(Бек-2): metrics/failures/repeats/interventions/timing + ranking.

            # --- explaining ----------------------------------------------
            await analyses_crud.set_stage(db, analysis_id, AnalysisStatus.explaining)
            await asyncio.sleep(STAGE_DELAY_SECONDS)
            # TODO(ML): context_builder -> llm.explain(packet) -> validator.
            # При падении LLM: сохранить rule_based-объяснения и статус partial.

            # --- assembling ----------------------------------------------
            await analyses_crud.set_stage(db, analysis_id, AnalysisStatus.assembling)
            # TODO(reports/builder.py): собрать Report из фактов + judgments.
            report = build_mock_report(analysis_id, session_id)
            write_artifacts(report)
            await analyses_crud.save_report(db, analysis_id, report)
            log.info("Анализ %s завершён со статусом %s", analysis_id, report.status)

        except Exception as exc:  # носитель статуса — БД, поэтому глушим здесь
            log.exception("Анализ %s упал", analysis_id)
            await analyses_crud.fail_analysis(db, analysis_id, f"{type(exc).__name__}: {exc}")


def schedule_analysis(analysis_id: str, session_id: str, *, llm_enabled: bool = True) -> None:
    """Запускает пайплайн в фоне. Ссылку на task держим, чтобы её не собрал GC."""
    task = asyncio.create_task(
        run_analysis(analysis_id, session_id, llm_enabled=llm_enabled),
        name=f"analysis:{analysis_id}",
    )
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


_BACKGROUND_TASKS: set[asyncio.Task] = set()
