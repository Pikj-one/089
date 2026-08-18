from dataclasses import dataclass, asdict, fields
from pathlib import Path
import os, tomllib

@dataclass
class Config:
    claude_exec: str="claude"; codex_exec: str="codex"; runs_root: str="runs"; target_dir: str="."; target_extra_dirs: list[str]=None
    max_rounds:int=5; max_workers:int=3; claude_timeout_s:int=300; codex_timeout_s:int=600; plan_retry_max:int=2; claude_model:str=""; claude_permission_mode:str="plan"; codex_sandbox:str="workspace-write"; codex_model:str=""; codex_approve_for_me:bool=True; coverage_threshold:float=.8; max_rounds_no_progress:int=2; dry_run:bool=False; verbose:bool=False
    def __post_init__(self): self.target_extra_dirs=self.target_extra_dirs or []

def load_config(path="config.toml", overrides=None):
    data={}
    p=Path(path)
    if p.exists():
        with p.open("rb") as f: data.update(tomllib.load(f))
    for f in fields(Config):
        key="VULNHUNT_"+f.name.upper()
        if key in os.environ: data[f.name]=os.environ[key]
    for k,v in (overrides or {}).items():
        if v is not None: data[k]=v
    for f in fields(Config):
        if f.name not in data: continue
        try:
            if f.type is bool and isinstance(data[f.name], str):
                value=data[f.name].strip().lower()
                if value not in ("true", "false", "1", "0", "yes", "no", "on", "off"): raise ValueError(value)
                data[f.name]=value in ("true", "1", "yes", "on")
            elif f.type in (int,float,bool):
                data[f.name]=f.type(data[f.name])
        except (ValueError,TypeError):
            pass
    return Config(**{f.name:data[f.name] for f in fields(Config) if f.name in data})
