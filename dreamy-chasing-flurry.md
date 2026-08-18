# MVP 项目骨架实施计划 — 编排 ClaudeCode + Codex 自动化漏洞挖掘

## Context

在 `F:\claude code\089`（当前仅有 `架构.md`）搭建编排本地 Claude Code CLI 与 Codex CLI 的**自动化漏洞挖掘工作流** MVP 骨架。三角色：**Claude Code = Planner/Reviewer**（产出结构化 Plan，不直接执行）、**Codex CLI = Worker**（自身 Sandbox 下执行子任务）、**Orchestrator = 控制层**（生命周期/调度/并发/持久化/恢复/完成判定）。

MVP 目标：一个用户提交的小任务能**端到端闭环**——Claude 规划 → Codex 并发执行 → 结果回灌 → Orchestrator 独立完成判定 → 报告落盘。

## 已确认决策
1. **纯标准库**（零第三方依赖；`tomllib` 读 config.toml）
2. **Codex sandbox 默认 `workspace-write`**，config 可切 `danger-full-access`
3. **端到端可跑通**真实 CLI

## 已实测的环境事实
- Windows 10 / Python 3.13.5 / uv 0.11.6；控制台 UTF-8
- **`claude.cmd` 是坏掉的 batch 包装**（指向不存在的 `C:\Users\Cutey\.clawgod\cli.js`）；真实可执行体 **`C:\Users\Cutey\.local\bin\claude.exe`**（native v2.1.233，`--version` 正常）→ **wrapper 必须直接调 `.exe`，`shell=False`**
- `codex.exe`（`...\OpenAI\Codex\bin\codex.exe`）v0.147.0：`exec` 支持 `--json` / `-o --output-last-message` / `--output-schema` / `-s <read-only|workspace-write|danger-full-access>` / `--approve-for-me` / `-C --cd` / `--skip-git-repo-check` / `--ephemeral` / `--color never`
- Claude CLI 无 `--max-turns` → **进程级超时由 Orchestrator 处理**（`taskkill /T /F` 杀进程树）
- Claude 支持 `-p --output-format json --permission-mode plan --json-schema <path>`、`--session-id <uuid>` / `-r --resume <id>`

## 1. 目录结构

```
F:\claude code\089\
├── pyproject.toml           # uv 可构建, dependencies=[] 零依赖, scripts: vulnhunt = vulnhunt.main:main
├── README.md
├── .gitignore               # runs/, *.tmp
├── config.toml              # 运行配置（env/argv 覆盖）
├── src\vulnhunt\
│   ├── __init__.py          # __version__
│   ├── __main__.py          # python -m vulnhunt
│   ├── main.py              # argparse: start/status/resume/doctor
│   ├── config.py            # Config dataclass + load_config()(toml+env+overrides)
│   ├── models.py            # 全部 dataclass+枚举+to_dict/from_dict
│   ├── schema.py            # PLAN_SCHEMA_V1 / TASK_RESULT_SCHEMA_V1 (dict 常量)
│   ├── state.py             # RunStore: 目录布局/原子写/恢复语义
│   ├── orchestrator.py      # 状态机/主循环/完成判定/轮次管理
│   ├── workers.py           # WorkerPool: ThreadPoolExecutor + queue 事件回传
│   ├── cli\
│   │   ├── base.py          # resolve_executable / run_process(超时/进程树杀/编码/流式回调)
│   │   ├── claude_code.py   # ClaudeWrapper: plan()/health_check()/parse_plan()
│   │   └── codex.py         # CodexWrapper: exec_task()/parse_jsonl()/health_check()
│   ├── prompts.py           # planner prompt 模板
│   ├── tui.py               # UI: stdin 线程 + 锁保护打印 + ANSI 状态栏
│   └── report.py            # build_report(run_dir) → report.md/json
├── tests\
│   ├── test_models.py  test_state.py  test_orchestrator.py  test_cli_wrappers.py
└── runs\<run_id>\            # 一次运行的完整证据链 (.gitignore)
    ├── run.json             # Run 元数据+config 快照+状态
    ├── state.json           # 状态机快照（orchestrator 主线程原子更新）
    ├── plans\round_001_plan.json  (+ _schema.json 副本)
    ├── tasks\round_001_task_0001_input.json / _result.json   # 成对
    ├── workspaces\round_001_task_0001\   # codex -C 指向, 含 _last_message.json
    ├── findings\round_001_finding_0001.json
    ├── logs\orchestrator.log / claude_round_001_{input.txt,output.jsonl} / codex_..._task_0001.log
    └── report\report.md + report.json
```

