import json
import unittest
from pathlib import Path

from parsers import link_tool_calls, parse_claude_code_lines, parse_claude_code_log
from schemas import Actor, StepKind, ToolCallStatus


class ClaudeCodeParserTests(unittest.TestCase):
    def test_emits_a_step_for_every_content_block_and_preserves_source(self) -> None:
        lines = [
            '{"type":"assistant","uuid":"event-a","sessionId":"s_7d9",'
            '"timestamp":"2026-09-20T10:00:00Z","message":{"id":"msg-a",'
            '"content":[{"type":"text","text":"Working"},'
            '{"type":"tool_use","id":"tool-1","name":"Bash",'
            '"input":{"command":"npm test"}}]}}\n'
        ]

        steps = list(parse_claude_code_lines(lines))

        self.assertEqual([step.kind for step in steps], [StepKind.assistant_text, StepKind.tool_call])
        self.assertEqual(steps[0].step_id, "s_7d9:line_1:block_0")
        self.assertEqual(steps[1].step_id, "s_7d9:line_1:block_1")
        self.assertEqual(steps[1].source.source_message_id, "msg-a")
        self.assertEqual(steps[1].arguments, {"command": "npm test"})

    def test_tool_result_inside_user_event_is_a_tool_not_a_human(self) -> None:
        lines = [
            '{"type":"user","sessionId":"s_7d9","message":{"content":['
            '{"type":"tool_result","tool_use_id":"tool-1","is_error":true,'
            '"content":"Missing script"}]}}\n'
        ]

        step = next(parse_claude_code_lines(lines))

        self.assertEqual(step.kind, StepKind.tool_result)
        self.assertEqual(step.actor, Actor.tool)
        self.assertTrue(step.is_error)
        self.assertEqual(step.tool_call_id, "tool-1")

    def test_links_tool_calls_by_id_even_when_results_are_not_adjacent(self) -> None:
        steps = list(
            parse_claude_code_lines(
                [
                    '{"type":"assistant","sessionId":"s-1","message":{"content":['
                    '{"type":"tool_use","id":"call-a","name":"Bash","input":{}}]}}\n',
                    '{"type":"assistant","sessionId":"s-1","message":{"content":['
                    '{"type":"tool_use","id":"call-b","name":"Read","input":{}}]}}\n',
                    '{"type":"user","sessionId":"s-1","message":{"content":['
                    '{"type":"tool_result","tool_use_id":"call-a","exit_code":1,"content":"failed"}]}}\n',
                    '{"type":"assistant","sessionId":"s-1","message":{"content":['
                    '{"type":"tool_use","id":"call-c","name":"Edit","input":{}}]}}\n',
                    '{"type":"user","sessionId":"s-1","message":{"content":['
                    '{"type":"tool_result","tool_use_id":"call-b","is_error":false,"content":"ok"}]}}\n',
                ]
            )
        )

        calls = {call.tool_call_id: call for call in link_tool_calls(steps)}

        self.assertEqual(calls["call-a"].result_step_ids, ["s-1:line_3:block_0"])
        self.assertEqual(calls["call-a"].status, ToolCallStatus.error)
        self.assertEqual(calls["call-b"].result_step_ids, ["s-1:line_5:block_0"])
        self.assertEqual(calls["call-b"].status, ToolCallStatus.success)
        self.assertTrue(calls["call-c"].unfinished)
        self.assertEqual(calls["call-c"].status, ToolCallStatus.unknown)

    def test_real_claude_code_fixture(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "claude_code_real_excerpt.jsonl"

        steps = list(parse_claude_code_log(fixture))

        self.assertEqual(len(steps), 8)
        self.assertEqual(steps[0].session_id, "f1466822-085e-4f7e-81f5-c46a97da7e8f")
        self.assertEqual(steps[0].kind, StepKind.system_event)
        self.assertIsNone(steps[0].text)  # internal thinking is never exposed
        self.assertEqual(steps[2].kind, StepKind.tool_call)
        self.assertEqual(steps[2].tool_name, "ToolSearch")
        self.assertEqual(steps[3].kind, StepKind.tool_result)
        self.assertEqual(steps[3].actor, Actor.tool)
        self.assertEqual(steps[5].tool_name, "WebFetch")
        self.assertTrue(steps[6].is_error)
        self.assertEqual(steps[7].text, "[Request interrupted by user for tool use]")

        expected = json.loads((fixture.with_suffix(".expected.json")).read_text())
        actual = [
            {
                "step_id": step.step_id,
                "ordinal": step.ordinal,
                "kind": step.kind.value,
                "actor": step.actor.value,
                "tool_call_id": step.tool_call_id,
                "tool_name": step.tool_name,
                "text": step.text,
                "is_error": step.is_error,
                "warnings": step.warnings,
            }
            for step in steps
        ]
        self.assertEqual(actual, expected)

    def test_invalid_content_block_type_does_not_abort_following_lines(self) -> None:
        steps = list(
            parse_claude_code_lines(
                [
                    '{"type":"assistant","sessionId":"s-1","message":{"content":['
                    '{"type":[],"text":"broken"}]}}\n',
                    '{"type":"user","sessionId":"s-1","message":{"content":"after"}}\n',
                ]
            )
        )

        self.assertEqual(steps[0].kind, StepKind.unknown)
        self.assertIn("invalid_content_block_type", steps[0].warnings)
        self.assertEqual(steps[1].text, "after")
        self.assertEqual(steps[1].ordinal, 1)

    def test_bad_and_unknown_input_does_not_abort_following_lines(self) -> None:
        lines = [
            '{broken\n',
            '{"type":"future-event","sessionId":"s_7d9"}\n',
            '{"type":"user","sessionId":"s_7d9","message":{"content":"Hello"}}\n',
        ]

        steps = list(parse_claude_code_lines(lines))

        self.assertEqual([step.ordinal for step in steps], [0, 1, 2])
        self.assertEqual(steps[0].kind, StepKind.unknown)
        self.assertIn("invalid_json", steps[0].warnings)
        self.assertEqual(steps[1].kind, StepKind.unknown)
        self.assertIn("unknown_event_type", steps[1].warnings)
        self.assertEqual(steps[2].kind, StepKind.human_message)
        self.assertEqual(steps[2].text, "Hello")


if __name__ == "__main__":
    unittest.main()


class LinkIsolationTests(unittest.TestCase):
    def test_result_cannot_be_linked_across_session_or_backwards_in_time(self):
        rows = [
            {"type": "assistant", "sessionId": "a", "message": {"content": [{"type": "tool_use", "id": "c", "name": "Bash", "input": {}}]}},
            {"type": "user", "sessionId": "b", "message": {"content": [{"type": "tool_result", "tool_use_id": "c", "is_error": True}]}},
            {"type": "assistant", "sessionId": "b", "message": {"content": [{"type": "tool_use", "id": "c", "name": "Bash", "input": {}}]}},
        ]
        calls = link_tool_calls(parse_claude_code_lines(json.dumps(r) for r in rows))
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(c.unfinished and c.status == ToolCallStatus.unknown for c in calls))

    def test_explicit_server_session_id_takes_precedence(self):
        steps = list(parse_claude_code_lines(['{"type":"user","sessionId":"client",'
            '"message":{"content":"hello"}}'], session_id="server"))
        self.assertEqual(steps[0].session_id, "server")
        self.assertTrue(steps[0].step_id.startswith("server:"))
