import argparse, sys, uuid
from datetime import datetime, timezone
from .config import load_config
from .models import Run
from .state import RunStore
from .cli.claude_code import ClaudeWrapper
from .cli.codex import CodexWrapper
from .orchestrator import Orchestrator
from .report import build_report
from .tui import TUI
from .logview import AggregateSink, format_line, replay_file
def main(argv=None):
    p=argparse.ArgumentParser(prog='vulnhunt'); sub=p.add_subparsers(dest='cmd',required=True); s=sub.add_parser('start'); s.add_argument('goal'); s.add_argument('--config',default='config.toml'); t=sub.add_parser('tui'); t.add_argument('--config',default='config.toml'); sub.add_parser('doctor'); r=sub.add_parser('resume'); r.add_argument('run_dir'); log=sub.add_parser('log'); log.add_argument('run_dir'); log.add_argument('--round',type=int)
    a=p.parse_args(argv)
    if a.cmd == 'log':
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        store=RunStore(a.run_dir)
        paths=sorted(store.logs.glob('claude_round_*.jsonl'))
        path=next((x for x in paths if x.name == f'claude_round_{a.round:03d}.jsonl'), paths[-1] if paths and a.round is None else None)
        if path is None: raise SystemExit('Claude log not found')
        replay_file(path, AggregateSink(lambda component, message: print(format_line(component, message))))
        return
    if a.cmd == 'tui':
        tui=TUI(); tui.log('UI', 'enter a goal to start, or type quit')
        try: goal=input('goal> ').strip()
        except (EOFError, KeyboardInterrupt): return
        if not goal: return
        c=load_config(a.config); tui=TUI(); run=Run(uuid.uuid4().hex[:12],goal,datetime.now(timezone.utc).isoformat(),max_rounds=c.max_rounds,config_snapshot=c.__dict__,target_dir=c.target_dir); store=RunStore.create(c.runs_root,run); claude=ClaudeWrapper(c,tui.log,store=store,streamer=tui.stream,stream_end=tui.stream_end); codex=CodexWrapper(c,tui.log,store=store); orchestrator=Orchestrator(c,store,claude,codex)
        def execute():
            result=orchestrator.run_loop(); tui.log('ORCH', f"运行结束：{result.status.value}"); tui.log('ORCH', f"报告已生成：{build_report(store.root)}")
        worker=__import__('threading').Thread(target=execute,daemon=True); worker.start(); tui.attach(store,worker,orchestrator); tui.command_loop(); return
    c=load_config(getattr(a,'config','config.toml'))
    if a.cmd=='doctor':
        claude=ClaudeWrapper(c); codex=CodexWrapper(c); print('claude:',claude.health_check()); print('codex:',codex.health_check()); return
    if a.cmd=='resume': store=RunStore(a.run_dir)
    else:
        run=Run(uuid.uuid4().hex[:12],a.goal,datetime.now(timezone.utc).isoformat(),max_rounds=c.max_rounds,config_snapshot=c.__dict__,target_dir=c.target_dir); store=RunStore.create(c.runs_root,run)
    claude=ClaudeWrapper(c,store=store); codex=CodexWrapper(c,store=store)
    result=Orchestrator(c,store,claude,codex).run_loop(); print(result.status.value); print(build_report(store.root))
