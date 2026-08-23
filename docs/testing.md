# vulnhunt 测试

## 1. 运行测试

```bash
PYTHONPATH=src python -m unittest discover tests -v
```

- **当前状态：42 个测试全部通过**（40 ok + 2 跳过），耗时约 5s。
- 单元测试全部用 Fake 类（`tests/fakes.py`），**不碰真实 CLI、不发任何请求**，可安全离线跑。
- 测试代码通过 `sys.path.insert(0, "src")` 直接引用源码，不要求先 `pip install`。

## 2. 真实 CLI 测试（门控）

`tests/test_real_cli.py` 会**真的调用本机 claude / codex**，默认跳过。需显式开启：

```bash
VULNHUNT_REAL_TESTS=1 PYTHONPATH=src python -m unittest tests.test_real_cli -v
```

包含两个用例：
- `test_claude_real_plan`：真实调 ClaudeWrapper.plan() 出一个最小审计计划（断言能解析出任务列表）。
- `test_codex_real_result`：真实调 CodexWrapper.exec_task() 在临时目录跑一个只输出 JSON 的任务（断言 `_last_message.json` 存在、状态 SUCCESS）。

> ⚠️ 会在有授权的前提下跑，否则不要开。

## 3. 测试文件覆盖点

| 文件 | 覆盖内容 |
|---|---|
| `test_orchestrator.py` | 状态机能一路推进到 COMPLETE（FakeClaude/FakeCodex 驱动） |
| `test_state.py` | RunStore 原子化落盘 roundtrip；新建 run 时自动复制项目 CLAUDE.md |
| `test_models.py` | Plan / WorkerResult 的 to_dict/from_dict roundtrip |
| `test_base.py` | `run_process` 生命周期：超时强杀、cancel 置位、正常退出 |
| `test_tui.py` | 心跳：子代理长时间无输出时输出"仍在运行"提示 |
| `test_logview.py` | 渲染与回放 sink；system/plan 组件区分；进度去重；tool 输入拼装与结果截断 |
| `test_cli_wrappers.py` | claude wrapper 捕获 Plan subagent、解析规划 JSON、流式进度；codex wrapper 解析结果文件（含前置文本容错）、相对 workspace resolve、黑板契约提示词 |
| `test_prompts.py` | planner prompt 契约：order/depends_on、去重规划、黑板路径注入、并发上限注入、**轮次阶段规则** |
| `test_blackboard.py` | 黑板噪音资产清理（CSS/图片/字体/响应头）与小黑板 JS 静默格式化 |
| `test_real_cli.py` | 真实 CLI 调用（门控，见上） |
| `fakes.py` | `FakeClaude`（返回固定 Plan）/ `FakeCodex`（返回固定 WorkerResult），测试桩 |

## 4. 新增测试要点

- 需要 `Plan`/`TaskSpec`/`WorkerResult` 的测试，优先复用 `fakes.py` 的桩，避免模拟 CLI。
- 涉及 `run_process` 的用例注意 Windows/POSIX 分支（`test_base.py` 有先例）。
- 不要给真实 CLI 测试去掉 skip 门控；新写的外部依赖用例也应加 `@unittest.skipUnless(...)` 类似门控。
- 代码风格与现有测试一致（紧凑、少换行，详见 [development.md](development.md)）。
