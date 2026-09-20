"""Тесты того, что детектор отдаёт наружу: покрытие направлений, полосы
значимости, рекомендации и готовый файл правил."""

import glob
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from analysis import analyze_file, analyze_log  # noqa: E402
from analysis.coverage import CLEAN, DIRECTIONS, FOUND, INSUFFICIENT  # noqa: E402
from analysis.detectors import FINDING_TYPES  # noqa: E402
from analysis.recommendations import CLAUDE_MD, RULE, SKILL, TEMPLATES  # noqa: E402
from analysis.severity import BANDS  # noqa: E402
from tests.test_hard import call_line, human_line, result_line  # noqa: E402

ARTIFACT_TYPES = {CLAUDE_MD, RULE, SKILL}


def npm_loop(times: int = 4) -> str:
    lines = [human_line("почини тесты", 0)]
    for i in range(times):
        lines += [call_line("Bash", {"command": "npm test"}, f"c{i}", i * 2 + 1),
                  result_line(f"c{i}", 'npm error Missing script: "test"', i * 2 + 2, is_error=True)]
    return "\n".join(lines)


class TestCoverage(unittest.TestCase):
    """По каждому из шести направлений отчёт обязан сказать что-то определённое."""

    def test_six_directions_always_present(self):
        for log in (npm_loop(), "", '{"битый', human_line("привет", 0)):
            cov = analyze_log(log)["coverage"]
            self.assertEqual([d["direction"] for d in cov], [d["id"] for d in DIRECTIONS])
            for d in cov:
                self.assertIn(d["status"], (FOUND, CLEAN, INSUFFICIENT))
                self.assertTrue(d["note"])

    def test_status_matches_findings(self):
        report = analyze_log(npm_loop())
        ids = {f["id"] for f in report["findings"]}
        for d in report["coverage"]:
            if d["status"] == FOUND:
                self.assertGreater(d["findings"], 0)
                self.assertTrue(set(d["findingIds"]).issubset(ids))
            else:
                self.assertEqual(d["findings"], 0)
            if d["status"] == CLEAN:
                self.assertGreater(sum(d["checked"].values()), 0, "чисто можно говорить только при данных")
            if d["status"] == INSUFFICIENT and "меньше трёх участков" not in d["note"]:
                self.assertEqual(sum(d["checked"].values()), 0)

    def test_empty_log_is_insufficient_everywhere(self):
        cov = analyze_log("")["coverage"]
        self.assertTrue(all(d["status"] == INSUFFICIENT for d in cov))

    def test_clean_direction_reports_denominator(self):
        """Лог без единой правки файлов: направление правок обязано сказать «данных нет»,
        а направление повторов — «проверено N вызовов»."""
        report = analyze_log(npm_loop())
        edits = next(d for d in report["coverage"] if d["direction"] == "edits")
        repeats = next(d for d in report["coverage"] if d["direction"] == "repeats")
        self.assertEqual(edits["status"], INSUFFICIENT)
        self.assertEqual(edits["checked"]["fileEdits"], 0)
        self.assertEqual(repeats["status"], FOUND)
        self.assertGreater(repeats["checked"]["toolCalls"], 0)


class TestSeverityBands(unittest.TestCase):
    def test_every_finding_has_band_and_rules(self):
        report = analyze_log(npm_loop())
        self.assertTrue(report["findings"])
        for f in report["findings"]:
            self.assertIn(f["severityBand"], BANDS)
            self.assertTrue(f["severityRules"], f"{f['type']} без объяснения полосы")
            self.assertIn(f["evidenceStrength"], ("direct", "indirect"))

    def test_sorted_by_band_then_number(self):
        report = analyze_file(_biggest_log()) if _biggest_log() else None
        if report is None:
            self.skipTest("нет настоящих логов")
        order = {b: i for i, b in enumerate(BANDS)}
        keys = [(order[f["severityBand"]], -f["severity"]) for f in report["findings"]]
        self.assertEqual(keys, sorted(keys), "находки не отсортированы по полосам")

    def test_confirmed_retry_loop_is_high(self):
        f = next(x for x in analyze_log(npm_loop(4))["findings"] if x["type"] == "retry_loop")
        self.assertEqual(f["severityBand"], "высокая")

    def test_pause_is_low_and_informational(self):
        log = "\n".join([human_line("сделай", 0), call_line("Bash", {"command": "ls"}, "c0", 1),
                         result_line("c0", "ok", 5000)])
        f = next((x for x in analyze_log(log)["findings"] if x["type"] == "idle_gaps"), None)
        self.assertIsNotNone(f)
        self.assertEqual(f["severityBand"], "низкая")
        self.assertTrue(f["informational"])


