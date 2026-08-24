import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from vulnhunt.models import Run, RunStatus
from vulnhunt.state import RunStore
from vulnhunt.orchestrator import Orchestrator
from fakes import config as make_config, FakeClaude, FakeCodex


class OrchestratorTests(unittest.TestCase):
    def test_orchestration_reaches_complete(self):
        with tempfile.TemporaryDirectory() as d:
            config = make_config(runs_root=d, max_rounds=1)
            store = RunStore.create(d, Run("r1", "audit", "now", max_rounds=1))
            result = Orchestrator(config, store, FakeClaude(), FakeCodex()).run_loop()
            self.assertEqual(result.status, RunStatus.COMPLETE)
            self.assertTrue((store.root / "plans/round_001_plan.json").exists())


if __name__ == "__main__": unittest.main()
