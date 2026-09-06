from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from rag_ime.agent_lab_golden_pi import AgentLabGoldenPiExecutor, GoldenPiCallError
from rag_ime.agent_sessions import AgentSessionStore
from tests.test_agent_lab_golden_pi import Runtime


class MemoryRuntime(Runtime):
    output = '{}'

    def await_turn_settled(self, *args, **kwargs):
        result = super().await_turn_settled(*args, **kwargs)
        result['receipt']['finalMessage']['content'] = [{'type': 'text', 'text': self.output}]
        return result


class MemoryPiTests(unittest.TestCase):
    def setUp(self):
        from rag_ime.agent_lab_memory_pi import AgentLabMemoryPiExecutor
        self.adapter = AgentLabMemoryPiExecutor
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sessions = AgentSessionStore(self.root / 'runtime.sqlite')
        self.sessions.initialize()
        self.addCleanup(self.sessions.close)
        self.runtime = MemoryRuntime()
        self.pi = AgentLabGoldenPiExecutor(self.root / 'runtime.sqlite', sessions=self.sessions, runtime=lambda: self.runtime)
        self.messages = [{'role': 'system', 'content': 'Return the personal Memory result.'}, {'role': 'user', 'content': '{"evidence":[]}'}]

    def executor(self, **kwargs):
        return self.adapter(self.root / 'private', pi_executor=self.pi, **kwargs)

    def test_real_session_receipt_and_schema_validation_replay_without_provider(self):
        executor = self.executor()
        executor.begin_run('curation-1', frozen_input_sha256='a' * 64)
        # Schema-invalid output is a settled model response, never a successful
        # organizer result; retrying it may not spend another request.
        for _ in range(2):
            with self.assertRaisesRegex(ValueError, 'schema'):
                executor.complete(phase='atom-first-curation', messages=self.messages)
        self.assertEqual(1, len(self.runtime.calls))
        receipt = executor.receipts[-1]
        self.assertEqual('pi_session', receipt['transport'])
        self.assertFalse(receipt['schemaValid'])
        self.assertEqual('turn-1', receipt['turnId'])
        self.assertEqual('extension:agent-lab', self.sessions.get(receipt['sessionId'])['ownerAppId'])
        self.assertFalse(receipt['sessionId'].startswith('private-luna:'))
        self.assertTrue(receipt['resumed'])

    def test_valid_phase_output_replays_same_pi_turn_across_logical_runs(self):
        from rag_ime.personal_memory_luna_evaluation import personal_memory_phase_schema
        schema = personal_memory_phase_schema('atom-first-curation')
        self.runtime.output = json.dumps({key: [] for key in schema['required']})
        executor = self.executor()
        executor.begin_run('curation-1', frozen_input_sha256='a' * 64)
        first = executor.complete(phase='atom-first-curation', messages=self.messages)
        self.assertTrue(first['receipt']['schemaValid'])
        self.assertFalse(first['receipt']['resumed'])
        executor.finish_run()
        restored = self.executor()
        restored.begin_run('rollback-replay-2', frozen_input_sha256='a' * 64)
        replay = restored.complete(phase='atom-first-curation', messages=self.messages)
        self.assertEqual(first['requestId'], replay['requestId'])
        self.assertEqual(first['receipt']['sessionId'], replay['receipt']['sessionId'])
        self.assertTrue(replay['receipt']['resumed'])
        self.assertEqual(1, len(self.runtime.calls))
        self.assertIn('Return exactly one JSON object', self.runtime.calls[0][1])
        self.assertNotIn('cost', replay['receipt']['usage'])

    def test_trials_isolate_requests_but_shadow_replay_keeps_original_identity(self):
        from rag_ime.personal_memory_luna_evaluation import personal_memory_phase_schema
        self.runtime.output = json.dumps({key: [] for key in personal_memory_phase_schema('atom-first-curation')['required']})
        first = self.adapter(self.root/'first', pi_executor=self.pi, request_namespace='lab-trial:first')
        first.begin_run('curation-1', frozen_input_sha256='a'*64)
        initial = first.complete(phase='atom-first-curation', messages=self.messages)
        first.finish_run()
        first.begin_run('shadow-replay', frozen_input_sha256='a'*64)
        replay = first.complete(phase='atom-first-curation', messages=self.messages)
        second = self.adapter(self.root/'second', pi_executor=self.pi, request_namespace='lab-trial:second')
        second.begin_run('curation-1', frozen_input_sha256='a'*64)
        fresh = second.complete(phase='atom-first-curation', messages=self.messages)
        self.assertEqual(initial['requestId'], replay['requestId'])
        self.assertTrue(replay['receipt']['resumed'])
        self.assertNotEqual(initial['requestId'], fresh['requestId'])
        self.assertFalse(fresh['receipt']['resumed'])
        self.assertEqual(2, len(self.runtime.calls))

    def test_interrupted_settlement_recovery_does_not_reprompt(self):
        executor = self.executor()
        executor.begin_run('curation-1', frozen_input_sha256='a' * 64)
        self.runtime.fail_lookup = True
        with self.assertRaises(GoldenPiCallError):
            executor.complete(phase='atom-first-curation', messages=self.messages)
        self.runtime.fail_lookup = False
        with self.assertRaisesRegex(ValueError, 'schema'):
            executor.complete(phase='atom-first-curation', messages=self.messages)
        self.assertEqual(1, len(self.runtime.calls))

    def test_close_and_cancel_after_admission_abort_the_original_pi_session(self):
        executor = self.executor(cancelled=lambda: bool(self.runtime.calls))
        executor.begin_run('curation-1', frozen_input_sha256='a' * 64)
        with self.assertRaises(GoldenPiCallError):
            executor.complete(phase='atom-first-curation', messages=self.messages)
        self.assertEqual([self.runtime.calls[0][0]], self.runtime.aborts)
        self.assertEqual('turn-1', executor.receipts[-1]['turnId'])
        self.assertEqual('cancelled', executor.receipts[-1]['status'])
        executor.close()
        with self.assertRaises(RuntimeError):
            executor.begin_run('after-close', frozen_input_sha256='a' * 64)

    def test_runner_factory_receives_frozen_controls_without_cli_execution(self):
        from types import SimpleNamespace
        from scripts.eval_personal_memory_luna import _create_evaluation_executor
        received = {}
        expected = SimpleNamespace(model_id='gpt-5.6-sol', thinking_level='max', context_profile='compact-json-v1', prompt_contract='concise-json-v1')
        def factory(artifact_root, **kwargs):
            received.update(kwargs)
            return expected
        args = SimpleNamespace(timeout_seconds=30, model='gpt-5.6-sol', context_profile='compact-json-v1', prompt_contract='concise-json-v1')
        self.assertIs(expected, _create_evaluation_executor(args, self.root, audit_db_path=self.root/'shadow.sqlite', executor_factory=factory))
        self.assertEqual('gpt-5.6-sol', received['model_id'])
        self.assertEqual('concise-json-v1', received['prompt_contract'])

    def test_usage_mapping_requires_actual_cache_counts_and_does_not_invent_money(self):
        from rag_ime.agent_lab_memory_pi import _memory_usage
        complete = _memory_usage({'inputTokens': 10, 'cacheReadTokens': 20, 'cacheWriteTokens': 0, 'outputTokens': 5})
        self.assertEqual(30, complete['inputTokens'])
        self.assertEqual(10, complete['uncachedInputTokens'])
        self.assertNotIn('costUsd', complete)
        self.assertFalse(_memory_usage({'inputTokens': 10, 'outputTokens': 5})['available'])

    def test_private_observer_preserves_admission_and_schema_failed_settlement(self):
        events = []
        executor = self.executor(receipt_observer=events.append)
        executor.begin_run('curation-1', frozen_input_sha256='a' * 64)
        with self.assertRaisesRegex(ValueError, 'schema'):
            executor.complete(phase='atom-first-curation', messages=self.messages)
        admitted = next(item for item in events if item['status'] == 'session_bound')
        settled = events[-1]
        self.assertEqual(admitted['requestId'], settled['requestId'])
        self.assertEqual(admitted['sessionId'], settled['sessionId'])
        self.assertEqual('turn-1', settled['turnId'])
        self.assertFalse(settled['schemaValid'])
        path = executor.artifact_root / 'pi-request-receipts.jsonl'
        persisted = [json.loads(line) for line in path.read_text().splitlines()]
        self.assertEqual(events, persisted)
        self.assertEqual(0, path.stat().st_mode & 0o077)
        self.assertNotIn(str(self.root), json.dumps(events))

    def test_shadow_audit_uses_actual_pi_session_snapshot_and_request(self):
        from rag_ime.personal_memory_luna_evaluation import personal_memory_phase_schema
        shadow = self.root/'shadow.sqlite'
        shadow_sessions = AgentSessionStore(shadow)
        shadow_sessions.initialize()
        self.addCleanup(shadow_sessions.close)
        self.runtime.output = json.dumps({key: [] for key in personal_memory_phase_schema('atom-first-curation')['required']})
        executor = self.executor(audit_db_path=shadow)
        executor.begin_run('actual-memory-run', frozen_input_sha256='a'*64)
        with sqlite3.connect(shadow) as conn:
            self.assertIsNone(conn.execute('SELECT session_id FROM memory_curation_model_runs').fetchone()[0])
        response = executor.complete(phase='atom-first-curation', messages=self.messages)
        executor.finish_run()
        with sqlite3.connect(shadow) as conn:
            row = conn.execute('SELECT session_id,state FROM memory_curation_model_runs').fetchone()
            self.assertEqual((response['receipt']['sessionId'], 'completed'), row)
            self.assertEqual([(row[0], 1)], conn.execute('SELECT id,evaluation_snapshot FROM agent_sessions').fetchall())
            request = conn.execute('SELECT request_id,session_id,turn_id,receipt_json FROM memory_curation_model_requests').fetchone()
            self.assertEqual((response['requestId'], row[0], 'turn-1'), request[:3])
            self.assertEqual(response['receipt'], json.loads(request[3]))
            self.assertEqual([], conn.execute('PRAGMA foreign_key_check').fetchall())
        self.assertEqual(1, len(self.runtime.calls))

    def test_shadow_audit_cannot_target_the_resident_database(self):
        with self.assertRaisesRegex(ValueError, 'isolated shadow'):
            self.executor(audit_db_path=self.root/'runtime.sqlite')

    def test_cancelled_settlement_keeps_actual_receipt_but_is_not_returned_to_owner(self):
        from rag_ime.personal_memory_luna_evaluation import personal_memory_phase_schema
        self.runtime.output = json.dumps({key: [] for key in personal_memory_phase_schema('atom-first-curation')['required']})
        stop = threading.Event()
        def observe(receipt):
            if receipt.get('status') == 'completed':
                stop.set()
        executor = self.executor(cancelled=stop.is_set, receipt_observer=observe)
        executor.begin_run('memory-run', frozen_input_sha256='a'*64)
        with self.assertRaises(GoldenPiCallError):
            executor.complete(phase='atom-first-curation', messages=self.messages)
        self.assertEqual(1, len(self.runtime.calls))
        self.assertEqual('completed', executor.receipts[-1]['status'])
        self.assertTrue(executor.receipts[-1]['schemaValid'])
        self.assertEqual('turn-1', executor.receipts[-1]['turnId'])

    def test_run_binding_rejects_model_or_frozen_input_drift_after_restart(self):
        executor = self.executor()
        executor.begin_run('curation-1', frozen_input_sha256='a' * 64)
        executor.finish_run()
        with self.assertRaisesRegex(ValueError, 'binding'):
            self.executor(model_id='gpt-5.6-sol').begin_run('curation-1', frozen_input_sha256='a' * 64)
        with self.assertRaisesRegex(ValueError, 'binding'):
            self.executor().begin_run('curation-1', frozen_input_sha256='b' * 64)
        self.assertEqual([], self.runtime.calls)

    def test_cancelled_callback_is_forwarded_without_admission(self):
        executor = self.executor(cancelled=lambda: True)
        executor.begin_run('curation-1', frozen_input_sha256='a' * 64)
        with self.assertRaises(GoldenPiCallError):
            executor.complete(phase='atom-first-curation', messages=self.messages)
        self.assertEqual([], self.runtime.calls)

    def test_verifier_requires_isolation_and_unsupported_thinking_fails_before_provider(self):
        with self.assertRaises(ValueError):
            self.executor(thinking_level='low')
        executor = self.executor()
        executor.begin_run('curation-1', frozen_input_sha256='a' * 64)
        with self.assertRaisesRegex(ValueError, 'isolation'):
            executor.complete(phase='atom-first-verifier', messages=self.messages)
        self.assertEqual([], self.runtime.calls)


if __name__ == '__main__':
    unittest.main()
