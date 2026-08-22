import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from vulnhunt.config import Config
from vulnhunt.models import Run, TaskSpec, WorkerResult
from vulnhunt.state import RunStore
from vulnhunt.workers import WorkerPool


class CountingCodex:
    def __init__(self): self.calls = []
    def exec_task(self, task, workspace):
        self.calls.append(task.id)
        return WorkerResult(task.id, summary=f"done {task.id}")


class WorkerPoolTests(unittest.TestCase):
    def test_drops_tasks_beyond_max_workers(self):
        with tempfile.TemporaryDirectory() as d:
            config = Config(runs_root=d, max_workers=2)
            store = RunStore.create(d, Run("r1", "audit", "now"))
            codex = CountingCodex()
            tasks = [TaskSpec(f"task_{i}", f"t{i}", "desc") for i in range(5)]
            results = WorkerPool(config, codex, store).run(tasks, 1)
            self.assertEqual(len(results), 2)
            self.assertEqual(codex.calls, ["task_0", "task_1"])
            self.assertTrue((store.root / "tasks/round_001_task_0_result.json").exists())
            self.assertTrue((store.root / "tasks/round_001_task_1_result.json").exists())
            self.assertFalse((store.root / "tasks/round_001_task_2_result.json").exists())
            log = (store.root / "logs/round_001.log").read_text(encoding="utf-8")
            self.assertIn("dropped 3 task(s)", log)
            self.assertIn("task_2", log)

    def test_no_drop_when_within_limit(self):
        with tempfile.TemporaryDirectory() as d:
            config = Config(runs_root=d, max_workers=3)
            store = RunStore.create(d, Run("r2", "audit", "now"))
            codex = CountingCodex()
            tasks = [TaskSpec(f"task_{i}", f"t{i}", "desc") for i in range(3)]
            results = WorkerPool(config, codex, store).run(tasks, 1)
            self.assertEqual(len(results), 3)
            self.assertFalse((store.root / "logs/round_001.log").exists())


if __name__ == "__main__": unittest.main()
