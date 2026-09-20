"""Contracts across the real parser, backend and grounded ML module."""

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault('DB__URL', 'postgresql+asyncpg://postgres:postgres@localhost:5433/postgres')

from agent_review import review_async
from agent_review.grounding import GroundingError, render_judgment
from agent_review.schemas import Citation, ModelDecision
from analysis import analyze_log
from analysis.parser import parse_file
from reports.builder import build_ml_packet, build_report, to_steps
from reports.exporters import render_report_md
from schemas import Actor, AnalysisStatus, Report
from tests.test_detectors import Log, npm_test_log


class IntegrationTests(unittest.TestCase):
    def make(self, text):
        raw = analyze_log(text)
        steps = to_steps(raw, 'session-test')
        packet, warnings = build_ml_packet(raw, steps, 'sha-test')
        return raw, steps, packet, warnings

    def test_actual_findings_link_to_persisted_steps_and_source_lines(self):
        raw, steps, packet, warnings = self.make(npm_test_log().text())
        report = build_report(raw, analysis_id='analysis-test', session_id='session-test', llm_enabled=False)
        self.assertTrue(report.findings)
        self.assertTrue(packet.candidates)
        ids = {s.step_id for s in steps}
        for finding in report.findings:
            self.assertTrue(set(finding.evidence_step_ids) <= ids)
            self.assertIsNone(finding.likely_cause)
            self.assertEqual(finding.explanation, finding.facts['fact_text'])
        for c in packet.candidates:
            self.assertTrue(all(e.step_id in ids and e.source_line > 0 for e in c.evidence))
        self.assertEqual(report.provenance.model, None)
        self.assertNotIn('мок', report.model_dump_json())
        Report.model_validate_json(report.model_dump_json())

    def test_ml_receives_compression_and_returns_citations_in_http_report(self):
        raw, steps, packet, warnings = self.make(npm_test_log().text())
        candidates = {c.candidate_id: c for c in packet.candidates}
        async def parse(**kwargs):
            incoming = json.loads(kwargs['input'])['candidate']
            self.assertNotIn('priority', incoming)
            c = candidates[incoming['candidate_id']]
            refs = {sid for f in c.facts for sid in f.evidence_step_ids}
            decision = ModelDecision(candidate_id=c.candidate_id, assessment='uncertain',
                fact_ids=[f.fact_id for f in c.facts], advice='inspect_observation', alternative_id=None,
                citations=[Citation(step_id=e.step_id, quote=e.text[:100]) for e in c.evidence if e.step_id in refs])
            return SimpleNamespace(status='completed', output_parsed=decision, usage=None)
        ml = asyncio.run(review_async(packet, client=SimpleNamespace(responses=SimpleNamespace(parse=parse))))
        report = build_report(raw, analysis_id='a', session_id='session-test', llm_enabled=True, ml=ml)
        self.assertGreater(report.coverage.candidates_explained, 0)
        for f in report.findings:
            if f.explanation_source == 'llm':
                self.assertTrue(f.citations)
                self.assertEqual(f.assessment, 'uncertain')
        self.assertTrue(report.ml_details['findings'][0]['compression'])

    def test_generic_detector_signal_cannot_be_declared_inefficient(self):
        _, _, packet, _ = self.make(npm_test_log().text())
        c = packet.candidates[0]
        d = ModelDecision(candidate_id=c.candidate_id, assessment='inefficient',
            fact_ids=[f.fact_id for f in c.facts], advice='inspect_observation', alternative_id=None,
            citations=[Citation(step_id=e.step_id, quote=e.text[:100]) for e in c.evidence])
        with self.assertRaisesRegex(GroundingError, 'insufficient_basis'):
            render_judgment(c, d)

    def test_oversized_ml_episode_keeps_all_detector_findings(self):
        raw, steps, packet, _ = self.make(npm_test_log().text())
        for s in steps:
            if s.arguments: s.arguments['large_context'] = 'x' * 10000
        packet, warnings = build_ml_packet(raw, steps, 's')
        report = build_report(raw, analysis_id='a', session_id='session-test', llm_enabled=True, warnings=warnings)
        self.assertTrue(warnings)
        self.assertEqual(len(report.findings), len(raw['findings']))
        self.assertEqual(report.status, AnalysisStatus.partial)

    def test_thinking_and_secrets_not_exposed(self):
        rows = [json.loads(line) for line in npm_test_log().text().splitlines()]
        rows[1]['message']['content'].insert(0, {'type': 'thinking', 'thinking': 'PRIVATE_REASONING'})
        rows[1]['message']['content'][1]['input']['api_key'] = 'private-key-value'
        raw, steps, packet, _ = self.make('\n'.join(json.dumps(r) for r in rows))
        serialized = '\n'.join(s.model_dump_json() for s in steps) + packet.model_dump_json()
        self.assertNotIn('PRIVATE_REASONING', serialized)
        self.assertNotIn('private-key-value', serialized)

    def test_unknown_format_never_exports_a_clean_session(self):
        raw, _, _, _ = self.make('{"unrelated":123}')
        report = build_report(raw, analysis_id='a', session_id='s', llm_enabled=False)
        self.assertEqual(report.status, AnalysisStatus.insufficient_data)
        self.assertIn('Данных недостаточно', render_report_md(report))

    def test_duplicate_records_do_not_invent_tool_calls(self):
        text = npm_test_log().text()
        raw = analyze_log(text + text)
        self.assertEqual(raw['kpi']['toolCalls'], 3)

    def test_repeated_error_text_inside_one_result_is_not_multiple_calls(self):
        raw = analyze_log(Log().call('Bash', {'command': 'tool'}, 'c')
            .result('c', 'tool: command not found\ntool: command not found', True).text())
        self.assertFalse(any(f['type'] == 'missing_cli' for f in raw['findings']))

    def test_missing_or_string_error_flag_is_unknown(self):
        for flag in [None, 'false']:
            rows = [json.loads(line) for line in Log().call('Bash', {'command': 'test'}, 'c').result('c', 'out').text().splitlines()]
            rows[-1]['message']['content'][0]['is_error'] = flag
            raw = analyze_log('\n'.join(json.dumps(r) for r in rows))
            self.assertEqual(raw['kpi']['failures'], 0)
            self.assertEqual(raw['kpi']['unknownStatusCount'], 1)
            self.assertIsNone(raw['kpi']['errorRate'])

    def test_tool_ids_from_other_agents_are_not_joined(self):
        rows = [json.loads(line) for line in Log().call('Bash', {'command': 'test'}, 'c').result('c', 'error', True).text().splitlines()]
        rows[0]['agentId'] = 'one'; rows[1]['agentId'] = 'two'
        raw = analyze_log('\n'.join(json.dumps(r) for r in rows))
        self.assertIsNone(raw['steps'][-1]['resultOf'])
        self.assertEqual(raw['kpi']['unknownStatusCount'], 1)

    def test_oversized_line_is_skipped_and_next_source_line_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sample.jsonl'
            path.write_text('x' * 300 + '\n' + '{"type":"user","message":{"content":"hello"}}\n')
            parsed = parse_file(str(path), max_line_bytes=100)
        self.assertEqual(parsed['meta']['badJson'], 1)
        self.assertEqual(parsed['steps'][0]['line'], 2)
        self.assertTrue(parsed['meta']['warnings'])


if __name__ == '__main__':
    unittest.main()
