import os, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from vulnhunt.config import Config
from vulnhunt.models import TaskSpec, TaskResultStatus
from vulnhunt.cli.claude_code import ClaudeWrapper
from vulnhunt.cli.codex import CodexWrapper

@unittest.skipUnless(os.getenv("VULNHUNT_REAL_TESTS") == "1", "set VULNHUNT_REAL_TESTS=1 to call local CLIs")
class RealCliTests(unittest.TestCase):
    def setUp(self):
        self.config = Config(claude_exec="claude", codex_exec="codex", claude_timeout_s=120, codex_timeout_s=120)

    def test_claude_real_plan(self):
        plan = ClaudeWrapper(self.config).plan("只检查项目入口并给出一个最小审计计划", 1, [], ".")
        self.assertEqual(plan.round, 1)
        self.assertIsInstance(plan.tasks, list)

    def test_codex_real_result(self):
        with tempfile.TemporaryDirectory() as d:
            workspace = Path(d)
            result = CodexWrapper(self.config).exec_task(TaskSpec("task_1", "输出最小 JSON 结果", "只输出一个成功结果，不执行修改", required_output="status、summary、findings"), workspace)
            self.assertEqual(result.status, TaskResultStatus.SUCCESS)
            self.assertTrue((workspace / "_last_message.json").exists())

if __name__ == "__main__": unittest.main()
