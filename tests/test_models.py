import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from vulnhunt.models import Plan, TaskSpec, WorkerResult


class ModelTests(unittest.TestCase):
    def test_plan_roundtrip(self):
        plan = Plan(1, [TaskSpec("task_1", "scan", "scan it")])
        restored = Plan.from_dict(plan.to_dict())
        self.assertEqual(restored.tasks[0].id, "task_1")
        self.assertEqual(restored.round, 1)

    def test_result_roundtrip(self):
        result = WorkerResult("x", summary="ok")
        self.assertEqual(WorkerResult.from_dict(result.to_dict()).summary, "ok")


if __name__ == "__main__": unittest.main()
