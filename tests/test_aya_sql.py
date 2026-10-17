"""Integrity tests for the adapter; live claims require real RHI receipts."""

import json
from pathlib import Path
import tempfile
import unittest

from mass.aya_sql import (
    BOUNDARY,
    END,
    OPTIMIZER_BUDGET,
    START,
    freeze_json,
    prepare_task,
    snapshot_workspace,
)


class AyaSqlTests(unittest.TestCase):
    def test_frozen_manifest_rejects_changed_input(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            freeze_json(path, {"hash": "original"})
            freeze_json(path, {"hash": "original"})
            with self.assertRaisesRegex(ValueError, "Frozen input changed"):
                freeze_json(path, {"hash": "changed"})

    def test_plain_task_preserves_text_and_adds_bounded_workflow(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = (
                Path(directory) / "source.txt",
                Path(directory) / "query1001_ourTeam.txt",
            )
            source.write_text("Answer each supplied SQL question.")
            prepare_task(source, target)
            text = target.read_text()
            self.assertTrue(text.startswith(source.read_text()))
            self.assertEqual(text.count(START), 1)
            self.assertEqual(text.count(END), 1)
            self.assertTrue(text.endswith(BOUNDARY + "\n"))
            self.assertIn(OPTIMIZER_BUDGET, text.split(START)[0])
            source.write_text("Changed task")
            with self.assertRaises(ValueError):
                prepare_task(source, target)

    def test_workspace_copies_dev_evidence_only_and_detects_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / "source", Path(directory) / "target"
            source.mkdir()
            for name, value in {
                "queries.json": {"dev-a": {"sql": "SELECT 1"}},
                "results.json": {"split": "development", "passed": 1},
                "run_status.json": {"status": "completed"},
                "heldout.json": {"private": "never copy"},
                ".env": {"KEY": "never copy"},
            }.items():
                (source / name).write_text(json.dumps(value))
            hashes = snapshot_workspace(source, target)
            self.assertEqual(
                set(hashes), {"queries.json", "results.json", "run_status.json"}
            )
            self.assertFalse((target / "heldout.json").exists())
            self.assertFalse((target / ".env").exists())
            self.assertTrue((target / "results/metrics.json").exists())
            snapshot_workspace(source, target)
            (source / "queries.json").write_text("{}")
            with self.assertRaises(ValueError):
                snapshot_workspace(source, target)

    def test_holdout_metrics_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            (source / "results.json").write_text('{"split":"heldout"}')
            with self.assertRaisesRegex(ValueError, "development results"):
                snapshot_workspace(source, source / "target")

    def test_public_development_context_is_frozen_without_gold(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / "source", Path(directory) / "target"
            source.mkdir()
            for name, value in {
                "queries.json": {"q1": {"sql": "SELECT 1"}},
                "results.json": {"split": "development", "passed": 1},
                "run_status.json": {"status": "completed"},
                "public-tasks.json": {
                    "split": "development",
                    "questions": [{"id": "q1", "db_id": "a", "question": "Count rows"}],
                    "databases": {"a": {"schema": "CREATE TABLE a(x)"}},
                },
            }.items():
                (source / name).write_text(json.dumps(value))
            hashes = snapshot_workspace(source, target)
            self.assertIn("public-tasks.json", hashes)
            self.assertIn("Count rows", (target / "research_report.md").read_text())
            public = json.loads((source / "public-tasks.json").read_text())
            public["questions"][0]["expected_sql"] = "SELECT count(*) FROM a"
            (source / "public-tasks.json").write_text(json.dumps(public))
            with self.assertRaisesRegex(ValueError, "oracle fields"):
                snapshot_workspace(source, target)


if __name__ == "__main__":
    unittest.main()
