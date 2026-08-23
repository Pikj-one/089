import json, time
from pathlib import Path
from .base import run_process, resolve_executable
from ..models import WorkerResult, TaskResultStatus
class CodexWrapper:
    def __init__(self,config,logger=None,store=None): self.config=config; self.logger=logger or (lambda component,message: None); self.cancel_event=None; self.store=store
    def health_check(self): return run_process([resolve_executable([self.config.codex_exec]),'--version'],timeout_s=20).exit_code==0
    def exec_task(self,task,workspace):
        # workspace 可能来自 runs_root 的相对路径，而子进程同时使用它作为 cwd。
        # Codex 会相对于 cwd 再解析 -C/-o；因此这里必须先固定为绝对路径，
        # 避免出现 workspace\runs\... 这样的错误嵌套路径（Windows 下报 os error 3）。
        workspace=Path(workspace).resolve()
        # 黑板目录：所有 codex 共享、跨轮保留；仅 store 存在时才启用。
        blackboard=(self.store.root/'blackboard').resolve() if self.store else None
        if blackboard: blackboard.mkdir(parents=True,exist_ok=True)
        blackboard_line=f"共享黑板目录（所有 codex 共享、跨轮保留）：{blackboard}\n\n" if blackboard else ""
        bb_scope="与共享黑板目录" if blackboard else ""
        prompt = rf"""任务：{task.description}
要求输出：{task.required_output}
相关上下文：{task.relevant_context or '无'}
本任务工作目录：{workspace}
{blackboard_line}任务完成时结束所有产生的子进程

严格限制：需要供其他 codex 复用的公共资源/中间结果可以写入共享黑板目录及其子目录；本任务的临时目录、脚本、报告、截图、响应等私有产物只能写入本任务工作目录。禁止访问或写入本任务工作目录{bb_scope}之外的任何路径，包括运行目录、tasks、logs、findings、report、其他任务目录、项目目录和用户目录。禁止使用 ..、切换到其他目录或通过绝对路径绕过限制。

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
        if session_id: args=[exe,'exec','resume',session_id,'-','--json','-o',str(output_file),'--skip-git-repo-check']
        elif blackboard: args=[exe,'exec','', '-C',str(workspace),'--add-dir',str(blackboard),'--json','-o',str(output_file),'-s',self.config.codex_sandbox,'--skip-git-repo-check','--color','never']
        else: args=[exe,'exec','', '-C',str(workspace),'--json','-o',str(output_file),'-s',self.config.codex_sandbox,'--skip-git-repo-check','--color','never']
        r=run_process(args,cwd=workspace,input_text=prompt,timeout_s=self.config.codex_timeout_s,cancel_event=self.cancel_event,on_stdout_line=on_line); p=output_file
        for line in r.stdout.splitlines():
            try:
                event=json.loads(line)
                if event.get('type')=='thread.started' and event.get('thread_id'): session_file.write_text(event['thread_id'],encoding='utf-8'); break
            except json.JSONDecodeError: pass
        if p.exists():
            for _ in range(20):
                try:
                    raw=p.read_text(encoding='utf-8').strip()
                    if raw:
                        d=json.loads(raw); d['task_id']=task.id; result=WorkerResult.from_dict(d); self.logger(f"CODEX-{task.id}", f"任务 {task.id} 完成：{result.status.value}，发现 {len(result.findings)} 个问题"); return result
                except (OSError, json.JSONDecodeError):
                    time.sleep(0.05)
        result=WorkerResult(task.id,r.exit_code,TaskResultStatus.FAILURE,error=r.stderr,stdout_tail=r.stdout[-4000:],stderr_tail=r.stderr[-4000:],duration_s=r.duration_s); self.logger("ERROR", f"任务 {task.id} 失败：{result.error or '无结果文件'}"); return result
