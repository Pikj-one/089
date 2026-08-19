import json, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from vulnhunt.config import Config
from vulnhunt.models import TaskSpec, TaskResultStatus
from vulnhunt.cli.base import ProcResult
from vulnhunt.cli.claude_code import ClaudeWrapper
from vulnhunt.cli.codex import CodexWrapper


class WrapperUnitTests(unittest.TestCase):
    def test_claude_wrapper_parses_plan_json(self):
        output = json.dumps({"type": "result", "result": json.dumps({"tasks": [{"id": "task_1", "title": "scan", "description": "scan it"}]})})
        with patch("vulnhunt.cli.claude_code.run_process", return_value=ProcResult(0, output, "")):
            plan = ClaudeWrapper(Config()).plan("audit", 1, [], ".")
        self.assertEqual(plan.tasks[0].id, "task_1")

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


if __name__ == "__main__": unittest.main()
