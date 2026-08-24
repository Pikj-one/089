import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from fakes import config as make_config
from vulnhunt.models import Run, TaskSpec, WorkerResult
from vulnhunt.state import RunStore
from vulnhunt.workers import WorkerPool


class CountingCodex:
    def __init__(self): self.calls = []
    def exec_task(self, task, workspace):
        self.calls.append(task.id)
        return WorkerResult(task.id, summary=f"done {task.id}")


class WorkerPoolTests(unittest.TestCase):
    def test_runstore_creates_blackboard_dir(self):
        with tempfile.TemporaryDirectory() as d:
            store = RunStore.create(d, Run("r1", "audit", "now"))
            self.assertTrue((store.root / "blackboard").is_dir())

    def test_drops_tasks_beyond_max_workers(self):
        with tempfile.TemporaryDirectory() as d:
            config = make_config(runs_root=d, max_workers=2)
            store = RunStore.create(d, Run("r1", "audit", "now"))
            codex = CountingCodex()
            tasks = [TaskSpec(f"task_{i}", f"t{i}", "desc") for i in range(5)]
            results = WorkerPool(config, codex, store).run(tasks, 1)
            self.assertEqual(len(results), 2)
            self.assertEqual(sorted(codex.calls), ["task_0", "task_1"])
            self.assertTrue((store.root / "tasks/round_001_task_0_result.json").exists())
            self.assertTrue((store.root / "tasks/round_001_task_1_result.json").exists())
            self.assertFalse((store.root / "tasks/round_001_task_2_result.json").exists())
            log = (store.root / "logs/round_001.log").read_text(encoding="utf-8")
            self.assertIn("dropped 3 task(s)", log)
            self.assertIn("task_2", log)

    def test_no_drop_when_within_limit(self):
        with tempfile.TemporaryDirectory() as d:
            config = make_config(runs_root=d, max_workers=3)
            store = RunStore.create(d, Run("r2", "audit", "now"))
            codex = CountingCodex()
            tasks = [TaskSpec(f"task_{i}", f"t{i}", "desc") for i in range(3)]
            results = WorkerPool(config, codex, store).run(tasks, 1)
            self.assertEqual(len(results), 3)
            self.assertFalse((store.root / "logs/round_001.log").exists())

    def test_executes_tasks_by_order_waves(self):
        with tempfile.TemporaryDirectory() as d:
            config = make_config(runs_root=d, max_workers=4)
            store = RunStore.create(d, Run("r3", "audit", "now"))
            codex = CountingCodex()
            tasks = [TaskSpec(f"task_{i}", f"t{i}", "desc", order=order) for i, order in enumerate([0, 1, 0, 1])]
            results = WorkerPool(config, codex, store).run(tasks, 1)
            self.assertEqual(len(results), 4)
            self.assertEqual(set(codex.calls[:2]), {"task_0", "task_2"})
            self.assertEqual(set(codex.calls[2:]), {"task_1", "task_3"})


if __name__ == "__main__": unittest.main()
