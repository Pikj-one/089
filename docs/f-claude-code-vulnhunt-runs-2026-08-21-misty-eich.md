# VulnHunt：TUI 全量渲染 Claude 运行日志 + 回放

## Context（背景）

VulnHunt（`F:\claude code\089`，纯 Python stdlib 编排工具）通过 `ClaudeWrapper` 以 `claude -p '' --output-format stream-json --include-partial-messages` 启动 Claude CLI，并把每行原始 JSON 事件落盘到 `logs/claude_round_NNN.jsonl`。

现在唯一 UI（`src/vulnhunt/tui.py` 的行式 TUI）只显示日志的**子集**：思考增量、文本增量、子代理生命周期行。其余内容——会话 init、工具调用与流式入参、工具结果、每轮 token 用量、thinking_tokens 计数、最终 `result`（耗时/成本/用量）——都进了日志却没显示。

用户需求（已确认）：
- **直播 + 回放**：运行时完整流式显示全部事件类型；事后在 TUI 里查看/回放已落盘的 `claude_round_*.jsonl`。
- **智能渲染**：覆盖全部事件类型（会话/思考/工具调用+入参/工具结果/子代理/汇总），但对纯噪音做聚合压缩（thinking_tokens 42 条、task_progress 65 条、input_json_delta 128 条逐字符碎片），长 tool_result 截断加标记，避免刷屏。

真实日志 `F:\claude code\vulnhunt-runs\2026\08\21\13-20\64e877e91cf4\logs\claude_round_001.jsonl`（539 行 / 361KB，已验证结构）：顶层 `type` = `stream_event`(198)/`assistant`(138)/`system`(136)/`user`(66)/`result`(1)。**关键发现：所有 `stream_event` 的 delta 都属于顶层 turn；子代理内容只以 `assistant`/`user` 记录形式出现（134/138 带 `subagent_type:"Plan"`）。** 因此去重规则 = 顶层 turn 用 delta 流式渲染，子代理用 `assistant` 记录渲染，不重复。

## 新增模块 `src/vulnhunt/logview.py`

纯标准库，承载共享渲染器、显示动作、sink、回放驱动、截断常量。

**截断常量**：`TOOL_RESULT_TRUNC=2000`（字符）+ `TOOL_RESULT_LINES=30`（行数，实测最大 tool_result 10KB）；`TOOL_INPUT_TRUNC=500`；`THINK_TRUNC=2000`；`TEXT_TRUNC=4000`；`RESULT_TRUNC=500`。辅助函数 `truncate(text, limit, lines=0)`；`format_line(component, message)` 拼 `[HH:MM:SS][COMP] msg`；`is_plan_stream(ev, event, plan_tool_ids)` 从现 `on_line` 启发式原样抽出（live 复用 `plan_tool_ids`，回放传空）。

**显示动作**（渲染器输出契约，live/回放共用）：
```python
@dataclass LogAction(component, message)       # 整行
@dataclass StreamAction(component, text)       # 增量（live 流式）
@dataclass StreamEndAction                     # 刷新当前流式行
```

**`ClaudeLogRenderer`**：`feed(ev, plan_stream) -> list[Action]`。内部状态三份 dict：`_progress_logged`（task_id→已显示描述，去重）、`_top_streamed`（本顶层 turn 是否已流式）、`_blocks`（content index→{kind,name,tool_id,input_json}，组装入参）。

