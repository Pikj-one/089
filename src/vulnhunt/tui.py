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
        self.store = None
        self.thread = None
        self.orchestrator = None
        self._colors = {"UI": "\x1b[90m", "CLAUDE": "\x1b[94m", "CODEX": "\x1b[93m", "ORCH": "\x1b[96m", "ERROR": "\x1b[91m"}

    def log(self, component, message):
        with self._lock:
            color = self._colors.get(component, "\x1b[37m") if __import__('sys').stdout.isatty() else ""
            reset = "\x1b[0m" if color else ""
            print(f"{color}[{time.strftime('%H:%M:%S')}][{component}]{reset} {message}", flush=True)

    def abort(self):
        self._aborted.set()
        if self.orchestrator:
            self.orchestrator.request_abort()

    @property
    def aborted(self):
        return self._aborted.is_set()

    def attach(self, store, thread, orchestrator=None):
        self.store, self.thread, self.orchestrator = store, thread, orchestrator

    def command_loop(self):
        """Run the MVP command loop. Commands are intentionally line-oriented."""
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
        if sys.stdout.isatty():
            with self._lock:
                sys.stdout.write("\r\x1b[2K")
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
