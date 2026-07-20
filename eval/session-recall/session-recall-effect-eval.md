# Session Recall Effect Evaluation

This evaluation exercises the same normalized vector blend used by the hybrid
retriever. It is intentionally task-labeled rather than a generic relevance
benchmark.

| User / summary weight | Useful hits | Forgetting recovery | Wrong old topic | Cross-scope leak | Irrelevant injection |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1.0 / 0.0 | 4 | 0 | 0 | 0 | 2 |
| 0.9 / 0.1 | 4 | 0 | 0 | 0 | 2 |
| **0.8 / 0.2** | **6** | **2** | **0** | **0** | **0** |
| 0.7 / 0.3 | 2 | 2 | 4 | 0 | 4 |
| 0.5 / 0.5 | 2 | 2 | 4 | 0 | 4 |

Selected policy: Session start does not blend old assistant prose. After a
successful compaction, the latest user request plus explicit task objective is
the 0.8 primary vector and the Pi compaction summary is a 0.2 vector-only hint.
The summary is not a lexical query and is not promoted into long-term memory.

Machine-readable evidence is in `session-recall-effect-receipt.v1.json`. The
runtime policy pins its SHA-256 so a changed receipt cannot silently justify the
same production weight.
