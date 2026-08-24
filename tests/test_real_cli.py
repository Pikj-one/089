import os, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from fakes import config as make_config
from vulnhunt.models import TaskSpec, TaskResultStatus, Run
from vulnhunt.state import RunStore
from vulnhunt.cli.claude_code import ClaudeWrapper
from vulnhunt.cli.codex import CodexWrapper

@unittest.skipUnless(os.getenv("VULNHUNT_REAL_TESTS") == "1", "set VULNHUNT_REAL_TESTS=1 to call local CLIs")
class RealCliTests(unittest.TestCase):
    def setUp(self):
        self.config = make_config(claude_exec="claude", codex_exec="codex", claude_timeout_s=120, codex_timeout_s=120)

    def test_claude_real_plan(self):
        plan = ClaudeWrapper(self.config).plan("只检查项目入口并给出一个最小审计计划", 1, [], ".")
        self.assertEqual(plan.round, 1)
        self.assertIsInstance(plan.tasks, list)

    def test_codex_real_result(self):
        with tempfile.TemporaryDirectory() as d:
            workspace = Path(d)
            result = CodexWrapper(self.config).exec_task(TaskSpec("task_1", "输出最小 JSON 结果", "只输出一个成功结果，不执行修改", required_output="status、summary、findings"), workspace)
            self.assertEqual(result.status, TaskResultStatus.SUCCESS)
            self.assertTrue((workspace / "_last_message.json").exists())

    def test_codex_real_resume_inherits_context_and_blackboard(self):
        # 真实 codex 中断续接：首次 exec 带 --add-dir 黑板写 marker 并落盘 .codex_session；
        # 第二次复用同一 workspace 走 resume（不传 --add-dir/-s，但 resume 分支显式传
        # --dangerously-bypass-approvals-and-sandbox），仍应复述 seed 并继续写黑板——
        # 0.149.0 的 resume 不继承 session_meta.sandbox_policy，全权沙箱只能靠该 flag。
        import uuid
        # ignore_cleanup_errors：Windows 下 codex 子进程退出后句柄释放有延迟，清理临时目录偶尔报 WinError 32；
        # 功能断言已完成，清理失败不应当让测试失败（残留目录无害）。
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            store = RunStore.create(Path(d), Run(uuid.uuid4().hex[:12], "resume-cli", "now", max_rounds=2, config_snapshot={}))
            ws = store.root / "workspaces" / "round_001_task_1"; ws.mkdir(parents=True)
            bb = store.root / "blackboard"
            wrapper = CodexWrapper(self.config, store=store)
            seed = "SEED-RESUME-CLI"
            r1 = wrapper.exec_task(TaskSpec("task_1", "resume-cli", f"在目录 {bb} 写入文件 marker.txt，内容精确为 {seed}，然后结束", required_output="status、summary、findings"), ws)
            self.assertEqual(r1.status, TaskResultStatus.SUCCESS)
            self.assertIn(seed, (bb / "marker.txt").read_text(encoding="utf-8"))
            self.assertTrue((ws / ".codex_session").exists())
            r2 = wrapper.exec_task(TaskSpec("task_1", "resume-cli", f"读取 {bb}/marker.txt 的内容并复述，然后在文件末尾追加一行 VERIFIED，然后结束", required_output="status、summary、findings"), ws)
            self.assertEqual(r2.status, TaskResultStatus.SUCCESS)
            self.assertIn("VERIFIED", (bb / "marker.txt").read_text(encoding="utf-8"))

    def test_claude_real_resume_reuses_session_across_rounds(self):
        # 真实 claude 中断续接：第 1 轮 --session-id 新建会话规划，第 2 轮（wrapper.session_id 仍在内存）
        # 自动走 --resume 续接同一会话。CLI 实测（2026-08-24）：跨进程 resume 恢复上下文记忆
        # （usage.cache_read_input_tokens 可见历史被加载），但 permission mode 不随会话继承——
        # resume 分支必须显式传 --permission-mode bypassPermissions（claude_code.py 每轮都传）。
        # 本测试验证端到端：两轮规划均成功、第 2 轮续接不因权限/会话问题失败。
        import uuid
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            store = RunStore.create(Path(d), Run(uuid.uuid4().hex[:12], "claude-resume", "now", max_rounds=2, config_snapshot={}))
            wrapper = ClaudeWrapper(self.config, store=store)
            p1 = wrapper.plan("只检查项目入口并给出一个最小审计计划", 1, [], ".")
            self.assertEqual(p1.round, 1)
            p2 = wrapper.plan("基于上一轮计划，给出下一轮的最小审计计划", 2, [], ".")
            self.assertEqual(p2.round, 2)
            self.assertTrue(wrapper.session_id)  # 会话 ID 跨轮保留（内存），供下轮 --resume

if __name__ == "__main__": unittest.main()
