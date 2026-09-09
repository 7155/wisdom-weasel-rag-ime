# Agent execution reliability

The fault matrix exercises task/attempt identity, idempotent dispatch, Worker
leases, process recovery, cancellation, and late-result handling. It uses local
processes, SQLite, loopback networking, and controlled failure fixtures.

Run from the repository root:

```bash
python3 scripts/check_agent_execution_fault_matrix.py
```

The checker reports the results of the current source tests. Passing this matrix
does not establish remote deployment behavior, Provider availability, or native
foreground acceptance. Implementation plans and historical acceptance diaries
are maintained locally.
