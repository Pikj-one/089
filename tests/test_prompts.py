import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from vulnhunt.prompts import planner_prompt


class PromptContractTests(unittest.TestCase):
    def test_order_contract(self):
        prompt = planner_prompt("audit", 1, [], ".")
        self.assertIn('"order"', prompt)
        self.assertIn('"depends_on"', prompt)
        self.assertIn("order = 1 +", prompt)
        self.assertIn("===开始===", prompt)
        self.assertIn("===结束===", prompt)

    def test_old_implicit_dependency_rules_removed(self):
        prompt = planner_prompt("audit", 1, [], ".")
        self.assertNotIn("不得存在彼此之间的隐式依赖", prompt)
        self.assertNotIn("不要在同一轮次中同时输出前置任务及其依赖任务", prompt)


if __name__ == "__main__": unittest.main()
