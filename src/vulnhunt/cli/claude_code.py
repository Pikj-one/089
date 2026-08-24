import json, uuid
from pathlib import Path
from .base import run_process, resolve_executable
from ..models import Plan, TaskSpec
from ..prompts import planner_prompt
from ..logview import ClaudeLogRenderer, LogAction, StreamAction, StreamEndAction, is_plan_stream
class ClaudeWrapper:
    def __init__(self,config,logger=None,store=None,streamer=None,stream_end=None):
        self.config=config; self.session_id=None; self.logger=logger or (lambda component,message: None); self.cancel_event=None; self.store=store; self.streamer=streamer; self.stream_end=stream_end or (lambda: None); self._renderer=ClaudeLogRenderer()
    def health_check(self): return run_process([resolve_executable([self.config.claude_exec]),'--version'],timeout_s=20).exit_code==0
    def plan(self,goal,round_no,prior,work_dir):
        work_dir=Path(work_dir).resolve()
        resuming=bool(self.session_id)  # 本轮是否续接既有会话（第 2 轮起为 True）
        subagent_input_parts={}
        tool_ids_by_index={}
        plan_tool_ids=set()
        plan_subagent_logged=False

        def apply(action):
            if isinstance(action, LogAction): self.logger(action.component, action.message)
            elif isinstance(action, StreamAction): self.streamer(action.component, action.text) if self.streamer else self.logger(action.component, action.text)
            elif isinstance(action, StreamEndAction): self.stream_end()

        def capture_plan_subagent(value):
            nonlocal plan_subagent_logged
            if not isinstance(value, dict):
                return False
            if value.get('subagent_type') == 'Plan':
                if not plan_subagent_logged:
                    self.stream_end()
                    self.logger('CLAUDE-PLAN', 'subagent_type=Plan')
                    plan_subagent_logged=True
                return True
            found=False
            for child in value.values():
                if isinstance(child, dict):
                    found=capture_plan_subagent(child) or found
                elif isinstance(child, list):
                    for item in child:
                        found=capture_plan_subagent(item) or found
            return found

        def remember_plan_tool(value, index=None):
            if not isinstance(value, dict):
                return
            if value.get('type') == 'tool_use':
                tool_id=value.get('id')
                if tool_id and capture_plan_subagent(value.get('input', {})):
                    plan_tool_ids.add(tool_id)
                    if index is not None:
                        tool_ids_by_index[index]=tool_id
            for child in value.values():
                if isinstance(child, dict):
                    remember_plan_tool(child, index)
                elif isinstance(child, list):
                    for item in child:
                        remember_plan_tool(item, index)

        def on_line(line):
            if self.store: self.store.append_log(f'claude_round_{round_no:03d}.jsonl', line)
            try: ev=json.loads(line)
            except json.JSONDecodeError: return
            event=ev.get('event') if isinstance(ev.get('event'), dict) else ev
            event_index=event.get('index')
            remember_plan_tool(event.get('content_block', {}), event_index)
            remember_plan_tool(ev.get('message', {}))
            capture_plan_subagent(ev)
            etype=event.get('type')
            if etype == 'content_block_delta':
                delta=event.get('delta') or {}
                if delta.get('type') == 'input_json_delta':
                    index=event.get('index')
                    partial=delta.get('partial_json', '')
                    if index is not None and partial:
                        subagent_input_parts[index]=subagent_input_parts.get(index, '') + partial
                        try:
                            input_data=json.loads(subagent_input_parts[index])
                            if capture_plan_subagent(input_data):
                                tool_id=tool_ids_by_index.get(index)
                                if tool_id:
                                    plan_tool_ids.add(tool_id)
                        except json.JSONDecodeError:
                            pass
            plan_stream=is_plan_stream(ev, event, plan_tool_ids)
            for action in self._renderer.feed(ev, plan_stream): apply(action)
        r=None
        for attempt in range(2):
            self.session_id=self.session_id or str(uuid.uuid4())
            args=[resolve_executable([self.config.claude_exec]),'-p','', '--output-format','stream-json','--include-partial-messages','--verbose','--permission-mode','bypassPermissions','--session-id',self.session_id]
            subagent_input_parts.clear(); tool_ids_by_index.clear(); plan_tool_ids.clear(); plan_subagent_logged=False
            r=run_process(args,cwd=work_dir,input_text=planner_prompt(goal,round_no,prior,work_dir,self.config.max_workers),timeout_s=self.config.claude_timeout_s,cancel_event=self.cancel_event,on_stdout_line=on_line)
            if not r.exit_code:
                break
            cause=(f"claude 规划超时（>{self.config.claude_timeout_s}s），已强制结束进程" if r.timed_out else r.stderr) or f'claude failed (exit={r.exit_code})'
            if attempt==0 and resuming and not r.timed_out:
                # 续接既有会话的 claude 子进程启动即退（Windows 上表现为向 stdin 写入 Broken pipe），
                # 此前曾导致第 2 轮起整次 run 崩溃 FAILED。放弃该会话、换全新会话重试一次；
                # prior 结果已随提示词传入，规划上下文不丢。
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
        plan=Plan.from_dict(json.loads(raw)); self.logger("CLAUDE", f"第 {round_no} 轮规划完成：拆分 {len(plan.tasks)} 个任务"); return plan
