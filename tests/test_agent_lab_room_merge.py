import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rag_ime.agent_lab.room_merge import BUDGET, RoomMergeTrialAdapter, merge_disjoint


class RoomMergeTests(unittest.TestCase):
    def test_merge_preserves_values_without_a_gold_lookup(self):
        contract = [{"caseId":"unseen", "outputSchema":{"caseId":"string","tokens":"integer"}}]
        answer = [{"caseId":"unseen","tokens":912}]
        self.assertEqual(merge_disjoint([answer],contract),answer)
        with self.assertRaises(ValueError):merge_disjoint([answer,answer],contract)
        with self.assertRaises(ValueError):merge_disjoint([[{"caseId":"unseen","tokens":True}]],contract)
        with self.assertRaises(ValueError):merge_disjoint([[]],contract)

    def test_one_workflow_change_uses_fresh_rooms_and_preserves_worker_inputs(self):
        truth={
            "room-identity":{"caseId":"room-identity","turnField":"sessionTurnId","clientField":"dispatchId"},
            "quality-state":{"caseId":"quality-state","executionComplete":True,"qualityPassed":False},
            "whole-turn-usage":{"caseId":"whole-turn-usage","tokens":280,"modelCalls":2},
        }
        calls=[]
        def complete(**kw):
            calls.append(kw)
            packet=json.loads(kw['prompt'].split('\nInstruction:')[0])
            if 'cases' in packet:
                answer=[truth[c['caseId']] for c in packet['cases']]
            else:
                answer={'operator':'deterministic_disjoint_merge','cause':'disjoint structured findings'}
            return {'text':json.dumps(answer),'sessionId':'s'+str(len(calls)),'turnId':'t',
                    'providerCalls':1,'usage':{'totalTokens':100,'estimatedCostUsd':.01},'receipt':{}}
        class Observer:
            def bind_session(self,*args,**kwargs):pass
            def progress(self,*args):pass
        with tempfile.TemporaryDirectory() as temporary:
            adapter=RoomMergeTrialAdapter(Path(temporary),complete=complete,room_complete=complete,abort_session=lambda _:None)
            private=adapter.prepare({'taskId':'room-merge'},'job')['privateInput']
            result=adapter.execute(private,Observer(),lambda:False)
        self.assertEqual(result['optimizationVerdict'],'improved')
        self.assertEqual(result['arms']['baseline']['providerCalls'],3)
        self.assertEqual(result['arms']['candidate']['providerCalls'],2)
        self.assertEqual(result['observed']['providerCalls'],6)
        self.assertEqual(calls[0]['prompt'],calls[4]['prompt'])
        self.assertEqual(calls[1]['prompt'],calls[5]['prompt'])
        self.assertNotEqual(calls[0]['room_group'],calls[4]['room_group'])

    def test_settled_budget_crossing_preserves_quality_without_another_call(self):
        from rag_ime.agent_lab.room_comparison import EXPECTED
        calls=[]
        def complete(**kw):
            calls.append(kw)
            packet=json.loads(kw['prompt'].split('\nInstruction:')[0])
            answer=[EXPECTED[c['caseId']] for c in packet['cases']] if 'cases' in packet else {'operator':'deterministic_disjoint_merge'}
            return {'text':json.dumps(answer),'sessionId':'s','turnId':'t','providerCalls':1,
                    'usage':{'totalTokens':100,'estimatedCostUsd':.01},'receipt':{}}
        class O:
            def bind_session(self,*args,**kwargs):pass
            def progress(self,*args):pass
        with tempfile.TemporaryDirectory() as d, patch.dict(BUDGET,{'maxObservedTokens':550}):
            adapter=RoomMergeTrialAdapter(d,complete=complete,room_complete=complete,abort_session=lambda _:None)
            result=adapter.execute(adapter.prepare({'taskId':'room-merge'},'j')['privateInput'],O(),lambda:False)
        self.assertEqual(len(calls),6)
        self.assertEqual(result['qualityVerdict'],'keep')
        self.assertEqual(result['optimizationVerdict'],'budget_exhausted')
        self.assertEqual(result['arms']['candidate']['score']['passed'],3)

    def test_budget_crossing_blocks_the_pending_integrator(self):
        from rag_ime.agent_lab.room_comparison import EXPECTED
        calls=[]
        def complete(**kw):
            calls.append(kw)
            packet=json.loads(kw['prompt'].split('\nInstruction:')[0])
            return {'text':json.dumps([EXPECTED[c['caseId']] for c in packet['cases']]),
                    'sessionId':'s','turnId':'t','providerCalls':1,
                    'usage':{'totalTokens':100,'estimatedCostUsd':.01},'receipt':{}}
        class O:
            def bind_session(self,*args,**kwargs):pass
            def progress(self,*args):pass
        with tempfile.TemporaryDirectory() as d, patch.dict(BUDGET,{'maxObservedTokens':150}):
            adapter=RoomMergeTrialAdapter(d,complete=complete,room_complete=complete,abort_session=lambda _:None)
            result=adapter.execute(adapter.prepare({'taskId':'room-merge'},'j')['privateInput'],O(),lambda:False)
        self.assertEqual(len(calls),2)
        self.assertEqual(result['observed']['tokens'],200)
        self.assertEqual(result['optimizationVerdict'],'budget_exhausted')
        self.assertIn('trial_budget_exhausted',result['error'])
        self.assertNotIn('score',result['arms']['baseline'])


if __name__=='__main__':unittest.main()
