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

    def test_codex_wrapper_tolerates_text_preamble(self):
        # codex 会在 JSON 前写解释文字（如 "All work complete..."），必须剥离后再解析，否则 findings 全丢。
        def fake_process(args, cwd=None, **kwargs):
            output_file = Path(args[args.index("-o") + 1])
            output_file.write_text(
                "All work complete. Final report written to `blackboard/task_1_findings.json`, subprocesses cleaned up.\n\n"
                + json.dumps({"status": "PARTIAL", "summary": "ok", "findings": [{"id": "F1"}]}),
                encoding="utf-8",
            )
            return ProcResult(0, "", "")

        with tempfile.TemporaryDirectory() as d, patch("vulnhunt.cli.codex.run_process", side_effect=fake_process):
            result = CodexWrapper(Config()).exec_task(TaskSpec("task_1", "test", "test"), Path(d))
        self.assertEqual(result.status, TaskResultStatus.PARTIAL)
        self.assertEqual(result.findings, [{"id": "F1"}])

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

    def test_claude_wrapper_retries_resumed_session_on_broken_pipe(self):
        # 第 2 轮起续接既有会话：claude 子进程启动即退（stdin 写入 Broken pipe）→
        # 放弃旧会话、换全新会话重试一次，run 不再因此整体 FAILED。
        calls = []
        output = json.dumps({"type": "result", "result": json.dumps({"tasks": [{"id": "task_1", "title": "scan", "description": "scan it"}]})})

        def fake_process(args, **kwargs):
            calls.append(args[args.index("--session-id") + 1])
            if len(calls) == 1:
                return ProcResult(-1, "", "[Errno 32] Broken pipe")
            return ProcResult(0, output, "")

        logs = []
        with patch("vulnhunt.cli.claude_code.run_process", side_effect=fake_process):
            wrapper = ClaudeWrapper(Config(), logger=lambda component, message: logs.append((component, message)))
            wrapper.session_id = "old-session"  # 模拟第 2 轮复用既有会话
            plan = wrapper.plan("audit", 2, [], ".")

        self.assertEqual(plan.tasks[0].id, "task_1")
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], "old-session")
        self.assertNotEqual(calls[1], "old-session")
        self.assertTrue(any("已切换新会话重试" in m for c, m in logs))

    def test_claude_wrapper_no_retry_on_first_round_failure(self):
        # 首轮（无既有会话可续）失败不应重试，直接抛错暴露原因。
        with patch("vulnhunt.cli.claude_code.run_process", return_value=ProcResult(-1, "", "boom")):
            with self.assertRaises(RuntimeError):
                ClaudeWrapper(Config()).plan("audit", 1, [], ".")

    def test_claude_wrapper_no_retry_on_resume_timeout(self):
        # 续会话但超时：这是规划跑太久被强杀，不是启动即退，重试无意义，直接抛错。
        wrapper = ClaudeWrapper(Config())
        wrapper.session_id = "old-session"
        with patch("vulnhunt.cli.claude_code.run_process", return_value=ProcResult(-1, "", "", True)):
            with self.assertRaises(RuntimeError):
                wrapper.plan("audit", 2, [], ".")


if __name__ == "__main__": unittest.main()
