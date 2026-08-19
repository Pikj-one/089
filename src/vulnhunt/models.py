from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any

class StrEnum(str, Enum): pass
class RunStatus(StrEnum): INIT="INIT"; PLANNING="PLANNING"; DISPATCHING="DISPATCHING"; RUNNING="RUNNING"; COLLECTING="COLLECTING"; DECISION="DECISION"; COMPLETE="COMPLETE"; FAILED="FAILED"; ABORTED="ABORTED"
class TaskStatus(StrEnum): PENDING="PENDING"; DISPATCHED="DISPATCHED"; RUNNING="RUNNING"; SUCCEEDED="SUCCEEDED"; FAILED="FAILED"; TIMED_OUT="TIMED_OUT"; SKIPPED="SKIPPED"; CANCELLED="CANCELLED"; RECOVERED="RECOVERED"
class TaskResultStatus(StrEnum): SUCCESS="SUCCESS"; FAILURE="FAILURE"; PARTIAL="PARTIAL"
class Severity(StrEnum): CRITICAL="CRITICAL"; HIGH="HIGH"; MEDIUM="MEDIUM"; LOW="LOW"; INFO="INFO"
class CompletionDecision(StrEnum): COMPLETE="COMPLETE"; CONTINUE="CONTINUE"; ABORT="ABORT"; MAX_ROUNDS="MAX_ROUNDS"; STALLED="STALLED"

def _plain(v):
    if isinstance(v, Enum): return v.value
    if isinstance(v, list): return [_plain(x) for x in v]
    if isinstance(v, dict): return {k:_plain(x) for k,x in v.items()}
    if hasattr(v, "__dataclass_fields__"): return {k:_plain(getattr(v,k)) for k in v.__dataclass_fields__}
    return v

@dataclass
class TaskSpec:
    id: str; title: str; description: str; priority: int = 1; required_output: str = "结构化发现与证据"; relevant_context: str = ""
    def to_dict(self): return _plain(self)
    @classmethod
    def from_dict(cls, d): return cls(**{k:d[k] for k in ("id","title","description")}, priority=d.get("priority",1), required_output=d.get("required_output","结构化发现与证据"), relevant_context=d.get("relevant_context",""))

@dataclass
class Plan:
    round: int; tasks: list[TaskSpec]
    def to_dict(self): return _plain(self)
    @classmethod
    def from_dict(cls,d): return cls(d.get("round",0),[TaskSpec.from_dict(x) for x in d.get("tasks",[])])

@dataclass
class WorkerResult:
    task_id: str; exit_code: int = 0; status: TaskResultStatus = TaskResultStatus.SUCCESS; summary: str = ""; findings: list[dict[str,Any]] = field(default_factory=list); evidence_files: list[str] = field(default_factory=list); output_files: list[str] = field(default_factory=list); stdout_tail: str = ""; stderr_tail: str = ""; error: str|None = None; duration_s: float = 0
    def to_dict(self): return _plain(self)
    @classmethod
    def from_dict(cls,d):
        d=dict(d); d["status"]=TaskResultStatus(d.get("status","FAILURE")); return cls(**{k:d.get(k) for k in cls.__dataclass_fields__})

@dataclass
class Run:
    run_id: str; goal: str; created_at: str; status: RunStatus=RunStatus.INIT; current_round: int=0; max_rounds: int=5; config_snapshot: dict=field(default_factory=dict); target_dir: str="."; updated_at: str=""
    def to_dict(self): return _plain(self)
    @classmethod
    def from_dict(cls,d): d=dict(d); d["status"]=RunStatus(d.get("status","INIT")); return cls(**d)
