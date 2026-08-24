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
    id: str; title: str; description: str; required_output: str = "结构化发现与证据"; relevant_context: str = ""; order: int = 0; depends_on: list[str] = field(default_factory=list)
    def to_dict(self): return _plain(self)
    @classmethod
    def from_dict(cls, d): return cls(**{k:d[k] for k in ("id","title","description")}, required_output=d.get("required_output","结构化发现与证据"), relevant_context=d.get("relevant_context",""), order=d.get("order",0), depends_on=list(d.get("depends_on") or []))

def compute_orders(tasks):
    """order 计算规则（原为顶层 LLM 提示词里的指令，现为确定性代码）：
    无 depends_on 或引用非本轮任务 → 0；否则 1 + max(依赖任务的 order)；参与循环/自依赖的任务按 0 处理。"""
    by_id={t.id:t for t in tasks}
    deps_of=lambda tid:[d for d in ((by_id[tid].depends_on if tid in by_id else []) or []) if d!=tid]
    cyclic=set()
    for start in by_id:
        seen=set(); stack=list(deps_of(start))
        while stack:
            cur=stack.pop()
            if cur==start: cyclic.add(start); break
            if cur in seen or cur not in by_id: continue
            seen.add(cur); stack.extend(deps_of(cur))
    memo={}
    def order_of(tid):
        if tid not in by_id or tid in cyclic: return 0
        if tid in memo: return memo[tid]
        deps=[d for d in deps_of(tid) if d in by_id]
        memo[tid]=(1+max(order_of(d) for d in deps)) if deps else 0
        return memo[tid]
    return {t.id:order_of(t.id) for t in tasks}

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
    run_id: str; goal: str; created_at: str; status: RunStatus=RunStatus.INIT; current_round: int=0; max_rounds: int=5; config_snapshot: dict=field(default_factory=dict); updated_at: str=""
    def to_dict(self): return _plain(self)
    @classmethod
    def from_dict(cls,d): d=dict(d); d["status"]=RunStatus(d.get("status","INIT")); d.pop("target_dir", None); return cls(**d)  # 兼容旧 run.json 的已删除字段
