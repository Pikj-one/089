import threading
import time

class TUI:
    """Small stdlib console facade; orchestration remains usable without a TTY."""
    def __init__(self):
        self._lock = threading.Lock()
        self._aborted = threading.Event()

    def log(self, component, message):
        with self._lock:
            print(f"[{time.strftime('%H:%M:%S')}][{component}] {message}", flush=True)

    def abort(self):
        self._aborted.set()

    @property
    def aborted(self):
        return self._aborted.is_set()
