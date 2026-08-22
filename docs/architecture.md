# vulnhunt 深度架构设计

> 源码级剖析。目标读者：要读懂/改动这个框架的人。所有机制均对照 `src/vulnhunt/` 源码核实。

## 1. 总体设计

vulnhunt 是一个 **编排框架**，本身不发任何 HTTP 请求、不做任何漏洞检测——真正的"活"全由外部两个 LLM CLI 干：

- **Claude（大脑）**：负责规划。每轮读取目标、上轮结果，拆出下一步该做什么，输出结构化任务列表。
- **Codex（手）**：负责执行。每个任务对应一个独立 Codex 实例，在隔离工作目录里完成审计/探测，返回结构化结果。

vulnhunt 在中间只做三件事：**组装上下文 → 调度子进程 → 持久化结果**。它刻意保持零第三方依赖（纯 stdlib），把复杂度集中在"跟两个 CLI 的协议对接"上。

```
                    ┌─────────────────────────── vulnhunt ───────────────────────────┐
  目标 + 上轮结果      │  prompts.py(模板)   orchestrator.py(状态机)   state.py(落盘)     │
──► Claude ──► Plan ──►  JSON tasks ──►  WorkerPool ──►  Codex x N ──► 结果文件
   (顶层代理)  (subagent)                (线程池)         (独立 workspace)    │
                                                                          ▼
                                                    report.py ◄── tasks/*_result.json
```

### 为什么用"大脑-手"两段式？

- **上下文隔离**：每个 Codex 实例不共享任何信息，任务之间天然并行且互不污染，避免一个长会话上下文膨胀失控。
- **规划收敛**：Claude 大脑汇总所有手的结果后统一决策，保证攻击面覆盖有全局视角。
- **进程级故障隔离**：Codex 崩了不影响其他手，也不影响规划进程；Claude 会话固定 session-id，可跨轮续上下文。

### 一次 run 的完整时序

```
start (main.py)
  └─ 建 Run + RunStore.create()           # 目录 vulnhunt-runs/<年>/<月>/<日>/<时-分>/<run_id>/
  │                                         # 复制项目根 CLAUDE.md 进 run 目录（授权上下文）
  └─ Orchestrator.run_loop()  循环 step()
       ├─ INIT        round=1 → PLANNING
       ├─ PLANNING    ClaudeWrapper.plan()：调 `claude -p`，喂 planner_prompt()
       │                ├─ 顶层 Claude 把"转发段"原样转发给 Plan subagent
       │                ├─ Plan subagent 输出 JSON tasks（含授权范围/清单占位符补全）
       │                ├─ 捕获 stream-json 里的 input_json_delta 拼装出完整 JSON
       │                └─ 存 plans/round_NNN_plan.json
       ├─ DISPATCHING → RUNNING
       ├─ RUNNING      WorkerPool：ThreadPoolExecutor(max_workers) 并行
       │                ├─ 每任务一个 workspaces/round_NNN_<taskid>/ 目录
       │                ├─ CodexWrapper.exec_task()：`codex exec -C <workspace> ...`
       │                ├─ codex 写回 _last_message.json（status/summary/findings）
       │                ├─ 结果读回 → WorkerResult → tasks/<tid>_result.json
       │                └─ .codex_session 存会话 id，供下轮 resume
       ├─ COLLECTING → DECISION
       └─ DECISION     若 current_round >= max_rounds → COMPLETE
                       否则 round+1 → PLANNING（上轮结果作为 prior 回填）
  结束 → build_report() 生成 report.json / report.md
```

## 2. 状态机（`src/vulnhunt/orchestrator.py`）

`Orchestrator.run_loop()` 是一个 while 循环，直到状态为 `COMPLETE / FAILED / ABORTED` 才停；`step()` 单步推进：

