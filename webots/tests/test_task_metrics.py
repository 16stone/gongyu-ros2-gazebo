import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "webots/common"))
from task_metrics import summarize_tasks


class TaskMetricsTest(unittest.TestCase):
    def test_full_rounds_count_uncompleted_tasks(self):
        card = json.loads((ROOT / "webots/config/scenario_medium.json").read_bytes())
        tasks = [task["id"] for task in card["tasks"]]
        for run, expected in [
            ("f-webots-full-01", (14, 14, [], [])),
            ("p-motor-full-01", (11, 11, ["blue2", "red1", "red2"], [])),
            ("p-motor-full-02", (12, 13, ["red1"], ["red2"])),
        ]:
            with self.subTest(run=run):
                raw = json.loads((ROOT / "evidence/webots" / run / "metrics.json").read_bytes())
                values = summarize_tasks(tasks, raw["task_completed"])
                self.assertEqual(values["total"], 14)
                self.assertEqual(tuple(values[key] for key in
                                 ("on_time", "completed", "missing_task_ids", "late_task_ids")),
                                 expected)

    def test_probes_can_have_no_tasks(self):
        self.assertEqual(summarize_tasks([], {})["total"], 0)
        self.assertEqual(summarize_tasks(["blue1"], {})["missing_task_ids"], ["blue1"])
