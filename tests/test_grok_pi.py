"""Grok / Pi loader 与项目编码测试（标准库 unittest）。"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import session_digest as sd  # noqa: E402


class TestLoadGrok(unittest.TestCase):
    def test_strips_system_reasoning_keeps_user_query_and_tools(self):
        lines = [
            {"type": "system", "content": "You are Grok"},
            {
                "type": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "<user_info>x</user_info>\n"
                            "<system-reminder>noise</system-reminder>\n"
                            "<user_query>\nhello\n</user_query>"
                        ),
                    }
                ],
            },
            {"type": "reasoning", "id": "r1", "summary": "think"},
            {
                "type": "assistant",
                "content": "hi",
                "tool_calls": [
                    {
                        "id": "c1",
                        "name": "read_file",
                        "arguments": '{"target_file":"a.py"}',
                    }
                ],
            },
            {"type": "tool_result", "tool_call_id": "c1", "content": "ok"},
        ]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "chat_history.jsonl"
            p.write_text(
                "\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8"
            )
            turns = sd.load_grok(p)
        roles = [t["role"] for t in turns]
        self.assertEqual(roles, ["user", "assistant"])
        user_text = " ".join(
            b["text"] for b in turns[0]["blocks"] if b["type"] == "text"
        )
        self.assertIn("hello", user_text)
        self.assertNotIn("user_info", user_text)
        self.assertNotIn("system-reminder", user_text)
        self.assertNotIn("noise", user_text)
        types = [b["type"] for b in turns[1]["blocks"]]
        self.assertIn("tool_use", types)
        self.assertIn("tool_result", types)
        tool = next(b for b in turns[1]["blocks"] if b["type"] == "tool_use")
        self.assertEqual(tool["name"], "read_file")
        self.assertEqual(tool["input"]["target_file"], "a.py")


class TestLoadPi(unittest.TestCase):
    def test_message_toolcall_and_toolresult(self):
        lines = [
            {"type": "session", "version": 3, "id": "abc", "cwd": "/tmp/proj"},
            {
                "type": "message",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": "q"}],
                },
            },
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "thinking": "nope"},
                        {"type": "text", "text": "a"},
                        {
                            "type": "toolCall",
                            "id": "t1",
                            "name": "bash",
                            "arguments": {"command": "ls"},
                        },
                    ],
                },
            },
            {
                "type": "message",
                "message": {
                    "role": "toolResult",
                    "toolCallId": "t1",
                    "toolName": "bash",
                    "content": [{"type": "text", "text": "out"}],
                    "isError": False,
                },
            },
        ]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.jsonl"
            p.write_text(
                "\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8"
            )
            turns = sd.load_pi(p)
        self.assertEqual([t["role"] for t in turns], ["user", "assistant"])
        self.assertTrue(
            any(
                b.get("type") == "text" and b.get("text") == "a"
                for b in turns[1]["blocks"]
            )
        )
        self.assertTrue(
            any(
                b.get("type") == "tool_use" and b.get("name") == "bash"
                for b in turns[1]["blocks"]
            )
        )
        self.assertTrue(
            any(b.get("type") == "tool_result" for b in turns[1]["blocks"])
        )
        self.assertFalse(
            any(b.get("type") == "thinking" for b in turns[1]["blocks"])
        )


class TestProjectEnc(unittest.TestCase):
    def test_pi_and_grok_encoding(self):
        path = "/Users/me/Agent/Foo"
        self.assertEqual(sd.enc_pi(path), "--Users-me-Agent-Foo--")
        self.assertEqual(sd.enc_grok(path), quote(path, safe=""))


if __name__ == "__main__":
    unittest.main()