class TestRecommendations(unittest.TestCase):
    def test_every_finding_type_has_a_template(self):
        self.assertEqual(sorted(set(FINDING_TYPES) - set(TEMPLATES)), [])

    def test_recommendations_are_tied_to_findings(self):
        report = analyze_log(npm_loop())
        ids = {f["id"] for f in report["findings"]}
        self.assertTrue(report["recommendations"])
        for r in report["recommendations"]:
            self.assertTrue(r["findingIds"], "рекомендация без находки — общий совет, так нельзя")
            self.assertTrue(set(r["findingIds"]).issubset(ids))
            self.assertIn(r["artifactType"], ARTIFACT_TYPES)
            self.assertTrue(r["filename"])
            self.assertTrue(r["content"].strip())
            for key in ("action", "rationale", "verify"):
                self.assertTrue(r[key].strip(), f"{r['id']}: пустое поле {key}")

    def test_findings_point_back_to_recommendation(self):
        report = analyze_log(npm_loop())
        rec_ids = {r["id"] for r in report["recommendations"]}
        for f in report["findings"]:
            self.assertIn(f["recommendationId"], rec_ids, f"{f['type']} без рекомендации")

    def test_no_findings_no_recommendations(self):
        log = "\n".join([human_line("прочитай файл", 0),
                         call_line("Read", {"file_path": "/p/a.ts"}, "c0", 1),
                         result_line("c0", "export const a = 1", 2)])
        report = analyze_log(log)
        self.assertEqual(report["findings"], [])
        self.assertEqual(report["recommendations"], [])
        self.assertIn("не предлагается", report["artifacts"]["CLAUDE.generated.md"])

    def test_claude_md_contains_every_patch(self):
        report = analyze_log(npm_loop())
        doc = report["artifacts"]["CLAUDE.generated.md"]
        for r in report["recommendations"]:
            if r["artifactType"] == CLAUDE_MD:
                self.assertIn(r["content"].splitlines()[0], doc)
                self.assertIn(r["verify"], doc)

    def test_skill_draft_appears_for_command_problems(self):
        report = analyze_log(npm_loop())
        skill = next((r for r in report["recommendations"] if r["artifactType"] == SKILL), None)
        self.assertIsNotNone(skill, "кейс просит черновик скилла — его нет")
        self.assertTrue(skill["filename"].endswith("SKILL.md"))
        self.assertTrue(skill["content"].startswith("---\nname: "))
        self.assertIn("description:", skill["content"])

    def test_no_skill_draft_without_command_problems(self):
        log = "\n".join([human_line("[Request interrupted by user]", 0),
                         human_line("[Request interrupted by user]", 1)])
        report = analyze_log(log)
        self.assertTrue(report["findings"])
        self.assertEqual([r for r in report["recommendations"] if r["artifactType"] == SKILL], [])

    def test_recommendations_quote_the_log(self):
        """Рекомендация должна быть привязана к находке, а не сформулирована в общем виде."""
        report = analyze_log(npm_loop())
        rec = next(r for r in report["recommendations"] if r["findingType"] == "retry_loop")
        self.assertTrue(rec["examples"])
        self.assertIn("npm test", json.dumps(rec["examples"], ensure_ascii=False))


class TestErrorDenominator(unittest.TestCase):
    def test_call_without_result_is_unknown_not_success(self):
        log = "\n".join([call_line("Bash", {"command": "ls"}, "c0", 1), result_line("c0", "ok", 2),
                         call_line("Bash", {"command": "sleep 1"}, "c1", 3)])  # результата нет
        kpi = analyze_log(log)["kpi"]
        self.assertEqual(kpi["toolCalls"], 2)
        self.assertEqual(kpi["callsWithKnownStatus"], 1)
        self.assertEqual(kpi["unknownStatusCount"], 1)
        self.assertEqual(kpi["errorRate"], 0.0)

    def test_error_rate_is_none_without_denominator(self):
        log = call_line("Bash", {"command": "ls"}, "c0", 1)
        kpi = analyze_log(log)["kpi"]
        self.assertIsNone(kpi["errorRate"], "нулевой знаменатель — это «нет данных», а не 0%")

    def test_rate_uses_known_status_only(self):
        lines = []
        for i in range(10):
            lines += [call_line("Bash", {"command": f"cmd{i}"}, f"c{i}", i)]
            if i < 6:
                lines += [result_line(f"c{i}", "Error: boom", i, is_error=True)]
        kpi = analyze_log("\n".join(lines))["kpi"]
        self.assertEqual(kpi["callsWithKnownStatus"], 6)
        self.assertEqual(kpi["unknownStatusCount"], 4)
        self.assertEqual(kpi["errorRate"], 1.0)


def _biggest_log():
    files = [f for f in glob.glob(os.path.expanduser("~/.claude/projects/**/*.jsonl"), recursive=True)
             if os.path.getsize(f) < 20_000_000]
    return max(files, key=os.path.getsize) if files else None


class TestRealLogsReport(unittest.TestCase):
    def test_all_real_logs_produce_full_report(self):
        files = sorted(glob.glob(os.path.expanduser("~/.claude/projects/**/*.jsonl"), recursive=True))
        if not files:
            self.skipTest("нет настоящих логов")
        for path in files:
            report = analyze_file(path)
            name = os.path.basename(path)[:8]
            self.assertEqual(len(report["coverage"]), 6, name)
            ids = {f["id"] for f in report["findings"]}
            for r in report["recommendations"]:
                self.assertTrue(set(r["findingIds"]).issubset(ids), name)
            for f in report["findings"]:
                self.assertIn(f["severityBand"], BANDS, name)
                self.assertTrue(f["severityRules"], f"{name}: {f['type']}")
            doc = report["artifacts"]["CLAUDE.generated.md"]
            self.assertTrue(doc.strip(), name)
            json.dumps(report, ensure_ascii=False)  # отчёт обязан сериализоваться целиком


