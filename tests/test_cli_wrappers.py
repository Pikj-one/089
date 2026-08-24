import json, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from fakes import config as make_config
from vulnhunt.models import TaskSpec, TaskResultStatus, Run
from vulnhunt.state import RunStore
from vulnhunt.cli.base import ProcResult
from vulnhunt.cli.claude_code import ClaudeWrapper, slim_prior
from vulnhunt.cli.codex import CodexWrapper


def _plan_output(tasks):
    return json.dumps({"type": "result", "result": json.dumps({"tasks": tasks})})


class WrapperUnitTests(unittest.TestCase):
    def test_claude_wrapper_parses_plan_json(self):
        output = _plan_output([{"id": "task_1", "title": "scan", "description": "scan it"}])
        with patch("vulnhunt.cli.claude_code.run_process", return_value=ProcResult(0, output, "")):
            plan = ClaudeWrapper(make_config()).plan("audit", 1, [], ".")
        self.assertEqual(plan.tasks[0].id, "task_1")

    def test_claude_wrapper_computes_orders_from_depends_on(self):
        # order 由代码按 depends_on 计算（原为顶层 LLM 的职责），模型输出的 order 字段被覆盖，depends_on 随后清空。
        output = _plan_output([
            {"id": "mirror", "title": "镜像", "description": "抓取", "order": 99},
            {"id": "analyze", "title": "分析", "description": "读黑板", "depends_on": ["mirror"]},
            {"id": "exploit", "title": "利用", "description": "深挖", "depends_on": ["analyze"]},
        ])
        with patch("vulnhunt.cli.claude_code.run_process", return_value=ProcResult(0, output, "")):
            plan = ClaudeWrapper(make_config()).plan("audit", 1, [], ".")
        by_id = {t.id: t for t in plan.tasks}
        self.assertEqual([by_id["mirror"].order, by_id["analyze"].order, by_id["exploit"].order], [0, 1, 2])
        self.assertTrue(all(t.depends_on == [] for t in plan.tasks))

    def test_claude_wrapper_slims_prior_in_prompt(self):
        # prior 瘦身：stdout_tail/stderr_tail（各 4000 字符噪音）不得进入规划提示词。
        captured = {}
        fat_prior = [{"task_id": "round_001_task_1", "status": "SUCCESS", "summary": "ok",
                      "stdout_tail": "X" * 4000, "stderr_tail": "Y" * 4000}]

        def fake_process(args, **kwargs):
            captured['prompt'] = kwargs['input_text']
            return ProcResult(0, _plan_output([{"id": "task_1", "title": "s", "description": "s"}]), "")

        with patch("vulnhunt.cli.claude_code.run_process", side_effect=fake_process):
            ClaudeWrapper(make_config()).plan("audit", 2, fat_prior, ".")
        self.assertNotIn("XXXX", captured['prompt'])
        self.assertIn('"summary": "ok"', captured['prompt'])
        # 落盘契约不受影响：slim_prior 是纯函数，原 dict 不被修改
        self.assertEqual(len(fat_prior[0]['stdout_tail']), 4000)

    def test_slim_prior_drops_only_noise_fields(self):
        item = {"task_id": "t", "status": "SUCCESS", "stdout_tail": "x", "stderr_tail": "y", "findings": [1]}
        slim = slim_prior([item])
        self.assertEqual(slim[0], {"task_id": "t", "status": "SUCCESS", "findings": [1]})
        self.assertEqual(slim_prior(None), [])
        self.assertEqual(slim_prior(["junk"]), [])

    def test_claude_wrapper_retries_resumed_session_on_broken_pipe(self):
        # 第 2 轮起用 --resume 续接既有会话；若子进程仍启动即退（Broken pipe）→
        # 放弃旧会话、换 --session-id 全新会话重试一次，run 不再因此整体 FAILED。
        calls = []
        output = _plan_output([{"id": "task_1", "title": "scan", "description": "scan it"}])

        def fake_process(args, **kwargs):
            if "--resume" in args:
                calls.append(("resume", args[args.index("--resume") + 1]))
            else:
                calls.append(("session-id", args[args.index("--session-id") + 1]))
            if len(calls) == 1:
                return ProcResult(-1, "", "[Errno 32] Broken pipe")
            return ProcResult(0, output, "")

        logs = []
        with patch("vulnhunt.cli.claude_code.run_process", side_effect=fake_process):
            wrapper = ClaudeWrapper(make_config(), logger=lambda component, message: logs.append((component, message)))
            wrapper.session_id = "old-session"  # 模拟第 2 轮复用既有会话
            plan = wrapper.plan("audit", 2, [], ".")

        self.assertEqual(plan.tasks[0].id, "task_1")
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], ("resume", "old-session"))
        self.assertEqual(calls[1][0], "session-id")  # 重试换全新会话
        self.assertNotEqual(calls[1][1], "old-session")
        self.assertTrue(any("已切换新会话重试" in m for c, m in logs))

    def test_claude_wrapper_round2_resumes_existing_session(self):
        # 第 2 轮续接既有会话走 --resume 且成功：不重试、无「已切换新会话」日志，会话 ID 保持不变。
        seen = []

        def fake_process(args, **kwargs):
            seen.append((list(args), kwargs.get('input_text', '')))
            return ProcResult(0, _plan_output([{"id": "task_1", "title": "scan", "description": "scan it"}]), "")

        with patch("vulnhunt.cli.claude_code.run_process", side_effect=fake_process):
            wrapper = ClaudeWrapper(make_config())
            wrapper.session_id = "kept-session"
            plan = wrapper.plan("audit", 2, [], ".")

        self.assertEqual(plan.tasks[0].id, "task_1")
        self.assertEqual(len(seen), 1)
        args, prompt = seen[0]
        self.assertIn("--resume", args)
        self.assertNotIn("--session-id", args)
        self.assertEqual(args[args.index("--resume") + 1], "kept-session")
        self.assertIn("当前轮次：2", prompt)

    def test_claude_wrapper_round1_creates_new_session(self):
        # 首轮无既有会话：仍用 --session-id 新建。
        with patch("vulnhunt.cli.claude_code.run_process", return_value=ProcResult(0, _plan_output([{"id": "task_1", "title": "scan", "description": "scan it"}]), "")) as m:
            ClaudeWrapper(make_config()).plan("audit", 1, [], ".")
        args = m.call_args[0][0]
        self.assertIn("--session-id", args)
        self.assertNotIn("--resume", args)

    def test_claude_wrapper_no_retry_on_first_round_failure(self):
        # 首轮（无既有会话可续）失败不应重试，直接抛错暴露原因。
        with patch("vulnhunt.cli.claude_code.run_process", return_value=ProcResult(-1, "", "boom")):
            with self.assertRaises(RuntimeError):
                ClaudeWrapper(make_config()).plan("audit", 1, [], ".")

    def test_claude_wrapper_no_retry_on_resume_timeout(self):
        # 续会话但超时：这是规划跑太久被强杀，不是启动即退，重试无意义，直接抛错。
        wrapper = ClaudeWrapper(make_config())
        wrapper.session_id = "old-session"
        with patch("vulnhunt.cli.claude_code.run_process", return_value=ProcResult(-1, "", "", True)):
            with self.assertRaises(RuntimeError):
                wrapper.plan("audit", 2, [], ".")

    def test_codex_wrapper_parses_result_file(self):
        def fake_process(args, cwd=None, **kwargs):
            output_file = Path(args[args.index("-o") + 1])
            output_file.write_text(json.dumps({"status": "SUCCESS", "summary": "ok", "findings": []}), encoding="utf-8")
            return ProcResult(0, "", "")

        with tempfile.TemporaryDirectory() as d, patch("vulnhunt.cli.codex.run_process", side_effect=fake_process):
            result = CodexWrapper(make_config()).exec_task(TaskSpec("task_1", "test", "test"), Path(d))
        self.assertEqual(result.status, TaskResultStatus.SUCCESS)

    def test_codex_wrapper_tolerates_text_preamble(self):
        # codex 会在 JSON 前写解释文字（如 "All work complete..."），必须剥离后再解析，否则 findings 全丢。
        def fake_process(args, cwd=None, **kwargs):
            output_file = Path(args[args.index("-o") + 1])
            output_file.write_text(
                "All work complete. Final report written to `blackboard/task_1_findings.json`, subprocesses cleaned up.\n\n"
                + json.dumps({"status": "PARTIAL", "summary": "ok", "findings": [{"id": "F1"}]}),
                encoding="utf-8",
            )
            return ProcResult(0, "", "")

        with tempfile.TemporaryDirectory() as d, patch("vulnhunt.cli.codex.run_process", side_effect=fake_process):
            result = CodexWrapper(make_config()).exec_task(TaskSpec("task_1", "test", "test"), Path(d))
        self.assertEqual(result.status, TaskResultStatus.PARTIAL)
        self.assertEqual(result.findings, [{"id": "F1"}])

    def test_codex_wrapper_fresh_branch_keeps_sandbox_flags(self):
        # 无 .codex_session → 全新会话：仍传 -s 沙箱、--color、--add-dir 黑板；
        # 只有 resume 分支才省略这些（沙箱/黑板随会话继承，见 test_codex_wrapper_resume_branch_omits_sandbox_flags）。
        captured = {}

        def fake_process(args, cwd=None, **kwargs):
            captured['args'] = args
            Path(args[args.index("-o") + 1]).write_text(json.dumps({"status": "SUCCESS", "summary": "ok", "findings": []}), encoding="utf-8")
            return ProcResult(0, "", "")

        with tempfile.TemporaryDirectory() as d:
            store = RunStore.create(Path(d), Run("r1", "audit", "now", max_rounds=2, config_snapshot={}))
            ws = store.root / "workspaces" / "round_001_task_1"; ws.mkdir(parents=True)
            with patch("vulnhunt.cli.codex.run_process", side_effect=fake_process):
                CodexWrapper(make_config(), store=store).exec_task(TaskSpec("task_1", "test", "test"), ws)
        args = captured['args']
        self.assertEqual(args[0], "codex")
        self.assertNotIn("resume", args)
        self.assertIn("--add-dir", args)   # 黑板目录
        self.assertIn("-s", args)          # 沙箱权限
        self.assertIn("--color", args)     # 禁色输出

    def test_codex_wrapper_resume_branch_omits_sandbox_flags(self):
        # workspace 有 .codex_session → 续接走 `codex exec resume`；
        # 不传 --add-dir/-s/--color（resume 不接受这些 exec-only 标志），但显式传
        # --dangerously-bypass-approvals-and-sandbox 获得全权沙箱——实测 resume 不继承 session_meta 的
        # sandbox_policy，不加此 flag 会回落 workspace-write、共享黑板目录被拒写。
        captured = {}

        def fake_process(args, cwd=None, **kwargs):
            captured['args'] = args
            Path(args[args.index("-o") + 1]).write_text(json.dumps({"status": "SUCCESS", "summary": "ok", "findings": []}), encoding="utf-8")
            return ProcResult(0, "", "")

        with tempfile.TemporaryDirectory() as d:
            ws = Path(d) / "ws"; ws.mkdir()
            (ws / ".codex_session").write_text("sess-abc", encoding="utf-8")
            with patch("vulnhunt.cli.codex.run_process", side_effect=fake_process):
                CodexWrapper(make_config()).exec_task(TaskSpec("task_1", "test", "test"), ws)
        args = captured['args']
        self.assertEqual(args[:4], ["codex", "exec", "resume", "sess-abc"])
        self.assertIn("--json", args)
        self.assertIn("-o", args)
        self.assertIn("--dangerously-bypass-approvals-and-sandbox", args)  # 全权沙箱：resume 不继承 sandbox_policy
        for banned in ("--add-dir", "-s", "--color", "-C"):
            self.assertNotIn(banned, args)


if __name__ == "__main__": unittest.main()
