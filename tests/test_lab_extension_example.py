from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from examples.lab.exact_match import ExactMatchTrial
from rag_ime.agent_lab.trial_execution import AgentLabTrialApplication
from rag_ime.agent_lab.trials import AgentLabTrialStore


class LabExtensionExampleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="paw-extension-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "answers.jsonl").write_text('\n'.join(json.dumps(row) for row in [
            {"actual": "a", "expected": "a"}, {"actual": "b", "expected": "c"},
        ])+'\n')
        self.store = AgentLabTrialStore(self.root / "trial.sqlite")
        self.app = AgentLabTrialApplication(self.store, {"local-text": ExactMatchTrial(self.root)}, start_workers=False)
        self.addCleanup(self.app.close)

    def _start(self):
        return self.app.start("local-1", "local-text", {"fixture": "answers.jsonl"})["job"]["jobId"]

    def test_registered_scene_runs_and_replays_without_scheduler_changes_or_private_input(self):
        job_id = self._start()
        result = self.app.run_job(job_id)["job"]
        self.assertEqual(result["state"], "completed")
        self.assertEqual(result["result"]["qualityVerdict"], "reject")
        self.assertEqual(result["result"]["score"], 0.5)
        self.assertEqual(self._start(), job_id)
        self.assertNotIn(str(self.root), json.dumps(self.app.read(job_id)))
        with self.assertRaises(ValueError):
            self.app.start("escape", "local-text", {"fixture": ".."})

    def test_cancellation_waits_for_open_fixture_to_close_before_terminal(self):
        entered, release = threading.Event(), threading.Event()
        handles = []
        original_open = Path.open
        original_progress = self.store.progress
        def open_file(path, *args, **kwargs):
            stream = original_open(path, *args, **kwargs)
            if path.name == "answers.jsonl":
                handles.append(stream)
            return stream
        def progress(*args, **kwargs):
            original_progress(*args, **kwargs)
            entered.set()
            release.wait(3)
        job_id = self._start()
        with patch.object(Path, "open", open_file), patch.object(self.store, "progress", side_effect=progress):
            worker = threading.Thread(target=self.app.run_job, args=(job_id,))
            worker.start()
            try:
                self.assertTrue(entered.wait(3))
                self.assertEqual(self.app.cancel(job_id)["job"]["state"], "cancelling")
                self.assertFalse(handles[0].closed)
            finally:
                release.set()
                worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertTrue(all(handle.closed for handle in handles))
        self.assertEqual(self.app.read(job_id)["job"]["state"], "cancelled")

    def test_malformed_fixture_fails_without_exposing_input(self):
        (self.root / "answers.jsonl").write_text('private malformed text\n')
        job_id = self._start()
        result = self.app.run_job(job_id)
        self.assertEqual(result["job"]["state"], "failed")
        self.assertNotIn("private malformed", json.dumps(result))
