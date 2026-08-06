from __future__ import annotations

import json
import os

from .knowledge_embedding_profile import probe_knowledge_embedding_profile


def main() -> int:
    try:
        result = probe_knowledge_embedding_profile({}, environ=os.environ)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "schemaVersion": "rag-ime.knowledge-embedding-probe.v1",
                    "ready": False,
                    "errorCode": "embedding_probe_failed",
                    "errorType": type(exc).__name__,
                    "secretsVisible": False,
                },
                separators=(",", ":"),
            )
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
