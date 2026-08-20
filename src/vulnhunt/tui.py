import threading
import time
from pathlib import Path
import json
import queue
import sys

class TUI:
    """Small stdlib console facade; orchestration remains usable without a TTY."""
    def __init__(self):
        self._lock = threading.Lock()
        self._aborted = threading.Event()
        self._stream_component = None
        self._stream_parts = []
        self._stream_start = ""
        self._transcript = Path(__file__).resolve().parents[2] / "tui.log.txt"
        self._last_activity = time.monotonic()
        self.store = None
        self.thread = None
        self.orchestrator = None
        self._colors = {"UI": "\x1b[90m", "THINK": "\x1b[90m", "CLAUDE": "\x1b[94m", "CODEX": "\x1b[93m", "ORCH": "\x1b[96m", "ERROR": "\x1b[91m"}

    def _transcribe(self, line):
        try:
            with self._transcript.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass

    def log(self, component, message):
        self._last_activity = time.monotonic()
        line = f"[{time.strftime('%H:%M:%S')}][{component}] {message}"
        with self._lock:
            color = self._color_for(component) if __import__('sys').stdout.isatty() else ""
            reset = "\x1b[0m" if color else ""
            print(f"{color}{line}{reset}", flush=True)
        self._transcribe(line)

    def stream(self, component, text):
        """Append streamed text for a component on the current line."""
        self._last_activity = time.monotonic()
        if not sys.stdout.isatty():
            self.log(component, text)
            return
        with self._lock:
            color = self._color_for(component)
            reset = "\x1b[0m" if color else ""
            if self._stream_component != component:
                if self._stream_component is not None:
                    sys.stdout.write("\n")
                    self._flush_stream_line()
                sys.stdout.write(f"{color}[{time.strftime('%H:%M:%S')}][{component}]{reset} ")
                self._stream_component = component
                self._stream_start = time.strftime('%H:%M:%S')
                self._stream_parts = []
            sys.stdout.write(text)
            self._stream_parts.append(text)
            sys.stdout.flush()

    def stream_end(self):
        """Finish the current streaming line."""
        self._last_activity = time.monotonic()
        if not sys.stdout.isatty():
            return
        with self._lock:
            if self._stream_component is not None:
                sys.stdout.write("\n")
                sys.stdout.flush()
                self._flush_stream_line()
                self._stream_component = None

    def _flush_stream_line(self):
        if self._stream_component is None:
            return
        self._transcribe(f"[{self._stream_start}][{self._stream_component}] {''.join(self._stream_parts)}")
        self._stream_parts = []

    def _color_for(self, component):
        if component.startswith("CLAUDE"):
            return self._colors["CLAUDE"]
        if component.startswith("CODEX"):
            return self._colors["CODEX"]
        return self._colors.get(component, "\x1b[37m")

    def abort(self):
        self._aborted.set()
        if self.orchestrator:
            self.orchestrator.request_abort()

    @property
    def aborted(self):
        return self._aborted.is_set()

    def attach(self, store, thread, orchestrator=None):
        self.store, self.thread, self.orchestrator = store, thread, orchestrator
        self._transcribe(f"==== TUI 运行开始 {time.strftime('%Y-%m-%d %H:%M:%S')} ====")
        try:
            goal = self.store.read_run().goal
            self._transcribe(f"[UI] 目标：{goal}")
        except Exception:
            pass

    def _heartbeat(self):
        """子代理长时间无输出时输出心跳行，避免界面看起来像卡死。"""
        while self.thread is not None and self.thread.is_alive():
            if time.monotonic() - self._last_activity >= 20:
                self.log("UI", "仍在运行，等待模型输出…")
            time.sleep(2)

    def command_loop(self):
        """Run the MVP command loop. Commands are intentionally line-oriented."""
        if self.thread is not None:
            threading.Thread(target=self._heartbeat, daemon=True).start()
        commands = queue.Queue()
        def read_commands():
            while True:
                try:
                    commands.put(input("> ").strip().lower())
                except (EOFError, KeyboardInterrupt):
                    commands.put(None)
                    return
        reader = threading.Thread(target=read_commands, daemon=True)
        reader.start()
        while True:
            if self.thread and not self.thread.is_alive() and commands.empty():
                self._clear_prompt()
                return
            try:
                command = commands.get(timeout=0.1)
            except queue.Empty:
                continue
            except KeyboardInterrupt:
                self.abort()
                self._clear_prompt()
                self.log("UI", "收到 Ctrl+C，正在优雅退出")
                return
            if command is None:
                self.abort()
                return
            if command in ("quit", "exit"):
                self.abort()
                self._clear_prompt()
                return
            if command == "abort":
                self.abort()
                self.log("UI", "abort requested")
                return
            if command == "status":
                self._show_json("run.json")
            elif command == "tasks":
                self._show_files("tasks", "_result.json")
            elif command == "findings":
                self._show_files("findings", ".json")
            elif command:
                self.log("UI", "commands: status, tasks, findings, abort, quit")

    def _clear_prompt(self):
        with self._lock:
            sys.stdout.write("\r\x1b[2K\r")
            sys.stdout.flush()

    def _show_json(self, name):
        if not self.store:
            self.log("UI", "no run started")
            return
        path = self.store.root / name
        if path.exists():
            self.log("UI", path.read_text(encoding="utf-8", errors="replace").replace("\n", " "))

    def _show_files(self, folder, suffix):
        if not self.store:
            self.log("UI", "no run started")
            return
        paths = sorted((self.store.root / folder).glob(f"*{suffix}"))
        self.log("UI", f"{folder}: {len(paths)} file(s)")
        for path in paths:
            self.log("UI", path.name)