## 2. 数据模型（models.py）

纯 stdlib `@dataclass` + 显式 `to_dict/from_dict`（枚举↔字符串、版本演进），JSON 一律 `ensure_ascii=False, indent=2`。

- **枚举**：`RunStatus(INIT/PLANNING/DISPATCHING/RUNNING/COLLECTING/DECISION/COMPLETE/FAILED/ABORTED)`、`TaskStatus(PENDING/DISPATCHED/RUNNING/SUCCEEDED/FAILED/TIMED_OUT/SKIPPED/CANCELLED/RECOVERED)`、`TaskResultStatus(SUCCESS/FAILURE/PARTIAL)`、`Severity(CRITICAL..INFO)`、`CompletenessSignal(COMPLETE/CONTINUE/UNKNOWN)`、`CompletionDecision(COMPLETE/CONTINUE/ABORT/MAX_ROUNDS/STALLED)`
- **Run**：`run_id / goal / created_at / status / current_round / max_rounds / config_snapshot / target_dir / updated_at`
- **Plan**（对齐 PLAN_SCHEMA_V1）：`round / goal_restatement / attack_surface / tasks: list[TaskSpec] / notes / completeness_signal / next_strategy`
- **TaskSpec**：`id("task_n") / title / description(主指令) / priority(0..3) / required_output / relevant_context`
- **CodexTask**：`task_id("round_001_task_0001") / round_no / spec / status / workspace / dispatched_at / finished_at / result?`
- **WorkerResult**：`task_id / exit_code / status / summary / findings / evidence_files / output_files / stdout_tail / stderr_tail / error / duration_s`（对齐 TASK_RESULT_SCHEMA_V1）
- **Finding**：`finding_id("round_001_finding_0001") / task_id / round_no / severity / title / description / affected / evidence / evidence_files / status(open)`
- **CompletionState**：`round_no / planned / succeeded / failed / timed_out / coverage_ratio / findings_new / findings_total / remaining_high_priority / rounds_no_progress / claude_signal / decision / reasons`（DECISION 判定输入+结论，落盘审计）

每个文件带 `_meta: {"version":1, "written_by": "...", "written_at": ISO8601}`。

## 3. 状态持久化（state.py）—— 可恢复/可观测的基石

`RunStore` 类：`create()/load()` + 读（read_run/read_state/read_plan/read_task_result）+ 写（save_run/save_state/save_plan/save_task_input/save_task_result/save_finding/append_log）+ 路径方法。

- **原子写**：`json.dumps` → `*.tmp` → `os.replace()`（NTFS 同卷原子；崩溃残留 tmp 可忽略）
- **恢复语义**（`resume <run_dir>`）：`RunStore.load` → 遍历当前轮任务：`SUCCEEDED` 直接采纳；`PENDING/DISPATCHED/RUNNING/RECOVERED` → 标记 RECOVERED 后重置 **PENDING** 重新派发（幂等，task_id 不变）。`run.status==PLANNING` 时用 `--resume <session_id>` 续接 Claude 会话保上下文。完成判定基于**已落盘结果文件**，不依赖内存 → 重启后口径一致。
- **并发写盘**：worker 只写各自 task 的 result/workspace（路径互斥无锁）；共享 `state.json` 仅 orchestrator 主线程更新

## 4. Orchestrator 状态机（orchestrator.py）

`Orchestrator.run()` = `while status not terminal: step()`；每步末尾 `store.save_state()`（被杀最多回退一步）。

状态转移表：

| 当前 | 条件 | 下一状态 |
|---|---|---|
| INIT | start | PLANNING |
| PLANNING | Claude 返回 Plan 且 schema 校验通过 | DISPATCHING |
| PLANNING | 失败/超时/解析失败，重试<plan_retry_max | PLANNING（`--resume` 保上下文） |
| PLANNING | 重试耗尽 | FAILED |
| DISPATCHING | 任务全部入池 | RUNNING |
| DISPATCHING | 空 plan 无任务 | DECISION |
| RUNNING | 全部任务终结 | COLLECTING |
| COLLECTING | 聚合完成 | DECISION |
| DECISION | CONTINUE | PLANNING（round+1） |
| DECISION | COMPLETE | COMPLETE |
| DECISION | ABORT/MAX_ROUNDS/STALLED | FAILED（report 标注原因） |
| 任意非终态 | 用户 quit/abort 或 Ctrl+C | ABORTED |

