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

    def test_role_split_structure(self):
        prompt = planner_prompt("audit", 1, [], ".")
        self.assertIn("# 最终输出格式", prompt)
        self.assertIn("## 你的职责（Plan subagent）", prompt)
        # 顶层指令会在步骤 2 引用 ===开始===，真实转发标记取最后一次出现（rindex）
        forward = prompt.rindex("===开始===")
        self.assertLess(prompt.index('"order": 0'), forward)          # 顶层输出示例在转发段之前
        self.assertLess(forward, prompt.index('"depends_on"(可选字段)'))  # subagent 示例只在转发段内
        # 旧矛盾句/typo/写死数量移除
        self.assertNotIn("只负责plan subganet", prompt)
        self.assertNotIn("超出十个", prompt)
        self.assertNotIn("你就是大脑", prompt)

    def test_max_workers_injected(self):
        self.assertIn("并发上限（5）", planner_prompt("audit", 1, [], ".", 5))
        self.assertIn("并发上限（10）", planner_prompt("audit", 1, [], "."))

    def test_blackboard_path_dynamic(self):
        prompt = planner_prompt("audit", 1, [], "C:/runs/r1")
        self.assertIn("C:/runs/r1/blackboard", prompt)
        self.assertNotIn("<run_dir>", prompt)

    def test_dedup_snapshot_guidance(self):
        prompt = planner_prompt("audit", 1, [], ".")
        self.assertIn("去重规划", prompt)
        self.assertIn("站点镜像", prompt)
        self.assertIn("不要重新下载", prompt)


if __name__ == "__main__": unittest.main()
