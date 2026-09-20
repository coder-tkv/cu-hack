"""Тесты детекторов. Логи собираем из тех же JSONL-строк, что и настоящие,
чтобы заодно проверять связку «парсер -> детектор»."""

import glob
import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from analysis import analyze_file, analyze_log  # noqa: E402
from analysis.detectors import run_all  # noqa: E402
from analysis.detectors.edits import detect_edit_churn  # noqa: E402
from analysis.detectors.failures import detect_failures  # noqa: E402
from analysis.detectors.human import detect_human_interventions  # noqa: E402
from analysis.detectors.repeated import detect_repeated_calls  # noqa: E402
from analysis.detectors.timing import detect_idle_and_slow  # noqa: E402
from analysis.parser import parse_log  # noqa: E402

BASE = datetime(2026, 9, 20, 10, 0, 0, tzinfo=timezone.utc)


class Log:
    """Мини-конструктор лога: .human(), .call(), .result()."""

    def __init__(self):
        self.lines: list[str] = []
        self.n = 0
        self.minute = 0

    def _ts(self) -> str:
        self.n += 1
        return (BASE + timedelta(minutes=self.minute, seconds=self.n)).isoformat().replace("+00:00", "Z")

    def at_minute(self, m: int) -> "Log":
        self.minute = m
        return self

    def human(self, text: str) -> "Log":
        self.lines.append(
            json.dumps({"type": "user", "timestamp": self._ts(), "uuid": f"h{self.n}",
                        "message": {"role": "user", "content": [{"type": "text", "text": text}]}})
        )
        return self

    def call(self, tool: str, args: dict, tool_id: str) -> "Log":
        self.lines.append(
            json.dumps({"type": "assistant", "timestamp": self._ts(), "uuid": f"a{self.n}",
                        "message": {"id": f"msg{self.n}", "role": "assistant", "model": "claude-opus-5",
                                    "content": [{"type": "tool_use", "id": tool_id, "name": tool, "input": args}],
                                    "usage": {"input_tokens": 100, "output_tokens": 50,
                                              "cache_read_input_tokens": 1000, "cache_creation_input_tokens": 0}}})
        )
        return self

    def result(self, tool_id: str, text: str, is_error: bool = False, extra: dict | None = None) -> "Log":
        row = {"type": "user", "timestamp": self._ts(), "uuid": f"r{self.n}",
               "message": {"role": "user",
                           "content": [{"type": "tool_result", "tool_use_id": tool_id, "content": text,
                                        "is_error": is_error}]}}
        if extra:
            row["toolUseResult"] = extra
        self.lines.append(json.dumps(row))
        return self

    def text(self) -> str:
        return "\n".join(self.lines) + "\n"

    def steps(self) -> list[dict]:
        return parse_log(self.text())["steps"]


def npm_test_log(times: int = 3, with_edit_between: bool = False) -> Log:
    """Канонический пример из постановки: npm test падает одинаково N раз."""
    log = Log().human("Запусти тесты и исправь ошибку")
    for i in range(times):
        if with_edit_between and i:
            log.call("Edit", {"file_path": "/p/a.ts", "old_string": f"v{i}", "new_string": f"v{i + 1}"}, f"e{i}")
            log.result(f"e{i}", "ok")
        log.call("Bash", {"command": "npm test"}, f"t{i}")
        log.result(f"t{i}", "npm error Missing script: \"test\"", is_error=True)
    return log


