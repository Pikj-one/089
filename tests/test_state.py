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
