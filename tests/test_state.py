import sys, tempfile, unittest
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from vulnhunt.models import Run
from vulnhunt.state import RunStore

class StateTests(unittest.TestCase):
    def test_atomic_run_and_state(self):
        with tempfile.TemporaryDirectory() as d:
            run = Run("r1", "goal", "now")
            store = RunStore.create(d, run)
            store.save_state({"status": "INIT"})
            self.assertEqual(store.read_run().run_id, "r1")
            self.assertEqual(store.read_state()["status"], "INIT")
            expected_prefix = Path(d) / datetime.now().strftime("%Y/%m/%d/%H-%M")
            self.assertEqual(store.root.parent, expected_prefix)
            self.assertFalse(list(Path(d).rglob("*.tmp")))

    def test_new_run_copies_claude_instructions(self):
        with tempfile.TemporaryDirectory() as d:
            store = RunStore.create(d, Run("r2", "goal", "now"))
            claude_md = Path(__file__).parents[1] / "CLAUDE.md"
            if claude_md.exists():
                self.assertEqual((store.root / "CLAUDE.md").read_text(encoding="utf-8"), claude_md.read_text(encoding="utf-8"))
