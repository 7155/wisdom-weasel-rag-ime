#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from rag_ime.room_release_gate import stage_room_v2_canary


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage the Room V2 canary gate without touching formal installs")
    parser.add_argument("--product-root", type=Path, required=True)
    parser.add_argument("--pi-root", type=Path, required=True)
    parser.add_argument("--source-db", type=Path, required=True)
    parser.add_argument("--frontend-dist", type=Path, required=True)
    parser.add_argument("--pi-build", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = stage_room_v2_canary(product_root=args.product_root, pi_root=args.pi_root, source_db=args.source_db,
        frontend_dist=args.frontend_dist, output_dir=args.output, pi_build=args.pi_build)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["productionCanaryEligible"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