**完成判定 `_decide_completion()`（orchestrator 独立拍板，按优先级）：**
1. `round >= max_rounds` → **MAX_ROUNDS**
2. `rounds_no_progress >= max_rounds_no_progress`（连续 N 轮零新增且覆盖度不升）→ **STALLED**
3. `remaining_high_priority==0 且 coverage_ratio >= coverage_threshold` → **COMPLETE**
4. `claude_signal==COMPLETE 且 剩余 P0 任务==0` → **COMPLETE**（P0 不可忽略；此条是唯一参考 Claude 信号处）
5. 其余 → **CONTINUE**

单任务失败/超时不中断运行；池级异常置 FAILED 保留已落盘内容供 resume。

## 5. CLI wrapper（cli/）

**base.py**：
- `resolve_executable(candidates)`：优先 `.exe`（native，`shell=False` 直调），退 `.cmd/.bat`（需 `shell=True`/`cmd /c`）。启动时 `doctor` 校验
- `run_process(args, cwd, env, timeout_s, input_text, on_stdout_line)` → `ProcResult(exit_code/stdout/stderr/timed_out/duration_s)`
- Windows 要点：`Popen(shell=False, text=True, encoding="utf-8", errors="replace")`；**stdout/stderr 用 reader 线程 + queue**（Windows 管道无 select）；超时 `proc.poll()+deadline` → **`taskkill /pid <pid> /T /F` 杀进程树**（`proc.kill()` 只杀主进程会留子进程）；prompt 走 **stdin** 喂入（避开 Windows ~32k argv 限制）；env 注入 `PYTHONIOENCODING=utf-8`

**claude_code.py** `ClaudeWrapper.plan()`：
```
claude.exe -p "" --output-format json --permission-mode plan
  --json-schema <schema_path> --add-dir <target_dir>
  [--session-id <uuid>] | [-r/--resume <id>]
```
prompt（prompts.py 组装：goal + 聚合 prior_results + findings 摘要）经 stdin；stdout 流式回调记 `logs/claude_round_00N_output.jsonl`。`parse_plan(raw)`：取 `result["text"]`，容错剥离 ```json 围栏再 `json.loads`；失败抛 PlanParseError 触发重试。每轮生成/持久化 session_id。

**codex.py** `CodexWrapper.exec_task()`：
```
codex.exe exec "" -C <task.workspace> --json -o <ws>/_last_message.json
  --output-schema <schema_file> -s <sandbox> --skip-git-repo-check --ephemeral --color never
