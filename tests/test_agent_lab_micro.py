import json
import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_lab.micro import MicroAdapter, BudgetExceeded, verify_policy, verify_export, turn_usage


class MicroTests(unittest.TestCase):
    def test_turn_usage_includes_intermediate_tool_calls_but_not_other_turns(self):
        def binding(t):return {'type':'custom','customType':'rag-ime.pi-turn-binding','data':{'turnId':t}}
        def msg(i,n):return {'type':'message','id':i,'message':{'role':'assistant','usage':{'input':n,'output':10,'cost':{'total':0.1}}}}
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'session.jsonl'
            p.write_text('\n'.join(json.dumps(x) for x in [binding('old'),msg('a',999),binding('target'),msg('b',100),msg('c',200),binding('next'),msg('d',999)]))
            r=turn_usage(p,'target')
            self.assertEqual(r['providerCalls'],2)
            self.assertEqual(r['usage']['totalTokens'],320)
            self.assertAlmostEqual(r['usage']['estimatedCostUsd'],0.2)
            with self.assertRaises(ValueError):turn_usage(p,'absent')

    def test_room_receipt_uses_dispatch_identity_not_user_message(self):
        from scripts.run_paw_micro_eval import room_turn_identity
        receipt={'clientMessageId':'user-1','dispatches':[{'accepted':True,'sessionTurnId':'pi-turn-1','dispatchId':'dispatch-1'}]}
        self.assertEqual(room_turn_identity(receipt),('pi-turn-1','dispatch-1'))
        with self.assertRaises(RuntimeError):room_turn_identity({'dispatches':[{'accepted':False}]})

    def test_fault_suite_references_real_individual_tests(self):
        from scripts.run_paw_micro_eval import FAULT_TESTS
        for name in FAULT_TESTS.values():
            suite=unittest.defaultTestLoader.loadTestsFromName(name)
            self.assertEqual(suite.countTestCases(),1)
            self.assertFalse(any(type(t).__name__=='_FailedTest' for t in suite),name)

    def test_candidate_cannot_drop_the_host_output_contract(self):
        prompts=[]
        good={'currency':'CNY','limit':800,'receiptRequired':True,'unknownCurrency':'manual'}
        answers=[good,{'cause':'shorten','candidatePrompt':'CNY up to 800 with receipt. Unknown currency manual review.'},good]
        def complete(**kw):
            prompts.append(kw['prompt'])
            return {'text':json.dumps(answers.pop(0)), 'sessionId':'s','turnId':str(len(prompts)),
                    'usage':{'totalTokens':100},'receipt':{}}
        class O:
            def progress(self,*a):pass
            def bind_session(self,*a,**kw):pass
        with tempfile.TemporaryDirectory() as d:
            a=MicroAdapter(Path(d),complete=complete)
            r=a.execute(a.prepare({'taskId':'optimization'},'j')['privateInput'],O(),lambda:False)
            self.assertEqual(r['qualityVerdict'],'keep')
            self.assertIn('unknownCurrency (manual/approved/rejected)',prompts[0])
            self.assertIn('unknownCurrency (manual/approved/rejected)',prompts[2])
            self.assertNotIn('expected',prompts[1])
            self.assertEqual(r['modelCalls'],3)

    def test_verifier_checks_behavior_and_rejects_wrong_config(self):
        good = {'currency':'CNY','limit':800,'receiptRequired':True,'unknownCurrency':'manual'}
        self.assertEqual(verify_policy(good)['passed'],4)
        self.assertEqual(verify_policy({**good,'limit':500})['passed'],3)
        self.assertFalse(verify_policy({**good,'receiptRequired':False})['allPassed'])
        self.assertFalse(verify_policy({'limit':800})['allPassed'])

    def test_export_uses_isolated_process_without_repo_imports(self):
        good = {'currency':'CNY','limit':800,'receiptRequired':True,'unknownCurrency':'manual'}
        with tempfile.TemporaryDirectory() as d:
            result=verify_export(good,Path(d))
            self.assertEqual(result['passed'],4)
            self.assertTrue(result['allPassed'])
            self.assertFalse(result['cleanMachineVerified'])

    def test_budget_stops_following_call_and_keeps_receipt(self):
        calls=[]
        def complete(**kw):
            calls.append(kw)
            return {'text':'{}','usage':{'totalTokens':21000},'receipt':{'requestId':kw['request_id']}}
        with tempfile.TemporaryDirectory() as d:
            adapter=MicroAdapter(Path(d),complete=complete)
            private=adapter.prepare({'taskId':'update'},'job-1')['privateInput']
            class Observer:
                def progress(self,*a):pass
                def bind_session(self,*a,**kw):pass
            result=adapter.execute(private,Observer(),lambda:False)
            self.assertEqual(result['status'],'failed')
            self.assertEqual(result['stopReason'],'token_budget_exceeded')
            self.assertEqual(result['modelCalls'],1)
            self.assertEqual(len(calls),1)
            self.assertEqual(result['totalTokens'],21000)

    def test_missing_usage_stops_instead_of_counting_zero(self):
        def complete(**kw):return {'text':'{}','usage':{},'receipt':{}}
        with tempfile.TemporaryDirectory() as d:
            a=MicroAdapter(Path(d),complete=complete)
            class O:
                def progress(self,*a):pass
                def bind_session(self,*a,**k):pass
            r=a.execute(a.prepare({'taskId':'update'},'j')['privateInput'],O(),lambda:False)
            self.assertEqual(r['stopReason'],'usage_unavailable')
            self.assertIsNone(r['totalTokens'])

    def test_preparation_does_not_call_model_and_validates_task(self):
        with tempfile.TemporaryDirectory() as d:
            a=MicroAdapter(Path(d),complete=lambda **kw:self.fail('called'))
            self.assertEqual(a.prepare({'taskId':'handoff'},'j')['publicSpec']['taskId'],'handoff')
            with self.assertRaises(ValueError):a.prepare({'taskId':'bad'},'j')
            with self.assertRaises(ValueError):a.prepare({'taskId':'handoff','maxCalls':100},'j')

if __name__=='__main__':unittest.main()
