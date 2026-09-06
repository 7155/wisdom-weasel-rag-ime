from __future__ import annotations

import contextlib
import io
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

from rag_ime.agent_lab_golden_pi import AgentLabGoldenPiExecutor
from rag_ime.agent_sessions import AgentSessionStore
from tests.test_agent_lab_golden_pi import Runtime


class FixtureRuntime(Runtime):
    """Deterministic deliberately-poor curator, through actual Pi settlement."""

    retain_durable = False

    def await_turn_settled(self, session_id, turn_id, **kwargs):
        result = super().await_turn_settled(session_id, turn_id, **kwargs)
        prompt = next(item[1] for item in self.calls if item[0] == session_id)
        packet = json.loads(prompt.split('BEGIN_UNTRUSTED_PRIVATE_PACKET\n')[1].split('\nEND_UNTRUSTED_PRIVATE_PACKET')[0])
        if 'expectedEvidenceRefs' in packet:
            output = {'v': 1, 'ok': 1, 'coveredEvidenceRefs': packet['expectedEvidenceRefs'],
                'checkedActionCount': packet['expectedActionCount'], 'decisionDigest': packet['decisionDigest'],
                'findings': [], 'errors': []}
        else:
            output = {key: [] for key in ('decisions', 'attach', 'create', 'update', 'supersede', 'merge', 'retract', 'ignore', 'tagMerges', 'warnings')}
            output['ignore'] = [item['ref'] for item in packet['snapshot']['inputs']]
            if self.retain_durable:
                from rag_ime.personal_memory_luna_evaluation import SYNTHETIC_PERSONAL_MEMORY_RAG_CASES
                fixtures = dict(zip((item['text'] for item in SYNTHETIC_PERSONAL_MEMORY_RAG_CASES[:4]),
                    ('durable_preference', 'personal_habit', 'personal_principle', 'project_requirement')))
                for item in packet['snapshot']['inputs']:
                    if item['text'] not in fixtures:
                        continue
                    output['ignore'].remove(item['ref'])
                    output['create'].append({'e': item['ref'], 'p': '', 'text': item['text'],
                        'kind': fixtures[item['text']], 'g': 'new:work-habits', 'topicRefs': [],
                        'topicTitle': '工作方式', 'tags': ['工作方式'], 'confidence': 0.99, 'reason': 'fixture'})
        result['receipt']['finalMessage'].update(content=[{'type': 'text', 'text': json.dumps(output)}],
            usage={'input': 100, 'cacheRead': 20, 'cacheWrite': 0, 'output': 10, 'cost': {'total': 0.004}})
        return result


class Observer:
    def __init__(self):
        self.messages, self.bindings, self.hooks = [], [], []

    def progress(self, message):
        self.messages.append(message)

    def bind_session(self, session_id, turn_id='', cancel=None):
        self.bindings.append((session_id, turn_id))
        if cancel is not None:
            self.hooks.append(cancel)


