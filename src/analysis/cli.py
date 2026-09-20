"""Прогон разбора из командной строки.

    python3 -m analysis.cli <файл.jsonl> [--json отчёт.json] [--claude-md CLAUDE.generated.md] [--top 10]

Без LLM: только то, что посчитал код. Кейс допускает вывод разбора в терминал,
так что это уже полноценная форма результата, а не только отладка.
"""

from __future__ import annotations

import argparse
import json
import sys

from . import analyze_file

STATUS_LABEL = {"found": "найдено", "clean": "чисто", "insufficient_data": "данных мало"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Разбор лога кодинг-агента (без LLM)")
    ap.add_argument("file", help="путь к <uuid>.jsonl")
    ap.add_argument("--json", dest="out", help="сохранить полный отчёт в файл")
    ap.add_argument("--claude-md", dest="claude_md", help="сохранить предлагаемые правила в файл")
    ap.add_argument("--top", type=int, default=10, help="сколько находок показать")
    args = ap.parse_args(argv)

    report = analyze_file(args.file)
    meta, kpi = report["meta"], report["kpi"]

    print(f"формат: {meta['format']}, шагов: {meta['steps']}, строк: {meta['lines']}")
    if meta["warnings"]:
        print(f"предупреждений: {len(meta['warnings'])} -> {meta['warnings'][0]}")
    cost = f"${kpi['cost']}" if kpi["cost"] is not None else "нет данных"
    rate = "нет данных" if kpi["errorRate"] is None else f"{round(kpi['errorRate'] * 100)}%"
    print(
        f"токены: вход {kpi['tokensIn']}, выход {kpi['tokensOut']}, "
        f"кэш чтение {kpi['cacheRead']}, кэш запись {kpi['cacheWrite']} "
        f"(из них часовой кэш {kpi['cacheWrite1h']}), стоимость {cost}"
    )
    print(
        f"время: активных {kpi['durationMin']} мин (span {kpi['spanMin']} мин), "
        f"вызовов {kpi['toolCalls']}, падений {kpi['failures']} "
        f"(доля {rate} от {kpi['callsWithKnownStatus']} с известным статусом, "
        f"без результата {kpi['unknownStatusCount']}), "
        f"правок файлов {kpi['fileEdits']}, реплик человека {kpi['humanMessages']}, "
        f"прерываний {kpi['interruptions']}"
    )

    print("\nпо направлениям:")
    for d in report["coverage"]:
        mark = STATUS_LABEL.get(d["status"], d["status"])
        print(f"  {d['title']}: {mark} ({d['findings']}) — {d['note']}")

    if not report["findings"]:
        print("\nЗначимых проблем не найдено в доступных данных.")
    else:
        print(f"\nнаходок: {len(report['findings'])}")
        for f in report["findings"][: args.top]:
            print(f"  [{f['id']}] значимость {f['severityBand']} ({f['severity']:.2f}) {f['type']}: {f['title']}")
            print(f"        шаги: {f['stepIds'][:8]}")
            for rule in f["severityRules"][:3]:
                print(f"        · {rule}")

    if report["recommendations"]:
        print(f"\nрекомендаций: {len(report['recommendations'])}")
        for r in report["recommendations"]:
            print(f"  [{r['id']}] {r['title']} -> {r['filename']} ({r['artifactType']})")
            print(f"        действие: {r['action']}")
            print(f"        по находкам: {', '.join(r['findingIds'][:6])}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False)
        print(f"\nотчёт сохранён: {args.out}")
    if args.claude_md:
        with open(args.claude_md, "w", encoding="utf-8") as fh:
            fh.write(report["artifacts"]["CLAUDE.generated.md"])
        print(f"правила сохранены: {args.claude_md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