| 状态 | step() 内做的事 | 结果 |
|---|---|---|
| `INIT` | `current_round=1` | → `PLANNING` |
| `PLANNING` | `self.claude.plan(goal, round, prior, run_dir)` → 存 plan | → `DISPATCHING` |
| `DISPATCHING` | 无操作，仅状态推进 | → `RUNNING` |
| `RUNNING` | `WorkerPool(...).run(plan.tasks, round)`，结果存进 `self.prior` | → `COLLECTING` |
| `COLLECTING` | 无操作，仅状态推进 | → `DECISION` |
| `DECISION` | `round >= max_rounds` ? 结束 : `round+1` | → `COMPLETE` 或 → `PLANNING` |
| 终态 | `COMPLETE / FAILED / ABORTED` | 循环退出 |

每步结束都 `save()`（`run.json` + `state.json`），所以**任意时刻崩溃都能从磁盘状态续跑**。

### 中断与异常归因

- `self._abort = threading.Event()`：挂到 claude/codex 的 `cancel_event`，子进程循环轮询后强杀；也用于 TUI 的 `abort` 命令。
- `KeyboardInterrupt` → `ABORTED`（用户主动）。
- 其他异常 → 若 `_abort.is_set()` 归为 `ABORTED`，否则 `FAILED`。

### resume 机制

`vulnhunt resume <run_dir>` 直接 `RunStore(run_dir)` 重建 store，`Orchestrator.__init__` 若 `run.current_round` 已有 plan 则从磁盘重建 `self.plan`，`run_loop()` 从当前状态继续。中断在 RUNNING 中途时，已完成的任务结果已在 `tasks/` 落盘，重新 `run()` 会重跑本轮的 plan（先读磁盘结果再决定？否——**重跑整轮**，见 `known-gaps.md` 缺口 9 的说明）。

## 3. PLANNING 深层机制（`src/vulnhunt/cli/claude_code.py`）

这是全项目最精巧的部分：**从 claude 的流式输出里实时截获 Plan subagent 产出的 JSON**。

### 3.1 调用形态

```python
claude -p "" --output-format stream-json --include-partial-messages --verbose \
       --permission-mode bypassPermissions --session-id <uuid>
```

- `-p` + stdin 传入 `planner_prompt()`（见 3.3）。
- `--output-format stream-json`：每行一个 JSON 事件，供实时解析。
- `--include-partial-messages`：**关键**——让 tool_use 的 `input_json_delta` 增量可见，才能拼出 Plan subagent 正在生成的 tasks JSON。
- `--permission-mode bypassPermissions`：允许 Claude 读 run 目录里的 CLAUDE.md 等文件而不弹权限。
- 固定 `--session-id`：跨轮续上下文（同一大脑延续历史）。

### 3.2 Plan subagent 的 JSON 捕获（三路并行）

