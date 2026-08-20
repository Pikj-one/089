import sys, threading, time, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from vulnhunt.cli.base import run_process


class RunProcessLifecycleTests(unittest.TestCase):
    def test_timeout_kills_child_on_posix(self):
        start = time.monotonic()
        r = run_process([sys.executable, "-c", "import time; time.sleep(60)"], timeout_s=1)
        elapsed = time.monotonic() - start
        self.assertTrue(r.timed_out)
        self.assertLess(elapsed, 10)
        self.assertNotEqual(r.exit_code, 0)

    def test_cancel_kills_child_on_posix(self):
        cancel = threading.Event()
        holder = {}

        def run():
            holder["r"] = run_process(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                timeout_s=60,
                cancel_event=cancel,
            )

        thread = threading.Thread(target=run)
        thread.start()
        time.sleep(0.5)
        cancel.set()
        thread.join(timeout=10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(holder["r"].exit_code, -2)


if __name__ == "__main__":
    unittest.main()
