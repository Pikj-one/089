import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from vulnhunt.config import Config
from vulnhunt.models import TaskSpec, TaskResultStatus
from vulnhunt.cli.claude_code import ClaudeWrapper
from vulnhunt.cli.codex import CodexWrapper

class WrapperUnitTests(unittest.TestCase):
    def test_dry_run_wrappers(self):
        config = Config(dry_run=True)
        plan = ClaudeWrapper(config).plan("audit", 1, [], ".")
        self.assertEqual(len(plan.tasks), 2)
        with tempfile.TemporaryDirectory() as d:
            result = CodexWrapper(config).exec_task(TaskSpec("task_1", "test", "test"), Path(d))
            self.assertEqual(result.status, TaskResultStatus.SUCCESS)

if __name__ == "__main__": unittest.main()
