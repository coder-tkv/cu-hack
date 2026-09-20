"""Аудит находок: каждое утверждение перепроверяем по шагам независимо от детектора.

Смысл: детектор может выдать красивый заголовок и ссылки на шаги, которые
этого утверждения не подтверждают. Судьи будут открывать шаги и сверять —
делаем это сами, на всех настоящих логах и на случайных.
"""

import glob
import json
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from analysis import analyze_file, analyze_log  # noqa: E402
from analysis.detectors import FINDING_TYPES  # noqa: E402
from analysis.detectors.human import is_correction  # noqa: E402
from analysis.pricing import billable_input_equivalent  # noqa: E402
from analysis.detectors.util import (  # noqa: E402
    MUTATING_TOOLS,
    error_signature,
    group_key,
    jaccard,
    norm,
    tokens_of,
)

IDLE_MS = 10 * 60 * 1000


class Audit:
    """Проверяльщик одной находки. Все claim_* обязаны совпасть с шагами."""

    def __init__(self, test: unittest.TestCase, steps: list[dict], case: str):
        self.t = test
        self.steps = steps
        self.by_id = {s["id"]: s for s in steps}
        self.case = case

    def _steps_of(self, ids) -> list[dict]:
        return [self.by_id[i] for i in ids if i in self.by_id]

    def check(self, f: dict) -> None:
        where = f"{self.case}/{f['type']}/{f['id']}"
        handler = getattr(self, "_" + f["type"], None)
        self.t.assertIsNotNone(handler, f"{where}: для типа находки нет проверки в аудиторе")
        if f.get("episodes"):
            self._check_merged(f, where, handler)
        else:
            handler(f, where)

    def _check_merged(self, f: dict, where: str, handler) -> None:
        """Склеенную находку проверяем поэпизодно: каждый эпизод обязан держаться сам."""
        episodes = f["episodes"]
        self.t.assertGreater(len(episodes), 1, f"{where}: склейка из одного эпизода")
        union = set()
        for i, ep in enumerate(episodes):
            self.t.assertTrue(ep.get("evidence"), f"{where}: эпизод {i} без доказательств")
            handler({
                "type": f["type"],
                "id": f"{f['id']}e{i}",
                "title": ep["title"],
                "metrics": ep["metrics"],
                "evidence": ep["evidence"],
                "stepIds": ep["stepIds"],
            }, f"{where}/эпизод{i}")
            union.update(ep["stepIds"])
        self.t.assertTrue(set(f["stepIds"]).issubset(union), f"{where}: ссылки вне эпизодов")
        self.t.assertEqual(f["episodeCount"], len(episodes) if not f.get("episodesTruncated") else f["episodeCount"],
                           f"{where}: врёт число эпизодов")
        self.t.assertEqual(f["metrics"].get("episodes"), f["episodeCount"], f"{where}: metrics.episodes не совпадает")
        if not f.get("episodesTruncated"):
            for field in ("repeats", "attempts"):
                parts = [ep["metrics"].get(field) for ep in episodes if isinstance(ep["metrics"].get(field), int)]
                if parts:
                    self.t.assertEqual(sum(parts), f["metrics"][field], f"{where}: сумма {field} не сходится")
        self.t.assertGreaterEqual(f["severity"], max(ep["severity"] for ep in episodes),
                                  f"{where}: склейка оценена ниже своего сильнейшего эпизода")
        if f["type"] in ("repeated_call", "similar_call") and f["metrics"].get("mutatingBetween"):
            self.t.assertNotIn("без изменений", f["title"],
                               f"{where}: заголовок обещает отсутствие правок, а метрика говорит обратное")
        self.t.assertIn(str(f["episodeCount"]), f["title"], f"{where}: в заголовке не видно числа эпизодов")

    # --- повторы -------------------------------------------------------
    def _repeated_call(self, f, where):
        calls = self._steps_of(f["evidence"]["callStepIds"])
        self.t.assertEqual(len(calls), f["metrics"]["repeats"], f"{where}: repeats не совпадает со ссылками")
        for c in calls:
            self.t.assertEqual(c["kind"], "tool_call", f"{where}: ссылка не на вызов инструмента")
        keys = {group_key(c) for c in calls}
        self.t.assertEqual(len(keys), 1, f"{where}: в «одинаковых» вызовах разные аргументы")

        first, last = calls[0]["id"], calls[-1]["id"]
        cluster = {c["id"] for c in calls}
        mutating = sum(
            1 for s in self.steps
            if first < s["id"] < last and s["kind"] == "tool_call"
            and s["id"] not in cluster and s.get("tool") in MUTATING_TOOLS
        )
        self.t.assertEqual(mutating, f["metrics"]["mutatingBetween"], f"{where}: врёт число правок между повторами")
        if f["metrics"]["mutatingBetween"] == 0:
            self.t.assertIn("без изменений", f["title"], f"{where}: заголовок не соответствует метрике")

        results = [self._result_of(c) for c in calls]
        texts = [(r.get("text") or "") if r else "" for r in results]
        identical = len(texts) > 1 and all(t == texts[0] != "" for t in texts)
        self.t.assertEqual(identical, f["evidence"]["resultsIdentical"], f"{where}: врёт «результат тот же»")

    def _similar_call(self, f, where):
        calls = self._steps_of(f["evidence"]["callStepIds"])
        self.t.assertGreaterEqual(len(calls), 3, f"{where}: меньше трёх вызовов")
        seed = tokens_of((calls[0].get("args") or {}).get("command", ""))
        for c in calls[1:]:
            sim = jaccard(seed, tokens_of((c.get("args") or {}).get("command", "")))
            self.t.assertGreaterEqual(sim, 0.7, f"{where}: вызов не похож на остальные (сходство {sim:.2f})")

    # --- падения -------------------------------------------------------
    def _retry_loop(self, f, where):
        calls = self._steps_of(f["evidence"]["callStepIds"])
        self.t.assertEqual(len(calls), f["metrics"]["attempts"], f"{where}: attempts не совпадает")
        sigs = set()
        for c in calls:
            r = self._result_of(c)
            self.t.assertIsNotNone(r, f"{where}: у падавшего вызова нет результата")
            self.t.assertTrue(r.get("isError"), f"{where}: результат не помечен ошибкой")
            sigs.add(error_signature(r.get("text")))
        self.t.assertEqual(f["metrics"]["sameError"], len(sigs) == 1, f"{where}: врёт «та же ошибка»")

    def _repeated_error(self, f, where):
        calls = self._steps_of(f["evidence"]["callStepIds"])
        self.t.assertGreaterEqual(len({group_key(c) for c in calls}), 2, f"{where}: это один и тот же вызов")
        for c in calls:
            r = self._result_of(c)
            self.t.assertTrue(r and r.get("isError"), f"{where}: ссылка не на упавший вызов")
            self.t.assertEqual(error_signature(r.get("text")), f["evidence"]["signature"], f"{where}: другая ошибка")

    def _high_failure_rate(self, f, where):
        calls = [s for s in self.steps if s["kind"] == "tool_call"]
        results = {s["resultOf"]: s for s in self.steps if s["kind"] == "tool_result" and s.get("resultOf")}
        failed = sum(1 for c in calls if results.get(c["id"], {}).get("isError"))
        self.t.assertEqual(len(calls), f["metrics"]["calls"], f"{where}: врёт число вызовов")
        self.t.assertEqual(failed, f["metrics"]["failures"], f"{where}: врёт число падений")

    def _api_errors(self, f, where):
        for s in self._steps_of(f["stepIds"]):
            self.t.assertIn("api_error", s.get("raw") or "", f"{where}: ссылка не на ошибку API")

    # --- токены --------------------------------------------------------
    def _token_hotspot(self, f, where):
        self._check_turn_range(f, where)

    def _spend_without_changes(self, f, where):
        lo, hi = self._check_turn_range(f, where)
        edits = [s for s in self.steps if lo <= s["id"] <= hi and s["kind"] == "tool_call" and s.get("tool") in MUTATING_TOOLS]
        self.t.assertEqual(edits, [], f"{where}: на участке всё-таки правили файлы: {[s['id'] for s in edits]}")

    def _check_turn_range(self, f, where):
        lo, hi = f["evidence"]["stepRange"]
        self.t.assertLessEqual(lo, hi, f"{where}: перевёрнутый диапазон")
        for i in f["stepIds"]:
            self.t.assertTrue(lo <= i <= hi, f"{where}: шаг {i} вне участка {lo}..{hi}")
        tin = tout = cread = cwrite = 0
        for s in self.steps:
            if lo <= s["id"] <= hi and isinstance(s.get("usage"), dict):
                u = s["usage"]
                tin += u["in"]
                tout += u["out"]
                cread += u["cacheRead"]
                cwrite += u["cacheWrite"]
        claimed = f["evidence"]["tokens"]
        self.t.assertEqual(
            (tin, tout, cread, cwrite),
            (claimed["in"], claimed["out"], claimed["cacheRead"], claimed["cacheWrite"]),
            f"{where}: врут токены участка",
        )
        self.t.assertEqual(
            billable_input_equivalent(tin, tout, cread, cwrite),
            f["metrics"]["billableTokens"],
            f"{where}: врёт расход участка",
        )
        return lo, hi

    # --- правки --------------------------------------------------------
    def _edit_revert(self, f, where):
        a = self.by_id[f["evidence"]["editStepId"]]
        b = self.by_id[f["evidence"]["revertStepId"]]
        self.t.assertLess(a["id"], b["id"], f"{where}: откат раньше самой правки")
        path = f["evidence"]["filePath"]
        for s in (a, b):
            self.t.assertIn(s.get("tool"), ("Edit", "MultiEdit"), f"{where}: ссылка не на правку")
            self.t.assertIn(path, self._paths_of(s), f"{where}: правка другого файла")
        # ключевое утверждение: поздняя правка вернула то, что убрала ранняя
        self.t.assertTrue(
            any(
                norm(new) and norm(new) in {norm(old) for old, _ in self._pairs_of(a)}
                for _, new in self._pairs_of(b)
            ),
            f"{where}: возвращённый текст не совпадает с убранным",
        )

    def _paths_of(self, step: dict) -> list[str]:
        out = []
        args = step.get("args") if isinstance(step.get("args"), dict) else {}
        if isinstance(args.get("file_path"), str):
            out.append(args["file_path"])
        res = step.get("result") if isinstance(step.get("result"), dict) else {}
        if isinstance(res.get("filePath"), str):
            out.append(res["filePath"])
        return out

    def _pairs_of(self, step: dict) -> list[tuple[str, str]]:
        """Пары (old, new) правки: из args или из toolUseResult, включая MultiEdit."""
        args = step.get("args") if isinstance(step.get("args"), dict) else {}
        res = step.get("result") if isinstance(step.get("result"), dict) else {}
        raw = args.get("edits") if isinstance(args.get("edits"), list) else res.get("edits")
        pairs = []
        if isinstance(raw, list):
            for e in raw:
                if isinstance(e, dict):
                    pairs.append((e.get("old_string") or e.get("oldString") or "",
                                  e.get("new_string") or e.get("newString") or ""))
        if not pairs:
            pairs.append((args.get("old_string") or res.get("oldString") or "",
                          args.get("new_string") or res.get("newString") or ""))
        return [(o if isinstance(o, str) else "", n if isinstance(n, str) else "") for o, n in pairs]

    def _file_churn(self, f, where):
        path = f["evidence"]["filePath"]
        for s in self._steps_of(f["evidence"]["editStepIds"]):
            self.t.assertIn(s.get("tool"), ("Edit", "MultiEdit"), f"{where}: ссылка не на правку")
            args_path = (s.get("args") or {}).get("file_path")
            result_path = (s.get("result") or {}).get("filePath") if isinstance(s.get("result"), dict) else None
            self.t.assertIn(path, [p for p in (args_path, result_path) if p], f"{where}: правка другого файла")
        self.t.assertGreaterEqual(f["metrics"]["edits"], 4, f"{where}: меньше четырёх правок")

    def _rewrite_loop(self, f, where):
        for s in self._steps_of(f["evidence"]["writeStepIds"]):
            self.t.assertEqual(s.get("tool"), "Write", f"{where}: ссылка не на Write")
            self.t.assertEqual((s.get("args") or {}).get("file_path"), f["evidence"]["filePath"], f"{where}: другой файл")

    # --- человек -------------------------------------------------------
    def _human_corrections(self, f, where):
        for m in f["evidence"]["messages"]:
            s = self.by_id[m["stepId"]]
            self.t.assertEqual(s["kind"], "human", f"{where}: ссылка не на реплику человека")
            self.t.assertFalse(s.get("synthetic"), f"{where}: служебная реплика выдана за человеческую")
            self.t.assertTrue(is_correction(s.get("text")), f"{where}: реплика не похожа на разворот")

    def _interruptions(self, f, where):
        for s in self._steps_of(f["stepIds"]):
            self.t.assertTrue(s.get("interrupted"), f"{where}: шаг не является прерыванием")

    def _repeated_instruction(self, f, where):
        msgs = self._steps_of([m["stepId"] for m in f["evidence"]["messages"]])
        self.t.assertGreaterEqual(len(msgs), 2, f"{where}: меньше двух реплик")
        for s in msgs:
            self.t.assertEqual(s["kind"], "human", f"{where}: ссылка не на реплику человека")
            self.t.assertFalse(s.get("synthetic"), f"{where}: служебная реплика")
        for a, b in zip(msgs, msgs[1:]):
            sim = jaccard(tokens_of(a.get("text")), tokens_of(b.get("text")))
            self.t.assertGreaterEqual(sim, 0.6, f"{where}: реплики не похожи (сходство {sim:.2f})")

    # --- время ---------------------------------------------------------
    def _idle_gaps(self, f, where):
        for g in f["evidence"]["topGaps"]:
            a, b = self.by_id[g["fromStepId"]], self.by_id[g["toStepId"]]
            self.t.assertGreater(b["ts"] - a["ts"], IDLE_MS, f"{where}: пауза короче десяти минут")
            self.t.assertEqual(g["minutes"], round((b["ts"] - a["ts"]) / 60000), f"{where}: врёт длину паузы")

    def _slow_tool_calls(self, f, where):
        for w in f["evidence"]["worst"]:
            call = self.by_id[w["stepId"]]
            result = self._result_of(call)
            self.t.assertIsNotNone(result, f"{where}: у долгого вызова нет результата")
            self.t.assertGreaterEqual(result["ts"] - call["ts"], 60_000, f"{where}: вызов быстрее минуты")
            self.t.assertEqual(w["seconds"], round((result["ts"] - call["ts"]) / 1000), f"{where}: врёт длительность")

    def _result_of(self, call: dict) -> dict | None:
        for s in self.steps:
            if s["kind"] == "tool_result" and s.get("resultOf") == call["id"]:
                return s
        return None


