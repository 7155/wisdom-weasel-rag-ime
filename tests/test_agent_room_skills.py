from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

import yaml

from rag_ime.agent_room_skills import (
    RoomSkillEpochRevoked,
    RoomSkillPolicy,
    RoomSkillPolicyConflict,
    RoomSkillPolicyStore,
    SkillCatalogRevisionMismatch,
    SkillContentRevisionMismatch,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = REPO_ROOT / "integrations/pi/room-skill-policy.json"
SKILLS_ROOT = REPO_ROOT / "integrations/pi/skills"
GENERAL_WORK_SKILLS = (
    "alignment-and-decision",
    "implementation-execution",
    "improve-codebase-architecture",
    "quality-gate",
)

AGENT_WORKFLOW_SKILLS = (
    "alignment-and-decision",
    "implementation-planning",
    "implementation-execution",
    "test-driven-implementation",
    "systematic-debugging",
    "improve-codebase-architecture",
    "quality-gate",
    "independent-review",
    "structured-handoff",
)


def _frontmatter(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    _empty, raw, _body = text.split("---", 2)
    value = yaml.safe_load(raw)
    if not isinstance(value, dict):
        raise AssertionError(f"invalid frontmatter: {path}")
    return value


class RoomNativeSkillTests(unittest.TestCase):
    def test_general_work_skills_are_bounded_progressive_entries(self) -> None:
        expected_keys = {
            "name",
            "description",
            "when",
            "notFor",
            "input",
            "output",
            "does",
        }

        for skill_id in GENERAL_WORK_SKILLS:
            with self.subTest(skill_id=skill_id):
                path = SKILLS_ROOT / skill_id / "SKILL.md"
                frontmatter = _frontmatter(path)
                body = path.read_text(encoding="utf-8").split("---", 2)[2]
                self.assertEqual(set(frontmatter), expected_keys)
                self.assertEqual(frontmatter["name"], skill_id)
                self.assertTrue(frontmatter["when"])
                self.assertTrue(frontmatter["notFor"])
                routing = {
                    key: frontmatter[key]
                    for key in ("name", "when", "does", "input", "output", "notFor")
                }
                encoded_routing = json.dumps(
                    routing,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                self.assertLessEqual(
                    len(encoded_routing),
                    420,
                    encoded_routing,
                )
                # Full bodies arrive only through skill_load Tool Results. They
                # may be structured enough to guide real work, but stay bounded.
                self.assertLessEqual(len(body.splitlines()), 120)
                self.assertLessEqual(len(body.encode()), 6_000)
                self.assertIn("## Self-Check", body)
                self.assertNotIn("create a Dispatch", body)
                self.assertNotIn("mark work complete", body)

        architecture = (
            SKILLS_ROOT / "improve-codebase-architecture/SKILL.md"
        ).read_text(encoding="utf-8")
        alignment = (SKILLS_ROOT / "alignment-and-decision/SKILL.md").read_text(
            encoding="utf-8"
        )
        planning = (
            SKILLS_ROOT / "implementation-planning/SKILL.md"
        ).read_text(encoding="utf-8")
        execution = (
            SKILLS_ROOT / "implementation-execution/SKILL.md"
        ).read_text(encoding="utf-8")
        continuity_contract = (
            SKILLS_ROOT
            / "implementation-execution/references/execution-continuity-contract.md"
        ).read_text(encoding="utf-8")
        quality = (SKILLS_ROOT / "quality-gate/SKILL.md").read_text(
            encoding="utf-8"
        )
        review = (SKILLS_ROOT / "independent-review/SKILL.md").read_text(
            encoding="utf-8"
        )
        alignment_ui = (
            SKILLS_ROOT / "alignment-and-decision/agents/openai.yaml"
        ).read_text(encoding="utf-8")
        self.assertIn("File size alone is not evidence", architecture)
        self.assertIn("**depth**", architecture)
        self.assertIn("**deletion test**", architecture)
        self.assertIn(
            "reserve Ask for a user-owned choice",
            " ".join(alignment.split()),
        )
        self.assertIn("one smallest question group", alignment)
        self.assertIn("Group 1-4 independent questions", alignment)
        self.assertIn("never rewrites or\nweakens the requirements", alignment)
        self.assertIn("Write a glossary, ADR, or decision record only", alignment)
        self.assertIn(
            "glossary terms need a confirmed meaning",
            " ".join(alignment.casefold().split()),
        )
        self.assertIn("a direct user choice and approved write", alignment)
        self.assertIn("Use the user's language", alignment)
        self.assertIn("Do not dump the packet into the public reply", alignment)
        self.assertIn("use native `ask`", alignment)
        self.assertIn("Original User Request", alignment)
        self.assertIn("Original User Vision", alignment)
        self.assertIn("every AI explanation in a\n  separate", alignment)
        self.assertIn("original request and vision outrank every AI summary", planning)
        self.assertIn("each persisted plan with that block byte-for-byte", planning)
        self.assertIn('display_name: "Align and Decide"', alignment_ui)
        self.assertIn("$alignment-and-decision", alignment_ui)
        self.assertIn("one continuous suite", execution)
        self.assertIn("workflow or work ID", execution)
        self.assertIn("Read only the bounded continuity block", execution)
        self.assertIn("one conditional inner\n  method at a time", execution)
        self.assertIn("red/green loop", execution)
        self.assertIn("The active execution owner writes it", execution)
        self.assertIn("two consecutive attempts", execution)
        self.assertIn("Public updates mention only material behavior", execution)
        self.assertIn("Never create a document per commit or code slice", execution)
        self.assertIn("active lifecycle Tool's exact private", quality)
        self.assertIn("user-facing\n   `publicSummary`", quality)
        self.assertIn("implementation-continuity:start", continuity_contract)
        self.assertIn("implementation-continuity:end", continuity_contract)
        self.assertIn("docs/agent/chat-summary.md", continuity_contract)
        self.assertIn("at most 6", continuity_contract)
        self.assertIn("at most 10", continuity_contract)
        self.assertIn("below 100 lines and 8 KiB", continuity_contract)
        self.assertIn("read only the project index", continuity_contract)
        self.assertIn("Do not read chronological project history", continuity_contract)
        self.assertIn("Only the active implementation owner writes", continuity_contract)
        self.assertIn("One Work Item, One WorkDocument", continuity_contract)
        self.assertIn("Both files are navigation, never authority", continuity_contract)
        self.assertIn("Rewriting unchanged content is a no-op", continuity_contract)
        self.assertNotIn("[Delivery Page]", continuity_contract)
        self.assertNotIn("[Execution Recovery]", continuity_contract)
        self.assertIn("Do not\nmark acceptance complete in these files", continuity_contract)
        self.assertNotIn("promotion service", execution)
        self.assertNotIn("interview_case", execution)
        self.assertNotIn("interview", continuity_contract.casefold())
        self.assertNotIn("面试", execution)
        self.assertIn("The Kernel binds", quality)
        self.assertIn("derives coverage and readiness", quality)
        self.assertIn("human-readable aliases", quality)
        self.assertIn("No completion claim without fresh", quality)
        self.assertIn("Do not send", quality)
        self.assertIn("acceptanceAliases", quality)
        self.assertIn("decision=handoff", quality)
        self.assertIn("do not send", review)
        self.assertIn("acceptanceAliases", review)

    def test_user_owned_room_choices_route_through_room_commit_options(
        self,
    ) -> None:
        skill = (
            SKILLS_ROOT / "alignment-and-decision" / "SKILL.md"
        ).read_text(encoding="utf-8")
        for exact_field in (
            '`decision="wait"`',
            '`waitingFor="user"`',
            '`questionKind="bounded"`',
            '`question="<one prompt>"`',
            "`questionOptions=[...]`",
        ):
            self.assertIn(exact_field, skill)
        self.assertIn("containing 2-5\n  unique options", skill)
        self.assertIn("at most one `recommended`", skill)
        self.assertIn('explicitly use `questionKind="unbounded"`', skill)
        self.assertIn("omit\n  `questionOptions`", skill)
        self.assertIn("rather than inventing choices", skill)
        self.assertIn("not a second\n  question Tool", skill)

    def test_work_document_archive_is_progressive_adapter_not_room_stage(
        self,
    ) -> None:
        skill_id = "work-document-archive"
        path = SKILLS_ROOT / skill_id / "SKILL.md"
        frontmatter = _frontmatter(path)
        body = path.read_text(encoding="utf-8").split("---", 2)[2]
        normalized_body = body.casefold()
        routing_catalog = json.loads(
            (REPO_ROOT / "integrations/pi/skill-routing-cards.json").read_text(
                encoding="utf-8"
            )
        )
        card = next(
            item for item in routing_catalog["cards"] if item["name"] == skill_id
        )

        self.assertEqual(
            set(frontmatter),
            {"name", "description", "when", "notFor", "input", "output", "does"},
        )
        self.assertIn("Operation-specific", frontmatter["input"])
        self.assertIn("untouched backend response", frontmatter["output"])
        self.assertIn("lifecycle owner", frontmatter["description"])
        self.assertTrue(
            any(
                "ownership" in boundary or "归属" in boundary
                for boundary in frontmatter["notFor"]
            )
        )
        projected = {
            key: frontmatter[key]
            for key in ("name", "when", "does", "input", "output", "notFor")
        }
        self.assertEqual(card, projected)
        self.assertNotIn("body", card)
        self.assertLessEqual(
            len(json.dumps(card, ensure_ascii=False, separators=(",", ":"))),
            420,
        )
        self.assertLessEqual(len(body.splitlines()), 120)
        self.assertLessEqual(len(body.encode()), 6_000)

        policy = RoomSkillPolicy(POLICY_PATH, SKILLS_ROOT)
        self.assertNotIn(skill_id, policy.skill_ids)
        self.assertIn("progressively loaded adapter", normalized_body)
        self.assertIn("defaults to non-archived documents", normalized_body)
        self.assertIn(
            "only after the\n   caller explicitly requests archived history",
            normalized_body,
        )
        self.assertIn("terminalreceiptid", normalized_body)
        self.assertIn("canonical owner", normalized_body)
        self.assertIn("this skill does\nnot expose either erase operation", normalized_body)
        self.assertIn("never move, rename, create, or delete", normalized_body)
        self.assertIn("not a mandatory room stage", normalized_body)
        self.assertIn("## Stop Conditions", body)
        self.assertIn("## Boundaries", body)
        self.assertIn("no automatic expiry or deletion\ntimer", normalized_body)

    def test_continuous_suite_preserves_user_source_without_commit_documents(
        self,
    ) -> None:
        alignment = (
            SKILLS_ROOT / "alignment-and-decision/SKILL.md"
        ).read_text(encoding="utf-8")
        planning = (
            SKILLS_ROOT / "implementation-planning/SKILL.md"
        ).read_text(encoding="utf-8")
        execution = (
            SKILLS_ROOT / "implementation-execution/SKILL.md"
        ).read_text(encoding="utf-8")
        continuity = (
            SKILLS_ROOT
            / "implementation-execution/references/execution-continuity-contract.md"
        ).read_text(encoding="utf-8")

        for stage in (alignment, planning, execution):
            self.assertIn("User Source", stage)
            self.assertIn("original request", stage.casefold())
            self.assertIn("vision", stage.casefold())

        source_start = continuity.index("<!-- user-source:start -->")
        request = continuity.index("### Original User Request")
        vision = continuity.index("### Original User Vision")
        corrections = continuity.index("### Later User Corrections")
        interpretation = continuity.index("## AI Interpretation")
        self.assertLess(
            source_start,
            request,
        )
        self.assertLess(request, vision)
        self.assertLess(vision, corrections)
        self.assertLess(corrections, interpretation)
        self.assertIn("The original request and vision are immutable", continuity)
        self.assertIn("Later corrections append", continuity)
        self.assertEqual(continuity.count("UTF-8 SHA-256: <required>"), 2)
        self.assertIn("recheck source hashes", continuity)
        self.assertIn("A commit\nnever creates a WorkDocument", continuity)
        self.assertIn("canonical terminal\n  receipt moves the complete file", continuity)
        self.assertIn("no automatic expiry or deletion", continuity)
        self.assertIn("excluded from default\n  context", continuity)
        self.assertIn("separate user-approved", continuity)

    def test_optimized_skill_contracts_are_explicit_and_bounded(self) -> None:
        skill_text = {
            path.parent.name: path.read_text(encoding="utf-8")
            for path in SKILLS_ROOT.glob("*/SKILL.md")
        }
        alignment = skill_text["alignment-and-decision"]
        work_documents = skill_text["work-document-archive"]
        memory = skill_text["memory-curation"]
        plugins = skill_text["plugin-creator"]
        execution = skill_text["implementation-execution"]
        handoff = skill_text["structured-handoff"]
        feedback = skill_text["review-feedback-resolution"]
        quality = skill_text["quality-gate"]
        independent_review = skill_text["independent-review"]
        for skill_id in (
            "alignment-and-decision",
            "work-document-archive",
            "memory-curation",
            "plugin-creator",
            "implementation-execution",
            "structured-handoff",
            "review-feedback-resolution",
            "quality-gate",
            "independent-review",
        ):
            with self.subTest(skill_id=skill_id):
                routing = _frontmatter(SKILLS_ROOT / skill_id / "SKILL.md")
                self.assertEqual(
                    set(routing),
                    {
                        "name",
                        "description",
                        "when",
                        "does",
                        "input",
                        "output",
                        "notFor",
                    },
                )
                for field in (
                    "description",
                    "when",
                    "does",
                    "input",
                    "output",
                    "notFor",
                ):
                    self.assertTrue(routing[field], f"{skill_id}.{field}")

        self.assertIn("Start an immutable `User Source` block", alignment)
        self.assertIn("Lock the requirements before comparing solutions", alignment)
        self.assertIn(
            "Never turn an inspectable path, owner, failure boundary, or verification result",
            " ".join(alignment.split()),
        )
        self.assertIn(
            "A material user choice changes goal, scope, acceptance, authority, data",
            " ".join(alignment.split()),
        )
        self.assertIn("Write a glossary, ADR, or decision record only", alignment)
        self.assertIn("`ready_for_planning`", alignment)
        self.assertIn("byte-preserved", alignment)

        for row in (
            "| `list` | `limit` and active scope |",
            "| `search` | `query`, `limit`, and explicit `history` scope |",
            "| `get` | `documentRef` |",
            "| `archive` | `documentRef`, `authorityRef`, and `terminalReceiptId` |",
            "| `repair` | `documentRef` and `authorityRef` |",
            "| `reopen` | `documentRef`, `authorityRef`, next `authorityRevision`, and `transitionReceiptId` |",
        ):
            self.assertIn(row, work_documents)
        self.assertIn("untouched backend response or receipt", work_documents)
        self.assertIn("after returning one backend outcome, stop", work_documents)

        self.assertIn("Call `memory`", memory)
        self.assertIn("remember_preview|remember_apply", memory)
        self.assertIn("maintenance_preview|maintenance_review", memory)
        self.assertIn("explanation operations never mutate memory", memory)
        self.assertIn("terminal for this Skill turn", memory)

        self.assertIn("`plugins` with `op=validate`", plugins)
        self.assertIn("exact returned `sourcePath`", plugins)
        for status in (
            "draft_created",
            "validation_failed",
            "proposal_pending_approval",
            "installed",
        ):
            self.assertIn(f"`{status}`", plugins)
        self.assertIn("authoritative install receipt", plugins)
        self.assertIn("never proof that installation occurred", plugins)
        self.assertIn(
            'display_name: "受管插件创建"',
            (
                SKILLS_ROOT / "plugin-creator/agents/openai.yaml"
            ).read_text(encoding="utf-8"),
        )

        execution_routing = _frontmatter(
            SKILLS_ROOT / "implementation-execution/SKILL.md"
        )
        self.assertEqual(
            execution_routing["when"],
            [
                "An accepted plan needs code",
            ],
        )
        self.assertIn("Project scope selects the shared recovery note", execution)
        self.assertIn("return the proposed document delta\nto the caller", execution)

        self.assertIn("eligible under the active\n   lifecycle schema", handoff)
        self.assertIn("prose claims alone are not evidence", handoff)
        self.assertIn("behavioral regression or a focused verifier", feedback)
        self.assertIn("two verified findings share the same invariant class", feedback)
        self.assertIn("third review round", feedback)
        self.assertIn("same state object", feedback)
        self.assertIn("This Skill creates neither", feedback)
        self.assertIn("visibility delta", quality)
        self.assertIn("Missing/degraded behavior", quality)
        self.assertIn("has no authority to set a result or Kernel verdict", quality)
        self.assertIn("verbatim user text supplied by the Runtime", independent_review)

        bundled_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in SKILLS_ROOT.rglob("*")
            if path.is_file()
        )
        self.assertNotIn("ime_memory", bundled_text)
        self.assertNotIn("ime_plugins", bundled_text)
        for forbidden_protocol in ("TOOL_REQUEST", "WorkflowSop", "ROLE_DIVIDE"):
            self.assertNotIn(forbidden_protocol, bundled_text)
        orphan_directories = sorted(
            path.name
            for path in SKILLS_ROOT.iterdir()
            if path.is_dir() and not (path / "SKILL.md").is_file()
        )
        self.assertEqual(orphan_directories, [])

    def test_workflow_skills_preserve_the_behavioral_essence(self) -> None:
        text = {
            name: " ".join(
                (
                    SKILLS_ROOT / name / "SKILL.md"
                ).read_text(encoding="utf-8").casefold().split()
            )
            for name in (
                "alignment-and-decision",
                "implementation-planning",
                "implementation-execution",
                "test-driven-implementation",
                "systematic-debugging",
                "quality-gate",
                "independent-review",
                "structured-handoff",
                "improve-codebase-architecture",
                "review-feedback-resolution",
            )
        }

        alignment = text["alignment-and-decision"]
        self.assertIn("explicit grill mode", alignment)
        self.assertIn("every material decision-tree branch", alignment)
        self.assertIn("including nonblocking tradeoffs", alignment)
        self.assertIn("ask one question at a time", alignment)
        self.assertIn("stop only after the user confirms shared understanding", alignment)
        self.assertIn("domain language delta", alignment)

        planning = text["implementation-planning"]
        self.assertIn("domain language delta, glossary, and adrs", planning)
        self.assertIn("highest stable behavior seam", planning)
        self.assertIn("tracer-bullet candidates", planning)
        self.assertIn("blocking edge", planning)

        execution = text["implementation-execution"]
        self.assertIn("quality-gate -> independent-review", execution)
        self.assertIn("review is optional", execution)
        self.assertIn("facilitator decides whether risk warrants", execution)

        tdd = text["test-driven-implementation"]
        self.assertIn("independent source of truth", tdd)
        self.assertIn("one seam, one test, and one minimal implementation", tdd)
        self.assertIn("do not prewrite horizontal batches", tdd)
        self.assertIn("add speculative behavior, or refactor inside", tdd)
        self.assertIn("tautological expectation", tdd)

        debugging = text["systematic-debugging"]
        self.assertIn("feedback loop gate", debugging)
        self.assertIn("agent-runnable command that goes red", debugging)
        self.assertIn("every remaining input and step is load-bearing", debugging)
        self.assertIn("three to five ranked, falsifiable hypotheses", debugging)
        self.assertIn("do not theorize", debugging)
        self.assertIn("remove temporary instrumentation", debugging)

        quality = text["quality-gate"]
        self.assertIn("matrix is evidence-ready", quality)
        self.assertIn("review is optional", quality)
        self.assertIn("after integration", quality)
        self.assertIn("without manufacturing a review stage", quality)

        review = text["independent-review"]
        self.assertIn("pin one review fixed point", review)
        self.assertIn("requirement fidelity", review)
        self.assertIn("code standards", review)
        self.assertIn("do not merge or rerank findings across axes", review)
        self.assertIn("speculative generality", review)
        self.assertIn("refused bequest", review)

        handoff = text["structured-handoff"]
        self.assertIn("by stable ref instead of copying", handoff)
        self.assertIn("redact credentials, tokens, pii", handoff)

        architecture = text["improve-codebase-architecture"]
        self.assertIn("explicit grill mode", architecture)
        self.assertIn("domain language delta", architecture)

        feedback = text["review-feedback-resolution"]
        self.assertIn("needs_execution", feedback)
        self.assertIn("do not change code here", feedback)
        self.assertIn("bypass execution/tdd or continuity", feedback)

    def test_implementation_planning_gates_durable_state_with_bounded_disclosure(
        self,
    ) -> None:
        path = SKILLS_ROOT / "implementation-planning/SKILL.md"
        frontmatter = _frontmatter(path)
        body = path.read_text(encoding="utf-8").split("---", 2)[2]
        normalized_body = body.casefold()
        collapsed_body = " ".join(normalized_body.split())

        for checklist_item in (
            "stateful-object census",
            "canonical owner",
            "transition table",
            "invariants",
            "crash boundaries",
            "concurrent or duplicate operations",
            "restart/restore/replay",
            "bypass attempts",
        ):
            with self.subTest(checklist_item=checklist_item):
                self.assertIn(checklist_item, normalized_body)

        for planning_rule in (
            "do not grill the user",
            "needs_alignment_decision",
            "return it to `alignment-and-decision`",
            "do not ask or compare options here",
            "planning goes deeper than alignment only to locate executable seams",
            "tracer-bullet candidates",
            "one fresh context window",
            "blocking edges",
            "on the frontier",
            "expand-migrate-contract",
            "publish tracker tickets",
            "write implementation code",
            "do not repeat the\nconfirmed requirements",
            "dump every field unless requested",
            "do not invent a work id between stages",
            "route the accepted plan\nreference and exact acceptance aliases to `implementation-execution`",
        ):
            with self.subTest(planning_rule=planning_rule):
                self.assertIn(" ".join(planning_rule.split()), collapsed_body)
        self.assertNotIn("quiz the user", normalized_body)
        self.assertNotIn("to-tickets", normalized_body)

        routing = {
            key: frontmatter[key]
            for key in ("name", "when", "does", "input", "output", "notFor")
        }
        encoded_routing = json.dumps(
            routing,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        self.assertLessEqual(len(encoded_routing.encode()), 450, encoded_routing)
        self.assertLessEqual(len(body.splitlines()), 120)
        self.assertLessEqual(len(body.encode()), 6_000)
        self.assertNotIn("cat cafe", normalized_body)
        self.assertNotIn("worktree", normalized_body)
        self.assertNotIn("pull request", normalized_body)

    def test_eight_workflow_skills_are_native_pi_skills_with_compact_routing_cards(self) -> None:
        policy = RoomSkillPolicy(POLICY_PATH, SKILLS_ROOT)
        self.assertEqual(policy.skill_ids, AGENT_WORKFLOW_SKILLS)
        expected_keys = {"name", "when", "notFor", "input", "output", "does"}

        self.assertEqual(len(policy.skill_ids), len(AGENT_WORKFLOW_SKILLS))
        self.assertIn("alignment-and-decision", policy.skill_ids)
        self.assertIn("implementation-execution", policy.skill_ids)
        self.assertNotIn("review-feedback-resolution", policy.skill_ids)
        for retired in (
            "requirement-alignment",
            "solution-convergence",
            "grill-me",
            "grill-me-docs",
        ):
            self.assertNotIn(retired, policy.skill_ids)
        for skill_id, routing in zip(policy.skill_ids, policy.catalog(), strict=True):
            with self.subTest(skill_id=skill_id):
                path = SKILLS_ROOT / skill_id / "SKILL.md"
                frontmatter = _frontmatter(path)
                self.assertEqual(frontmatter["name"], skill_id)
                self.assertTrue(frontmatter["description"])
                self.assertTrue(frontmatter["when"])
                self.assertTrue(frontmatter["notFor"])
                self.assertTrue(frontmatter["input"])
                self.assertTrue(frontmatter["output"])
                self.assertTrue(frontmatter["does"])
                self.assertEqual(set(routing), expected_keys)
                loaded = policy.load_exact(skill_id)
                self.assertEqual(loaded["name"], skill_id)
                self.assertIn("## Workflow", loaded["body"])
                self.assertNotIn("body", routing)
                encoded = json.dumps(routing, ensure_ascii=False, separators=(",", ":"))
                self.assertLessEqual(len(encoded.encode()), 450, encoded)
                body = path.read_text(encoding="utf-8").split("---", 2)[2]
                self.assertLessEqual(len(body.encode()), 6_000)
                self.assertIn("## Workflow", body)
                self.assertIn("## Output Contract", body)
                self.assertIn("## Self-Check", body)
                self.assertIn("## Boundaries", body)

    def test_exact_load_adds_only_one_skill_body_and_revision(self) -> None:
        policy = RoomSkillPolicy(POLICY_PATH, SKILLS_ROOT)
        expected_catalog_keys = {"name", "when", "notFor", "input", "output", "does"}

        catalog = policy.catalog()
        loaded = policy.load_exact("structured-handoff")

        self.assertTrue(all(set(item) == expected_catalog_keys for item in catalog))
        self.assertEqual(set(loaded), expected_catalog_keys | {"body", "contentRevision"})
        self.assertIn("## Output Contract", loaded["body"])
        self.assertIn("current model cannot finish", loaded["body"])
        self.assertIn("exact takeover point", loaded["body"])
        self.assertIn("## Private Receiver Packet", loaded["body"])
        self.assertIn("Public report:", loaded["body"])
        self.assertIn("two distinct products", loaded["body"])
        self.assertEqual(len(loaded["contentRevision"]), 64)
        self.assertFalse(any("body" in item for item in catalog))
        self.assertNotIn("nextCandidates", loaded)
        self.assertNotIn("risk", loaded)
        self.assertNotIn("stages", loaded)

    def test_policy_references_only_governance_metadata_not_skill_content(self) -> None:
        raw = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        allowed_root = {"schemaVersion", "policyId", "version", "hashRule", "skills"}
        allowed_entry = {"skillId", "stages", "risk", "nextCandidates"}

        self.assertEqual(set(raw), allowed_root)
        for entry in raw["skills"]:
            self.assertLessEqual(set(entry), allowed_entry)
        serialized = json.dumps(raw, ensure_ascii=False)
        for duplicated_field in ('"description"', '"when"', '"does"', '"notFor"', '"prompt"', '"content"'):
            self.assertNotIn(duplicated_field, serialized)

    def test_real_confusions_are_excluded_by_skill_source_truth(self) -> None:
        debugging = _frontmatter(SKILLS_ROOT / "systematic-debugging/SKILL.md")
        implementation = _frontmatter(SKILLS_ROOT / "test-driven-implementation/SKILL.md")
        handoff = _frontmatter(SKILLS_ROOT / "structured-handoff/SKILL.md")
        quality = _frontmatter(SKILLS_ROOT / "quality-gate/SKILL.md")

        self.assertTrue(any("普通实现" in item for item in debugging["notFor"]))
        self.assertTrue(any("Unexplained failures" in item for item in implementation["notFor"]))
        self.assertTrue(any("最终收口" in item for item in handoff["notFor"]))
        self.assertTrue(any("降低阈值" in item for item in quality["notFor"]))

    def test_governed_stages_select_one_exact_skill(self) -> None:
        policy = RoomSkillPolicy(POLICY_PATH, SKILLS_ROOT)

        required = policy.select_stage("requirements")
        solution = policy.select_stage("solution")
        implementation = policy.select_stage("implementation")
        debugging = policy.select_stage("debugging")
        feedback = policy.select_stage("feedback")
        implementation_inner = policy.select_stage("implementation-code")
        review = policy.select_stage("review")
        missing = policy.select_stage("unknown-stage")

        self.assertEqual(required["selection"], "required")
        self.assertEqual(required["skillId"], "alignment-and-decision")
        self.assertEqual(required["candidateSkillIds"], [])
        self.assertEqual(solution["selection"], "required")
        self.assertEqual(solution["skillId"], "alignment-and-decision")
        self.assertEqual(solution["candidateSkillIds"], [])
        self.assertEqual(implementation["selection"], "required")
        self.assertEqual(implementation["skillId"], "implementation-execution")
        self.assertEqual(implementation["candidateSkillIds"], [])
        self.assertEqual(debugging["selection"], "required")
        self.assertEqual(debugging["skillId"], "systematic-debugging")
        self.assertEqual(feedback["selection"], "required")
        self.assertEqual(feedback["skillId"], "implementation-execution")
        self.assertEqual(implementation_inner["selection"], "none")
        self.assertEqual(review["selection"], "required")
        self.assertEqual(review["skillId"], "independent-review")
        self.assertEqual(review["candidateSkillIds"], [])
        self.assertEqual(missing["selection"], "none")
        self.assertEqual(missing["candidateSkillIds"], [])
        for result in (
            required,
            solution,
            implementation,
            debugging,
            feedback,
            implementation_inner,
            review,
            missing,
        ):
            self.assertFalse(any("dispatch" in key.lower() for key in result))

    def test_retired_alignment_skill_names_resolve_to_one_canonical_skill(self) -> None:
        policy = RoomSkillPolicy(POLICY_PATH, SKILLS_ROOT)

        canonical = policy.load_exact("alignment-and-decision")
        for legacy_name in (
            "requirement-alignment",
            "solution-convergence",
            "grill-me",
            "grill-me-docs",
            "room-requirement-clarification",
            "room-solution-convergence",
        ):
            with self.subTest(legacy_name=legacy_name):
                loaded = policy.load_exact(legacy_name)
                self.assertEqual(loaded["name"], "alignment-and-decision")
                self.assertEqual(
                    loaded["contentRevision"],
                    canonical["contentRevision"],
                )

    def test_retired_execution_names_resolve_to_one_canonical_skill(self) -> None:
        policy = RoomSkillPolicy(POLICY_PATH, SKILLS_ROOT)

        canonical = policy.load_exact("implementation-execution")
        for legacy_name in (
            "managed-task-execution",
            "project-devlog",
            "room-managed-task-execution",
            "room-implementation-execution",
        ):
            with self.subTest(legacy_name=legacy_name):
                loaded = policy.load_exact(legacy_name)
                self.assertEqual(loaded["name"], "implementation-execution")
                self.assertEqual(
                    loaded["contentRevision"],
                    canonical["contentRevision"],
                )

    def test_matt_diagnosing_bugs_name_resolves_to_room_bounded_debugging(self) -> None:
        policy = RoomSkillPolicy(POLICY_PATH, SKILLS_ROOT)

        canonical = policy.load_exact("systematic-debugging")
        loaded = policy.load_exact("diagnosing-bugs")

        self.assertEqual(loaded["name"], "systematic-debugging")
        self.assertEqual(
            loaded["contentRevision"],
            canonical["contentRevision"],
        )

    def test_next_candidates_are_advice_and_have_no_dispatch_side_effect(self) -> None:
        with tempfile.TemporaryDirectory(prefix="room-skills-next-") as tmp:
            store = RoomSkillPolicyStore(
                Path(tmp) / "room.sqlite",
                RoomSkillPolicy(POLICY_PATH, SKILLS_ROOT),
            )
            store.initialize()
            with sqlite3.connect(Path(tmp) / "room.sqlite") as conn:
                dispatch_tables = [
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE '%dispatch%'"
                    )
                ]
                before = {
                    name: conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
                    for name in dispatch_tables
                }
            advice = store.next_candidates("alignment-and-decision")
            planning_advice = store.next_candidates("implementation-planning")
            execution_advice = store.next_candidates("implementation-execution")
            tdd_advice = store.next_candidates("test-driven-implementation")
            debugging_advice = store.next_candidates("systematic-debugging")
            architecture_advice = store.next_candidates(
                "improve-codebase-architecture"
            )
            quality_advice = store.next_candidates("quality-gate")
            review_advice = store.next_candidates("independent-review")
            handoff_advice = store.next_candidates("structured-handoff")

            self.assertEqual(
                advice,
                ["implementation-planning"],
            )
            self.assertEqual(planning_advice, ["implementation-execution"])
            self.assertEqual(
                execution_advice,
                [
                    "test-driven-implementation",
                    "systematic-debugging",
                    "improve-codebase-architecture",
                    "quality-gate",
                ],
            )
            self.assertEqual(tdd_advice, ["implementation-execution"])
            self.assertEqual(
                debugging_advice,
                ["implementation-execution", "improve-codebase-architecture"],
            )
            self.assertEqual(architecture_advice, ["alignment-and-decision"])
            self.assertEqual(quality_advice, ["independent-review"])
            self.assertEqual(review_advice, ["implementation-execution"])
            self.assertEqual(handoff_advice, [])
            with sqlite3.connect(Path(tmp) / "room.sqlite") as conn:
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM room_v2_skill_load_receipts").fetchone()[0],
                    0,
                )
                after = {
                    name: conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
                    for name in dispatch_tables
                }
            self.assertEqual(after, before)


class RoomSkillReceiptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="room-skill-receipts-")
        self.root = Path(self.tmp.name)
        self.skills_root = self.root / "skills"
        shutil.copytree(SKILLS_ROOT, self.skills_root)
        self.policy_path = self.root / "room-skill-policy.json"
        shutil.copy2(POLICY_PATH, self.policy_path)
        self.policy = RoomSkillPolicy(self.policy_path, self.skills_root)
        self.store = RoomSkillPolicyStore(self.root / "room.sqlite", self.policy)
        self.store.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _pin(self, **overrides: object) -> tuple[dict[str, object], bool]:
        values: dict[str, object] = {
            "receipt_id": "skill-receipt:1",
            "root_id": "root:1",
            "task_id": "task:1",
            "dispatch_id": "dispatch:1",
            "session_id": "session:1",
            "skill_id": "alignment-and-decision",
            "skill_hash": self.policy.skill_hash("alignment-and-decision"),
            "catalog_revision": "a" * 64,
            "load_reason": "stage_required",
            "capability_epoch": 4,
            "idempotency_key": "dispatch:1/requirements",
            "created_at_ms": 100,
        }
        values.update(overrides)
        return self.store.pin_skill(**values)  # type: ignore[arg-type]

    def _restore(
        self,
        receipt: dict[str, object],
        *,
        store: RoomSkillPolicyStore | None = None,
        **overrides: object,
    ) -> dict[str, object]:
        values: dict[str, object] = {
            "expected_root_id": receipt["rootId"],
            "expected_task_id": receipt["taskId"],
            "expected_dispatch_id": receipt["dispatchId"],
            "expected_session_id": receipt["sessionId"],
            "expected_capability_epoch": receipt["capabilityEpoch"],
            "catalog_revision": receipt["catalogRevision"],
        }
        values.update(overrides)
        return (store or self.store).restore_for_compaction(
            str(receipt["receiptId"]),
            **values,  # type: ignore[arg-type]
        )

    def test_load_receipt_pins_policy_catalog_and_body_hash_idempotently(self) -> None:
        first, created = self._pin()
        repeated, repeated_created = self._pin()

        self.assertTrue(created)
        self.assertFalse(repeated_created)
        self.assertEqual(repeated, first)
        self.assertEqual(first["schemaVersion"], "wisdom-weasel.room-skill-load-receipt.v1")
        self.assertEqual(first["catalogRevision"], "a" * 64)
        self.assertEqual(first["skillHash"], self.policy.skill_hash(str(first["skillId"])))
        self.assertEqual(first["hashRule"], "sha256-skill-body-utf8-v1")
        self.assertEqual(first["state"], "active")

    def test_compaction_restores_exact_receipt_not_stage_reselection(self) -> None:
        receipt, _ = self._pin()

        recovered = self._restore(receipt)

        self.assertEqual(recovered["restoredFromReceiptId"], receipt["receiptId"])
        self.assertEqual(recovered["skillId"], receipt["skillId"])
        self.assertEqual(recovered["skillHash"], receipt["skillHash"])
        self.assertNotIn("stage", recovered)
        self.assertNotIn("candidateSkillIds", recovered)

    def test_compaction_restore_fails_closed_on_catalog_or_content_change(self) -> None:
        receipt, _ = self._pin()

        with self.assertRaises(SkillCatalogRevisionMismatch):
            self._restore(
                receipt,
                catalog_revision="b" * 64,
            )

        path = self.skills_root / "alignment-and-decision/SKILL.md"
        path.write_text(path.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")
        with self.assertRaises(SkillContentRevisionMismatch):
            self._restore(receipt)

    def test_compaction_restore_keeps_the_pinned_policy_version(self) -> None:
        receipt, _ = self._pin()
        raw = json.loads(self.policy_path.read_text(encoding="utf-8"))
        raw["version"] = int(raw["version"]) + 1
        self.policy_path.write_text(
            json.dumps(raw, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        changed_store = RoomSkillPolicyStore(
            self.root / "room.sqlite",
            RoomSkillPolicy(self.policy_path, self.skills_root),
        )

        with self.assertRaises(RoomSkillPolicyConflict):
            self._restore(receipt, store=changed_store)

    def test_revocation_blocks_live_use_but_preserves_exact_sealed_session(self) -> None:
        receipt, _ = self._pin()
        revoked = self.store.revoke_before_epoch(
            "root:1",
            new_capability_epoch=5,
            revoked_at_ms=200,
        )

        self.assertEqual(revoked, 1)
        self.assertEqual(
            self.store.revoke_before_epoch(
                "root:1",
                new_capability_epoch=5,
                revoked_at_ms=201,
            ),
            0,
        )
        with self.assertRaisesRegex(ValueError, "advance monotonically"):
            self.store.revoke_before_epoch(
                "root:1",
                new_capability_epoch=4,
                revoked_at_ms=202,
            )
        with self.assertRaises(RoomSkillEpochRevoked):
            self._restore(receipt)
        sealed = self._restore(receipt, allow_revoked=True)
        self.assertEqual(sealed["restoredFromReceiptId"], receipt["receiptId"])
        next_receipt, created = self._pin(
            receipt_id="skill-receipt:2",
            task_id="task:2",
            dispatch_id="dispatch:2",
            session_id="session:2",
            idempotency_key="dispatch:2/requirements",
            capability_epoch=5,
            created_at_ms=201,
        )
        self.assertTrue(created)
        self.assertEqual(next_receipt["capabilityEpoch"], 5)
        self.store.revoke_before_epoch(
            "root:1",
            new_capability_epoch=6,
            revoked_at_ms=202,
        )
        self.assertEqual(
            self._restore(receipt, allow_revoked=True)[
                "restoredFromReceiptId"
            ],
            receipt["receiptId"],
        )
        self.assertEqual(
            self._restore(next_receipt, allow_revoked=True)[
                "restoredFromReceiptId"
            ],
            next_receipt["receiptId"],
        )

    def test_sealed_restore_rejects_wrong_lineage_and_newer_session_receipt(self) -> None:
        receipt, _ = self._pin()
        self.store.revoke_before_epoch(
            "root:1",
            new_capability_epoch=5,
            revoked_at_ms=200,
        )

        for field, value in (
            ("expected_root_id", "root:other"),
            ("expected_task_id", "task:other"),
            ("expected_dispatch_id", "dispatch:other"),
            ("expected_session_id", "session:other"),
        ):
            with self.subTest(field=field), self.assertRaises(
                RoomSkillEpochRevoked
            ):
                self._restore(
                    receipt,
                    allow_revoked=True,
                    **{field: value},
                )

        self._pin(
            receipt_id="skill-receipt:session-reused",
            dispatch_id="dispatch:2",
            session_id="session:1",
            idempotency_key="dispatch:2/requirements",
            capability_epoch=5,
            created_at_ms=201,
        )
        with self.assertRaises(RoomSkillEpochRevoked):
            self._restore(receipt, allow_revoked=True)

    def test_parallel_dispatch_revocation_keeps_shared_epoch_available(self) -> None:
        first, _ = self._pin()
        second, _ = self._pin(
            receipt_id="skill-receipt:2",
            task_id="task:2",
            dispatch_id="dispatch:2",
            session_id="session:2",
            idempotency_key="dispatch:2/requirements",
            created_at_ms=101,
        )

        revoked = self.store.revoke_dispatch(
            root_id="root:1",
            dispatch_id="dispatch:1",
            session_id="session:1",
            capability_epoch=4,
            revoked_at_ms=200,
        )

        self.assertEqual(revoked, 1)
        self.assertEqual(self.store.latest_for_session("session:1")["state"], "revoked")
        self.assertEqual(self.store.latest_for_session("session:2")["state"], "active")
        restored = self._restore(second)
        self.assertEqual(restored["restoredFromReceiptId"], second["receiptId"])
        self.assertEqual(first["capabilityEpoch"], second["capabilityEpoch"])

    def test_receipt_requires_an_explicit_skill_id(self) -> None:
        selection = self.policy.select_stage("review")
        self.assertEqual(selection["selection"], "required")
        self.assertEqual(selection["skillId"], "independent-review")
        with self.assertRaisesRegex(ValueError, "explicit skillId"):
            self._pin(skill_id="")

    def test_pin_requires_the_exact_current_epoch_and_native_body_hash(self) -> None:
        self._pin()
        with self.assertRaises(RoomSkillEpochRevoked):
            self._pin(
                receipt_id="skill-receipt:future",
                dispatch_id="dispatch:future",
                idempotency_key="dispatch:future/requirements",
                capability_epoch=99,
            )
        with self.assertRaises(SkillContentRevisionMismatch):
            self._pin(
                receipt_id="skill-receipt:wrong-hash",
                dispatch_id="dispatch:wrong-hash",
                idempotency_key="dispatch:wrong-hash/requirements",
                skill_hash="f" * 64,
            )


if __name__ == "__main__":
    unittest.main()