class TestRepeated(unittest.TestCase):
    def test_three_identical_calls_flagged_with_step_ids(self):
        steps = npm_test_log(3).steps()
        found = [f for f in detect_repeated_calls(steps) if f["type"] == "repeated_call"]
        self.assertEqual(len(found), 1)
        f = found[0]
        self.assertEqual(f["metrics"]["repeats"], 3)
        self.assertEqual(f["metrics"]["mutatingBetween"], 0)
        self.assertTrue(f["evidence"]["resultsIdentical"])
        calls = [s["id"] for s in steps if s["kind"] == "tool_call"]
        self.assertEqual(f["evidence"]["callStepIds"], calls)
        self.assertTrue(set(calls).issubset(set(f["stepIds"])))

    def test_two_calls_are_not_a_finding(self):
        self.assertEqual(detect_repeated_calls(npm_test_log(2).steps()), [])

    def test_edits_between_lower_severity(self):
        hot = detect_repeated_calls(npm_test_log(3).steps())[0]["severity"]
        calm = [f for f in detect_repeated_calls(npm_test_log(3, with_edit_between=True).steps())
                if f["type"] == "repeated_call"][0]
        self.assertLess(calm["severity"], hot)
        self.assertEqual(calm["metrics"]["mutatingBetween"], 2)

    def test_similar_commands_clustered(self):
        log = Log().human("собери проект")
        for i, cmd in enumerate(["npm run build", "npm run build --force", "npm run build --verbose"]):
            log.call("Bash", {"command": cmd}, f"c{i}")
            log.result(f"c{i}", "error")
        found = [f for f in detect_repeated_calls(log.steps()) if f["type"] == "similar_call"]
        self.assertEqual(len(found), 1)
        self.assertEqual(len(found[0]["evidence"]["variants"]), 3)

    def test_args_normalized_before_comparison(self):
        log = Log().human("x")
        for i, cmd in enumerate(['cd /p && npm test', 'npm  test', 'NPM TEST']):
            log.call("Bash", {"command": cmd}, f"c{i}")
            log.result(f"c{i}", "same")
        found = [f for f in detect_repeated_calls(log.steps()) if f["type"] == "repeated_call"]
        self.assertEqual(len(found), 1, "одна и та же команда в разном написании — это повтор")


class TestFailures(unittest.TestCase):
    def test_retry_loop_same_error(self):
        found = [f for f in detect_failures(npm_test_log(3).steps()) if f["type"] == "retry_loop"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["metrics"]["attempts"], 3)
        self.assertTrue(found[0]["metrics"]["sameError"])

    def test_same_error_across_different_calls(self):
        log = Log().human("почини")
        for i, cmd in enumerate(["pytest", "python -m pytest", "make test"]):
            log.call("Bash", {"command": cmd}, f"c{i}")
            log.result(f"c{i}", "ModuleNotFoundError: No module named 'app'", is_error=True)
        found = [f for f in detect_failures(log.steps()) if f["type"] == "repeated_error"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["metrics"]["distinctCalls"], 3)

    def test_error_signature_ignores_line_numbers(self):
        log = Log().human("почини")
        for i in range(3):
            log.call("Bash", {"command": f"node a{i}.js"}, f"c{i}")
            log.result(f"c{i}", f"Error: cannot find module at line {i * 17}", is_error=True)
        found = [f for f in detect_failures(log.steps()) if f["type"] == "repeated_error"]
        self.assertEqual(len(found), 1, "номера строк не должны делать ошибки разными")

    def test_interrupted_tool_result_counts_as_error(self):
        log = Log().human("x").call("Bash", {"command": "sleep 100"}, "c0")
        log.result("c0", "", extra={"interrupted": True})
        steps = log.steps()
        self.assertTrue(next(s for s in steps if s["kind"] == "tool_result")["isError"])

    def test_no_failures_no_findings(self):
        log = Log().human("x").call("Read", {"file_path": "/p/a.ts"}, "c0").result("c0", "содержимое")
        self.assertEqual(detect_failures(log.steps()), [])


