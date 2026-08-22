from concurrent.futures import ThreadPoolExecutor
class WorkerPool:
    def __init__(self,config,wrapper,store): self.config=config; self.wrapper=wrapper; self.store=store
    def run(self,tasks,round_no):
        tasks=list(tasks); dropped=tasks[self.config.max_workers:]
        if dropped:
            self.store.append_log(f'round_{round_no:03d}.log', f'dropped {len(dropped)} task(s) exceeding max_workers={self.config.max_workers}: '+', '.join(t.id for t in dropped))
        tasks=tasks[:self.config.max_workers]
        def one(t):
            tid=f'round_{round_no:03d}_{t.id}'; ws=self.store.root/'workspaces'/tid; ws.mkdir(parents=True,exist_ok=True); self.store.save_task_input(tid,t.to_dict()); result=self.wrapper.exec_task(t,ws); result.task_id=tid; self.store.save_task_result(tid,result); return result
        with ThreadPoolExecutor(max_workers=self.config.max_workers) as pool: return list(pool.map(one,tasks))
