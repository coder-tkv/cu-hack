"""Тесты парсера: порченые логи, отсутствующие поля, неизвестные события."""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from analysis.parser import Parser, parse_log, session_timing  # noqa: E402

USAGE = {
    "input_tokens": 10,
    "output_tokens": 20,
    "cache_read_input_tokens": 100,
    "cache_creation_input_tokens": 5,
}


def L(obj) -> str:
    return json.dumps(obj, ensure_ascii=False) + "\n"


def asst(msg_id, blocks, **extra) -> str:
    return L(
        {
            "type": "assistant",
            "uuid": f"u{msg_id}",
            "sessionId": "s1",
            "cwd": "/p",
            "timestamp": "2026-09-20T10:00:00.000Z",
            "message": {
                "id": f"msg_{msg_id}",
                "role": "assistant",
                "model": "claude-opus-5",
                "content": blocks,
                "usage": USAGE,
            },
            **extra,
        }
    )


def user_text(text) -> str:
    return L({"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}})


class TestParser(unittest.TestCase):
    def test_empty_file(self):
        r = parse_log("")
        self.assertEqual(r["steps"], [])
        self.assertEqual(r["meta"]["format"], "empty")

    def test_garbage_input_types(self):
        for bad in (None, 123, {}, [], b"x"):
            r = parse_log(bad)
            self.assertIsInstance(r["steps"], list)

    def test_truncated_last_line(self):
        log = asst(1, [{"type": "text", "text": "привет"}]) + '{"type":"assistant","message":{"cont'
        r = parse_log(log)
        self.assertEqual(len(r["steps"]), 1)
        self.assertEqual(r["meta"]["badJson"], 1)
        self.assertTrue(any("строка 2" in w for w in r["meta"]["warnings"]))

    def test_unknown_event_types(self):
        log = L({"type": "atis-latch", "foo": 1}) + L({"type": "совсем-новый-тип"}) + L({"nothing": True})
        r = parse_log(log)
        self.assertEqual(len(r["steps"]), 3)
        self.assertTrue(all(s["kind"] == "other" for s in r["steps"]))
        self.assertEqual(r["steps"][1]["raw"], "совсем-новый-тип")
        self.assertEqual(r["steps"][2]["raw"], "unknown")

    def test_missing_fields(self):
        log = (
            L({"type": "assistant"})
            + L({"type": "assistant", "message": {"id": "m1", "content": None}})
            + L({"type": "user", "message": {"role": "user"}})
            + L({"type": "assistant", "message": {"id": "m2", "content": [{"type": "text", "text": "ок"}]}})
        )
        r = parse_log(log)
        self.assertEqual(len(r["steps"]), 4)
        self.assertTrue(all(s["ts"] is None for s in r["steps"]))
        self.assertEqual(r["steps"][3]["kind"], "assistant_text")

    def test_non_object_json_lines(self):
        r = parse_log('[1,2,3]\n"строка"\n42\n')
        self.assertEqual(r["steps"], [])
        self.assertEqual(r["meta"]["badJson"], 3)

    def test_content_as_string(self):
        log = asst(1, "просто текст") + L({"type": "user", "message": {"role": "user", "content": "сделай X"}})
        r = parse_log(log)
        self.assertEqual(r["steps"][0]["kind"], "assistant_text")
        self.assertEqual(r["steps"][1]["kind"], "human")
        self.assertFalse(r["steps"][1]["synthetic"])

    def test_usage_counted_once_per_message_id(self):
        log = (
            asst(7, [{"type": "thinking", "thinking": "думаю"}])
            + asst(7, [{"type": "text", "text": "отвечаю"}])
            + asst(7, [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}}])
        )
        r = parse_log(log)
        total_out = sum(s["usage"]["out"] for s in r["steps"] if s["usage"])
        self.assertEqual(total_out, 20)

    def test_tool_result_linked_to_call(self):
        log = asst(1, [{"type": "tool_use", "id": "tu_1", "name": "Bash", "input": {"command": "npm test"}}]) + L(
            {
                "type": "user",
                "timestamp": "2026-09-20T10:00:05.000Z",
                "message": {
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": "tu_1", "content": "FAIL", "is_error": True}],
                },
                "toolUseResult": {"stdout": "", "stderr": "boom", "interrupted": False},
            }
        )
        r = parse_log(log)
        call = next(s for s in r["steps"] if s["kind"] == "tool_call")
        res = next(s for s in r["steps"] if s["kind"] == "tool_result")
        self.assertEqual(res["resultOf"], call["id"])
        self.assertEqual(res["tool"], "Bash")
        self.assertTrue(res["isError"])

    def test_orphan_tool_result(self):
        r = parse_log(
            L({"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "нет", "content": "x"}]}})
        )
        self.assertEqual(r["steps"][0]["kind"], "tool_result")
        self.assertIsNone(r["steps"][0]["resultOf"])

    def test_synthetic_vs_human(self):
        log = "".join(
            user_text(t)
            for t in (
                "[Request interrupted by user]",
                "<system-reminder>служебное</system-reminder>",
                "<task-notification>\n<task-id>x</task-id>",
                "Continue from where you left off.",
                "прерывание видно по тексту вроде «[Request interrupted by user]»",
                "стоп, не то",
            )
        )
        r = parse_log(log)
        flags = [(s["synthetic"], s["interrupted"]) for s in r["steps"]]
        self.assertEqual(
            flags,
            [(True, True), (True, False), (True, False), (True, False), (False, False), (False, False)],
        )

    def test_tool_result_with_block_list(self):
        r = parse_log(
            L(
                {
                    "type": "user",
                    "message": {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "a",
                                "content": [{"type": "text", "text": "часть 1"}, {"type": "image"}],
                            }
                        ],
                    },
                }
            )
        )
        self.assertIn("часть 1", r["steps"][0]["text"])

    def test_huge_values_truncated(self):
        r = parse_log(asst(1, [{"type": "tool_use", "id": "t", "name": "Write", "input": {"content": "x" * 200000}}]))
        self.assertLess(len(r["steps"][0]["args"]["content"]), 30000)

    def test_ids_sequential_lines_preserved(self):
        log = "\n" + asst(1, [{"type": "text", "text": "a"}]) + "\n" + asst(2, [{"type": "text", "text": "b"}])
        r = parse_log(log)
        self.assertEqual([(s["id"], s["line"]) for s in r["steps"]], [(1, 2), (2, 4)])

    def test_foreign_format_not_claimed_as_claude_code(self):
        r = parse_log(L({"event": "tool", "name": "x"}) + L({"event": "msg"}))
        self.assertEqual(r["meta"]["format"], "unknown")
        self.assertEqual(len(r["steps"]), 2)

    def test_session_timing_excludes_idle(self):
        t0 = 1_758_369_600_000
        steps = [{"ts": t0 + d} for d in (0, 60_000, 120_000, 3 * 3_600_000, 3 * 3_600_000 + 60_000)]
        r = session_timing(steps)
        self.assertEqual(r["activeMin"], 3)
        self.assertEqual(r["spanMin"], 181)
        self.assertEqual(len(r["idleGaps"]), 1)

    def test_streaming_matches_whole_file(self):
        log = asst(1, [{"type": "text", "text": "a"}]) + asst(
            2, [{"type": "tool_use", "id": "t", "name": "Read", "input": {}}]
        )
        p = Parser()
        for line in log.split("\n"):
            p.line(line)
        self.assertEqual(
            [s["kind"] for s in p.finish()["steps"]],
            [s["kind"] for s in parse_log(log)["steps"]],
        )


if __name__ == "__main__":
    unittest.main()
