from dataclasses import dataclass, asdict, fields
from pathlib import Path
import os, tomllib

@dataclass
class Config:
    """统一配置管理器：所有运行参数经此单点读取，实际值由 config.toml 提供（代码不兜底，字段无默认值）。

    加载优先级：config.toml → VULNHUNT_<字段大写> 环境变量 → 调用方 overrides（见 load_config）。
    config.toml 必须完整提供全部字段，缺失即报错；各字段含义见 config.toml 内注释与 docs/configuration.md。
    新增配置字段必须同时：在此登记、写进 config.toml、接线到对应调用点，避免「声明但未使用」的僵尸字段。
    """
    claude_exec: str            # claude CLI 可执行文件名或绝对路径（cli/claude_code.py 用它启规划子进程）
    codex_exec: str             # codex CLI 可执行文件名或绝对路径（cli/codex.py 用它启执行子进程）
    runs_root: str              # 运行记录根目录（state.py RunStore.create 在其下按 年/月/日/时-分/run_id 建目录）
    max_rounds: int             # 最大轮次上限（orchestrator.py DECISION 判定：轮次达上限则 COMPLETE）
    max_workers: int            # 并行 codex 数（workers.py ThreadPoolExecutor 并发上限；超出部分任务被丢弃不排队）
    claude_timeout_s: int       # 单轮 claude 规划超时（秒），超时强杀（cli/claude_code.py run_process）
    codex_timeout_s: int        # 单个 codex 任务超时（秒）；一亿≈暂不禁用（cli/codex.py run_process 超时强杀）
    codex_sandbox: str          # codex 沙箱权限声明（cli/codex.py 的 -s 参数）；仅对授权目标使用
    prettier_max_bytes: int     # 黑板 JS 静默格式化大小阈值（字节），超限视为压缩产物跳过（blackboard.py format_blackboard_js）

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
    missing=[f.name for f in fields(Config) if f.name not in data]
    if missing:
        raise ValueError(f"配置缺失：请在 config.toml / VULNHUNT_* 环境变量 / overrides 中提供全部字段，缺少：{', '.join(missing)}")
    return Config(**{f.name:data[f.name] for f in fields(Config)})