**事件→显示映射**（两模式共用）：
- `system/init` → `CLAUDE-PLAN` `session: model=… v=… {permissionMode} tools={len}`；`status` → `status: …`；**`thinking_tokens` 抑制**。
- `system/task_started` → `{kind}启动：{description}`（kind=子代理/后台任务）；`task_progress` → 仅描述变化时 `正在执行：{description}`（去重）；`task_notification` → `{kind}结束（{status}）：{summary}`；`background_tasks_changed` → 按 task_id 去重 `后台任务：{desc}`。
- `stream_event/message_start` → `CLAUDE` `turn: model=… in=… ttft=…ms`，重置 `_top_streamed`；`content_block_start`(tool_use) → 记录到 `_blocks`（不显示）；`thinking_delta` → `StreamAction(CLAUDE-THINK|CLAUDE-PLAN)`；`text_delta` → `StreamAction(CLAUDE|CLAUDE-PLAN)`；`input_json_delta` → **逐字符抑制**，追加进 `_blocks[i].input_json`；`signature_delta` 抑制；`content_block_stop`(tool_use) → `CLAUDE-TOOL` `tool: {name} {组装后json.dumps}`（不可解析则截断原串），弹出该块；`content_block_stop`(thinking/text) → `StreamEndAction`；`message_delta` → `CLAUDE` `turn end: stop=… in=… out=…`；`message_stop` → `StreamEndAction`。
- `assistant`（带 `subagent_type`）→ 逐块 `CLAUDE-PLAN`：thinking→`思考：{截断}`、tool_use→`tool: {name} {截断input}`、text→`{截断text}`；顶层（无 subagent_type）在 `_top_streamed=True` 时跳过（已流式），tool_use 已在 stop 时显示故也跳过。
- `user` → tool_result 块：`CLAUDE-PLAN`（子代理）或 `CLAUDE-TOOL`（顶层）`result{短id}{ [ERROR]}: {截断content}`（content 兼容 str / `[{type:text}]` 列表 / 顶层 `tool_use_result` 兜底）；synthetic text → `[user text] …`。
- `result` → `ORCH` `round done: {subtype} is_error=… turns=… dur=… cost=${…}`；`CLAUDE` `final({stop_reason}): {截断result}`；`CLAUDE` `usage: in=… out=… thinking=… cache_w=… cache_r=…`（全部 `.get()` 兜底）。
- 兜底：任何未识别形状 → `CLAUDE` `{type}: {截断json}`——保证未来新事件类型也"全部显示"。

**Sink + 驱动**：`AggregateSink(emit)` —— `log` 先 flush 再 emit；`stream` 按 component 归并碎片；`stream_end` flush。回放经 `replay_file(path, sink, plan_tool_ids=())`：逐行解析 → `is_plan_stream` → `renderer.feed` → 分发到 sink。

## 直播集成 `src/vulnhunt/cli/claude_code.py`

**保持不动**：`append_log`、`remember_plan_tool`/`capture_plan_subagent`/`plan_tool_ids`/`tool_ids_by_index`、`subagent_input_parts` 累积块（Plan 子代理识别）、`result` 信封的 plan 提取（118-127 行）。

**只替换显示块**（现 64-115 行）：`__init__` 加 `self._renderer = ClaudeLogRenderer()`；新增 `_apply(action)` 分发（LogAction→`logger`，StreamAction→`streamer` 无则 `logger`，StreamEndAction→`stream_end`）；在 plan 识别后调 `is_plan_stream` + `for a in self._renderer.feed(ev, plan_stream): self._apply(a)`。

既有测试（`tests/test_cli_wrappers.py`）不变即过：`Plan output` text_delta → StreamAction，测试无 streamer → 回退 logger → 相同 tuple；`子代理启动/正在执行(去重)/子代理结束` 字符串原样复刻；plan 提取路径未动。新增显示：init、status、message_start/delta、顶层 tool_use（由 input_json_delta 组装）、子代理全部块、tool_result、最终 result。

## 回放可达性 `src/vulnhunt/tui.py` + `src/vulnhunt/main.py`

v1 采用：(a) 命令循环运行结束后不退出 + 新增 `logs`/`claude [N]` 命令；(c) 新增非交互 `vulnhunt log <run_dir> [--round N]`。暂不做 `tui --replay` 交互模式（与 (c) 功能重叠且引入 stdin 复杂度）。

**TUI.command_loop 改动**：原"run 线程死亡即 return"改为一次性提示后**不退出**：
```python
if self.thread and not self.thread.is_alive() and not self._finished:
    self._finished = True; self._clear_prompt()
    self.log("UI", "run finished — commands: status, tasks, findings, logs, claude [round], abort, quit")
```
仅 `quit`/`exit`/`abort`/EOF/Ctrl+C 退出；`abort` 去掉 `return`（中止后仍可复查）。`_heartbeat` 在线程死后自然停止。抽出 `_handle_command(command) -> bool` 便于单测（无 `input()` 也能测退出逻辑）。

**新命令**：
- `logs` → 列出 `store.logs.glob("claude_round_*.jsonl")`。
- `claude [N]` → 默认最新轮日志，`--round`/参数 N 精确匹配 `claude_round_NNN.jsonl`；`self.log("UI", f"replay {path.name} ({size} bytes)")` 后 `replay_file(path, AggregateSink(self.log))`。

