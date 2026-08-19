import json, uuid
from .base import run_process, resolve_executable
from ..models import Plan, TaskSpec
from ..prompts import planner_prompt
class ClaudeWrapper:
    def __init__(self,config,logger=None,store=None,streamer=None,stream_end=None):
        self.config=config; self.session_id=None; self.logger=logger or (lambda component,message: None); self.cancel_event=None; self.store=store; self.streamer=streamer; self.stream_end=stream_end or (lambda: None)
    def health_check(self): return self.config.dry_run or run_process([resolve_executable([self.config.claude_exec]),'--version'],timeout_s=20).exit_code==0
    def plan(self,goal,round_no,prior,work_dir):
        if self.config.dry_run:
            plan=Plan(round_no,goal,['代码入口','输入验证','数据流'],[TaskSpec('task_1','静态审计','审计目标代码中的高风险漏洞并给出证据',0),TaskSpec('task_2','边界分析','检查输入边界、路径和权限相关问题',1)])
            self.logger("CLAUDE", f"第 {round_no} 轮规划完成：拆分 {len(plan.tasks)} 个任务，攻击面包括 {', '.join(plan.attack_surface)}")
            return plan
        self.session_id=self.session_id or str(uuid.uuid4()); args=[resolve_executable([self.config.claude_exec]),'-p','', '--output-format','stream-json','--include-partial-messages','--verbose','--permission-mode','plan','--add-dir',self.config.target_dir,'--session-id',self.session_id]
        def on_line(line):
            if self.store: self.store.append_log(f'claude_round_{round_no:03d}.jsonl', line)
            try: ev=json.loads(line)
            except json.JSONDecodeError: return
            event=ev.get('event') if isinstance(ev.get('event'), dict) else ev
            etype=event.get('type')
            if etype=='content_block_delta':
                delta=event.get('delta') or {}
                dtype=delta.get('type')
                if dtype=='thinking_delta' and delta.get('thinking'):
                    self.streamer("THINK", delta['thinking']) if self.streamer else self.logger("THINK", delta['thinking'])
                elif dtype=='text_delta' and delta.get('text'):
                    self.streamer("CLAUDE", delta['text']) if self.streamer else self.logger("CLAUDE", delta['text'])
            elif etype=='content_block_stop': self.stream_end()
        r=run_process(args,cwd=work_dir,input_text=planner_prompt(goal,round_no,prior),timeout_s=self.config.claude_timeout_s,cancel_event=self.cancel_event,on_stdout_line=on_line)
        if r.exit_code: raise RuntimeError(r.stderr or 'claude failed')
        envelopes=[]
        for line in r.stdout.splitlines():
            try: envelopes.append(json.loads(line))
            except json.JSONDecodeError: pass
        envelope=next((item for item in reversed(envelopes) if item.get('type') == 'result'), envelopes[-1] if envelopes else {})
        result=envelope.get('result', r.stdout)
        raw=result.get('text', '') if isinstance(result, dict) else result
        raw=(raw or r.stdout).strip().removeprefix('```json').removesuffix('```').strip()
        if raw.startswith('{') and '\n{' in raw: raw=raw.splitlines()[-1]
        plan=Plan.from_dict(json.loads(raw)); self.logger("CLAUDE", f"第 {round_no} 轮规划完成：拆分 {len(plan.tasks)} 个任务，攻击面包括 {', '.join(plan.attack_surface)}"); return plan
