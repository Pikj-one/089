# vulnhunt 故障排查指南

> 按症状找对策。所有条目基于源码行为（`src/vulnhunt/`）推演，标注了定位位置与排查路径。相关机制见 [architecture.md](architecture.md)。

## 1. 环境 / 启动

| 症状 | 原因 | 对策 |
|---|---|---|
| `vulnhunt doctor` 输出 `claude: False` / `codex: False` | CLI 不在 PATH 或版本过旧 | 确认 `claude --version`、`codex --version` 可用；`config.toml`/`VULNHUNT_CLAUDE_EXEC`/`VULNHUNT_CODEX_EXEC` 指定绝对路径 |
| `python -m vulnhunt` / `vulnhunt` 命令不存在 | 未安装 | `pip install -e .`（项目根执行） |
| `vulnhunt log` 输出乱码 | Windows 控制台编码 | `log` 命令内部已 `reconfigure(utf-8, errors=replace)`；仍乱码则 `chcp 65001` 或改用 Windows Terminal |

## 2. 运行失败（start / tui）

| 症状 | 定位 | 对策 |
|---|---|---|
| 运行立刻结束，状态 `FAILED` | `run_loop` 捕获异常归因为 FAILED | 看 `logs/claude_round_001.jsonl` 尾部；`state.json` 里 `status` 确认卡点 |
| `claude -p` 退出码非 0 → `RuntimeError` | `claude_code.py` 末尾 `if r.exit_code: raise` | 复现：手动跑 `claude -p ... --output-format stream-json` 看 stderr；多半是认证/额度/上下文超限 |
| Plan 输出无法解析成 JSON → run FAILED | `claude_code.py` `json.loads(raw)` 抛异常 | 检查 `logs/claude_round_*.jsonl` 最后几行：模型是否吐了 Markdown/解释而非纯 JSON；清洗规则只处理 ```json 围栏和"最后一行含 {" 的情况，多行杂讯会失败 |
| 某个任务 `status=FAILURE` | `codex.py` 20 次轮询仍无有效 `_last_message.json`。注：codex 在 JSON 前写解释文字导致解析失败的路径已修复（`_extract_json` 剥离前置文本，见 [known-gaps](known-gaps.md) §10）；残留原因通常是超时或输出完全非 JSON | 看该 task 的 `codex_<tid>.jsonl`；`tasks/<tid>_result.json` 的 `error/stdout_tail/stderr_tail` 有原始尾部输出 |
| 所有任务都很快 FAILURE | codex 未认证 / 沙箱不可用 | 手动 `codex exec "" -C <临时目录> ...` 验证；确认 codex 登录态 |

## 3. Windows 专项

| 症状 | 原因 | 对策 |
|---|---|---|
| codex 报 `os error 3`、路径变成 `...\runs\workspaces\...` | workspace 相对路径在 Windows 下与 cwd 嵌套 | `codex.py` 已 `Path(workspace).resolve()` 兜底；若仍出现，确认传给 `-C` 的是绝对路径 |
| 进程杀了但子进程还挂着 | 只杀了主进程 | 正常场景 `_kill_process` 用 `taskkill /T /F` 会带掉整棵进程树；个别仍残留时手动 `taskkill /F /PID <pid>` |
| TUI 无彩色 / 输出一行一行刷 | 非 TTY（重定向/管道/某些终端） | 属于设计内回退：流式输出自动降级为整行日志，功能不受影响 |

## 4. 中断 / resume

| 症状 | 说明 | 对策 |
|---|---|---|
| Ctrl+C 后状态变 `ABORTED` | 用户主动中断 | 可随时 `vulnhunt resume <run_dir>` 续跑 |
| resume 后又重跑本轮 | 设计如此：RUNNING 中断会重跑整轮当前 plan（见 [known-gaps](known-gaps.md) 缺口 9） | 接受或按缺口修复建议实现"跳过已完成任务" |
| 卡在"仍在运行，等待模型输出…" | 心跳提示，模型长时间无增量输出 | 默认 20s 无活动打一行；若持续很久，可能模型在长思考/长工具执行，等；若确认为挂死，Ctrl+C → resume |
| `abort` 命令后仍收尾缓慢 | codex/claude 有 50ms 轮询延迟 + 强杀时间 | 属正常，`taskkill` 需要时间回收 |

## 5. 日志定位

- **卡在哪个状态**：看 `<run_dir>/state.json` 的 `{"status": "...", "round": N}`。
- **规划过程**：`vulnhunt log <run_dir> --round N` 回放第 N 轮 Claude 全部思考/工具调用。
- **执行过程**：`logs/codex_<tid>.jsonl` 是 codex 逐行 JSON；`tasks/<tid>_result.json` 是最终结构化结果。
- **报告为什么是空的**：见下一节。

## 6. 报告 / findings 为空

| 症状 | 原因 | 对策 |
|---|---|---|
| `report.md` 只有一行行 `task_id: summary`，无漏洞明细 | 报告实现极简，不展开 findings | 直接看各 `tasks/<tid>_result.json` 的 `findings` 字段，那里有 Codex 返回的完整证据 |
| `findings/` 目录为空、TUI `findings` 命令无内容 | `save_finding()` 从未被调用（缺口 2） | 属已知缺口，先绕过：从 task 结果里找证据；待修复后正常 |
| 任务 `status=SUCCESS` 但 `findings=[]` | Codex 没挖到，或没按"findings 字段"输出 | 看该 task 的 `_last_message.json` / `codex_*.jsonl` 原始输出，确认是否格式不符导致解析丢弃 |

## 7. 超时调参

| 场景 | 字段 | 默认 |
|---|---|---|
| Claude 单轮规划超时 | `claude_timeout_s` | 900s |
| 单个 Codex 任务超时 | `codex_timeout_s` | `100_000_000`s（一亿，≈1157 天，暂等效不限制） |

改法：`config.toml` 或环境变量（`VULNHUNT_CLAUDE_TIMEOUT_S`）。探测类任务（爆破/大范围扫描）建议调大；任务挂死时可调小并观察 FAILURE 归因。

## 8. 常见报错速查

| 报错 | 含义 | 对策 |
|---|---|---|
| `RuntimeError: claude failed: ...` | `claude -p` 非零退出 | 见 2 节 |
| `json.decoder.JSONDecodeError: ...` | Plan/结果 JSON 解析失败 | 见 2 节 / 查看对应 jsonl |
| `FileNotFoundError: .../report/report.md` | 报告未生成 | run 未跑完即结束；先看 `state.json` 状态 |
| `PermissionError: ...`（Windows） | 文件被占用 | TUI/其他进程正读该文件；关掉 TUI 再试 |
| 任务失败但报错是 `Reading additional input from stdin...` | 这是 codex 启动读 stdin 的提示，被当作 stderr 捕获；曾有的「JSON 前写解释文字导致解析失败」路径已在 `codex.py` 修复（`_extract_json` 剥离前置文本）。若仍 FAILURE 且 `_last_message.json` 是纯 JSON，则定位到 exit-code/超时 | 看该任务 `*_result.json` 的 `duration_s`，若≈`codex_timeout_s` 则确系超时，调大超时或给任务减负；否则直接读 `workspaces/<tid>/_last_message.json` 确认内容 |

> 排查不决时，把 `state.json` + 对应轮的 `claude_round_*.jsonl` 尾部 + 某个 FAILURE 任务的 `*_result.json` 三样一起拿出来对照 [architecture.md](architecture.md) 的时序看。