class TestEdits(unittest.TestCase):
    def test_revert_detected(self):
        log = Log().human("поменяй порт")
        log.call("Edit", {"file_path": "/p/config.ts", "old_string": "port = 3000", "new_string": "port = 8080"}, "e1")
        log.result("e1", "ok")
        log.call("Bash", {"command": "npm start"}, "b1").result("b1", "fail", is_error=True)
        log.call("Edit", {"file_path": "/p/config.ts", "old_string": "port = 8080", "new_string": "port = 3000"}, "e2")
        log.result("e2", "ok")
        found = [f for f in detect_edit_churn(log.steps()) if f["type"] == "edit_revert"]
        self.assertEqual(len(found), 1)
        self.assertEqual(len(found[0]["stepIds"]), 2)
        self.assertEqual(found[0]["evidence"]["filePath"], "/p/config.ts")

    def test_revert_read_from_tool_use_result(self):
        """Args могут отсутствовать — тогда берём oldString/newString из toolUseResult."""
        log = Log().human("правь")
        log.call("Edit", {}, "e1")
        log.result("e1", "ok", extra={"filePath": "/p/a.ts", "oldString": "A", "newString": "B"})
        log.call("Edit", {}, "e2")
        log.result("e2", "ok", extra={"filePath": "/p/a.ts", "oldString": "B", "newString": "A"})
        found = [f for f in detect_edit_churn(log.steps()) if f["type"] == "edit_revert"]
        self.assertEqual(len(found), 1)

    def test_file_churn_from_four_edits(self):
        log = Log().human("правь")
        for i in range(4):
            log.call("Edit", {"file_path": "/p/a.ts", "old_string": f"v{i}", "new_string": f"v{i + 1}"}, f"e{i}")
            log.result(f"e{i}", "ok")
        found = [f for f in detect_edit_churn(log.steps()) if f["type"] == "file_churn"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["metrics"]["edits"], 4)

    def test_three_edits_are_fine(self):
        log = Log().human("правь")
        for i in range(3):
            log.call("Edit", {"file_path": "/p/a.ts", "old_string": f"v{i}", "new_string": f"v{i + 1}"}, f"e{i}")
            log.result(f"e{i}", "ok")
        self.assertEqual([f for f in detect_edit_churn(log.steps()) if f["type"] == "file_churn"], [])

    def test_rewrite_loop(self):
        log = Log().human("перепиши")
        for i in range(2):
            log.call("Write", {"file_path": "/p/a.ts", "content": f"версия {i}"}, f"w{i}")
            log.result(f"w{i}", "ok")
        found = [f for f in detect_edit_churn(log.steps()) if f["type"] == "rewrite_loop"]
        self.assertEqual(len(found), 1)


class TestHuman(unittest.TestCase):
    def test_corrections_counted(self):
        log = Log().human("сделай форму").human("нет, не то").human("стоп, верни как было")
        found = [f for f in detect_human_interventions(log.steps()) if f["type"] == "human_corrections"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["metrics"]["corrections"], 2)

    def test_long_message_is_not_a_correction(self):
        long_text = "нет " + "подробное описание новой задачи " * 12
        log = Log().human(long_text).human("нет, не так")
        self.assertEqual([f for f in detect_human_interventions(log.steps()) if f["type"] == "human_corrections"], [])

    def test_repeated_instruction_is_one_finding_per_cluster(self):
        msg = "пожалуйста, сначала проверь scripts в package.json перед запуском тестов"
        log = Log().human(msg).human(msg + " ещё раз").human(msg + " я повторяю")
        found = [f for f in detect_human_interventions(log.steps()) if f["type"] == "repeated_instruction"]
        self.assertEqual(len(found), 1, "цепочка похожих реплик — одна находка, а не три")
        self.assertEqual(found[0]["metrics"]["repeats"], 3)

    def test_interruptions(self):
        log = Log().human("[Request interrupted by user]").human("[Request interrupted by user]")
        found = [f for f in detect_human_interventions(log.steps()) if f["type"] == "interruptions"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["metrics"]["interruptions"], 2)

    def test_synthetic_messages_ignored(self):
        log = Log().human("<system-reminder>нет, не то</system-reminder>").human("<task-notification>стоп</task-notification>")
        self.assertEqual(detect_human_interventions(log.steps()), [])


