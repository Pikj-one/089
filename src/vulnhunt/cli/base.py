from dataclasses import dataclass
from pathlib import Path
import subprocess, threading, time, os
@dataclass
class ProcResult: exit_code:int; stdout:str; stderr:str; timed_out:bool=False; duration_s:float=0
def resolve_executable(candidates):
    for c in candidates:
        if Path(c).exists(): return str(c)
    return candidates[0] if candidates else ""
def run_process(args,cwd=None,env=None,timeout_s=60,input_text="",on_stdout_line=None):
    start=time.monotonic(); out=[]; err=[]
    try:
        p=subprocess.Popen(args,cwd=cwd,env=env or os.environ.copy(),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',errors='replace',shell=False)
        def read(stream,bucket,callback=None):
            for line in stream:
                bucket.append(line)
                if callback: callback(line.rstrip('\n'))
        ts=[threading.Thread(target=read,args=(p.stdout,out,on_stdout_line)),threading.Thread(target=read,args=(p.stderr,err))]
        [t.start() for t in ts]
        try: p.communicate(input=input_text,timeout=timeout_s)
        except subprocess.TimeoutExpired:
            subprocess.run(['taskkill','/pid',str(p.pid),'/T','/F'],capture_output=True); p.wait(); return ProcResult(-1,''.join(out),''.join(err),True,time.monotonic()-start)
        [t.join() for t in ts]; return ProcResult(p.returncode,''.join(out),''.join(err),False,time.monotonic()-start)
    except OSError as e: return ProcResult(-1,'',str(e),False,time.monotonic()-start)
