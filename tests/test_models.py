import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
import unittest
from vulnhunt.models import Plan, TaskSpec, CompletenessSignal, WorkerResult

class ModelTests(unittest.TestCase):
    def test_plan_roundtrip(self):
        plan = Plan(1, "audit", ["input"], [TaskSpec("task_1", "scan", "scan it", 0)], completeness_signal=CompletenessSignal.COMPLETE)
        restored = Plan.from_dict(plan.to_dict())
        self.assertEqual(restored.tasks[0].id, "task_1")
        self.assertEqual(restored.completeness_signal, CompletenessSignal.COMPLETE)

    def test_result_roundtrip(self):
        result = WorkerResult("x", summary="ok")
        self.assertEqual(WorkerResult.from_dict(result.to_dict()).summary, "ok")
