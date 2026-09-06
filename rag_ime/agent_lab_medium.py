"""Frozen medium coding task and host-side behavioral acceptance.

Candidate workspaces receive SPEC and smoke examples, never this evaluator.
The host does not repair generated implementations.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

SPEC = '''# Durable Lab event ledger
Build a Python standard-library-only CLI and library. Edit ledger/*.py and
HANDOFF.md; local tests may be added. Do not access other workspaces, networks,
external packages, model credentials or Host evaluation code.

Events are JSON objects: eventId (nonempty string), runId (nonempty string),
jobId (nonempty string), seq (nonnegative integer; bool is invalid), type and
type-specific fields. Supported types are queued, running, completed, failed,
cancelled, quality, usage. Additional JSON fields must be preserved.

ledger.store.EventStore(path): ingest(list_of_events)->new_count,
events(run_id=None)->list_of_events, close(). Persist to SQLite across processes.
Identity is (runId,eventId). Identical retry is a no-op; changed content for the
same identity raises ValueError. Validate the ENTIRE batch before committing:
malformed input or conflict leaves no partial inserts. Reads sort by runId,
jobId,seq,eventId, optionally filtering runId. Preserve the original objects.
Invalid basic fields/types or unsupported event type raise ValueError.

ledger.report.summarize(events)->list of objects sorted by (runId,jobId):
{runId,jobId,state,executionComplete,qualityPassed,totalTokens,costUsd,costComplete}.
Fold each job by (seq,eventId), independently of input order. State begins
queued; queued/running update it until the FIRST terminal completed/failed/
cancelled. Later execution events never reopen or replace a terminal.
executionComplete is true for any terminal, not just success. qualityPassed is
null until a quality event with passed exactly boolean; latest quality event
wins, including after execution completes. A quality event never changes state.
Usage events have tokens (nonnegative int) and optional costUsd (nonnegative
finite number excluding bool). Sum valid tokens; no usage means tokens 0,
costUsd null, costComplete false. Any usage with missing/invalid cost makes
aggregate costUsd null and costComplete false; otherwise sum costs. Invalid
tokens raise ValueError rather than silently undercount. No cross-run/job leaks.

CLI: python -m ledger.cli import --db PATH --input JSONL
prints one JSON object {inserted:N}. Blank lines ignored. Parse and validate all
lines before writing; errors exit nonzero and leave DB unchanged.
CLI: python -m ledger.cli export --db PATH [--run RUN]
prints one JSON array from summarize. Empty DB exports []. No debug text on stdout.

Work in the current authorized workspace. Save concise HANDOFF.md with API,
completed work, tests run, risks and next step. Do not claim checks you did not run.
'''

UPDATE = '''# Continuation requirement (v2)
Keep all v1 behavior and public APIs. A usage event may now carry callId.
Within one (runId,jobId), identical usage payloads (tokens,costUsd) with the same
nonempty string callId represent the same Provider call: count once despite
different eventId/seq. Conflicting payloads for a repeated callId raise ValueError.
Different jobs/runs do NOT share call identity. Missing callId means an independent
legacy usage event; empty or non-string callId raises ValueError. Unknown cost
still propagates. Do not deduplicate ordinary state or quality updates by callId.

Resume the existing checkpoint.sqlite; do not delete or reconstruct it. Import
continuation.jsonl with the CLI, then import the same file again: second inserted
count must be 0. Export the resulting full DB with the CLI into final.json.
Final output must preserve prior jobs and reflect the new usage/quality events.
Finish all modules, run your tests, and update HANDOFF.md. No further stage follows.
'''

SEED = {
    'AGENTS.md':'This is an authorized, source-isolated coding task. Read SPEC.md. Only modify this workspace. Implement and test; record a truthful HANDOFF.md. No network, packages, extra agents or commits.\n',
    'SPEC.md':SPEC,
    'ledger/__init__.py':'"""Durable Lab event ledger."""\n',
    'ledger/store.py':'class EventStore:\n    def __init__(self, path):\n        raise NotImplementedError("implement SQLite event storage")\n    def ingest(self, events):\n        raise NotImplementedError\n    def events(self, run_id=None):\n        raise NotImplementedError\n    def close(self):\n        raise NotImplementedError\n',
    'ledger/report.py':'def summarize(events):\n    raise NotImplementedError("implement event fold")\n',
    'ledger/cli.py':'def main():\n    raise NotImplementedError("implement CLI")\n\nif __name__ == "__main__":\n    main()\n',
    'HANDOFF.md':'# Handoff\nNo implementation yet.\n',
    'smoke.py':'''import tempfile
from ledger.store import EventStore
from ledger.report import summarize
with tempfile.TemporaryDirectory() as d:
 s=EventStore(d+'/events.db')
 event={'eventId':'e1','runId':'demo','jobId':'j','seq':0,'type':'queued'}
 assert s.ingest([event])==1
 assert s.ingest([event])==0
 assert summarize(s.events())[0]['state']=='queued'
 s.close()
print('smoke passed')
''',
}

def event(eid,kind,seq=0,run='r1',job='j1',**extra):
    return dict(eventId=eid,runId=run,jobId=job,seq=seq,type=kind,**extra)

CHECKPOINT = [event('q','queued'),event('r','running',1),event('u','usage',2,tokens=120,costUsd=.02,callId='c1'),event('c','completed',3),event('quality','quality',4,passed=False),event('q2','queued',run='r2',job='j2')]
CONTINUATION = [event('u-replay','usage',5,tokens=120,costUsd=.02,callId='c1'),event('u-new','usage',6,tokens=30,costUsd=.01,callId='c2'),event('quality-new','quality',7,passed=True),event('late','running',8),event('done2','cancelled',1,run='r2',job='j2')]

def task_seed(storage_format='sqlite'):
    if storage_format not in {'sqlite','jsonl'}:raise ValueError('unsupported storage format')
    if storage_format=='sqlite':return dict(SEED)
    return {name:text.replace('Persist to SQLite across processes.',
        'Persist as UTF-8 JSON Lines across processes, one original event object per line.\n'
        'Use Python file operations and atomic replacement for an all-or-nothing batch.\n'
        'No SQLite, binary database, database libraries or protected database files.\n'
        'This single-writer task requires durable close/reopen, not concurrent writers.').replace(
        'implement SQLite event storage','implement durable JSON Lines event storage').replace('--db','--store').replace(
        'events.db','events.jsonl') for name,text in SEED.items()}

def checkpoint_name(storage_format='sqlite'):
    return 'checkpoint.jsonl' if storage_format=='jsonl' else 'checkpoint.sqlite'

def task_update(storage_format='sqlite'):
    return UPDATE.replace('checkpoint.sqlite',checkpoint_name(storage_format))

def create_workspace(root,storage_format='sqlite'):
    root=Path(root)
    root.mkdir(parents=True)
    for name,text in task_seed(storage_format).items():
        p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)


# Executed in a clean interpreter outside candidate source. Check outcomes are
# independent contract observations, not independent complete tasks.
HOST_CHECKS = r'''
import contextlib,io,json,math,os,subprocess,sys,tempfile
sys.path.insert(0,sys.argv[1])
from ledger.store import EventStore
from ledger.report import summarize
workspace=sys.argv[1]; phase=sys.argv[2];rows=[]
def e(i,t,seq=0,run='a',job='j',**kw):return dict(eventId=i,type=t,seq=seq,runId=run,jobId=job,**kw)
def check(name,fn):
 try:fn();rows.append({'name':name,'passed':True})
 except Exception as exc:rows.append({'name':name,'passed':False,'error':type(exc).__name__+':'+str(exc)[:240]})
def equal(a,b):
 if a!=b:raise AssertionError(repr(a)+' != '+repr(b))
def raises(fn):
 try:fn()
 except ValueError:return
 raise AssertionError('expected ValueError')
with tempfile.TemporaryDirectory() as d:
 def fresh(name):return EventStore(d+'/'+name+'.sqlite')
 def persistence():
  s=fresh('persist');equal(s.ingest([e('1','queued')]),1);s.close();s=fresh('persist');equal(s.events(),[e('1','queued')]);s.close()
 check('store.persist_and_reopen',persistence)
 def retry():
  s=fresh('retry');v=e('1','queued');s.ingest([v]);equal(s.ingest([v,v]),0);equal(s.events(),[v]);s.close()
 check('store.identical_retries',retry)
 def scoping():
  s=fresh('scope');s.ingest([e('same','queued',run='b'),e('same','queued')]);equal(len(s.events()),2);equal(s.events('b'),[e('same','queued',run='b')]);s.close()
 check('store.run_scope',scoping)
 def atomic_conflict():
  s=fresh('conflict');s.ingest([e('old','queued')]);raises(lambda:s.ingest([e('new','running'),e('old','failed')]));equal(s.events(),[e('old','queued')]);s.close()
 check('store.atomic_conflict',atomic_conflict)
 def malformed():
  for i,bad in enumerate([e('x','unknown'),e('x','queued',seq=True),e('x','queued',seq=-1),e('','queued')]):
   s=fresh('bad'+str(i));raises(lambda:s.ingest([e('good','queued'),bad]));equal(s.events(),[]);s.close()
 check('store.atomic_invalid_batch',malformed)
 def ordering():
  s=fresh('order');v=[e('z','queued',3),e('a','running',2,extra={'keep':1}),e('b','queued',2)];s.ingest(v);equal(s.events(),[v[1],v[2],v[0]]);s.close()
 check('store.order_and_roundtrip',ordering)
 if phase!='storage':
  def terminal():
   v=[e('q','queued'),e('f','failed',3),e('c','completed',4),e('r','running',8)]
   r=summarize(list(reversed(v)))[0];equal((r['state'],r['executionComplete']),('failed',True))
  check('report.first_terminal_wins',terminal)
  def quality():
   r=summarize([e('q','queued'),e('c','completed',1),e('p','quality',3,passed=False)])[0]
   equal((r['state'],r['executionComplete'],r['qualityPassed']),('completed',True,False))
  check('report.execution_quality_separate',quality)
  check('report.no_usage_unknown',lambda:equal((summarize([e('q','queued')])[0]['costUsd'],summarize([e('q','queued')])[0]['costComplete']),(None,False)))
  def unknown():
   r=summarize([e('u','usage',tokens=12,costUsd=.2),e('v','usage',1,tokens=4)])[0];equal((r['totalTokens'],r['costUsd'],r['costComplete']),(16,None,False))
  check('report.partial_cost_unknown',unknown)
  def invalid_cost():
   for cost in [True,-1,float('nan'),float('inf'),'0.2']:
    r=summarize([e('u','usage',tokens=2,costUsd=cost)])[0];equal((r['costUsd'],r['costComplete']),(None,False))
  check('report.invalid_cost_unknown',invalid_cost)
  check('report.invalid_tokens_rejected',lambda:raises(lambda:summarize([e('u','usage',tokens=True,costUsd=.1)])))
  def sums():
   r=summarize([e('u','usage',tokens=10,costUsd=.1),e('v','usage',1,tokens=20,costUsd=.2)])[0];equal(r['totalTokens'],30);equal(r['costComplete'],True);assert abs(r['costUsd']-.3)<1e-8
  check('report.full_usage_sum',sums)
  def split_jobs():
   r=summarize([e('x','completed',run='b'),e('y','cancelled',job='other'),e('z','running')]);equal([(x['runId'],x['jobId'],x['state']) for x in r],[('a','j','running'),('a','other','cancelled'),('b','j','completed')])
  check('report.job_isolation',split_jobs)
  def cli(args):
   p=subprocess.run([sys.executable,'-m','ledger.cli',*args],cwd=workspace,capture_output=True,text=True,timeout=8)
   return p.returncode,p.stdout,p.stderr
  def cli_cycle():
   path=d+'/events.jsonl';open(path,'w').write(json.dumps(e('q','queued'))+'\n\n');db=d+'/cli.db'
   code,out,err=cli(['import','--db',db,'--input',path]);equal(code,0);equal(json.loads(out),{'inserted':1})
   code,out,err=cli(['import','--db',db,'--input',path]);equal(json.loads(out),{'inserted':0})
   code,out,err=cli(['export','--db',db,'--run','a']);equal(code,0);equal(json.loads(out)[0]['state'],'queued')
  check('cli.import_replay_export',cli_cycle)
  def cli_atomic():
   path=d+'/bad.jsonl';open(path,'w').write(json.dumps(e('valid','queued'))+'\n{bad\n');db=d+'/bad.db'
   code,out,err=cli(['import','--db',db,'--input',path]);assert code!=0
   code,out,err=cli(['export','--db',db]);equal(code,0);equal(json.loads(out),[])
  check('cli.invalid_input_atomic',cli_atomic)
 if phase=='final':
  def dedup():
   r=summarize([e('u','usage',tokens=11,costUsd=.2,callId='call'),e('v','usage',1,tokens=11,costUsd=.2,callId='call'),e('w','usage',2,tokens=5,costUsd=.1)])[0]
   equal(r['totalTokens'],16);assert abs(r['costUsd']-.3)<1e-8
  check('update.call_id_dedup_and_legacy',dedup)
  check('update.conflicting_call_rejected',lambda:raises(lambda:summarize([e('u','usage',tokens=1,costUsd=.1,callId='c'),e('v','usage',1,tokens=2,costUsd=.1,callId='c')])))
  def call_scope():
   r=summarize([e('u','usage',tokens=1,costUsd=.1,callId='c'),e('v','usage',tokens=3,costUsd=.2,callId='c',run='b')]);equal([x['totalTokens'] for x in r],[1,3])
  check('update.call_scope',call_scope)
  def invalid_id():
   for value in ['',None,3]:raises(lambda:summarize([e('u','usage',tokens=1,callId=value)]))
  check('update.invalid_call_identity',invalid_id)
print(json.dumps(rows))
'''

def verify_workspace(root,phase,storage_format='sqlite'):
    checks_code=HOST_CHECKS if storage_format=='sqlite' else HOST_CHECKS.replace('.sqlite','.jsonl').replace('.db','.jsonl').replace('--db','--store')
    result=subprocess.run([sys.executable,'-c',checks_code,str(Path(root).resolve()),phase],
                          capture_output=True,text=True,timeout=45,cwd=tempfile.gettempdir())
    try:
        checks=json.loads(result.stdout)
        if result.returncode or not isinstance(checks,list):raise ValueError('host result unavailable')
    except (ValueError,TypeError):
        return {'phase':phase,'passed':0,'total':{'storage':6,'base':16,'final':20}[phase],
                'allPassed':False,'checks':[],'error':result.stderr[-1500:] or result.stdout[-1000:]}
    return {'phase':phase,'passed':sum(c['passed'] for c in checks),'total':len(checks),
            'allPassed':bool(checks) and all(c['passed'] for c in checks),'checks':checks}

def prepare_checkpoint(root,storage_format='sqlite'):
    root=Path(root)
    code=f'import json,sys;from ledger.store import EventStore;s=EventStore({checkpoint_name(storage_format)!r});s.ingest(json.loads(sys.argv[1]));s.close()'
    result=subprocess.run([sys.executable,'-c',code,json.dumps(CHECKPOINT)],cwd=root,capture_output=True,text=True,timeout=15)
    (root/'continuation.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in CONTINUATION))
    (root/'UPDATE.md').write_text(task_update(storage_format))
    return {'prepared':result.returncode==0,'error':result.stderr[-1200:] if result.returncode else ''}

def verify_delivery(root,storage_format='sqlite'):
    # Replay is a write. Verify on a copy so Host checks cannot manufacture a
    # candidate's delivered state or change the artifact for later inspection.
    with tempfile.TemporaryDirectory(prefix='paw-ledger-delivery-') as temporary:
        isolated=Path(temporary)/'candidate'
        shutil.copytree(root,isolated,ignore=shutil.ignore_patterns('__pycache__'))
        return _verify_delivery_copy(isolated,storage_format)

def _verify_delivery_copy(root,storage_format='sqlite'):
    root=Path(root)
    checkpoint=checkpoint_name(storage_format);flag='--store' if storage_format=='jsonl' else '--db'
    expected=[{'runId':'r1','jobId':'j1','state':'completed','executionComplete':True,'qualityPassed':True,'totalTokens':150,'costUsd':.03,'costComplete':True},
              {'runId':'r2','jobId':'j2','state':'cancelled','executionComplete':True,'qualityPassed':None,'totalTokens':0,'costUsd':None,'costComplete':False}]
    checks=[]
    def record(name,fn):
        try:fn();checks.append({'name':name,'passed':True})
        except Exception as exc:checks.append({'name':name,'passed':False,'error':type(exc).__name__+':'+str(exc)[:200]})
    def matching(rows):
        assert len(rows)==2
        for actual,want in zip(rows,expected):
            for key,value in want.items():
                if key=='costUsd' and value is not None:assert abs(actual[key]-value)<1e-8
                else:assert actual[key]==value,(key,actual[key],value)
    record('delivery.final_json',lambda:matching(json.loads((root/'final.json').read_text())))
    def cli_export():
        p=subprocess.run([sys.executable,'-m','ledger.cli','export',flag,checkpoint],cwd=root,capture_output=True,text=True,timeout=10)
        assert p.returncode==0;matching(json.loads(p.stdout))
    record('delivery.persisted_database',cli_export)
    def retained():
        code=f'import json;from ledger.store import EventStore;s=EventStore({checkpoint!r});print(json.dumps(s.events()));s.close()'
        p=subprocess.run([sys.executable,'-c',code],cwd=root,capture_output=True,text=True,timeout=10)
        assert p.returncode==0;rows=json.loads(p.stdout)
        assert all(e in rows for e in CHECKPOINT)
        assert len(rows)==len(CHECKPOINT)+len(CONTINUATION)
        if storage_format=='jsonl':
            lines=[json.loads(line) for line in (root/checkpoint).read_text(encoding='utf-8').splitlines() if line.strip()]
            assert len(lines)==len(rows) and all(e in lines for e in rows)
    record('delivery.original_events_preserved',retained)
    def replay():
        p=subprocess.run([sys.executable,'-m','ledger.cli','import',flag,checkpoint,'--input','continuation.jsonl'],cwd=root,capture_output=True,text=True,timeout=10)
        assert p.returncode==0;assert json.loads(p.stdout)=={'inserted':0};cli_export()
    record('delivery.replay_no_duplicates',replay)
    return {'passed':sum(c['passed'] for c in checks),'total':4,'allPassed':all(c['passed'] for c in checks),'checks':checks}