if __name__ == "__main__":
    unittest.main()


class TestMergedFindings(unittest.TestCase):
    """Однотипные находки по одной цели склеиваются в одну со списком эпизодов."""

    def _log_with_episodes(self, episodes: int = 3, per_episode: int = 3) -> str:
        lines = [human_line("поработай", 0)]
        t = 1
        for ep in range(episodes):
            for i in range(per_episode):
                lines += [call_line("Bash", {"command": "docker compose up -d"}, f"c{ep}_{i}", t),
                          result_line(f"c{ep}_{i}", "Error: port is already allocated", t + 1, is_error=True)]
                t += 2
            for j in range(12):  # разрыв, чтобы эпизоды не слиплись в один кластер
                lines += [call_line("Read", {"file_path": f"/p/f{ep}_{j}.ts"}, f"r{ep}_{j}", t),
                          result_line(f"r{ep}_{j}", "ok", t + 1)]
                t += 2
        return "\n".join(lines)

    def test_same_target_becomes_one_finding(self):
        report = analyze_log(self._log_with_episodes())
        repeats = [f for f in report["findings"] if f["type"] == "repeated_call"]
        self.assertEqual(len(repeats), 1, "три эпизода одного вызова — одна находка")
        f = repeats[0]
        self.assertEqual(f["episodeCount"], 3)
        self.assertEqual(f["metrics"]["repeats"], 9)
        self.assertIn("эпизодах", f["title"])

    def test_each_episode_keeps_its_own_evidence(self):
        f = next(x for x in analyze_log(self._log_with_episodes())["findings"] if x["type"] == "repeated_call")
        for ep in f["episodes"]:
            self.assertTrue(ep["callStepIds"], "эпизод без ссылок на шаги нельзя проверить")
            self.assertTrue(ep["evidence"])
            self.assertTrue(set(ep["callStepIds"]).issubset(set(ep["stepIds"])))

    def test_different_targets_stay_separate(self):
        lines = [human_line("поработай", 0)]
        t = 1
        for cmd in ("npm test", "docker compose up -d"):
            for i in range(3):
                lines += [call_line("Bash", {"command": cmd}, f"{cmd[:3]}{i}", t),
                          result_line(f"{cmd[:3]}{i}", "Error: boom", t + 1, is_error=True)]
                t += 2
        repeats = [f for f in analyze_log("\n".join(lines))["findings"] if f["type"] == "repeated_call"]
        self.assertEqual(len(repeats), 2, "разные команды склеивать нельзя")

    def test_merged_is_not_weaker_than_its_episodes(self):
        f = next(x for x in analyze_log(self._log_with_episodes())["findings"] if x["type"] == "repeated_call")
        self.assertGreaterEqual(f["severity"], max(ep["severity"] for ep in f["episodes"]))
        self.assertIn("эпизодов в сессии: 3", f["severityRules"])

    def test_session_level_findings_untouched(self):
        log = "\n".join(human_line("[Request interrupted by user]", i) for i in range(3))
        f = next(x for x in analyze_log(log)["findings"] if x["type"] == "interruptions")
        self.assertNotIn("episodes", f)

    def test_merged_finding_still_has_recommendation(self):
        report = analyze_log(self._log_with_episodes())
        rec_ids = {r["id"] for r in report["recommendations"]}
        for f in report["findings"]:
            self.assertIn(f["recommendationId"], rec_ids)

    def _churn_log(self, files: int) -> str:
        lines = [human_line("правь", 0)]
        t = 1
        for n in range(files):
            for i in range(4):
                lines += [call_line("Edit", {"file_path": f"/p/file{n}.ts",
                                             "old_string": f"v{i}", "new_string": f"v{i + 1}"}, f"e{n}_{i}", t),
                          result_line(f"e{n}_{i}", "ok", t + 1)]
                t += 2
        return "\n".join(lines)

    def test_few_per_file_findings_stay_separate(self):
        findings = [f for f in analyze_log(self._churn_log(3))["findings"] if f["type"] == "file_churn"]
        self.assertEqual(len(findings), 3, "на коротком логе три файла показываем отдельно")
        self.assertTrue(all("episodes" not in f for f in findings))

    def test_many_per_file_findings_are_merged(self):
        findings = [f for f in analyze_log(self._churn_log(6))["findings"] if f["type"] == "file_churn"]
        self.assertEqual(len(findings), 1, "шесть файлов сворачиваем в одну находку")
        f = findings[0]
        self.assertEqual(f["episodeCount"], 6)
        self.assertEqual(f["metrics"]["edits"], 24)
        for ep in f["episodes"]:
            self.assertTrue(ep["evidence"]["filePath"], "в эпизоде должен остаться конкретный файл")
