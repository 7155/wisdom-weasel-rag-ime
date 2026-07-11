# Third-Party Notices

This file records the current dependency and reference boundaries. It is not a
substitute for legal review. Before distributing a release, pin every shipped
version, include the corresponding upstream license text, and verify that the
release bundle satisfies each license.

The release gate also requires `rag-ime.release-manifest.v1` evidence for the
exact `THIRD_PARTY_NOTICES.md` digest and the patched-Squirrel corresponding
source archive. A notice filename or product-status boolean is not treated as
proof: the manifest-listed files must exist and their SHA-256 values must match.

## Modified Or Linked Components

| Project | Use in this repository | Version / source | License boundary |
| --- | --- | --- | --- |
| [Squirrel](https://github.com/rime/squirrel) | The production macOS route applies `squirrel-patches/0001-add-rag-ime-sidecar.patch` and can distribute a modified Squirrel binary. | Commit `2158538` | GPL-3.0. Distribution of the patched source or binary must satisfy the GPL, including source-availability and notice obligations. |
| [librime](https://github.com/rime/librime) | Rime engine linked by the pinned Squirrel checkout. | Commit `33e78140250125871856cdc5b42ddc6a5fcd3cd4` in the pinned checkout | BSD 3-Clause in the upstream `LICENSE`; retain its notices when distributing binaries. |
| [MiniMind](https://github.com/jingyaogong/minimind) | Architecture and training baseline for the project-specific completion checkpoint. No upstream or local weights are committed here. | Obtain separately | Apache-2.0 covers upstream code. A custom checkpoint and training corpus need their own provenance and artifact license. |
| [MLX](https://github.com/ml-explore/mlx) / [MLX-LM](https://github.com/ml-explore/mlx-lm) | Optional local Apple Silicon inference runtime installed separately. | Not vendored | Both are MIT upstream. Preserve their notices if a packaged release redistributes either runtime. |
| [Ollama](https://github.com/ollama/ollama) / [llama.cpp](https://github.com/ggml-org/llama.cpp) | Optional externally managed loopback model servers. | Not vendored | Both are MIT upstream. No binaries are redistributed by the current source tree. |

## Design And Interaction References

These projects informed design study or interaction expectations. They are not
runtime dependencies and their names do not imply endorsement.

- [Wisdom-Weasel](https://github.com/Felix3322/Wisdom-Weasel): GPL-3.0
  prediction and candidate-lifecycle reference. No source file is intentionally
  copied into this repository.
- [VCPToolBox](https://github.com/lioensky/VCPToolBox): memory/RAG and context
  injection study. No VCP service is required. The upstream project states
  CC BY-NC-SA 4.0; do not copy its material into a differently licensed release
  without reviewing those terms.
- [OpenLess](https://github.com/Open-Less/openless): MIT voice-pipeline and
  push-to-talk architecture reference. No OpenLess source is intentionally
  copied.
- [LazyTyper releases](https://github.com/oldcai/LazyTyper-releases): interaction
  reference only. The linked repository is a binary release channel and does
  not establish an open-source license for reusable code.

## Remote Service

[Volcengine Doubao streaming ASR 2.0](https://docs.volcengine.com/docs/6561/1354869?lang=zh)
is an optional remote speech-recognition service. Audio leaves the Mac only
during an explicit voice session. Users are responsible for the provider's
terms, privacy policy, credentials, and charges.

The optional Notion Worker / Custom Agent integration is also a remote-service
workflow. The template in this repository is project-authored; users remain
responsible for Notion's current platform and service terms.
