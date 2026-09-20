"""Optional private corpus, explicitly supplied by the team; never scan HOME."""

import os
from functools import lru_cache
from pathlib import Path
from zipfile import ZipFile


@lru_cache(maxsize=1)
def real_logs():
    path = Path(os.getenv("TEST_LOGS_ZIP", Path(__file__).parents[1] / "ml/data/logs.zip"))
    if not path.is_file():
        return []
    with ZipFile(path) as archive:
        return [(member.filename, archive.read(member).decode("utf-8", errors="replace"))
                for member in archive.infolist()
                if member.filename.endswith(".jsonl") and member.file_size < 20_000_000]
