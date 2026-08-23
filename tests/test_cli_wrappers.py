import json, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from vulnhunt.config import Config
from vulnhunt.models import TaskSpec, TaskResultStatus, Run
from vulnhunt.state import RunStore
from vulnhunt.cli.base import ProcResult
from vulnhunt.cli.claude_code import ClaudeWrapper
from vulnhunt.cli.codex import CodexWrapper


class WrapperUnitTests(unittest.TestCase):
    def test_claude_wrapper_parses_plan_json(self):
        output = json.dumps({"type": "result", "result": json.dumps({"tasks": [{"id": "task_1", "title": "scan", "description": "scan it"}]})})
        with patch("vulnhunt.cli.claude_code.run_process", return_value=ProcResult(0, output, "")):
            plan = ClaudeWrapper(Config()).plan("audit", 1, [], ".")
        self.assertEqual(plan.tasks[0].id, "task_1")

    def test_claude_wrapper_captures_plan_subagent_type(self):
        output = json.dumps({"type": "result", "result": json.dumps({"tasks": []})})
        events = [json.dumps({
            "type": "stream_event",
            "event": {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "tool_use", "id": "tool_plan", "name": "Task", "input": {"subagent_type": "Plan"}},
            },
        }), json.dumps({
            "type": "stream_event",
            "event": {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "Plan output"}},
            "parent_tool_use_id": "tool_plan",
            "subagent_type": "Plan",
        })]

        def fake_process(args, **kwargs):
            for event in events:
                kwargs["on_stdout_line"](event)
            return ProcResult(0, output, "")

        logs = []
        with patch("vulnhunt.cli.claude_code.run_process", side_effect=fake_process):
            ClaudeWrapper(Config(), logger=lambda component, message: logs.append((component, message))).plan("audit", 1, [], ".")
        self.assertIn(("CLAUDE-PLAN", "subagent_type=Plan"), logs)
        self.assertIn(("CLAUDE-PLAN", "Plan output"), logs)

    def test_claude_wrapper_streams_subagent_progress(self):
        output = json.dumps({"type": "result", "result": json.dumps({"tasks": []})})
        events = [json.dumps({
            "type": "system", "subtype": "task_started",
            "task_id": "t1", "description": "规划攻击路径", "task_type": "local_agent",
        }), json.dumps({
            "type": "system", "subtype": "task_progress",
            "task_id": "t1", "description": "Running Fetch homepage headers", "last_tool_name": "Bash",
        }), json.dumps({
            "type": "system", "subtype": "task_progress",
            "task_id": "t1", "description": "Running Fetch homepage headers", "last_tool_name": "Bash",
        }), json.dumps({
            "type": "system", "subtype": "task_notification",
            "task_id": "t1", "status": "completed", "summary": "Extract signing logic", "task_type": "local_agent",
        }), json.dumps({
            "type": "system", "subtype": "task_started",
            "task_id": "t2", "description": "Probe API prefixes", "task_type": "local_bash",
        }), json.dumps({
            "type": "system", "subtype": "task_notification",
            "task_id": "t2", "status": "completed", "summary": "Probe API prefixes", "task_type": "local_bash",
        })]

        def fake_process(args, **kwargs):
            for event in events:
                kwargs["on_stdout_line"](event)
            return ProcResult(0, output, "")

        logs = []
        with patch("vulnhunt.cli.claude_code.run_process", side_effect=fake_process):
            ClaudeWrapper(Config(), logger=lambda component, message: logs.append((component, message))).plan("audit", 1, [], ".")
        self.assertIn(("CLAUDE-PLAN", "子代理启动：规划攻击路径"), logs)
        self.assertEqual(0, logs.count(("CLAUDE-PLAN", "正在执行：Running Fetch homepage headers")))
        self.assertIn(("CLAUDE-PLAN", "子代理结束（completed）：Extract signing logic"), logs)
        self.assertIn(("CLAUDE-PLAN", "后台任务启动：Probe API prefixes"), logs)
        self.assertIn(("CLAUDE-PLAN", "后台任务结束（completed）：Probe API prefixes"), logs)

    def test_codex_wrapper_parses_result_file(self):
        def fake_process(args, cwd=None, **kwargs):
            output_file = Path(args[args.index("-o") + 1])
            output_file.write_text(json.dumps({"status": "SUCCESS", "summary": "ok", "findings": []}), encoding="utf-8")
            return ProcResult(0, "", "")

        with tempfile.TemporaryDirectory() as d, patch("vulnhunt.cli.codex.run_process", side_effect=fake_process):
            result = CodexWrapper(Config()).exec_task(TaskSpec("task_1", "test", "test"), Path(d))
        self.assertEqual(result.status, TaskResultStatus.SUCCESS)

    def test_codex_wrapper_resolves_relative_workspace(self):
        captured = {}

        def fake_process(args, cwd=None, **kwargs):
            captured['args'] = args
            captured['cwd'] = cwd
            output_file = Path(args[args.index("-o") + 1])
            output_file.write_text(json.dumps({"status": "SUCCESS", "summary": "ok", "findings": []}), encoding="utf-8")
            return ProcResult(0, "", "")

        with tempfile.TemporaryDirectory() as d, patch("vulnhunt.cli.codex.run_process", side_effect=fake_process):
            relative_workspace = Path(d) / "workspace"
            relative_workspace.mkdir()
            result = CodexWrapper(Config()).exec_task(TaskSpec("task_1", "test", "test"), relative_workspace)

        self.assertEqual(result.status, TaskResultStatus.SUCCESS)
        self.assertTrue(Path(captured['cwd']).is_absolute())
        self.assertTrue(Path(captured['args'][captured['args'].index("-C") + 1]).is_absolute())

    def test_codex_wrapper_passes_blackboard_add_dir(self):
        captured = {}

        def fake_process(args, cwd=None, **kwargs):
            captured['args'] = args
            captured['prompt'] = kwargs.get('input_text', '')
            output_file = Path(args[args.index("-o") + 1])
            output_file.write_text(json.dumps({"status": "SUCCESS", "summary": "ok", "findings": []}), encoding="utf-8")
            return ProcResult(0, "", "")

        with tempfile.TemporaryDirectory() as d, patch("vulnhunt.cli.codex.run_process", side_effect=fake_process):
            store = RunStore.create(d, Run("r1", "audit", "now"))
            workspace = store.root / "workspaces" / "round_001_task_1"
            workspace.mkdir(parents=True)
            result = CodexWrapper(Config(), store=store).exec_task(TaskSpec("task_1", "test", "test"), workspace)

        self.assertEqual(result.status, TaskResultStatus.SUCCESS)
        self.assertIn("--add-dir", captured['args'])
        blackboard = str((store.root / "blackboard").resolve())
        self.assertEqual(captured['args'][captured['args'].index("--add-dir") + 1], blackboard)
        self.assertIn(blackboard, captured['prompt'])

    def test_codex_prompt_enforces_blackboard_contract(self):
        captured = {}

        def fake_process(args, cwd=None, **kwargs):
            captured['prompt'] = kwargs.get('input_text', '')
            output_file = Path(args[args.index("-o") + 1])
            output_file.write_text(json.dumps({"status": "SUCCESS", "summary": "ok", "findings": []}), encoding="utf-8")
            return ProcResult(0, "", "")

        with tempfile.TemporaryDirectory() as d, patch("vulnhunt.cli.codex.run_process", side_effect=fake_process):
            store = RunStore.create(d, Run("r1", "audit", "now"))
            workspace = store.root / "workspaces" / "round_001_task_1"
            workspace.mkdir(parents=True)
            CodexWrapper(Config(), store=store).exec_task(TaskSpec("task_1", "test", "test"), workspace)

        prompt = captured['prompt']
        self.assertIn("共享黑板契约", prompt)
        self.assertIn("下载前先查黑板", prompt)
        self.assertIn("round_001_task_1_umi.js", prompt)  # 命名规范带工作目录名前缀
        self.assertIn("禁止重复下载", prompt)
        self.assertIn("禁止访问或写入任何其他路径", prompt)

    def test_codex_prompt_without_blackboard_has_no_contract(self):
        captured = {}

        def fake_process(args, cwd=None, **kwargs):
            captured['prompt'] = kwargs.get('input_text', '')
            output_file = Path(args[args.index("-o") + 1])
            output_file.write_text(json.dumps({"status": "SUCCESS", "summary": "ok", "findings": []}), encoding="utf-8")
            return ProcResult(0, "", "")

        with tempfile.TemporaryDirectory() as d, patch("vulnhunt.cli.codex.run_process", side_effect=fake_process):
            CodexWrapper(Config()).exec_task(TaskSpec("task_1", "test", "test"), Path(d))

        self.assertNotIn("共享黑板契约", captured['prompt'])


if __name__ == "__main__": unittest.main()