**main.py 新子命令**：
```python
log = sub.add_parser("log"); log.add_argument("run_dir"); log.add_argument("--round", type=int)
# 处理：store=RunStore(run_dir); 选 --round 匹配或最新 claude_round_*.jsonl;
# sink = AggregateSink(lambda c, m: print(format_line(c, m))); replay_file(path, sink)
```
无需 config，可作用于任意 run 目录。多轮用 `--round`，默认最新。**v1 不分页**（539 行/361KB 可接受，且 `vulnhunt log <dir> | more` 可管道）；分页器记为后续项。

## Codex 日志

超出本次范围。`replay_file` + `AggregateSink` 已 schema 无关，未来加 `CodexLogRenderer` 即可复用同一驱动；`vulnhunt log` 可加 `--kind codex`。本次不改。

## 测试（stdlib unittest，沿用 `patch("vulnhunt.cli.claude_code.run_process")` 模式）

**新增 `tests/test_logview.py`**：init/status 渲染；thinking_tokens 抑制；task_progress 去重；delta 流式组件（含 plan_stream 下 CLAUDE-PLAN）；tool_use 由 input_json_delta 组装；assistant 子代理全量渲染；顶层 assistant 不重复；tool_result 截断 + `[ERROR]` 标记；result 汇总；message_delta usage；replay_file 驱动聚合；AggregateSink 碎片归并；truncate 辅助。

**扩展 `tests/test_cli_wrappers.py`**：既有 3 个 claude 测试必须原样通过；新增 tool_use+tool_result 显示、init/status 显示测试。

**扩展 `tests/test_tui.py`**：`claude(1)` 回放临时 log 输出格式化行；`logs` 列轮；command_loop 线程死后保持存活、`quit` 退出。

**可选 `tests/test_main.py`**：`vulnhunt log <tmp_run_dir>` 冒烟（redirect_stdout）。

## 版本与提交

SemVer 次版本（新功能，向后兼容）：**0.2.8 → 0.3.0**（`pyproject.toml` + `src/vulnhunt/__init__.py` 的 `__version__`）。README 更新 TUI 命令与 `vulnhunt log` 用法；`docs/architecture.md` 提一句 `logview` 渲染器与回放。提交（按 AGENTS.md 约定式提交）：
```
feat(tui): 全量渲染 Claude 运行日志并支持回放
docs(readme): 更新 TUI 命令与 vulnhunt log 用法
chore(release): 升级版本至 v0.3.0
```

## 风险 / 说明

- `stream()` 仅 TTY 生效；非 TTY 直播回退 `log()` 逐碎片（既有行为，本次不改）。
- 直播 `on_line` 在 reader 线程、`claude` 回放在主线程，都经 `TUI._lock` 串行，不会交错；回放中日志持续增长属可接受快照语义。
- 顶层 tool_use 由流组装在 `content_block_stop` 显示；中途中止的顶层 tool 可能缺行——可接受。
- `task_notification` 无 `task_type` 时归为"后台任务"是既有怪癖，原样保留。
- 多轮日志：`claude 2` / `--round 2`，默认最新。

## 关键文件

- 新增 `src/vulnhunt/logview.py`（渲染器/动作/sink/驱动/常量）
- `src/vulnhunt/cli/claude_code.py`（替换 on_line 显示块，保留 plan 提取）
- `src/vulnhunt/tui.py`（命令循环存活 + `logs`/`claude [N]`）
- `src/vulnhunt/main.py`（`vulnhunt log <run_dir> [--round N]`）
- `tests/test_logview.py`（新）+ `tests/test_cli_wrappers.py` / `tests/test_tui.py`（扩展）

## 验证

1. `PYTHONPATH=src python -m unittest discover -s tests -v` 全绿（含既有 3 个 claude wrapper 回归测试）。
2. `python -m compileall -q src` 编译通过。
3. 用真实日志回放：`PYTHONPATH=src python -m vulnhunt log "F:\claude code\vulnhunt-runs\2026\08\21\13-20\64e877e91cf4"` —— 应输出全部事件类型（session 行、turn 行、工具调用与结果、子代理生命周期、最终 cost/usage），thinking_tokens 与 input_json 碎片被聚合、超长 tool_result 截断。
4. `python -m vulnhunt tui` 起真实（dry_run=false）直播，确认新事件类型实时出现；运行结束后 `>` 提示符仍在，输入 `logs`、`claude` 可回放。
5. 与 `tui.log.txt` 对照：同一 run 的直播输出应与 `vulnhunt log` 回放内容一致（除流式增量外）。
