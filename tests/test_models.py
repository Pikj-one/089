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

    def test_task_order_roundtrip(self):
        task = TaskSpec("task_1", "scan", "scan it", order=2)
        restored = TaskSpec.from_dict(task.to_dict())
        self.assertEqual(restored.order, 2)

    def test_task_order_defaults_to_zero(self):
        task = TaskSpec.from_dict({"id": "task_1", "title": "scan", "description": "scan it"})
        self.assertEqual(task.order, 0)

    def test_result_roundtrip(self):
        result = WorkerResult("x", summary="ok")
        self.assertEqual(WorkerResult.from_dict(result.to_dict()).summary, "ok")


if __name__ == "__main__": unittest.main()