1. **`input_json_delta` 流式拼装**：`on_line()` 把每个 `content_block_delta.input_json_delta.partial_json` 按 `index` 累加进 `subagent_input_parts[index]`；每次累加后尝试 `json.loads`，一旦能解析且内容命中 `capture_plan_subagent()`（含 `subagent_type == "Plan"`），就认为这是规划任务，记录该 tool 的 id。
2. **`content_block` 静态扫描**：`remember_plan_tool()` 递归遍历每个事件的 `content_block` / `message`，找出 `type == "tool_use"` 且 input 里带 `subagent_type == "Plan"` 的 tool_id，记入 `plan_tool_ids`。
3. **result envelope 回退**：进程结束后，从 stdout 反序遍历找 `type == "result"` 的 envelope，取 `result.text` 作为规划输出；再做清洗：
   - 去掉 ```` ```json ```` 围栏（`removeprefix/removesuffix`）；
   - 若 raw 以 `{` 开头且含 `\n{`，**只取最后一行**（防模型把解释文字和 JSON 混在一行）；
   - `json.loads` 失败即抛异常 → 整个 run 标记 FAILED。

`plan_tool_ids` 同时喂给 `logview.py` 的 `is_plan_stream()`，让 TUI/日志渲染时能把 Plan subagent 的 thinking/tool 调用区分出来高亮。

### 3.3 桥接协议（`src/vulnhunt/prompts.py`）

`planner_prompt(goal, round_no, prior, workspace_root)` 生成喂给顶层 Claude 的提示词，内含：

- **输出期望**：顶层 Claude 只负责"桥接"，必须输出**纯英文、纯 JSON** 的 `{"tasks":[{id,title,description,required_output?,relevant_context?}]}`，系统据此解析后派发。
- **转发标记段**：`===转发内容从这开始===` 到 `===转发内容到这结束===`，要求顶层 Claude 原样转发给 Plan subagent，严禁增删。转发内容里包含：
  - 任务（漏洞挖掘规划）、类型（黑盒）、目的（Critical/High/Medium）；
  - **`授权范围：{{这里由你填写}}` / `垃圾漏洞清单：{{这里有由你填写}}`** —— 占位符，由顶层 Claude 读取 run 目录里复制的 `CLAUDE.md` 后补全（机制依赖 `RunStore.create()` 的复制行为）；
  - 唯一工作目录 = `workspace_root`（run 目录绝对路径），禁止越权访问父目录；
  - 目标 / 当前轮次 / 上轮结果（prior，JSON 序列化回填）。
- **大脑-手约束**：
  - "每个 codex 之间信息并不互通，严禁 codex 依赖其他 codex 的结果"；
  - "第一轮你只会获得一个域名……严禁刻意子域名收集"；
  - "你有十个 codex 但不是必须都给……简易任务和依赖前置任务的适当分配即可"；
  - 注：超出 `max_workers`（默认 10）的 task 会被系统**直接丢弃不排队**（见 `known-gaps.md` 缺口 6 已解决）。

### 3.4 日志

每轮 claude 的 stream-json 逐行追加到 `logs/claude_round_<NNN>.jsonl`（原文保留，供 `vulnhunt log` 回放）。解析动作通过 `logger/streamer/stream_end` 回调输出到 TUI 或静默丢弃。

## 4. RUNNING 深层机制（`src/vulnhunt/workers.py` + `cli/codex.py`）

### 4.1 并发模型

`WorkerPool.run(tasks, round_no)`：

```python
with ThreadPoolExecutor(max_workers=self.config.max_workers) as pool:
    return list(pool.map(one, tasks))
```

- `pool.map` 保序返回，但任务是并发执行的。
- **超出 `max_workers` 的 task 直接丢弃**——只执行前 `max_workers` 个，不排队；被丢弃的任务 ID 记录在 `logs/round_<NNN>.log`，供下一轮重新规划。
- 每个 task 的 workspace：`<run_dir>/workspaces/round_<NNN>_<task_id>/`，`exec_task` 内 `mkdir`。
- 任务输入先落盘 `tasks/<tid>_input.json`；结果由 `exec_task` 返回后落盘 `tasks/<tid>_result.json`。

### 4.2 Codex 调用形态

```python
codex exec "" -C <workspace> --json -o <workspace>/_last_message.json \
      -s danger-full-access --skip-git-repo-check --color never
```

- `-C <workspace>`：工作目录（先 `Path(workspace).resolve()` 固定为绝对路径，避免 Windows 下 cwd 相对嵌套成 `runs\...\workspaces\...` 的 os error 3）。
- `-s danger-full-access`：完整沙箱权限（执行命令、读写文件、联网）。**这是强沙箱声明，请只对授权目标使用**。
- `--json -o _last_message.json`：codex 把最终回复写成 JSON 文件，vulnhunt 再轮询读取。
- 任务提示词（模板内嵌）严格约束：
  - 要求输出 `status`（SUCCESS/FAILURE/PARTIAL）+ `summary` + `findings` 的**纯 JSON**；
  - **只允许写本任务 workspace**，禁止 `..`、绝对路径、访问 tasks/logs/findings/report/其他任务目录；
  - "任务完成时结束所有产生的子进程"。

### 4.3 会话续跑

- `exec_task` 先查 workspace 里是否有 `.codex_session`：有则走 `codex exec resume <id> - ...`（同一会话继续，保留历史上下文）。
- 首次运行：从 stdout 里找 `type == "thread.started"` 事件，取 `thread_id` 写入 `.codex_session`。
- 效果：同一 task 跨轮/断点续跑时，Codex 还记得上一轮的思考，而不是从头再来。

### 4.4 结果读取

`_last_message.json` 有内容后 `json.loads` 转 `WorkerResult`（字段见 `models.py`）；若 20 次轮询（每次 50ms）仍无内容，则构造一个 `FAILURE` 的 `WorkerResult`（带 `stdout_tail/stderr_tail/error`）返回，不抛异常——失败被记录，不拖垮整轮。

## 5. 进程管理（`src/vulnhunt/cli/base.py`）

`run_process()` 是唯一子进程入口，统一处理：

- **双读线程**：stdout / stderr 各起一个线程逐行读，避免管道填满死锁；`on_stdout_line` 回调支持逐行实时处理（claude 日志就是靠它）。
- **cancel 检查**：主循环 50ms 轮询 `cancel_event`，置位则强杀。
- **超时**：`deadline = start + timeout_s`；到点 `_kill_process()`，置 `timed_out=True`。
- **强杀跨平台**：Windows 用 `taskkill /pid <pid> /T /F`（杀整棵进程树，codex 派生的子进程也会被带走）；POSIX 先 `terminate()` 再 `kill()`。
- **编码**：统一 `utf-8 errors=replace`，Windows 控制台乱码不致命。
- **异常**：`OSError`（可执行文件不存在等）返回 `exit_code=-1`。

## 6. 落盘协议（`src/vulnhunt/state.py`）

`RunStore` 是一层薄封装，核心两个设计：

### 6.1 原子写

```python
def _write(self, name, obj):
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(...)
    os.replace(tmp, path)   # 原子替换
```

先写 `.tmp` 再 `os.replace`，崩溃不会留下半截 JSON。

### 6.2 目录布局与上下文复制

```
<run_dir>/
├── run.json / state.json        # 运行状态（原子写）
├── CLAUDE.md                    # RunStore.create() 时从项目根 shutil.copy2
├── plans/round_<NNN>_plan.json  # 每轮规划
├── tasks/<tid>_input.json       # 任务输入
├── tasks/<tid>_result.json      # 任务结果（WorkerResult 序列化）
├── findings/                    # ⚠️ 目录恒空，save_finding() 无调用点
├── logs/claude_round_<NNN>.jsonl / codex_<tid>.jsonl
├── report/report.json / report.md
└── workspaces/round_<NNN>_<tid>/   # codex 独立工作目录（含 _last_message.json / .codex_session）
```

序列化统一走 `models._plain()`：把 dataclass / Enum / list / dict 全部降为纯 JSON 类型。

## 7. 日志体系（`src/vulnhunt/logview.py`）

- **三层动作**：`LogAction`（整行）、`StreamAction`（流式增量）、`StreamEndAction`（结束当前流式行）。TUI 与 `AggregateSink`（回放）都消费这层抽象。
- **截断策略**（常量）：tool 结果 2000 字符/30 行、tool 输入 500、思考 2000、文本 4000、最终结果 500——长输出不会刷爆界面。
- **`is_plan_stream()`**：命中 `subagent_type=="Plan"` 或 `parent_tool_use_id ∈ plan_tool_ids` 的行按"规划"组件高亮，把大脑的规划思考与顶层输出区分开。
- **回放**：`vulnhunt log <run_dir> [--round N]` → `replay_file()` 重新喂给 `ClaudeLogRenderer`，重现当时界面。

## 8. 关键设计权衡

| 决策 | 理由 | 代价 |
|---|---|---|
| 子进程而非 in-process 调用 LLM | 隔离、可强杀、复用成熟 CLI | 协议对接复杂（stream-json 解析） |
| Codex 任务间不互通 | 天然并行、上下文干净、互不污染 | 无法复用彼此的中间结果，靠大脑汇总 |
| Claude 固定 session-id | 跨轮延续规划上下文 | 长 run 上下文成本持续累积 |
| 每任务独立 workspace + 会话续跑 | 断点续跑、故障隔离 | 磁盘占用、需要 .codex_session 机制 |
| 纯 stdlib、零依赖 | 部署即用、无供应链面 | 一切轮子自己造（TUI、渲染、并发） |
| findings 独立落盘方法存在但未接 | 预留扩展（见 known-gaps） | 实际 findings 只藏在 task 结果里 |
