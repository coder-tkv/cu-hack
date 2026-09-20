"""Прогон разбора из командной строки.

    python3 -m analysis.cli <файл.jsonl> [--json отчёт.json] [--top 10]

Без LLM: только то, что посчитал код. Удобно для проверки на новом логе
и для отладки бэкенда.
"""

from __future__ import annotations

import argparse
import json
import sys

from . import analyze_file


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Разбор лога кодинг-агента (без LLM)")
    ap.add_argument("file", help="путь к <uuid>.jsonl")
    ap.add_argument("--json", dest="out", help="сохранить полный отчёт в файл")
    ap.add_argument("--top", type=int, default=10, help="сколько находок показать")
    args = ap.parse_args(argv)

    report = analyze_file(args.file)
    meta, kpi = report["meta"], report["kpi"]

    print(f"формат: {meta['format']}, шагов: {meta['steps']}, строк: {meta['lines']}")
    if meta["warnings"]:
        print(f"предупреждений: {len(meta['warnings'])} -> {meta['warnings'][0]}")
    cost = f"${kpi['cost']}" if kpi["cost"] is not None else "нет данных"
    print(
        f"токены: вход {kpi['tokensIn']}, выход {kpi['tokensOut']}, "
        f"кэш чтение {kpi['cacheRead']}, кэш запись {kpi['cacheWrite']}, стоимость {cost}"
    )
    print(
        f"время: активных {kpi['durationMin']} мин (span {kpi['spanMin']} мин), "
        f"вызовов {kpi['toolCalls']}, падений {kpi['failures']}, "
        f"реплик человека {kpi['humanMessages']}, прерываний {kpi['interruptions']}"
    )

    if not report["findings"]:
        print("\nЗначимых проблем не найдено в доступных данных.")
    else:
        print(f"\nнаходок: {len(report['findings'])}")
        for f in report["findings"][: args.top]:
            print(f"  [{f['id']}] {f['severity']:.2f} {f['type']}: {f['title']}")
            print(f"        шаги: {f['stepIds'][:8]}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False)
        print(f"\nотчёт сохранён: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