```
prompt = description + required_output + relevant_context，走 stdin。**结果权威源 = `-o` 的 last-message 文件**（配 `--output-schema`），JSONL 事件流（`agent_message/execution_step/approval_request`）只用于日志/进度，不解析顺序脆弱。`WorkerResult.status` 映射：exit0+有 findings→SUCCESS/PARTIAL，非0→FAILURE，`timed_out=True`→TIMED_OUT。

**沙箱映射**：`workspace-write` → `-s workspace-write --approve-for-me`（默认）；`danger-full-access` → `-s danger-full-access`；`read-only` → `-s read-only`

## 6. 并发 Worker Pool（workers.py）

`ThreadPoolExecutor(max_workers=config.max_workers, 默认3)`；每 worker 一个 subprocess（`Popen`）天然隔离。`submit(task)` → future 回调不直接改共享 state，**只推 `queue.Queue` 事件**（`TASK_STARTED/TASK_DONE/FINDING`）由 UI 消费打印。`wait_all()` 后 orchestrator 读 `store.read_task_result()`（以落盘为准）。

## 7. 极简 TUI（tui.py）—— 纯 stdlib

- `threading.Lock` 保护全部终端写；stdin **reader 线程** `input()` 阻塞，主线程跑 orchestrator 循环
- 命令：`start "<goal>"` / `status` / `tasks` / `findings` / `abort` / `quit`
- ANSI：`os.system("")` 激活 VT，`sys.stdout.isatty()` 检测降级；日志 `[hh:mm:ss][组件]` 前缀，组件色 ORCH 青/CLAUDE 蓝/CODEX 黄/UI 灰
- 日志到来时若在等输入：`\r` 覆盖 → 打日志 → 重绘 `"> "`
- Ctrl+C → 优雅 abort 落盘；二次强退

## 8. 配置（config.toml + env override）

`Config` 字段：`claude_exec`(默认 `C:/Users/Cutey/.local/bin/claude.exe`)、`codex_exec`、`runs_root("runs")`、`target_dir(".")`、`target_extra_dirs[]`、`max_rounds(5)`、`max_workers(3)`、`claude_timeout_s(300)`、`codex_timeout_s(600)`、`plan_retry_max(2)`、`claude_model/claude_permission_mode("plan")`、`codex_sandbox("workspace-write")`、`codex_model/codex_approve_for_me(True)`、`coverage_threshold(0.8)`、`max_rounds_no_progress(2)`、**`dry_run`**（不真调 CLI，打印命令+假结果，**打通端到端不烧 token 的关键**）、`verbose`

`load_config()`：`tomllib` → dataclass → `VULNHUNT_<UPPER>` env → argv overrides；校验 exec 存在（dry_run 跳过）。

## 9. 入口与端到端流程（main.py）

argparse 子命令：`start "<goal>" [--config] [--run-id]` / `status` / `resume <run_dir>` / `doctor`（两个 CLI health_check，专门防 `.cmd` 路径漂移）。

端到端路径：config→doctor→`RunStore.create`→UI→WorkerPool→`Orchestrator.run()`：PLANNING(round1 空上下文) → DISPATCHING(3 tasks 入池) → RUNNING(并发 codex) → COLLECTING(聚合+去重 findings) → DECISION(CONTINUE) → PLANNING(round2 注入上轮结果, `--resume`) → ... → COMPLETE → `report.build_report()` 出 report.md/json → UI 打印报告路径。

## 10. 实施顺序

1. `pyproject.toml` + 包骨架 + `.gitignore` + `config.toml` + `config.py`
2. `models.py` + `schema.py`（**先冻结数据契约**）
3. `state.py` + `test_state.py`
4. `cli/base.py` → `claude_code.py` → `codex.py` + `test_cli_wrappers.py`（dry_run 打通参数拼接/JSONL 解析 → `doctor` 验真实 CLI）
5. `workers.py`
6. `orchestrator.py` + `test_orchestrator.py`（注入假 CLI wrapper，覆盖状态转移+完成判定表）
7. `tui.py` + `main.py`
8. `report.py`
9. 端到端冒烟

## 11. 验证方式

1. **单元**：`uv run pytest`（models roundtrip / state 原子写与恢复 / orchestrator 假 CLI 下全状态转移+判定 / wrapper dry_run 参数拼接+JSONL 解析）
2. **doctor**：`uv run python -m vulnhunt doctor` → 确认两 CLI 版本、`.cmd` 失效被正确绕开
3. **dry-run 冒烟**：`vulnhunt start "审计 demo/target.py 是否可路径穿越利用"` 配 `dry_run=true` → 全状态机走通、每步落盘、report 生成、Ctrl+C 后 `resume` 恢复
4. **真实闭环**：关 dry_run，用最小目标跑一轮真实 Claude+Codex，确认 plan 解析、并发执行、结果回灌、判定落盘
5. **Windows 专项**：超时杀进程树无残留（`tasklist | findstr claude/codex` 为空）、中文输出无乱码

## 12. 关键风险与对策

| 风险 | 对策 |
|---|---|
| `claude.cmd` batch 漂移（本机已失效） | `doctor` + 优先直调 `.exe`（`shell=False`） |
| Windows argv 长度限制 | prompt 全走 stdin |
| 超时子进程残留 | `taskkill /pid /T /F` 杀整树 |
| Claude `result.text` 非裸 JSON | 容错解析 + `--resume` 重试保上下文 |
| codex JSONL 顺序脆弱 | 事件流只做日志，结果权威源=`-o` 文件 |
| token 失控 | dry_run 联调、max_rounds、停滞收敛 |
| 重启丢进度 | 每步原子写 state.json；结果文件幂等重跑 |

## Critical Files

- `src/vulnhunt/models.py` — 数据契约基石
- `src/vulnhunt/orchestrator.py` — 状态机/完成判定核心
- `src/vulnhunt/state.py` — 原子写/恢复语义
- `src/vulnhunt/cli/base.py` — Windows 子进程生命周期底座
- `src/vulnhunt/cli/claude_code.py` — Planner 结构化输出解析
