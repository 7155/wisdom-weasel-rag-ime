import json
import tempfile
import unittest
from pathlib import Path
from rag_ime.agent_lab.room_comparison import RoomComparisonAdapter,EXPECTED,score

class RoomComparisonTests(unittest.TestCase):
    def test_score_rejects_duplicates_omissions_and_wrong_fields(self):
        rows=list(EXPECTED.values())
        self.assertEqual(score(rows)['passed'],3)
        self.assertFalse(score(rows+[rows[0]])['allPassed'])
        self.assertEqual(score(rows[1:])['passed'],2)
        self.assertFalse(score([{'caseId':'room-identity','turnField':'turnId','clientField':'userClientId'}])['allPassed'])
        self.assertEqual(score([{'caseId':[]},None])['extraRows'],2)
    def test_all_arms_are_measured_and_handoff_is_not_task_recall(self):
        class O:
            def bind_session(self,*a,**kw):pass
        calls=[]
        def complete(**kwargs):
            prefix=kwargs['prompt'].split(' All information')[0]
            cases=json.loads(prefix)['cases'];calls.append(kwargs)
            answer=[EXPECTED[c['caseId']] for c in cases]
            return {'text':json.dumps(answer),'sessionId':'s','turnId':str(len(calls)),
                    'usage':{'totalTokens':100,'estimatedCostUsd':0.01},'providerCalls':1,'receipt':{}}
        with tempfile.TemporaryDirectory() as d:
            adapter=RoomComparisonAdapter(Path(d),complete=complete,room_complete=complete,abort_session=lambda _:None)
            private=adapter.prepare({'taskId':'room-comparison'},'j')['privateInput']
            r=adapter.execute(private,O(),lambda:False)
            self.assertEqual(r['qualityVerdict'],'keep')
            self.assertEqual(r['arms']['solo']['providerCalls'],1)
            self.assertEqual(r['arms']['room']['providerCalls'],3)
            self.assertEqual(r['arms']['room']['omittedCorrectHandoffFacts'],0)
            self.assertEqual(len(calls),4)
            self.assertEqual(r['armBudget']['maxProviderCalls'],4)

    def test_missing_settlement_is_unknown_cost_not_zero(self):
        class O:
            def bind_session(self,*a,**kw):pass
        def fails(**kwargs):
            raise ConnectionError('accepted call settlement was lost')
        with tempfile.TemporaryDirectory() as d:
            adapter=RoomComparisonAdapter(d,complete=fails,room_complete=fails,abort_session=lambda _:None)
            private=adapter.prepare({'taskId':'room-comparison'},'j')['privateInput']
            result=adapter.execute(private,O(),lambda:False)
            self.assertEqual(result['qualityVerdict'],'reject')
            self.assertFalse(result['arms']['solo']['costKnown'])
            self.assertIsNone(result['arms']['solo']['costPerSuccessfulCaseUsd'])
