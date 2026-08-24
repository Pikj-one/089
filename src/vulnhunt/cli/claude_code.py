import json, uuid
from pathlib import Path
from .base import run_process, resolve_executable
from ..models import Plan, compute_orders
from ..prompts import planner_prompt
from ..logview import ClaudeLogRenderer, LogAction, StreamAction, StreamEndAction

# prior 瘦身：注入规划提示词前剥掉 codex 原始输出尾部（各 4000 字符）——
# 规划决策只需要 status/summary/findings 与证据路径，裸 stdout/stderr 是纯噪音，
# 且一旦进入续接会话的历史就永远随每轮请求重发。落盘的 tasks/*_result.json 保留全量字段不受影响。
_PRIOR_DROP=('stdout_tail','stderr_tail')
def slim_prior(prior):
    return [{k:v for k,v in item.items() if k not in _PRIOR_DROP} for item in (prior or []) if isinstance(item,dict)]

class ClaudeWrapper:
    def __init__(self,config,logger=None,store=None,streamer=None,stream_end=None):
        self.config=config; self.session_id=None; self.logger=logger or (lambda component,message: None); self.cancel_event=None; self.store=store; self.streamer=streamer; self.stream_end=stream_end or (lambda: None); self._renderer=ClaudeLogRenderer()

    def health_check(self): return run_process([resolve_executable([self.config.claude_exec]),'--version'],timeout_s=20).exit_code==0

    def plan(self,goal,round_no,prior,work_dir):
        work_dir=Path(work_dir).resolve()
        prompt=planner_prompt(goal,round_no,slim_prior(prior),work_dir,self.config.max_workers)

        def apply(action):
            if isinstance(action, LogAction): self.logger(action.component, action.message)
            elif isinstance(action, StreamAction): self.streamer(action.component, action.text) if self.streamer else self.logger(action.component, action.text)
            elif isinstance(action, StreamEndAction): self.stream_end()

        def on_line(line):
            if self.store: self.store.append_log(f'claude_round_{round_no:03d}.jsonl', line)
            for action in self._renderer.feed(_as_event(line)): apply(action)

        r=None
        for attempt in range(2):
            resuming=bool(self.session_id)  # 本轮是否续接既有会话（第 2 轮起为 True）
            if resuming:
                session_args=['--resume',self.session_id]  # --session-id 对已落盘的 ID 会报 already in use 秒退，续接必须用 --resume
            else:
                self.session_id=str(uuid.uuid4())
                session_args=['--session-id',self.session_id]
            args=[resolve_executable([self.config.claude_exec]),'-p','', '--output-format','stream-json','--include-partial-messages','--verbose','--permission-mode','bypassPermissions',*session_args]
            r=run_process(args,cwd=work_dir,input_text=prompt,timeout_s=self.config.claude_timeout_s,cancel_event=self.cancel_event,on_stdout_line=on_line)
            if not r.exit_code:
                break
            cause=(f"claude 规划超时（>{self.config.claude_timeout_s}s），已强制结束进程" if r.timed_out else r.stderr) or f'claude failed (exit={r.exit_code})'
            # 续会话子进程启动即退（Windows 上表现为 stdin Broken pipe）曾把整次 run 打成 FAILED。
            # 放弃该会话、换全新会话重试一次；prior 已随提示词传入，规划上下文不丢（主 agent 直连后状态本就全在 prior+黑板里）。
            if attempt==0 and resuming and not r.timed_out:
                self.logger('CLAUDE', '规划子进程启动失败（疑似续会话异常），已切换新会话重试')
                self.session_id=None
                continue
            raise RuntimeError(cause)
        envelopes=[]
        for line in r.stdout.splitlines():
            try: envelopes.append(json.loads(line))
            except json.JSONDecodeError: pass
        envelope=next((item for item in reversed(envelopes) if item.get('type') == 'result'), envelopes[-1] if envelopes else {})
        result=envelope.get('result', r.stdout)
        raw=result.get('text', '') if isinstance(result, dict) else result
        raw=(raw or r.stdout).strip().removeprefix('```json').removesuffix('```').strip()
        if raw.startswith('{') and '\n{' in raw: raw=raw.splitlines()[-1]
        plan=Plan.from_dict(json.loads(raw))
        orders=compute_orders(plan.tasks)  # order 由代码按 depends_on 计算，不再依赖模型
        for t in plan.tasks: t.order=orders[t.id]; t.depends_on=[]
        self.logger("CLAUDE", f"第 {round_no} 轮规划完成：拆分 {len(plan.tasks)} 个任务")
        return plan

def _as_event(line):
    """stream-json 行 → renderer 可消费的事件。"""
    try: ev=json.loads(line)
    except json.JSONDecodeError: return {}
    return ev
