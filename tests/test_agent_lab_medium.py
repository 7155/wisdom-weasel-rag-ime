import json
from pathlib import Path
import tempfile
import unittest

from rag_ime.agent_lab.medium import create_workspace,verify_workspace,verify_delivery


class MediumTaskVerifierTests(unittest.TestCase):
    def test_delivery_replay_cannot_modify_the_candidate_artifact(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'candidate';create_workspace(root,'jsonl')
            original='{"original":true}\n';(root/'checkpoint.jsonl').write_text(original)
            (root/'ledger/cli.py').write_text('from pathlib import Path\nPath("checkpoint.jsonl").write_text("mutated by verifier CLI")\nprint("[]")\n')
            verify_delivery(root,'jsonl')
            self.assertEqual((root/'checkpoint.jsonl').read_text(),original)

    def test_jsonl_task_has_separate_storage_contract_and_preserves_acceptance_scope(self):
        from rag_ime.agent_lab.medium import task_seed,task_update
        seed=task_seed('jsonl')
        self.assertIn('atomic replacement',seed['SPEC.md'])
        self.assertIn('No SQLite',seed['SPEC.md'])
        self.assertIn('--store',seed['SPEC.md'])
        self.assertIn('checkpoint.jsonl',task_update('jsonl'))
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'candidate';create_workspace(root,'jsonl')
            result=verify_workspace(root,'final','jsonl')
            self.assertEqual((result['passed'],result['total']),(0,20))

    def test_workspace_rejection_is_a_structured_tool_error(self):
        from rag_ime.agent_workspace import WorkspaceHarnessError
        from scripts.run_paw_medium_eval import WorkspaceGateway
        class Rejected:
            def execute(self,payload):raise WorkspaceHarnessError('scoped command rejected')
        gateway=WorkspaceGateway();gateway.base=Rejected()
        response=gateway.execute({'tool':'workspace_shell'})
        self.assertFalse(response['ok'])
        self.assertEqual(response['error'],'scoped command rejected')
        self.assertEqual(response['errorCode'],'WorkspaceHarnessError')

    def test_unimplemented_workspace_fails_every_layer(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'candidate';create_workspace(root)
            for phase,count in [('storage',6),('base',16),('final',20)]:
                result=verify_workspace(root,phase)
                self.assertEqual(result['total'],count)
                self.assertEqual(result['passed'],0)
                self.assertFalse(result['allPassed'])

    def test_correct_output_file_does_not_prove_durable_delivery(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'candidate';create_workspace(root)
            (root/'final.json').write_text(json.dumps([
                {'runId':'r1','jobId':'j1','state':'completed','executionComplete':True,'qualityPassed':True,'totalTokens':150,'costUsd':.03,'costComplete':True},
                {'runId':'r2','jobId':'j2','state':'cancelled','executionComplete':True,'qualityPassed':None,'totalTokens':0,'costUsd':None,'costComplete':False}]))
            result=verify_delivery(root)
            self.assertEqual(result['passed'],1)
            self.assertEqual(result['total'],4)
            self.assertFalse(result['allPassed'])


if __name__=='__main__':unittest.main()
