import json, time
from pathlib import Path
from .base import run_process, resolve_executable
from ..models import WorkerResult, TaskResultStatus
class CodexWrapper:
    def __init__(self,config,logger=None): self.config=config; self.logger=logger or (lambda component,message: None); self.cancel_event=None
    def health_check(self): return self.config.dry_run or run_process([resolve_executable([self.config.codex_exec]),'--version'],timeout_s=20).exit_code==0
    def exec_task(self,task,workspace):
        if self.config.dry_run:
            result=WorkerResult(task.id,summary=f'dry-run completed: {task.title}'); self.logger("CODEX", f"任务 {task.id} 完成：{result.summary}，发现 {len(result.findings)} 个问题"); return result
        prompt=(f"任务：{task.description}\n"
                f"要求输出：{task.required_output}\n"
                f"相关上下文：{task.relevant_context or '无'}\n"
                "请严格只输出一个 JSON 对象，不要输出 Markdown、解释文字或额外内容。"
                "字段必须包含 status、summary、findings；status 使用 SUCCESS、FAILURE 或 PARTIAL。")
        args=[resolve_executable([self.config.codex_exec]),'exec','', '-C',str(workspace),'--json','-o',str(Path(workspace)/'_last_message.json'),'-s',self.config.codex_sandbox,'--skip-git-repo-check','--ephemeral','--color','never']; r=run_process(args,cwd=workspace,input_text=prompt,timeout_s=self.config.codex_timeout_s,cancel_event=self.cancel_event); p=Path(workspace)/'_last_message.json'
        if p.exists():
            for _ in range(20):
                try:
                    raw=p.read_text(encoding='utf-8').strip()
                    if raw:
                        d=json.loads(raw); d['task_id']=task.id; result=WorkerResult.from_dict(d); self.logger("CODEX", f"任务 {task.id} 完成：{result.summary or '无摘要'}，发现 {len(result.findings)} 个问题"); return result
                except (OSError, json.JSONDecodeError):
                    time.sleep(0.05)
        result=WorkerResult(task.id,r.exit_code,TaskResultStatus.FAILURE,error=r.stderr,stdout_tail=r.stdout[-4000:],stderr_tail=r.stderr[-4000:],duration_s=r.duration_s); self.logger("ERROR", f"任务 {task.id} 失败：{result.error or '无结果文件'}"); return result