class MemoryTrialTests(unittest.TestCase):
    def setUp(self):
        from rag_ime.agent_lab_memory_trial import AgentLabMemoryTrialAdapter
        self.adapter_type = AgentLabMemoryTrialAdapter
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime = FixtureRuntime()
        self.sessions = None
        self.pi = None
        self.factory = Mock(side_effect=self.make_pi)
        self.abort = Mock(side_effect=lambda sid: self.runtime.abort(sid))
        self.adapter = self.adapter_type(self.root / 'trials', pi_executor_factory=self.factory,
            abort_session=self.abort, production_db=self.root / 'production.sqlite')

    def make_pi(self):
        if self.pi is None:
            self.sessions = AgentSessionStore(self.root / 'runtime.sqlite')
            self.sessions.initialize()
            self.addCleanup(self.sessions.close)
            self.pi = AgentLabGoldenPiExecutor(self.root / 'runtime.sqlite', sessions=self.sessions, runtime=lambda: self.runtime)
        return self.pi

    def prepared(self, job_id='lab-trial:first', spec=None):
        return self.adapter.prepare(spec or {}, job_id)

    def test_prepare_is_read_only_and_freezes_synthetic_controls_without_source_paths(self):
        prepared = self.prepared(spec={'model': 'gpt-5.6-sol', 'contextProfile': 'compact-json-v1', 'promptContract': 'concise-json-v1'})
        self.assertEqual({'publicSpec', 'privateInput'}, set(prepared))
        self.assertEqual('synthetic-fixture', prepared['publicSpec']['evaluationMode'])
        self.assertEqual('gpt-5.6-sol', prepared['publicSpec']['model'])
        self.assertEqual(5, prepared['publicSpec']['fixtureCaseCount'])
        self.assertFalse((self.root / 'trials').exists())
        self.assertNotIn(str(self.root), json.dumps(prepared['publicSpec']))
        self.factory.assert_not_called()

    def test_frontend_cannot_select_paths_or_unsupported_controls(self):
        for spec in ({'shadowDb': str(self.root / 'production.sqlite')}, {'privateDir': '/tmp/out'},
                     {'sourceAssetId': '../production.sqlite'}, {'sourceAssetId': 'missing'},
                     {'candidatePromptText': 'arbitrary prompt'}, {'model': 'gpt-6-astra'},
                     {'thinkingLevel': 'low'}):
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                self.prepared(spec=spec)
        self.factory.assert_not_called()

    def test_host_source_is_frozen_and_drift_fails_before_execution(self):
        source = self.root / 'host-shadow.sqlite'
        source.write_bytes(b'private-source-sentinel')
        source.chmod(0o600)
        adapter = self.adapter_type(self.root / 'trials', pi_executor_factory=self.factory, abort_session=self.abort,
            source_assets={'approved-shadow': source}, production_db=self.root / 'production.sqlite')
        with patch('rag_ime.agent_lab_memory_trial.verify_recovered_memory_shadow', return_value={}):
            prepared = adapter.prepare({'sourceAssetId': 'approved-shadow'}, 'lab-trial:host')
        self.assertEqual('host-shadow', prepared['publicSpec']['evaluationMode'])
        self.assertNotIn('private-source-sentinel', json.dumps(prepared))
        self.assertNotIn(str(source), json.dumps(prepared['publicSpec']))
        source.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'changed'):
            adapter.execute(prepared['privateInput'], Observer(), lambda: False)
        self.factory.assert_not_called()

    def test_production_source_alias_is_rejected_before_open(self):
        production = self.root / 'production.sqlite'
        production.write_bytes(b'never-open')
        alias = self.root / 'production-alias.sqlite'
        alias.hardlink_to(production)
        adapter = self.adapter_type(self.root / 'trials', pi_executor_factory=self.factory, abort_session=self.abort,
            source_assets={'forbidden': alias}, production_db=production)
        with patch('rag_ime.agent_lab_memory_trial.verify_recovered_memory_shadow') as verify:
            with self.assertRaisesRegex(ValueError, 'production'):
                adapter.prepare({'sourceAssetId': 'forbidden'}, 'lab-trial:forbidden')
        verify.assert_not_called()

    def test_real_fixture_pipeline_reports_actual_failed_quality_and_private_pi_cost(self):
        observer = Observer()
        output = io.StringIO()
        with contextlib.redirect_stdout(output), patch('scripts.eval_personal_memory_luna.os.umask') as umask:
            result = self.adapter.execute(self.prepared()['privateInput'], observer, lambda: False)
        umask.assert_not_called()
        self.assertEqual('', output.getvalue())
        self.assertEqual('rag-ime.agent-lab-trial-result.v1', result['schemaVersion'])
        self.assertEqual('memory', result['sceneId'])
        self.assertEqual(5, result['caseCount'])
        self.assertEqual('reject', result['qualityVerdict'])
        self.assertEqual(5, result['metrics']['curation']['sourceCount'])
        self.assertFalse(result['signals']['personalMemoryQualityMeasured'])
        self.assertTrue(result['signals']['syntheticFixture'])
        self.assertGreater(len(self.runtime.calls), 0)
        self.assertTrue(any(turn == 'turn-1' for _, turn in observer.bindings))
        self.assertTrue(result['cost']['available'])
        self.assertAlmostEqual(0.004 * len(self.runtime.calls), result['cost']['estimatedCostUsd'])
        self.assertNotIn(str(self.root), json.dumps(result))
        self.assertNotIn('我长期偏好', json.dumps(result, ensure_ascii=False))
        self.assertNotIn('modelRequests', result)
        private_receipts = list((self.root / 'trials').rglob('pi-request-receipts.jsonl'))
        self.assertEqual(1, len(private_receipts))
        receipts = [json.loads(line) for line in private_receipts[0].read_text().splitlines()]
        self.assertTrue(any(item.get('turnId') == 'turn-1' for item in receipts))
        self.assertTrue(any('estimatedCostUsd' in dict(item.get('usage') or {}).get('runtimeUsage', {}) for item in receipts))
        self.assertFalse(list((self.root / 'trials').rglob('work')))
        for path in (self.root / 'trials').rglob('*'):
            self.assertEqual(0, path.stat().st_mode & 0o077, path.name)

    def test_cancel_prevents_next_phase_aborts_once_and_cleans_shadow(self):
        from rag_ime.agent_lab_trial_execution import AgentLabTrialApplication
        from rag_ime.agent_lab_trials import AgentLabTrialStore
        entered, released = threading.Event(), threading.Event()
        original_wait = self.runtime.await_turn_settled
        def wait(*args, **kwargs):
            entered.set()
            if not released.wait(10):
                raise TimeoutError('test did not release cancelled turn')
            return original_wait(*args, **kwargs)
        def abort(sid):
            result = self.runtime.abort(sid)
            released.set()
            return result
        self.runtime.await_turn_settled = wait
        self.abort.side_effect = abort
        app = AgentLabTrialApplication(AgentLabTrialStore(self.root / 'jobs.sqlite'), {'memory': self.adapter}, start_workers=False)
        self.addCleanup(app.close)
        job = app.start('click', 'memory', {})['job']['jobId']
        worker = threading.Thread(target=app.run_job, args=(job,))
        worker.start()
        try:
            self.assertTrue(entered.wait(20))
            app.cancel(job)
        finally:
            released.set()
            worker.join(20)
        self.assertFalse(worker.is_alive())
        self.assertEqual('cancelled', app.read(job)['job']['state'])
        self.assertEqual(1, self.abort.call_count)
        self.assertEqual(1, len(self.runtime.calls))
        retained = app.read(job)['job']['result']
        self.assertEqual('cancelled', retained['status'])
        self.assertEqual('unavailable', retained['qualityVerdict'])
        self.assertEqual(1, retained['cost']['requestCount'])
        self.assertFalse(retained['metrics']['recovery']['replayAttempted'])
        self.assertFalse(list((self.root / 'trials').rglob('work')))
        self.assertTrue(list((self.root / 'trials').rglob('pi-request-receipts.jsonl')))

    def test_cancel_before_execution_constructs_no_pi_and_reads_no_host_source(self):
        result = self.adapter.execute(self.prepared()['privateInput'], Observer(), lambda: True)
        self.assertEqual('cancelled', result['status'])
        self.factory.assert_not_called()
        self.assertFalse(list((self.root / 'trials').rglob('work')))

    def test_missing_runtime_cost_is_unavailable_not_zero(self):
        from rag_ime.agent_lab_memory_trial import _public_cost
        result = _public_cost([{'requestId': 'a', 'status': 'completed', 'usage': {'available': False}}])
        self.assertFalse(result['available'])
        self.assertNotIn('estimatedCostUsd', result)

    def test_unattempted_recovery_is_not_reported_as_passed_after_failure_or_cancel(self):
        from rag_ime.agent_lab_memory_trial import _public_report
        report = _public_report({'status': 'cancelled', 'passed': True,
            'rollback': {'attempted': False, 'ok': True}, 'replay': {'attempted': False, 'ok': True}},
            job_id='lab-trial:cancelled', mode='synthetic-fixture', cost={'available': False})
        self.assertEqual('cancelled', report['status'])
        self.assertEqual('unavailable', report['qualityVerdict'])
        self.assertIsNone(report['metrics']['recovery']['rollbackPassed'])
        self.assertIsNone(report['metrics']['recovery']['replayPassed'])

    def test_failed_pi_execution_is_failed_with_unavailable_quality_and_retained_cost(self):
        from rag_ime.agent_lab_trial_execution import AgentLabTrialApplication
        from rag_ime.agent_lab_trials import AgentLabTrialStore
        self.runtime.failed = True
        app = AgentLabTrialApplication(AgentLabTrialStore(self.root / 'jobs.sqlite'), {'memory': self.adapter}, start_workers=False)
        self.addCleanup(app.close)
        job_id = app.start('failed-call', 'memory', {})['job']['jobId']
        result = app.run_job(job_id)['job']
        self.assertEqual('failed', result['state'])
        self.assertEqual('failed', result['result']['status'])
        self.assertEqual('unavailable', result['result']['qualityVerdict'])
        self.assertEqual(1, result['result']['cost']['requestCount'])
        self.assertEqual(1, len(self.runtime.calls))
        app.run_job(job_id)
        self.assertEqual(1, len(self.runtime.calls))
        self.assertFalse(list((self.root / 'trials').rglob('work')))

    def test_fixture_success_exercises_atom_book_retrieval_rollback_and_cached_replay(self):
        self.runtime.retain_durable = True
        result = self.adapter.execute(self.prepared()['privateInput'], Observer(), lambda: False)
        self.assertEqual('pass', result['qualityVerdict'], result)
        self.assertEqual(4, result['metrics']['curation']['currentAtomCount'])
        self.assertTrue(result['metrics']['retrieval']['passed'])
        self.assertTrue(result['metrics']['recovery']['rollbackPassed'])
        self.assertTrue(result['metrics']['recovery']['replayPassed'])
        self.assertTrue(result['metrics']['recovery']['replayReusedModelRequests'])
        self.assertEqual(2, len(self.runtime.calls))
        self.assertAlmostEqual(0.008, result['cost']['estimatedCostUsd'])

    def test_concurrent_trials_use_separate_shadows_and_actual_requests(self):
        self.make_pi()
        prepared = [self.prepared('lab-trial:' + name)['privateInput'] for name in ('one', 'two')]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda item: self.adapter.execute(item, Observer(), lambda: False), prepared))
        self.assertTrue(all(item['caseCount'] == 5 for item in results))
        self.assertEqual(2, len(list((self.root/'trials').glob('*/evaluation-report.json'))))
        self.assertEqual(len(self.runtime.calls), len({item[2] for item in self.runtime.calls}))
        self.assertEqual(4, len(self.runtime.calls))
        self.assertFalse(list((self.root/'trials').rglob('work')))

    def test_cancel_at_verifier_receipt_prevents_new_semantic_writes_and_replay(self):
        self.runtime.retain_durable = True
        observer, stop = Observer(), threading.Event()
        original_bind = observer.bind_session
        def bind(session_id, turn_id='', cancel=None):
            original_bind(session_id, turn_id, cancel)
            if len([item for item in observer.bindings if item[1]]) == 2:
                stop.set()
        observer.bind_session = bind
        result = self.adapter.execute(self.prepared()['privateInput'], observer, stop.is_set)
        self.assertEqual('cancelled', result['status'])
        self.assertEqual(0, result['metrics']['curation']['currentAtomCount'])
        self.assertFalse(result['metrics']['recovery']['replayAttempted'])
        self.assertEqual(2, len(self.runtime.calls))
        self.assertAlmostEqual(0.008, result['cost']['estimatedCostUsd'])
        self.assertFalse(list((self.root/'trials').rglob('work')))

    def test_cancel_after_curation_applied_still_rolls_back_without_replay(self):
        self.runtime.retain_durable = True
        observer, stop = Observer(), threading.Event()
        def progress(message):
            observer.messages.append(message)
            if message.startswith('Memory curation returned;'):
                stop.set()
        observer.progress = progress
        result = self.adapter.execute(self.prepared()['privateInput'], observer, stop.is_set)
        self.assertEqual('cancelled', result['status'])
        self.assertEqual(4, result['metrics']['curation']['currentAtomCount'])
        self.assertTrue(result['metrics']['recovery']['rollbackRestoredBaseline'])
        self.assertFalse(result['metrics']['recovery']['replayAttempted'])
        self.assertEqual(2, len(self.runtime.calls))
        self.assertFalse(list((self.root/'trials').rglob('work')))

    def test_failed_settlement_is_interrupted_and_cannot_reexecute_same_trial(self):
        from rag_ime.agent_lab_trial_execution import AgentLabTrialExecutionInterrupted
        self.runtime.fail_lookup = True
        prepared = self.prepared()['privateInput']
        for _ in range(2):
            with self.assertRaises(AgentLabTrialExecutionInterrupted):
                self.adapter.execute(prepared, Observer(), lambda: False)
        self.assertEqual(1, len(self.runtime.calls))
        self.assertFalse(list((self.root/'trials').rglob('work')))
        self.assertTrue(list((self.root/'trials').rglob('execution-error.json')))


if __name__ == '__main__':
    unittest.main()
