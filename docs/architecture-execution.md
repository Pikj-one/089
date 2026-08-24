# RUNNING 与进程管理（`src/vulnhunt/workers.py` + `src/vulnhunt/cli/codex.py` + `src/vulnhunt/cli/base.py`）

> 源码级剖析。主 hub 见 [architecture.md](architecture.md) §1~2（总体设计 / 状态机）。本文件是原 architecture.md §4、§5 的独立拆分，章节号已重排；涉及跨子系统机制时给出链接。

## 1. RUNNING 深层机制

### 1.1 并发模型（`src/vulnhunt/workers.py`）

`WorkerPool.run(tasks, round_no)`：

```python
with ThreadPoolExecutor(max_workers=self.config.max_workers) as pool:
    return list(pool.map(one, tasks))
```

- 保留任务按 `order` 升序**稳定排序**后分组：同一 order 一波，波内 `ThreadPoolExecutor(max_workers)` 并行；`pool.map` 返回即本波全部完成，形成**波间同步屏障**，后一波才启动。结果按波次顺序拼接（波内保序）。
- **超出 `max_workers` 的 task 直接丢弃**——只执行前 `max_workers` 个，不排队；被丢弃的任务 ID 记录在 `logs/round_<NNN>.log`，供下一轮重新规划。
- 每个 task 的 workspace：`<run_dir>/workspaces/round_<NNN>_<task_id>/`，`exec_task` 内 `mkdir`。
- 任务输入先落盘 `tasks/<tid>_input.json`；结果由 `exec_task` 返回后落盘 `tasks/<tid>_result.json`。

### 1.2 Codex 调用形态（`src/vulnhunt/cli/codex.py`）

```python
# fresh 分支（workspace 无 .codex_session，codex.py:76-77）：
#   单 store 场景（vulnhunt 正常运行）带共享黑板：
codex exec "" -C <workspace> --add-dir <blackboard> --json -o <workspace>/_last_message.json \
      -s danger-full-access --skip-git-repo-check --color never
#   无 store（黑测单跑/测试）时省略 --add-dir：
codex exec "" -C <workspace> --json -o <workspace>/_last_message.json \
      -s danger-full-access --skip-git-repo-check --color never
```

- `-C <workspace>`：工作目录（先 `Path(workspace).resolve()` 固定为绝对路径，避免 Windows 下 cwd 相对嵌套成 `runs\...\workspaces\...` 的 os error 3）。
- `--add-dir <blackboard>`：开放 `<run_dir>/blackboard/` 作为共享黑板目录（所有 codex 共享、跨轮保留）。该目录会随会话写入 `session_meta.workspace_roots`，但实测（0.149.0）**resume 不恢复会话的 `sandbox_policy`**——它回落默认沙箱（cwd=workspace 时 `workspace-write`、共享黑板被拒写；cwd 在其他目录时甚至只读），`session_meta` 里的 `workspace_roots`/`sandbox_policy` 并不会让黑板恢复可写。因此 resume 分支必须显式传 `--dangerously-bypass-approvals-and-sandbox` 获得与 fresh 分支 `danger-full-access` 等价的全权访问（2026-08-24 实测：不加此 flag 黑板写入被拒，加了即可写）。
- `-s danger-full-access`：完整沙箱权限（执行命令、读写文件、联网）。**这是强沙箱声明，请只对授权目标使用**。
- `--json -o _last_message.json`：codex 把最终回复写成 JSON 文件，vulnhunt 再轮询读取。
- 任务提示词（模板内嵌）严格约束：
  - 要求输出 `status`（SUCCESS/FAILURE/PARTIAL）+ `summary` + `findings` 的**纯 JSON**；
  - **共享黑板契约**：可写入黑板的共享资源为页面 HTML、JS 源码/提取产物、robots.txt、API 文档/响应提取物（JSON/文本）与派生中间结果（端点清单、指纹报告、路由/账号清单等），命名规范 `<工作目录名>_<原文件名>`（如 `round_001_task_2_umi.js`）；**禁止写入** CSS、图片、字体、原始 HTTP 响应头 dump（噪音资产，留在 workspace 即可）；**下载前先查黑板**，已有同名/同 URL 资源直接复用、禁止重复下载；私有产物（脚本、临时文件、最终 JSON 报告、截图）只写本任务 workspace；
  - 路径限制：本任务只允许访问 workspace 与共享黑板目录，禁止 `..`、绝对路径、访问 tasks/logs/findings/report/其他任务目录；
  - "任务完成时结束所有产生的子进程"。
