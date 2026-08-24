import sys, threading, time, unittest
from pathlib import Path
from unittest.mock import patch
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

    def test_broken_pipe_preserves_child_stderr(self):
        # 子进程启动即退/关闭 stdin 时，父进程向 stdin 写提示词会抛 BrokenPipeError。
        # run_process 必须返回非零退出码，并保留子进程已打印的 stderr——
        # 之前 stderr 被整个丢弃，真实错误被吞成 "[Errno 32] Broken pipe"，导致 run 莫名 FAILED。
        class BrokenStdin:
            def write(self, data):
                raise BrokenPipeError(32, "Broken pipe")

            def close(self):
                pass

        class FakeProc:
            stdin = BrokenStdin()
            stdout = iter([])
            stderr = iter(["claude: resume session crashed\n"])
            returncode = 0

            def poll(self):
                return 0

        with patch("vulnhunt.cli.base.subprocess.Popen", return_value=FakeProc()):
            r = run_process(["claude", "-p"], input_text="x")

        self.assertEqual(r.exit_code, -1)
        self.assertIn("resume session crashed", r.stderr)
        self.assertNotIn("Broken pipe", r.stderr)


if __name__ == "__main__":
    unittest.main()
