import json
from pathlib import Path
from .base import run_process, resolve_executable
from ..models import WorkerResult, TaskResultStatus
class CodexWrapper:
    def __init__(self,config,logger=None): self.config=config; self.logger=logger or (lambda component,message: None)
    def health_check(self): return self.config.dry_run or run_process([resolve_executable([self.config.codex_exec]),'--version'],timeout_s=20).exit_code==0
    def exec_task(self,task,workspace):
        if self.config.dry_run:
            result=WorkerResult(task.id,summary=f'dry-run completed: {task.title}'); self.logger("CODEX", f"任务 {task.id} 完成：{result.summary}，发现 {len(result.findings)} 个问题"); return result
        args=[resolve_executable([self.config.codex_exec]),'exec','', '-C',str(workspace),'--json','-o',str(Path(workspace)/'_last_message.json'),'-s',self.config.codex_sandbox,'--skip-git-repo-check','--ephemeral','--color','never']; r=run_process(args,cwd=workspace,input_text=task.description,timeout_s=self.config.codex_timeout_s); p=Path(workspace)/'_last_message.json'
        if p.exists():
            d=json.loads(p.read_text(encoding='utf-8')); d['task_id']=task.id; result=WorkerResult.from_dict(d); self.logger("CODEX", f"任务 {task.id} 完成：{result.summary or '无摘要'}，发现 {len(result.findings)} 个问题"); return result
        result=WorkerResult(task.id,r.exit_code,TaskResultStatus.FAILURE,error=r.stderr,stdout_tail=r.stdout[-4000:],stderr_tail=r.stderr[-4000:],duration_s=r.duration_s); self.logger("ERROR", f"任务 {task.id} 失败：{result.error or '无结果文件'}"); return result
