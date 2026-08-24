import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from vulnhunt.prompts import planner_prompt


class PromptContractTests(unittest.TestCase):
    def test_scope_via_claude_md_instruction(self):
        # 授权范围/垃圾清单由模型自行读取 run 目录的 CLAUDE.md（cwd 即 run 目录），不做代码注入。
        prompt = planner_prompt("audit", 1, [], ".")
        self.assertIn("CLAUDE.md", prompt)
        self.assertIn("授权范围", prompt)
        self.assertIn("垃圾漏洞清单", prompt)

    def test_single_layer_no_forward_segment(self):
        # 架构改为主 agent 直连规划：不再有顶层→subagent 转发协议。
        prompt = planner_prompt("audit", 1, [], ".")
        self.assertNotIn("===开始===", prompt)
        self.assertNotIn("===结束===", prompt)
        self.assertNotIn("Plan subagent", prompt)

    def test_output_contract(self):
        prompt = planner_prompt("audit", 1, [], ".")
        self.assertIn('"tasks"', prompt)
        self.assertIn('"depends_on"', prompt)
        self.assertIn("order 由系统按 depends_on 计算，你不输出 order", prompt)

    def test_dynamic_fields_injected(self):
        prompt = planner_prompt("audit", 2, [{"task_id": "task_1"}], "C:/runs/r1", 5)
        self.assertIn("当前轮次：2", prompt)
        self.assertIn('上轮结果：[{"task_id": "task_1"}]', prompt)
        self.assertIn("并发上限（5）", prompt)
        self.assertIn("C:/runs/r1/blackboard", prompt)
        self.assertNotIn("<run_dir>", prompt)

    def test_round_phase_rules(self):
        prompt = planner_prompt("audit", 1, [], ".")
        self.assertIn("信息收集轮", prompt)
        self.assertIn("方向规划轮", prompt)
        self.assertIn("利用深化轮", prompt)
        self.assertIn("严禁规划任何漏洞探测", prompt)
        self.assertIn("一个任务只聚焦一个方向", prompt)


if __name__ == "__main__": unittest.main()