class TestFindingsAreTruthful(unittest.TestCase):
    def _audit(self, report: dict, case: str) -> int:
        audit = Audit(self, report["steps"], case)
        seen = set()
        for f in report["findings"]:
            audit.check(f)
            key = (f["type"], tuple(f["stepIds"]))
            self.assertNotIn(key, seen, f"{case}: две одинаковые находки {f['type']} на тех же шагах")
            seen.add(key)
        return len(report["findings"])

    def test_real_logs_findings_verified(self):
        files = sorted(glob.glob(os.path.expanduser("~/.claude/projects/**/*.jsonl"), recursive=True))
        if not files:
            self.skipTest("нет настоящих логов")
        checked = 0
        for f in files:
            checked += self._audit(analyze_file(f), os.path.basename(f)[:8])
        self.assertGreater(checked, 50, "аудит должен реально что-то проверить")

    def test_fuzz_findings_verified(self):
        """Случайные логи: находки на мусоре тоже обязаны быть правдивыми."""
        from tests.test_hard import TestFuzz

        gen = TestFuzz()
        for seed in range(25):
            rnd = random.Random(1000 + seed)
            log = "\n".join(gen._random_line(rnd, i) for i in range(rnd.randint(5, 150)))
            self._audit(analyze_log(log), f"fuzz-{seed}")

    def test_every_finding_type_has_an_auditor(self):
        """Новый тип находки без проверки в аудиторе — незакрытая дыра."""
        missing = sorted(t for t in FINDING_TYPES if not hasattr(Audit, "_" + t))
        self.assertEqual(missing, [], f"типы находок без аудитора: {missing}")

    def test_registry_matches_source(self):
        """Реестр не должен расходиться с кодом детекторов."""
        import re

        base = os.path.join(os.path.dirname(__file__), "..", "src", "analysis", "detectors")
        in_source = set()
        for name in sorted(os.listdir(base)):
            if not name.endswith(".py") or name == "__init__.py":
                continue
            with open(os.path.join(base, name), encoding="utf-8") as fh:
                body = fh.read()
            in_source.update(re.findall(r'finding\(\s*"([a-z_]+)"', body))
            in_source.update(re.findall(r'"(repeated_call|similar_call)"', body))
        self.assertEqual(sorted(in_source - set(FINDING_TYPES)), [], "тип есть в коде, но не в реестре")

    def test_auditor_catches_a_lie(self):
        """Проверяем сам аудитор: подделанная находка обязана не пройти."""
        log_lines = []
        for i in range(3):
            log_lines.append(json.dumps({"type": "assistant", "timestamp": "2026-09-20T10:00:0%d.000Z" % i,
                                         "message": {"id": f"m{i}", "role": "assistant", "model": "claude-opus-5",
                                                     "content": [{"type": "tool_use", "id": f"t{i}", "name": "Bash",
                                                                  "input": {"command": f"echo {i}"}}]}}))
        report = analyze_log("\n".join(log_lines))
        fake = {
            "id": "f1", "type": "repeated_call", "severity": 0.9, "title": "врунишка без изменений",
            "stepIds": [1, 2, 3], "metrics": {"repeats": 3, "mutatingBetween": 0},
            "evidence": {"callStepIds": [1, 2, 3], "resultsIdentical": False}, "explanation": "x",
        }
        audit = Audit(self, report["steps"], "fake")
        with self.assertRaises(AssertionError):
            audit.check(fake)  # у вызовов разные аргументы — аудитор обязан это заметить


if __name__ == "__main__":
    unittest.main()
