from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from scripts import eval_personal_memory_luna as runner


class MemoryEvaluationBodyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.sqlite'
        self.source.write_bytes(b'source remains unchanged')
        self.args = runner.build_parser().parse_args([
            '--shadow-db', str(self.source), '--private-dir', str(self.root / 'private')])

    def body(self, *, cancel_after_first=False, cancel_at=None):
        cancelled = [False]
        events = []
        def progress(event):
            events.append(event)
            if (cancel_after_first and event.get('stage') == 'curation_completed') or event.get('stage') == cancel_at:
                cancelled[0] = True
        executor = SimpleNamespace(model_id=self.args.model, thinking_level='max',
            context_profile=self.args.context_profile, prompt_contract=self.args.prompt_contract,
            transport='pi_session', receipts=(), close=Mock())
        factory = Mock(return_value=executor)
        curator = Mock()
        curator.run_due.return_value = {'ok': True, 'results': [{'runId': 'actual-curator-run', 'runStatus': 'applied'}]}
        baseline = {'logicalStateSha256': 'baseline', 'allGovernedCurrentAtomsHaveLegalLineage': True,
                    'bookProjection': {'inSync': True}}
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(runner, 'prepare_verified_memory_shadow', return_value={
                'workingDb': self.root/'private'/'shadow.sqlite', 'sourceIdentity': runner._file_identity(self.source),
                'sourceFileSha256': 'source', 'verification': {}}))
            stack.enter_context(patch.object(runner, 'prepare_private_shadow_schema_view', return_value=self.root))
            stack.enter_context(patch.object(runner, 'atom_first_memory_state_summary', return_value=baseline))
            stack.enter_context(patch.object(runner, 'ManagedPiMemoryOrganizer', return_value=Mock()))
            stack.enter_context(patch.object(runner, 'OwnerMemoryCurator', return_value=curator))
            rollback = stack.enter_context(patch.object(runner, 'rollback_memory_book_run', return_value={'status': 'rolled_back'}))
            umask = stack.enter_context(patch.object(runner.os, 'umask'))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                report = runner.run_evaluation(self.args, executor_factory=factory, progress=progress,
                    cancelled=lambda: cancelled[0])
            self.assertEqual('', output.getvalue())
            umask.assert_not_called()
        return report, executor, factory, curator, rollback, events

    def test_embedded_body_returns_report_without_stdout_or_process_umask(self):
        report, executor, factory, curator, rollback, events = self.body()
        self.assertEqual('pi_session', report['transport'])
        self.assertFalse(report['pipelineResumeSupported'])
        self.assertEqual(2, curator.run_due.call_count)
        executor.close.assert_called_once()
        self.assertTrue(callable(factory.call_args.kwargs['cancelled']))
        self.assertTrue(callable(factory.call_args.kwargs['receipt_observer']))
        self.assertEqual('completed', events[-1]['stage'])
        for path in (self.root/'private').rglob('*'):
            self.assertEqual(0, path.stat().st_mode & 0o077, path.name)

    def test_cancel_after_applied_curation_rolls_back_but_never_replays(self):
        report, executor, factory, curator, rollback, events = self.body(cancel_after_first=True)
        self.assertEqual('cancelled', report['status'])
        self.assertFalse(report['passed'])
        self.assertEqual(1, curator.run_due.call_count)
        rollback.assert_called_once()
        self.assertTrue(report['rollback']['restoredBaseline'])
        self.assertFalse(report['replay']['attempted'])
        self.assertEqual('cancelled', events[-1]['stage'])

    def test_cancel_before_preparation_never_constructs_executor(self):
        factory = Mock()
        with patch.object(runner, 'prepare_verified_memory_shadow') as prepare:
            report = runner.run_evaluation(self.args, executor_factory=factory, cancelled=lambda: True)
        self.assertEqual('cancelled', report['status'])
        prepare.assert_not_called()
        factory.assert_not_called()

    def test_cancel_at_replay_admission_preserves_cleanup_receipt(self):
        report, executor, factory, curator, rollback, events = self.body(cancel_at='replay')
        self.assertEqual('cancelled', report['status'])
        self.assertEqual(1, curator.run_due.call_count)
        self.assertTrue(report['rollback']['restoredBaseline'])
        self.assertFalse(report['replay']['attempted'])

    def test_cancel_after_replay_applied_does_necessary_local_cleanup(self):
        report, executor, factory, curator, rollback, events = self.body(cancel_at='replay_completed')
        self.assertEqual('cancelled', report['status'])
        self.assertEqual(2, curator.run_due.call_count)
        self.assertEqual(2, rollback.call_count)
        self.assertTrue(report['replay']['cancelledCleanup']['restoredBaseline'])

    def test_semantic_body_returns_report_and_closes_without_global_effects(self):
        self.args.semantic_timeline_id = 'approved-timeline'
        executor = SimpleNamespace(model_id=self.args.model, thinking_level='max',
            context_profile=self.args.context_profile, prompt_contract=self.args.prompt_contract,
            transport='pi_session', receipts=(), close=Mock(), begin_run=Mock(), finish_run=Mock(), fail_run=Mock())
        organizer = Mock()
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(runner, 'verify_recovered_memory_shadow', return_value={}))
            stack.enter_context(patch.object(runner, 'load_frozen_activity_timeline', return_value=SimpleNamespace(project='project')))
            stack.enter_context(patch.object(runner, 'build_personal_memory_semantic_evaluation_bundle', return_value=({}, {'semanticBundleSha256': 'a'*64})))
            stack.enter_context(patch.object(runner, 'ManagedPiMemoryOrganizer', return_value=organizer))
            stack.enter_context(patch.object(runner, 'redacted_semantic_curation_summary', return_value={}))
            umask = stack.enter_context(patch.object(runner.os, 'umask'))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                report = runner.run_evaluation(self.args, executor_factory=lambda *a, **kw: executor)
        self.assertEqual('', output.getvalue())
        umask.assert_not_called()
        self.assertEqual('historical_semantic_quality_only', report['evaluationKind'])
        self.assertEqual('pi_session', report['transport'])
        self.assertFalse(report['pipelineResumeSupported'])
        executor.finish_run.assert_called_once()
        executor.close.assert_called_once()

    def test_invalid_embedded_request_raises_value_error_instead_of_exiting_host(self):
        self.args.run_id = '/invalid'
        with self.assertRaises(ValueError):
            runner.run_evaluation(self.args)

    def test_synthetic_only_parser_does_not_require_a_personal_shadow(self):
        args = runner.build_parser().parse_args(['--private-dir', str(self.root/'synthetic'),
            '--seed-synthetic-rag-fixture', '--clean-synthetic-shadow'])
        self.assertIsNone(args.shadow_db)

    def test_missing_shadow_is_rejected_for_non_synthetic_evaluation(self):
        self.args.shadow_db = None
        with self.assertRaisesRegex(ValueError, 'shadow'):
            runner.run_evaluation(self.args)

    def test_cancel_does_not_hide_uncertain_transport_or_cleanup_failure(self):
        for error in (TimeoutError('private transport'), OSError('private cleanup')):
            with self.subTest(error=type(error).__name__), patch.object(runner, '_run_evaluation_body', side_effect=error):
                with self.assertRaises(type(error)):
                    runner.run_evaluation(self.args, cancelled=lambda: True)

    def test_main_retains_cli_json_and_exit_code(self):
        summary = {'passed': False, 'status': 'iterate', 'model': 'gpt-5.6-luna', 'thinking': 'max'}
        with patch.object(runner, 'run_evaluation', return_value=summary) as body, patch.object(runner.os, 'umask') as umask:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = runner.main(['--shadow-db', str(self.source), '--private-dir', str(self.root/'private')])
        self.assertEqual(1, code)
        self.assertEqual('iterate', json.loads(output.getvalue())['status'])
        umask.assert_called_once_with(0o077)
        body.assert_called_once()
