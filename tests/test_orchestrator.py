import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from vulnhunt.config import Config
from vulnhunt.models import Run, RunStatus
from vulnhunt.state import RunStore
from vulnhunt.cli.claude_code import ClaudeWrapper
from vulnhunt.cli.codex import CodexWrapper
from vulnhunt.orchestrator import Orchestrator

class OrchestratorTests(unittest.TestCase):
    def test_dry_run_reaches_complete(self):
        with tempfile.TemporaryDirectory() as d:
            config = Config(runs_root=d, max_rounds=1, dry_run=True)
            store = RunStore.create(d, Run("r1", "audit", "now", max_rounds=1))
            result = Orchestrator(config, store, ClaudeWrapper(config), CodexWrapper(config)).run_loop()
            self.assertEqual(result.status, RunStatus.COMPLETE)
            self.assertTrue((store.root / "plans/round_001_plan.json").exists())

if __name__ == "__main__": unittest.main()
