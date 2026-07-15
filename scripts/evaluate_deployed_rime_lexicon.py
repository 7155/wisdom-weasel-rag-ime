#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_ime.rime_lexicon_eval import evaluate_librime_probe, load_rime_lexicon_eval


DEFAULT_FIXTURE = ROOT / "dataset" / "rime_lexicon_eval.v1.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate the deployed standalone librime candidate order")
    parser.add_argument("--fixture", default=str(DEFAULT_FIXTURE))
    parser.add_argument("--probe-script", default=str(ROOT / "scripts" / "probe_deployed_librime_candidates.sh"))
    parser.add_argument("--probe-output", default="", help="Offline TSV replay instead of invoking deployed librime")
    parser.add_argument("--report", default="")
    args = parser.parse_args(argv)

    try:
        fixture = load_rime_lexicon_eval(args.fixture)
        cases = fixture["cases"]
        if args.probe_output:
            output = Path(args.probe_output).read_text(encoding="utf-8")
        else:
            env = dict(os.environ)
            env["RAG_IME_RIME_EXPECT_FIRST_CANDIDATE"] = ""
            result = subprocess.run(
                [args.probe_script, *[str(case["input"]) for case in cases]],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or f"probe exited {result.returncode}")
            output = result.stdout
        report = evaluate_librime_probe(fixture, output)
    except (FileNotFoundError, json.JSONDecodeError, RuntimeError, subprocess.TimeoutExpired, ValueError) as exc:
        report = {"schemaVersion": "rag-ime.rime-lexicon-eval-report.v1", "ok": False, "error": str(exc)}

    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.report:
        Path(args.report).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
