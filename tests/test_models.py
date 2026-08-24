import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from vulnhunt.models import Plan, TaskSpec, WorkerResult, compute_orders


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

    def test_depends_on_roundtrip_and_default(self):
        task = TaskSpec("b", "scan", "s", depends_on=["a"])
        restored = TaskSpec.from_dict(task.to_dict())
        self.assertEqual(restored.depends_on, ["a"])
        bare = TaskSpec.from_dict({"id": "c", "title": "t", "description": "d"})
        self.assertEqual(bare.depends_on, [])

    def test_compute_orders_chain(self):
        tasks = [
            TaskSpec("mirror", "镜像", "抓取"),
            TaskSpec("analyze", "分析", "读黑板", depends_on=["mirror"]),
            TaskSpec("exploit", "利用", "深挖", depends_on=["analyze", "ghost"]),  # 悬空引用按 0
        ]
        orders = compute_orders(tasks)
        # exploit 混合引用了悬空 id：悬空项被忽略，仍按有效依赖取 max → 2
        self.assertEqual(orders, {"mirror": 0, "analyze": 1, "exploit": 2})

    def test_compute_orders_diamond_and_cycle(self):
        # 菱形：max(依赖 order)；循环环上任务一律按 0。
        diamond = [
            TaskSpec("root", "r", "r"),
            TaskSpec("left", "l", "l", depends_on=["root"]),
            TaskSpec("right", "ri", "ri", depends_on=["root"]),
            TaskSpec("join", "j", "j", depends_on=["left", "right"]),
        ]
        self.assertEqual(compute_orders(diamond), {"root": 0, "left": 1, "right": 1, "join": 2})

        cycle = [
            TaskSpec("a", "", "", depends_on=["b"]),
            TaskSpec("b", "", "", depends_on=["a"]),
            TaskSpec("c", "", "", depends_on=["cycle_c"]),  # 自引用悬空 → 0
        ]
        orders = compute_orders(cycle)
        self.assertEqual(orders["a"], 0)
        self.assertEqual(orders["b"], 0)
        self.assertEqual(orders["c"], 0)

    def test_result_roundtrip(self):
        result = WorkerResult("x", summary="ok")
        self.assertEqual(WorkerResult.from_dict(result.to_dict()).summary, "ok")


if __name__ == "__main__": unittest.main()