class TestTiming(unittest.TestCase):
    def test_idle_gap_detected(self):
        log = Log().human("сделай").call("Bash", {"command": "ls"}, "c0")
        log.at_minute(90).result("c0", "ok")
        found = [f for f in detect_idle_and_slow(log.steps()) if f["type"] == "idle_gaps"]
        self.assertEqual(len(found), 1)
        self.assertGreaterEqual(found[0]["metrics"]["idleMinutes"], 60)

    def test_no_timestamps_no_crash(self):
        steps = parse_log(json.dumps({"type": "assistant", "message": {"id": "m", "content": [{"type": "text", "text": "x"}]}}))["steps"]
        self.assertEqual(detect_idle_and_slow(steps), [])


class TestRunAll(unittest.TestCase):
    def test_findings_sorted_and_identified(self):
        findings, warnings = run_all(npm_test_log(4).steps())
        self.assertTrue(findings)
        self.assertEqual([f["id"] for f in findings], [f"f{i + 1}" for i in range(len(findings))])
        sev = [f["severity"] for f in findings]
        self.assertEqual(sev, sorted(sev, reverse=True))
        self.assertEqual(warnings, [])

    def test_step_ids_always_exist(self):
        steps = npm_test_log(4).steps()
        valid = {s["id"] for s in steps}
        findings, _ = run_all(steps)
        for f in findings:
            self.assertTrue(f["stepIds"])
            self.assertTrue(set(f["stepIds"]).issubset(valid), f["type"])

    def test_broken_detector_does_not_kill_report(self):
        import analysis.detectors as det

        def boom(steps):
            raise RuntimeError("сломался")

        original = det.DETECTORS
        det.DETECTORS = (("boom", boom),) + original
        try:
            findings, warnings = run_all(npm_test_log(3).steps())
        finally:
            det.DETECTORS = original
        self.assertTrue(findings)
        self.assertTrue(any("boom" in w for w in warnings))

    def test_clean_session_has_no_findings(self):
        log = Log().human("прочитай файл и скажи, что там")
        log.call("Read", {"file_path": "/p/a.ts"}, "c0").result("c0", "export const a = 1")
        findings, _ = run_all(log.steps())
        self.assertEqual(findings, [], "на нормальной сессии придумывать проблемы нельзя")

    def test_analyze_log_contract(self):
        r = analyze_log(npm_test_log(3).text())
        for key in ("meta", "kpi", "findings", "recommendations", "steps"):
            self.assertIn(key, r)
        self.assertEqual(r["meta"]["format"], "claude-code")
        self.assertGreater(r["kpi"]["failures"], 0)
        self.assertIsNotNone(r["kpi"]["cost"])

    def test_analyze_survives_broken_log(self):
        r = analyze_log('{"type":"assistant","message":{"id":"m","content":[{"type":"tex')
        self.assertEqual(r["findings"], [])
        self.assertTrue(r["meta"]["warnings"])


class TestRealLogs(unittest.TestCase):
    """Главный тест: незнакомый настоящий лог не должен ронять разбор."""

    def setUp(self):
        self.files = sorted(glob.glob(os.path.expanduser("~/.claude/projects/**/*.jsonl"), recursive=True))
        if not self.files:
            self.skipTest("нет настоящих логов на этой машине")

    def test_every_real_log_analyzed(self):
        for f in self.files:
            if os.path.getsize(f) > 20_000_000:
                continue
            r = analyze_file(f)
            self.assertEqual(r["meta"]["format"], "claude-code", f)
            valid = {s["id"] for s in r["steps"]}
            for finding in r["findings"]:
                self.assertTrue(set(finding["stepIds"]).issubset(valid), f"{f}: {finding['type']}")
                self.assertTrue(finding["title"])
                self.assertTrue(finding["explanation"])

    def test_truncated_real_log(self):
        f = max((x for x in self.files if os.path.getsize(x) < 5_000_000), key=os.path.getsize)
        with open(f, encoding="utf-8", errors="replace") as fh:
            raw = fh.read()
        r = analyze_log(raw[: len(raw) // 2])
        self.assertIsInstance(r["findings"], list)


if __name__ == "__main__":
    unittest.main()
