#!/usr/bin/env python3
"""Read-only exact-turn reconciliation; never runs a model or edits old receipts."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from rag_ime.agent_lab_micro import turn_usage, canonical


def reconcile(root):
    root=Path(root).resolve()
    jobs=[]
    transcripts={}
    with sqlite3.connect((root/'agent.sqlite').as_uri()+'?mode=ro',uri=True) as conn:
        transcripts={row[0]:root/'sessions'/Path(row[1]).name for row in conn.execute('SELECT id,session_file FROM agent_sessions') if row[1]}
    for job_file in sorted(root.glob('*-job.json')):
        job=json.loads(job_file.read_text());result=job.get('result') or {}
        calls=[]
        for receipt_file in sorted((root/'trials'/result.get('artifactKey','absent')).glob('call-*.json')):
            original=json.loads(receipt_file.read_text())
            sid,tid=original.get('sessionId'),original.get('turnId')
            row={'callFile':str(receipt_file.relative_to(root)), 'sessionId':sid,'turnId':tid,
                 'originalReceiptSha256':hashlib.sha256(receipt_file.read_bytes()).hexdigest(),
                 'available':False}
            if sid and tid:
                try:row.update(turn_usage(transcripts[sid],tid),available=True)
                except (KeyError,ValueError,OSError):pass
            calls.append(row)
        complete=bool(calls) and all(c['available'] for c in calls)
        cost_known=complete and all('estimatedCostUsd' in c['usage'] for c in calls)
        total_tokens=sum(c['usage']['totalTokens'] for c in calls) if complete else None
        provider_calls=sum(c.get('providerCalls',0) for c in calls) if complete else None
        budget=job.get('publicSpec',{}).get('budget',{})
        budget_status=('unknown' if not complete else 'exceeded' if total_tokens>budget.get('maxObservedTokensPerTrial',20000) or provider_calls>budget.get('maxCallsPerTrial',6) else 'within')
        jobs.append({'taskId':result.get('taskId'), 'state':job['state'],'qualityVerdict':result.get('qualityVerdict'),
                     'reconciledBudgetStatus':budget_status,
                     'checks':result.get('checks'), 'artifacts':result.get('artifacts'),
                     'jobReceiptSha256':hashlib.sha256(job_file.read_bytes()).hexdigest(),
                     'completionAttempts':len(calls),'providerCalls':provider_calls,
                     'totalTokens':total_tokens,
                     'estimatedCostUsd':sum(c['usage']['estimatedCostUsd'] for c in calls) if cost_known else None,
                     'knownEstimatedCostUsd':sum(c.get('usage',{}).get('estimatedCostUsd',0) for c in calls),
                     'calls':calls, 'costComplete':cost_known})
    return {'runName':root.name, 'jobs':jobs}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run-root',type=Path,action='append',required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if len({r.resolve() for r in a.run_root})!=len(a.run_root):p.error('duplicate runs')
    report={'schemaVersion':'paw.micro-selfboot-reconciled.v1','authority':'exact Pi transcript turn binding',
            'providerBill':False,'selection':'all supplied runs; failures retained in order',
            'runs':[reconcile(root) for root in a.run_root]}
    jobs=[j for r in report['runs'] for j in r['jobs']]
    report['knownEstimatedCostUsd']=sum(j['knownEstimatedCostUsd'] for j in jobs)
    report['costComplete']=all(j['costComplete'] for j in jobs)
    report['knownTokens']=sum(c.get('usage',{}).get('totalTokens',0) for j in jobs for c in j['calls'])
    report['knownProviderCalls']=sum(c.get('providerCalls',0) for j in jobs for c in j['calls'])
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('x') as h:h.write(canonical(report)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='runs'},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
