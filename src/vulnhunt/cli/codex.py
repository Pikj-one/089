import json, time
from pathlib import Path
from .base import run_process, resolve_executable
from ..models import WorkerResult, TaskResultStatus


def _extract_json(raw):
    """codex 可能在 JSON 前/后写解释文字：取第一个 { 到最后一个 } 之间的子串再解析。"""
    if not raw:
        return None
    s = raw.strip()
    start = s.find('{')
    end = s.rfind('}')
    if start < 0 or end <= start:
        return None
    return s[start:end + 1]


class CodexWrapper:
    def __init__(self,config,logger=None,store=None): self.config=config; self.logger=logger or (lambda component,message: None); self.cancel_event=None; self.store=store
    def health_check(self): return run_process([resolve_executable([self.config.codex_exec]),'--version'],timeout_s=20).exit_code==0
    def exec_task(self,task,workspace):
        # --output-schema：用 JSON Schema 硬约束最终回复结构，把结果格式从「靠 prompt 约定」升级为
        # 「生成端强制」；_extract_json 兜底仍保留（模型偶尔在 JSON 前后夹解释文字/超 schema 字段）。
        schema_file=Path(__file__).resolve().parent.parent/'schemas'/'worker_result.json'
        schema_args=['--output-schema',str(schema_file)]
        # workspace 可能来自 runs_root 的相对路径，而子进程同时使用它作为 cwd。
        # Codex 会相对于 cwd 再解析 -C/-o；因此这里必须先固定为绝对路径，
        # 避免出现 workspace\runs\... 这样的错误嵌套路径（Windows 下报 os error 3）。
        workspace=Path(workspace).resolve()
        # 黑板目录：所有 codex 共享、跨轮保留；仅 store 存在时才启用。
        blackboard=(self.store.root/'blackboard').resolve() if self.store else None
        if blackboard: blackboard.mkdir(parents=True,exist_ok=True)
        bb_scope="与共享黑板目录" if blackboard else ""
        name_tag=workspace.name
        blackboard_contract=(
            f"""## 共享黑板契约（必须遵守）
共享黑板目录：{blackboard}，所有 codex 共享、跨轮保留，可直接读写。
1. **可写入黑板的共享资源**：页面 HTML、JS 源码/提取产物、robots.txt、API 文档/响应提取物（JSON/文本）以及派生的公共中间结果（端点清单、指纹报告、路由/账号清单等）。命名规范 `{name_tag}_<原文件名>`（如 `{name_tag}_umi.js`），不要写进本任务工作目录。
2. **禁止写入黑板**：CSS 样式表、图片（png/jpg/jpeg/gif/svg/webp/ico/bmp）、字体（woff/woff2/ttf/eot/otf）、原始 HTTP 响应头 dump（如 `*_headers.txt`）。这些是不可复用噪音资产，留在本任务工作目录即可，禁止写入黑板。
3. **下载前先查黑板**：黑板上已存在同名/同 URL 的资源时，直接从黑板读取复用，禁止重复下载。
4. 本任务工作目录只存放私有产物：仅供本任务单次使用的抓取、分析脚本、临时文件、本任务最终 JSON 报告、截图。

"""
            if blackboard else ""
        )
        prompt = rf"""任务：{task.description}
要求输出：{task.required_output}
相关上下文：{task.relevant_context or '无'}
本任务工作目录：{workspace}
{blackboard_contract}任务完成时结束所有产生的子进程

## 路径限制
本任务只允许访问本任务工作目录{bb_scope}。禁止访问或写入任何其他路径，包括运行目录、tasks、logs、findings、report、其他任务目录、项目目录和用户目录。禁止使用 ..、切换到其他目录或通过绝对路径绕过限制。

## 安全边界（硬性约束，即使任务描述要求更激进也必须遵守）
你只证明漏洞存在并产出证据，不执行任何会造成实际危害的操作：
- 只读验证：禁止 DELETE / DROP / TRUNCATE / INSERT / UPDATE / ALTER、文件删除或覆盖、写入后门、创建持久化访问入口等破坏性动作。
- 数据类漏洞（SQL 注入、任意文件读等）：只证明漏洞存在（报错回显、布尔/时间盲注、探测返回结构），禁止读取、导出或回传真实业务数据（表数据、用户凭据、个人隐私）。
- 爆破 / 枚举：控制速率并设尝试次数上限，达到上限即停止，避免触发账号锁定或服务过载。
- 目标范围：只对任务描述涉及的目标主机与端点发起请求；禁止请求任务范围外的任何主机、域名或 IP。
- 结束后不留后门、不留持久化进程、不留目标侧痕迹。

请严格只输出一个 JSON 对象，不要输出 Markdown、解释文字或额外内容。
字段必须包含 status、summary、findings；status 使用 SUCCESS、FAILURE 或 PARTIAL。"""
        exe=resolve_executable([self.config.codex_exec]); output_file=Path(workspace)/'_last_message.json'; session_file=Path(workspace)/'.codex_session'; session_id=session_file.read_text(encoding='utf-8').strip() if session_file.exists() else ''; log_file=f'codex_{task.id}.jsonl'
        def on_line(line):
            if self.store: self.store.append_log(log_file, line)
            try: ev=json.loads(line)
            except json.JSONDecodeError: return
            item=ev.get('item') if isinstance(ev.get('item'), dict) else {}
            if ev.get('type')=='item.completed' and item.get('text'):
                if item.get('type')=='reasoning': self.logger(f"CODEX-{task.id}-THINK", item['text'])
                elif item.get('type')=='agent_message': self.logger(f"CODEX-{task.id}", item['text'])
        # resume 分支：实测 codex 0.149.0 不继承会话的 sandbox_policy（session_meta 记录 danger-full-access，
        # resume 仍回落默认沙箱：cwd=workspace 时为 workspace-write、共享黑板目录被沙箱拒绝写入）。
        # resume 不接受 -s/--add-dir（exec-only 标志），全权沙箱只能靠 --dangerously-bypass-approvals-and-sandbox
        # （语义 ≈ fresh 分支的 danger-full-access，仅对授权目标使用）。
        if session_id: args=[exe,'exec','resume',session_id,'-','--json','-o',str(output_file),*schema_args,'--skip-git-repo-check','--dangerously-bypass-approvals-and-sandbox']
        elif blackboard: args=[exe,'exec','', '-C',str(workspace),'--add-dir',str(blackboard),'--json','-o',str(output_file),'-s',self.config.codex_sandbox,*schema_args,'--skip-git-repo-check','--color','never']
        else: args=[exe,'exec','', '-C',str(workspace),'--json','-o',str(output_file),'-s',self.config.codex_sandbox,*schema_args,'--skip-git-repo-check','--color','never']
        r=run_process(args,cwd=workspace,input_text=prompt,timeout_s=self.config.codex_timeout_s,cancel_event=self.cancel_event,on_stdout_line=on_line); p=output_file
        for line in r.stdout.splitlines():
            try:
                event=json.loads(line)
                if event.get('type')=='thread.started' and event.get('thread_id'): session_file.write_text(event['thread_id'],encoding='utf-8'); break
            except json.JSONDecodeError: pass
        result=None
        if p.exists():
            for _ in range(20):
                try:
                    raw=p.read_text(encoding='utf-8').strip()
                    body=_extract_json(raw) if raw else None
                    if body:
                        d=json.loads(body); d['task_id']=task.id; result=WorkerResult.from_dict(d); break
                except (OSError, json.JSONDecodeError):
                    time.sleep(0.05)
        if result is None:
            # 超时被强杀时，codex 的 stderr 只残留启动提示（如 "Reading additional input from stdin..."），会把真实原因掩盖掉。
            # 这里在 timed_out 时优先报超时归因；原始 stderr 仍保留在 stderr_tail 供排查。
            err=(f"codex 执行超时（>{self.config.codex_timeout_s}s），已强制结束进程，未生成结果文件 _last_message.json" if r.timed_out else r.stderr)
            result=WorkerResult(task.id,r.exit_code,TaskResultStatus.FAILURE,error=err,stdout_tail=r.stdout[-4000:],stderr_tail=r.stderr[-4000:],duration_s=r.duration_s); self.logger("ERROR", f"任务 {task.id} 失败：{err or '无结果文件'}")
        else:
            self.logger(f"CODEX-{task.id}", f"任务 {task.id} 完成：{result.status.value}，发现 {len(result.findings)} 个问题")
        # 无论成败，强制清理黑板上 codex 写入的噪音资产（css/图片/字体/响应头），并对小黑板 JS 做 Prettier 静默格式化。
        if blackboard:
            from ..blackboard import sanitize_blackboard, format_blackboard_js
            sanitize_blackboard(blackboard, self.logger)
            format_blackboard_js(blackboard, self.config.prettier_max_bytes, self.logger)
        return result
