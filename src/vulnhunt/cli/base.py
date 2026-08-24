from dataclasses import dataclass
from pathlib import Path
import subprocess, threading, time, os
@dataclass
class ProcResult: exit_code:int; stdout:str; stderr:str; timed_out:bool=False; duration_s:float=0
def resolve_executable(candidates):
    for c in candidates:
        if Path(c).exists(): return str(c)
    return candidates[0] if candidates else ""
def _kill_process(p):
    """强制结束子进程，兼容 Windows(taskkill) 与 POSIX(terminate/kill)。"""
    if os.name == 'nt':
        subprocess.run(['taskkill','/pid',str(p.pid),'/T','/F'],capture_output=True)
    else:
        try:
            p.terminate()
        except OSError:
            pass
    try:
        p.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            p.kill()
        except OSError:
            pass
        p.wait(timeout=5)
def run_process(args,cwd=None,env=None,timeout_s=60,input_text="",on_stdout_line=None,cancel_event=None):
    start=time.monotonic(); out=[]; err=[]; ts=[]
    try:
        p=subprocess.Popen(args,cwd=cwd,env=env or os.environ.copy(),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',errors='replace',shell=False)
        def read(stream,bucket,callback=None):
            for line in stream:
                bucket.append(line)
                if callback: callback(line.rstrip('\n'))
        ts=[threading.Thread(target=read,args=(p.stdout,out,on_stdout_line)),threading.Thread(target=read,args=(p.stderr,err))]
        [t.start() for t in ts]
        if input_text:
            p.stdin.write(input_text)
        p.stdin.close()
        deadline=time.monotonic()+timeout_s
        while p.poll() is None and time.monotonic() < deadline:
            if cancel_event is not None and cancel_event.is_set():
                _kill_process(p); return ProcResult(-2,''.join(out),''.join(err),False,time.monotonic()-start)
            time.sleep(0.05)
        if p.poll() is None:
            _kill_process(p); timed_out=True
        else:
            timed_out=False
        [t.join(timeout=2) for t in ts]
        for stream in (p.stdout, p.stderr):
            try: stream.close()
            except (OSError, ValueError): pass
        return ProcResult(p.returncode,''.join(out),''.join(err),timed_out,time.monotonic()-start)
    except OSError as e:
        # 子进程启动失败或 stdin 管道破裂（如 claude/codex 启动即退、关闭 stdin 导致 BrokenPipeError）：
        # 不要丢弃子进程已打印的 stderr，否则真实错误被吞成干巴巴的 "[Errno 32] Broken pipe"，
        # 会让整次 run 莫名 FAILED 且无从排查。子进程没输出时退回异常本身。
        [t.join(timeout=2) for t in ts]
        return ProcResult(-1,'',''.join(err) or str(e),False,time.monotonic()-start)
