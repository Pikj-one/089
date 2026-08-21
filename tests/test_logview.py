import json, sys, unittest
from pathlib import Path
from tempfile import TemporaryDirectory
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from vulnhunt.logview import AggregateSink, ClaudeLogRenderer, LogAction, StreamAction, replay_file, truncate


class LogViewTests(unittest.TestCase):
    def test_system_noise_and_progress_are_compacted(self):
        renderer = ClaudeLogRenderer()
        self.assertEqual(renderer.feed({"type": "system", "subtype": "thinking_tokens"}), [])
        event = {"type": "system", "subtype": "task_progress", "task_id": "t", "description": "same"}
        self.assertEqual(renderer.feed(event), [LogAction("CLAUDE-PLAN", "正在执行：same")])
        self.assertEqual(renderer.feed(event), [])

    def test_tool_input_is_assembled_and_result_is_truncated(self):
        renderer = ClaudeLogRenderer()
        renderer.feed({"type": "stream_event", "event": {"type": "content_block_start", "index": 0, "content_block": {"type": "tool_use", "id": "tool", "name": "Bash"}}})
        renderer.feed({"type": "stream_event", "event": {"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": '{"command":"ls"}'}}})
        actions = renderer.feed({"type": "stream_event", "event": {"type": "content_block_stop", "index": 0}})
        self.assertEqual(actions[0].message, 'tool: Bash {"command": "ls"}')
        result = renderer.feed({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "tool", "is_error": True, "content": "x" * 2500}]}})
        self.assertIn("[ERROR]", result[0].message)
        self.assertIn("truncated", result[0].message)

    def test_stream_and_replay_sink(self):
        renderer = ClaudeLogRenderer()
        self.assertEqual(renderer.feed({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hello"}}}), [StreamAction("CLAUDE", "hello")])
        with TemporaryDirectory() as d:
            path = Path(d) / "claude_round_001.jsonl"
            path.write_text("\n".join(json.dumps({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": x}}}) for x in ("a", "b")) + "\n", encoding="utf-8")
            lines = []
            replay_file(path, AggregateSink(lambda c, m: lines.append((c, m))))
            self.assertEqual(lines, [("CLAUDE", "ab")])

    def test_truncate(self):
        self.assertIn("truncated", truncate("abcdef", 3))
        self.assertIn("lines truncated", truncate("a\nb\nc", 99, 1))


if __name__ == "__main__": unittest.main()
