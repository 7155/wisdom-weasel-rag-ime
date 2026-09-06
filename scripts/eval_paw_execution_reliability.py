#!/usr/bin/env python3
"""Measure actual Lab admission/cancel/restart effects with an isolated DB.

Provider work is simulated; the real TrialApplication/TrialStore own lifecycle.
Timing measures cancel request to persisted terminal, not whole unittest time.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import statistics
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rag_ime.agent_lab_trial_execution import AgentLabTrialApplication
from rag_ime.agent_lab_trials import AgentLabTrialStore


class EffectAdapter:
    def __init__(self, path):
        self.path = path
        self.entered = threading.Event()
        self.release = threading.Event()
        self.aborted = threading.Event()
        self.abort_count = 0
        self.executions = 0
        self.kind = "normal"

    def prepare(self, spec, job_id):
        return {"publicSpec":dict(spec), "privateInput":dict(spec)}

    def abort(self):
        self.abort_count += 1
        self.aborted.set()

    def execute(self, spec, observer, cancelled):
        self.executions += 1
        if self.kind in {"cancel_running", "cancel_late_bind"}:
            if self.kind == "cancel_running":
                observer.bind_session("fixture-session", spec["key"], cancel=self.abort)
            self.entered.set()
            if not self.release.wait(3):
                raise TimeoutError("fixture release missing")
            if self.kind == "cancel_late_bind":
                observer.bind_session("fixture-session", spec["key"], cancel=self.abort)
            if not self.aborted.wait(3):
                raise TimeoutError("actual cancel hook missing")
            # Deliberate late success must be suppressed by the real owner.
            return {"status":"completed", "qualityVerdict":"keep"}
        with sqlite3.connect(self.path) as conn:
            conn.execute("INSERT INTO effects(request_key) VALUES (?)", (spec["key"],))
        if self.kind == "interrupted_after_write":
            raise ConnectionError("simulated lost result after committed effect")
        return {"status":"completed", "qualityVerdict":"keep"}


def evaluate(root, repeats=20):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = root / "trial.sqlite"
    effects = root / "effects.sqlite"
    with sqlite3.connect(effects) as conn:
        # No uniqueness constraint: a duplicate execution would remain visible.
        conn.execute("CREATE TABLE effects(id INTEGER PRIMARY KEY, request_key TEXT NOT NULL)")
    store = AgentLabTrialStore(db)
    rows = []
    kinds = ("concurrent_admission", "lost_ack_replay", "cancel_queued", "cancel_running",
             "cancel_late_bind", "interrupted_after_write", "restore_completed", "restart_before_execution")
    for kind in kinds:
        for repeat in range(repeats):
            adapter = EffectAdapter(effects)
            adapter.kind = kind
            app = AgentLabTrialApplication(store, {"fault":adapter}, start_workers=False)
            key = f"{kind}:{repeat}"
            request = {"key":key}
            cancel_ms = recovery_ms = None
            before_restart_state = None
            thread = None
            expected_effects = 0 if kind in {"cancel_queued", "cancel_running", "cancel_late_bind", "restart_before_execution"} else 1
            expected_state = ("cancelled" if kind.startswith("cancel_") else "interrupted"
                              if kind in {"restart_before_execution", "interrupted_after_write"} else "completed")
            try:
                if kind == "concurrent_admission":
                    with ThreadPoolExecutor(max_workers=4) as pool:
                        responses = list(pool.map(lambda _, app=app, key=key, request=request:app.start(key,"fault",request),range(4)))
                    ids = {r["job"]["jobId"] for r in responses}
                    job_id = responses[0]["job"]["jobId"]
                    with ThreadPoolExecutor(max_workers=4) as pool:
                        list(pool.map(lambda _, app=app, job_id=job_id:app.run_job(job_id),range(4)))
                    identity_ok = len(ids) == 1
                else:
                    if kind == "restart_before_execution":
                        app.close()
                        original = store.admit(key,"fault",request,adapter.prepare)
                    else:
                        original = app.start(key,"fault",request)
                    job_id = original["job"]["jobId"]
                    identity_ok = True
                    if kind == "cancel_queued":
                        started = time.perf_counter_ns()
                        app.cancel(job_id)
                        app.run_job(job_id)
                        cancel_ms = (time.perf_counter_ns()-started)/1e6
                    elif kind in {"cancel_running", "cancel_late_bind"}:
                        thread = threading.Thread(target=app.run_job,args=(job_id,))
                        thread.start()
                        if not adapter.entered.wait(3):
                            raise RuntimeError("fixture never entered execution")
                        started = time.perf_counter_ns()
                        app.cancel(job_id)
                        adapter.release.set()
                        thread.join(3)
                        if thread.is_alive():
                            raise RuntimeError("cancel did not settle")
                        # Include durable readback in the requested cancel latency.
                        app.read(job_id)
                        cancel_ms = (time.perf_counter_ns()-started)/1e6
                    elif kind == "restart_before_execution":
                        # Close the old owner before constructing the exact
                        # persisted crash point, so close() cannot pre-recover
                        # it outside the measured replacement interval.
                        if store.claim(job_id) is None:
                            raise RuntimeError("crash fixture did not reach a running claim")
                    else:
                        app.run_job(job_id)
                    if kind in {"restore_completed", "restart_before_execution", "interrupted_after_write"}:
                        before_restart_state = app.read(job_id)["job"]["state"]
                        app.close()
                        started = time.perf_counter_ns()
                        app = AgentLabTrialApplication(store,{"fault":adapter},start_workers=False)
                        replay = app.start(key,"fault",request)
                        identity_ok = replay["replayed"] and replay["job"]["jobId"] == job_id
                        app.run_job(job_id)
                        app.read(job_id)
                        recovery_ms = (time.perf_counter_ns()-started)/1e6
                    elif kind == "lost_ack_replay":
                        # The caller discards the first return and retries its
                        # exact stable request identity after the effect exists.
                        replay = app.start(key,"fault",request)
                        identity_ok = replay["replayed"] and replay["job"]["jobId"] == job_id
                        app.run_job(job_id)
                job = app.read(job_id)["job"]
                with sqlite3.connect(effects) as conn:
                    count = conn.execute("SELECT count(*) FROM effects WHERE request_key=?",(key,)).fetchone()[0]
                late_success_suppressed = job["result"] is None if kind in {"cancel_running", "cancel_late_bind"} else True
                abort_ok = adapter.abort_count == 1 if kind in {"cancel_running", "cancel_late_bind"} else adapter.abort_count == 0
                rows.append({"scenario":kind,"repeat":repeat+1,"jobId":job_id,"state":job["state"],
                    "expectedState":expected_state,"sideEffects":count,"expectedSideEffects":expected_effects,
                    "duplicateSideEffects":max(0,count-expected_effects),"adapterExecutions":adapter.executions,
                    "abortHookCalls":adapter.abort_count,"identityPreserved":identity_ok,
                    "lateSuccessSuppressed":late_success_suppressed,"cancelToTerminalMs":cancel_ms,
                    "beforeRestartState":before_restart_state,
                    "restoreToReadbackMs":recovery_ms,"passed":identity_ok and count==expected_effects
                    and job["state"]==expected_state and late_success_suppressed and abort_ok})
            finally:
                adapter.release.set()
                if thread is not None:thread.join(3)
                app.close()
        print(kind, sum(r["passed"] for r in rows if r["scenario"]==kind),"/",repeats,flush=True)
    def latency(field):
        values=sorted(r[field] for r in rows if r[field] is not None)
        if not values:return None
        import math
        return {"samples":len(values),"medianMs":statistics.median(values),"maxMs":max(values),
                "p95Ms":values[math.ceil(.95*len(values))-1],"method":"nearest_rank"}
    report={"schemaVersion":"paw.execution-reliability-metrics.v1","scenarios":len(kinds),"observations":len(rows),
            "passed":sum(r["passed"] for r in rows),"duplicateSideEffects":sum(r["duplicateSideEffects"] for r in rows),
            "cancelToTerminal":latency("cancelToTerminalMs"),"restoreToReadback":latency("restoreToReadbackMs"),
            "rows":rows,"providerCalls":0,"syntheticBusinessEffect":True,
            "boundary":"real Lab owner + SQLite; in-process restart and caller ACK loss, no network packet loss or native UI claim",
            "sourceHashes":{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
                (Path(__file__),ROOT/"rag_ime/agent_lab_trials.py",ROOT/"rag_ime/agent_lab_trial_execution.py")}}
    (root/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    return report


def main():
    os.umask(0o077)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root",type=Path,required=True)
    parser.add_argument("--repeats",type=int,default=20)
    args=parser.parse_args()
    root=args.output_root.expanduser().resolve()
    if root.exists() or root.is_relative_to(ROOT) or not 1<=args.repeats<=30:
        parser.error("new private root outside repo and repeats 1..30 required")
    result=evaluate(root,args.repeats)
    print(json.dumps({k:v for k,v in result.items() if k not in {"rows","sourceHashes"}},ensure_ascii=False))
    return 0 if result["passed"]==result["observations"] else 1


if __name__=="__main__":raise SystemExit(main())
