import threading
import time
from pathlib import Path
import json

class TUI:
    """Small stdlib console facade; orchestration remains usable without a TTY."""
    def __init__(self):
        self._lock = threading.Lock()
        self._aborted = threading.Event()
        self.store = None
        self.thread = None

    def log(self, component, message):
        with self._lock:
            print(f"[{time.strftime('%H:%M:%S')}][{component}] {message}", flush=True)

    def abort(self):
        self._aborted.set()

    @property
    def aborted(self):
        return self._aborted.is_set()

    def attach(self, store, thread):
        self.store, self.thread = store, thread

    def command_loop(self):
        """Run the MVP command loop. Commands are intentionally line-oriented."""
        while True:
            try:
                command = input("> ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                self.abort()
                return
            if command in ("quit", "exit"):
                self.abort()
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