- codex 任务结束后（无论成败），`exec_task` 对黑板执行两道后处理（`src/vulnhunt/blackboard.py`）：`sanitize_blackboard()` 按后缀+内容启发式删除 CSS/图片/字体/响应头 dump 噪音文件；`format_blackboard_js()` 对未压缩的小型 .js 用 Prettier 静默格式化（跳过 >1MB 或平均行长 >2000 的压缩产物，失败静默忽略）。

### 1.3 会话续跑

```python
# resume 分支（workspace 有 .codex_session，内容即 <session_id>；codex.py:75）：
# 上下文记忆跨进程保留，但 sandbox_policy 不随会话继承——全权沙箱只能靠该 flag，
# 且 resume 不接受 -s/--add-dir/--color（exec-only 标志）
codex exec resume <session_id> - --json -o <workspace>/_last_message.json \
      --skip-git-repo-check --dangerously-bypass-approvals-and-sandbox
```

- `exec_task` 先查 workspace 里是否有 `.codex_session`：有则走 resume 分支（同一会话继续，保留历史上下文）。
- 首次运行：从 stdout 里找 `type == "thread.started"` 事件，取 `thread_id` 写入 `.codex_session`。
- 效果：同一 task 跨轮/断点续跑时，Codex 还记得上一轮的思考，而不是从头再来。
- 沙箱不继承：实测 `codex exec resume` 不会恢复会话记录的 `sandbox_policy`（`session_meta` 存了 `danger-full-access`，resume 仍回落默认沙箱），且 resume 不接受 `-s`/`--add-dir`。因此 resume 分支显式传 `--dangerously-bypass-approvals-and-sandbox` 取得全权沙箱（`codex.py:71`），黑板与工作目录才能读写——**勿误以为配置随会话继承而省略该 flag**。
- 选项集差异：`codex exec resume` 的选项集比 `exec` 更小——不接受 `--color`（报 `unexpected argument`）、`--add-dir`、`-s`，沙箱相关仅 `--dangerously-bypass-approvals-and-sandbox`。全权沙箱只能靠该 flag（见上一条）；**勿给 resume 分支补 `--color never` 等 exec-only 标志**。

### 1.4 结果读取

`_last_message.json` 有内容后 `json.loads` 转 `WorkerResult`（字段见 `models.py`）；若 20 次轮询（每次 50ms）仍无内容，则构造一个 `FAILURE` 的 `WorkerResult`（带 `stdout_tail/stderr_tail/error`）返回，不抛异常——失败被记录，不拖垮整轮。

## 2. 进程管理（`src/vulnhunt/cli/base.py`）

`run_process()` 是唯一子进程入口，统一处理：

- **双读线程**：stdout / stderr 各起一个线程逐行读，避免管道填满死锁；`on_stdout_line` 回调支持逐行实时处理（claude 日志就是靠它）。
- **cancel 检查**：主循环 50ms 轮询 `cancel_event`，置位则强杀。
- **超时**：`deadline = start + timeout_s`；到点 `_kill_process()`，置 `timed_out=True`。
- **强杀跨平台**：Windows 用 `taskkill /pid <pid> /T /F`（杀整棵进程树，codex 派生的子进程也会被带走）；POSIX 先 `terminate()` 再 `kill()`。
- **编码**：统一 `utf-8 errors=replace`，Windows 控制台乱码不致命。
- **异常**：`OSError`（可执行文件不存在、stdin 管道破裂等）返回 `exit_code=-1`，并保留子进程已打印的 stderr——否则 claude/codex 启动即退关闭 stdin 时，真实报错会被吞成干巴巴的 `[Errno 32] Broken pipe`（见 [troubleshooting.md](troubleshooting.md) §2）。
