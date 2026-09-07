"""App-owned job scheduling over registered scene adapters, not an Agent loop.

One Application owns a trial database at a time. On replacement construction,
unsettled jobs become interrupted. Neither replay, read nor run_job restarts
them. Adapters must return only after actual execution and cleanup settle;
their publicSpec/progress/report must be safe for the authenticated App API.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Protocol

from .trials import AgentLabTrialStore, TERMINAL_STATES


class AgentLabTrialExecutionInterrupted(RuntimeError):
    """The original execution is uncertain; inspect it without admitting a retry."""


class TrialObserver(Protocol):
    def progress(self, message: str) -> None: ...
    def bind_session(self, session_id: str, turn_id: str = "", cancel: Callable[[], object] | None = None) -> None: ...


class TrialAdapter(Protocol):
    def prepare(self, spec: Mapping, job_id: str) -> Mapping: ...
    def execute(self, private_input: Mapping, observer: TrialObserver, cancelled: Callable[[], bool]) -> Mapping: ...


@dataclass
class _Run:
    job_id: str
    stop: threading.Event = field(default_factory=threading.Event)
    done: threading.Event = field(default_factory=threading.Event)
    condition: threading.Condition = field(default_factory=lambda: threading.Condition(threading.RLock()))
    hooks: dict[tuple[str, str], Callable] = field(default_factory=dict)
    called: set[tuple[str, str]] = field(default_factory=set)
    hooks_inflight: int = 0
    interrupted: bool = False
    settled: bool = False


class _Observer:
    def __init__(self, app: AgentLabTrialApplication, run: _Run):
        self.app, self.run = app, run

    def progress(self, message: str) -> None:
        self.app.store.progress(self.run.job_id, message)

    def bind_session(self, session_id: str, turn_id: str = "", cancel: Callable[[], object] | None = None) -> None:
        if cancel is not None and not callable(cancel):
            raise ValueError("cancel must be a callable abort hook")
        with self.run.condition:
            if self.run.settled:
                return
            self.app.store.bind_session(self.run.job_id, session_id, turn_id)
            if cancel is not None:
                self.run.hooks[(session_id, turn_id)] = cancel
        if self.run.stop.is_set():
            self.app._abort(self.run)


class AgentLabTrialApplication:
    def __init__(self, store: AgentLabTrialStore, adapters: Mapping[str, TrialAdapter], *, start_workers: bool = True, max_workers: int = 2):
        if type(max_workers) is not int or not 1 <= max_workers <= 8:
            raise ValueError("max_workers must be between 1 and 8")
        self.store = store
        self.adapters = dict(adapters)
        if any(not callable(getattr(adapter, "prepare", None)) or not callable(getattr(adapter, "execute", None)) for adapter in self.adapters.values()):
            raise ValueError("Every scene adapter must provide prepare and execute")
        self._lock = threading.RLock()
        self._active: dict[str, _Run] = {}
        self._closed = False
        self._close_done = threading.Event()
        self.store.recover_interrupted()
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="paw-lab-trial") if start_workers else None

    def read(self, job_id: str = "") -> dict:
        return self.store.read(job_id)

    def start(self, client_request_id: str, scene_id: str, spec: Mapping) -> dict:
        with self._lock:
            if self._closed:
                raise RuntimeError("Lab trial application is closed")
            def prepare(request_spec, job_id):
                adapter = self.adapters.get(scene_id)
                if adapter is None:
                    raise ValueError("Scene has no registered execution adapter")
                return adapter.prepare(request_spec, job_id)

            # Persisted identity is checked before adapter availability: a
            # removed adapter cannot block replay or disguise an input conflict.
            admitted = self.store.admit(client_request_id, scene_id, spec, prepare)
            # Replayed admission never becomes permission to retry execution.
            if not admitted["replayed"] and self._pool is not None:
                job_id = admitted["job"]["jobId"]
                try:
                    self._pool.submit(self.run_job, job_id)
                except RuntimeError:
                    settled = self._finish(job_id, "interrupted", error="Worker scheduling failed; this admission will not be retried automatically.")
                    admitted = {**settled, "replayed": False}
            return admitted

    def run_job(self, job_id: str) -> dict:
        with self._lock:
            if self._closed or job_id in self._active:
                return self.read(job_id)
            data = self.store.claim(job_id)
            if data is None:
                return self.read(job_id)
            run = _Run(job_id)
            self._active[job_id] = run
        state, result, error = "completed", None, ""
        try:
            if run.stop.is_set():
                state = "cancelled"
            else:
                adapter = self.adapters[data["job"]["sceneId"]]
                result = adapter.execute(data["privateInput"], _Observer(self, run), run.stop.is_set)
                if not isinstance(result, Mapping):
                    raise ValueError("Scene adapter must return an actual report mapping")
                state = result.get("status", "completed")
                if not isinstance(state, str) or state not in TERMINAL_STATES:
                    raise ValueError("Scene report execution status must be terminal")
                if state == "interrupted":
                    with run.condition:
                        run.interrupted = True
        except BaseException as exc:
            # Never publish arbitrary exception text: it can include private
            # input, host paths, raw model output or credentials.
            uncertain = isinstance(exc, (AgentLabTrialExecutionInterrupted, TimeoutError, ConnectionError, OSError, KeyboardInterrupt, SystemExit)) or getattr(exc, "interrupted", False)
            if uncertain:
                with run.condition:
                    run.interrupted = True
            state, result = "interrupted" if uncertain else "failed", None
            error = "Execution settlement is uncertain; inspect the original bindings. No automatic retry." if uncertain else "Scene execution failed; inspect the original execution records."
        finally:
            try:
                with run.condition:
                    while run.hooks_inflight:
                        run.condition.wait()
                    failure_report = result if isinstance(result, Mapping) and result.get("status") in {"failed", "cancelled", "interrupted"} else None
                    if run.interrupted:
                        state, result, error = "interrupted", failure_report, "Execution was interrupted; inspect original bindings. Resume is unavailable."
                    elif run.stop.is_set():
                        state, result, error = "cancelled", failure_report, ""
                    # Completing the adapter also means its cleanup is done.
                    # Holding this lock closes the late-abort registration race.
                    try:
                        self._finish(job_id, state, result=result, error=error)
                    except (ValueError, TypeError):
                        self._finish(job_id, "failed", error="Scene report is not a valid JSON mapping.")
                    run.settled = True
            finally:
                with self._lock:
                    self._active.pop(job_id, None)
                run.done.set()
        return self.read(job_id)

    def _finish(self, job_id: str, state: str, **kwargs) -> dict:
        # The adapter has settled. Retrying the same idempotent receipt write
        # cannot repeat a Provider call or change a terminal result. SQLite's
        # connection timeout may still end in a transient busy/IO failure.
        for attempt in range(3):
            try:
                return self.store.finish(job_id, state, **kwargs)
            except (sqlite3.OperationalError, OSError):
                if attempt == 2:
                    raise
                time.sleep(0.05 * (attempt + 1))
        raise AssertionError("unreachable trial persistence retry")

    def _abort(self, run: _Run) -> None:
        with run.condition:
            if run.settled:
                return
            hooks = [(key, hook) for key, hook in run.hooks.items() if key not in run.called]
            run.called.update(key for key, _ in hooks)
            run.hooks_inflight += len(hooks)
        for _, hook in hooks:
            try:
                hook()
            except BaseException:
                with run.condition:
                    run.interrupted = True
            finally:
                with run.condition:
                    run.hooks_inflight -= 1
                    run.condition.notify_all()

    def cancel(self, job_id: str) -> dict:
        with self._lock:
            response = self.store.request_cancel(job_id)
            run = self._active.get(job_id)
            if run is not None and response["job"]["state"] not in TERMINAL_STATES:
                with run.condition:
                    run.stop.set()
                    # Reserve callbacks under the same lock as stop; _abort
                    # invokes them outside it, with inflight accounting.
                    self._reserve_abort(run)
            else:
                run = None
        if run is not None:
            self._invoke_reserved(run)
        return self.read(job_id)

    def _reserve_abort(self, run: _Run) -> None:
        # A reserved no-op blocks terminalization until _abort has registered
        # every current callback, closing cancel-vs-execute-return races.
        run.hooks_inflight += 1

    def _invoke_reserved(self, run: _Run) -> None:
        try:
            self._abort(run)
        finally:
            with run.condition:
                run.hooks_inflight -= 1
                run.condition.notify_all()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                already_closing = True
            else:
                already_closing = False
                self._closed = True
                runs = list(self._active.values())
                reserved = []
                for run in runs:
                    with run.condition:
                        if not run.settled:
                            run.interrupted = True
                            run.stop.set()
                            self._reserve_abort(run)
                            reserved.append(run)
        if already_closing:
            self._close_done.wait()
            return
        try:
            for run in reserved:
                self._invoke_reserved(run)
            for run in runs:
                run.done.wait()
            if self._pool is not None:
                self._pool.shutdown(wait=True, cancel_futures=True)
            self.store.recover_interrupted()
        finally:
            self._close_done.set()
