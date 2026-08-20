import io, sys, threading, time, unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from vulnhunt.tui import TUI


class _AliveThread:
    alive = True

    def is_alive(self):
        return self.alive


class TUIHeartbeatTests(unittest.TestCase):
    def test_heartbeat_reports_long_silence(self):
        tui = TUI()
        tui.thread = _AliveThread()
        tui._last_activity = time.monotonic() - 30
        buf = io.StringIO()
        with TemporaryDirectory() as d:
            tui._transcript = Path(d) / "tui.log.txt"
            with redirect_stdout(buf):
                tui._last_activity = time.monotonic() - 30
                heartbeat = threading.Thread(target=tui._heartbeat, daemon=True)
                heartbeat.start()
                deadline = time.monotonic() + 8
                while "仍在运行" not in buf.getvalue() and time.monotonic() < deadline:
                    time.sleep(0.2)
            tui.thread.alive = False
            heartbeat.join(timeout=5)
        self.assertIn("仍在运行", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
