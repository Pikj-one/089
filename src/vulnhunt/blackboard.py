"""黑板目录的噪音过滤与 JS 格式化。

黑板是所有 codex 共享、跨轮保留的目录。codex 按契约写入共享资源，
但可能顺手把 CSS、图片、字体、无用的 HTTP 响应头 dump 也写进来。
本模块提供两道防线：
- `sanitize_blackboard`：按后缀 + 内容启发式删除噪音文件（强制过滤）。
- `format_blackboard_js`：对黑板上未压缩的小型 .js 文件用 Prettier 静默格式化
  （跳过超大/压缩产物，失败静默忽略，不打断主流程）。
"""
import re
import shutil
from pathlib import Path

from .cli.base import run_process

# CSS / 图片 / 字体 等不可复用资产的后缀
_BANNED_SUFFIXES = {
    ".css",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".bmp",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
}
# 文件名形如 ..._headers.txt / .headers / headers.txt 的响应头 dump
_HEADER_DUMP_NAME_HINTS = ("headers.txt", "_headers.txt", "-headers.txt", ".headers")
# 响应头 dump 内容启发式：绝大多数非空行形如 "Key: value"
_HEADER_LINE = re.compile(r"^[A-Za-z0-9_-]+\s*:")
def _is_header_dump(path: Path) -> bool:
    name = path.name.lower()
    if name == "robots.txt":
        return False  # robots.txt 也是 "Key: value" 形态，但属合法共享资源
    if path.suffix.lower() != ".txt" and not name.endswith(_HEADER_DUMP_NAME_HINTS):
        return False
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return False
    nonempty = [ln.strip() for ln in lines if ln.strip()]
    if not nonempty:
        return False
    # 大多形如 "Key: value"，且正文不含 HTML/JSON/脚本骨架，判定为响应头 dump
    headerish = sum(1 for ln in nonempty if _HEADER_LINE.match(ln))
    if headerish < max(3, len(nonempty) * 0.6):
        return False
    body = "".join(nonempty)
    return not any(ch in body for ch in ("{", "<", "["))


def _is_banned(path: Path) -> bool:
    if path.suffix.lower() in _BANNED_SUFFIXES:
        return True
    return _is_header_dump(path)


def sanitize_blackboard(blackboard, logger=None):
    """删除黑板上 CSS/图片/字体/无用的 HTTP 响应头等噪音文件。

    返回被删除的文件路径列表。任何失败都静默跳过，不抛出。
    """
    root = Path(blackboard)
    if not root.is_dir():
        return []
    removed = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and _is_banned(path):
            try:
                path.unlink()
                removed.append(path)
            except OSError as e:
                if logger:
                    logger("BLACKBOARD", f"清理失败 {path.name}: {e}")
    if logger and removed:
        logger("BLACKBOARD", f"黑板清理：删除 {len(removed)} 个噪音文件（css/图片/字体/响应头 dump）")
    return removed


def format_blackboard_js(blackboard, max_bytes, logger=None):
    """对黑板上未压缩的小型 .js 文件用 Prettier 静默格式化。

    - 跳过超过 max_bytes 的文件（压缩整包）与换行极少的压缩产物；阈值由 Config.prettier_max_bytes（config.toml）提供，代码不兜底。
    - 用 `prettier --write` 就地格式化；prettier 不存在或失败时静默忽略。
    - 返回成功格式化的文件数。
    """
    root = Path(blackboard)
    if not root.is_dir():
        return 0
    targets = []
    for path in sorted(root.rglob("*.js")):
        try:
            size = path.stat().st_size
            newlines = path.read_text(encoding="utf-8", errors="ignore").count("\n")
            if size > max_bytes:
                continue  # 压缩整包，格式化耗时且膨胀
            # 小文件格式化成本可忽略，一律格式化；大文件用平均行长判断是否压缩产物
            if size > 32 * 1024 and newlines * 2000 < size:
                continue  # 平均行长 >2000 字符，视为压缩产物（单行/近单行）
        except OSError:
            continue
        targets.append(str(path))
    if not targets:
        return 0
    prettier = shutil.which("prettier") or "prettier"
    r = run_process(
        [prettier, "--write", "--no-error-on-unparsable-text", *targets],
        timeout_s=60,
    )
    if logger and r.timed_out:
        logger("BLACKBOARD", f"Prettier 格式化超时，跳过 {len(targets)} 个 JS 文件")
    return 0 if r.timed_out else len(targets)
