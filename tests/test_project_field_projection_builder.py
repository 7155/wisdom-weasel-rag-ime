from __future__ import annotations

import json
import re
import sys
import unittest
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_project_field_projection import (  # noqa: E402
    PROJECTION_SCHEMA,
    ProjectionBuildError,
    build_projection,
    session_roots,
    validate_curation_audit,
    validate_project,
)
from wayfinder_projection import (  # noqa: E402
    WAYFINDER_PROJECTION_SCHEMA,
    build_wayfinder_projection,
    validate_wayfinder_projection,
)


WAYFINDER_ROOT = (
    ROOT
    / "design-system/rag-ime-control-center/prototypes/room-navigation-wayfinder"
)
MANIFEST_PATH = (
    WAYFINDER_ROOT
    / "real-project-reconstruction/reconstruction-manifest.v1.json"
)
GENERATED_PATH = (
    ROOT
    / "control-center-web/src/features/project-field/generated/personal-agent-workbench.v1.json"
)
CURATION_AUDIT_PATH = (
    WAYFINDER_ROOT
    / "reconciliation/wayfinder-luna-source-audit.v1.json"
)


class ProjectFieldProjectionBuilderTests(unittest.TestCase):
    def test_generated_projection_contains_only_bounded_receipts(self) -> None:
        path = (
            ROOT
            / "control-center-web/src/features/project-field/generated/personal-agent-workbench.v1.json"
        )
        payload = json.loads(path.read_text(encoding="utf-8"))
        serialized = json.dumps(payload, ensure_ascii=False)

        self.assertEqual(PROJECTION_SCHEMA, payload["schemaVersion"])
        self.assertEqual(8, len(payload["project"]["rooms"]))
        self.assertEqual(35, len(payload["sourceReceipts"]))
        document_receipts = [
            receipt
            for receipt in payload["sourceReceipts"]
            if receipt["kind"] == "project-document"
        ]
        session_receipts = [
            receipt
            for receipt in payload["sourceReceipts"]
            if receipt["kind"] == "agent-session"
        ]
        self.assertEqual(
            "git-head",
            next(receipt for receipt in document_receipts if receipt["id"] == "doc-product-readme")[
                "snapshotMode"
            ],
        )
        self.assertTrue(all(receipt["userMessageCount"] > 0 for receipt in session_receipts))
        self.assertEqual(7, len(document_receipts))
        self.assertEqual(12, len(session_receipts))
        self.assertEqual(
            16,
            len([receipt for receipt in payload["sourceReceipts"] if receipt["kind"] == "git-commit"]),
        )
        self.assertNotIn("/Users/", serialized)
        self.assertNotIn("/Volumes/", serialized)
        self.assertNotIn("userExcerpts", serialized)
        self.assertFalse(payload["privacy"]["rawChatIncluded"])
        self.assertFalse(payload["privacy"]["toolResultsIncluded"])
        self.assertFalse(payload["privacy"]["assistantReasoningIncluded"])

    def test_manifest_validation_rejects_source_count_drift(self) -> None:
        sources = [
            {
                "id": "doc-one",
                "kind": "project-document",
                "role": "intent",
                "label": "Original requirement",
                "detail": "Keeps the source vision.",
                "ref": "README.md",
                "observedAt": "2026-08-02",
                "authority": "primary",
            },
            {
                "id": "session-one",
                "kind": "agent-session",
                "role": "decision",
                "label": "Primary session",
                "detail": "Records the decision path.",
                "ref": "agent-session:codex:019fbdd9-3ce4-7413-a20c-6d5725d0b6ac",
                "observedAt": "2026-08-02",
                "provider": "codex",
                "authority": "primary",
            },
            {
                "id": "commit-one",
                "kind": "git-commit",
                "role": "acceptance",
                "label": "Commit evidence",
                "detail": "Corroborates implementation only.",
                "ref": "git:92e6a62",
                "observedAt": "2026-08-02",
                "authority": "corroborating",
            },
        ]
        project = {
            "id": "project",
            "name": "Project",
            "compactTitle": "Project",
            "shortName": "P",
            "subtitle": "Project reconstruction",
            "defaultRoomId": "room",
            "routeCamera": {"x": 0, "y": 0, "scale": 1},
            "rooms": [
                {
                    "id": "room",
                    "title": "Outcome Room",
                    "shape": 1,
                    "x": 0,
                    "y": 0,
                    "sources": sources,
                }
            ],
            "reconstruction": {
                "sourceCounts": {
                    "projectDocuments": 1,
                    "agentSessions": 1,
                    "gitCommits": 1,
                }
            },
        }

        self.assertEqual(3, len(validate_project(project)))
        drifted = deepcopy(project)
        drifted["reconstruction"]["sourceCounts"]["agentSessions"] = 2
        with self.assertRaisesRegex(ProjectionBuildError, "sourceCounts"):
            validate_project(drifted)

    def test_manifest_owns_only_boundaries_geometry_and_source_receipts(self) -> None:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            {
                "id",
                "name",
                "compactTitle",
                "shortName",
                "subtitle",
                "defaultRoomId",
                "routeCamera",
                "reconstruction",
                "rooms",
            },
            set(manifest["project"]),
        )
        for room in manifest["project"]["rooms"]:
            self.assertEqual({"id", "title", "x", "y", "shape", "sources"}, set(room))

    def test_luna_curation_receipt_fails_closed_after_human_review(self) -> None:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        audit = json.loads(CURATION_AUDIT_PATH.read_text(encoding="utf-8"))
        kwargs = {
            "curated_at": manifest["curatedAt"],
            "git_head": manifest["factualSource"]["gitHead"],
        }

        validate_curation_audit(manifest["curation"], audit, **kwargs)

        swapped_alias = deepcopy(audit)
        swapped_alias["deduplication"]["exactAliasGroups"][0][
            "canonicalSourceId"
        ] = "session-codex-019fc874"
        with self.assertRaisesRegex(ProjectionBuildError, "exact alias mappings"):
            validate_curation_audit(manifest["curation"], swapped_alias, **kwargs)

        leaked_chat = deepcopy(audit)
        leaked_chat["privacy"]["rawChatIncluded"] = True
        with self.assertRaisesRegex(ProjectionBuildError, "privacy contract"):
            validate_curation_audit(manifest["curation"], leaked_chat, **kwargs)

    def test_generated_wayfinder_exactly_matches_authoritative_docs(self) -> None:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        generated = json.loads(GENERATED_PATH.read_text(encoding="utf-8"))
        manifest_rooms = manifest["project"]["rooms"]
        room_boundaries = {room["id"]: room["title"] for room in manifest_rooms}
        source_ids_by_room = {
            room["id"]: {source["id"] for source in room["sources"]}
            for room in manifest_rooms
        }
        expected = build_wayfinder_projection(
            WAYFINDER_ROOT,
            expected_project_id=manifest["project"]["id"],
            expected_current_room_id=manifest["project"]["defaultRoomId"],
            room_boundaries=room_boundaries,
            available_source_ids_by_room=source_ids_by_room,
        )

        self.assertEqual(WAYFINDER_PROJECTION_SCHEMA, expected["schemaVersion"])
        self.assertEqual(expected, generated["project"]["wayfinder"])
        self.assertEqual(
            [
                "input-experience",
                "governed-memory",
                "unified-workbench",
                "room-delivery",
                "agent-continuity",
                "workflow-system",
                "project-field",
                "release-journey",
            ],
            [room["roomId"] for room in expected["rooms"]],
        )
        self.assertEqual(
            "unreached",
            expected["destination"]["state"],
        )
        self.assertEqual("left-to-right", expected["evolution"]["direction"])
        self.assertEqual(
            [
                "input-origin",
                "memory-control",
                "agent-room",
                "product-convergence",
                "project-field",
            ],
            [epoch["id"] for epoch in expected["evolution"]["epochs"]],
        )
        self.assertEqual("release-journey", expected["evolution"]["releaseLane"]["roomId"])
        self.assertGreaterEqual(len(expected["evolution"]["releaseLane"]["checkpoints"]), 4)
        self.assertTrue(
            all(
                room["progress"]["completed"] <= room["progress"]["total"]
                and room["progress"]["total"] == len(room["progress"]["items"])
                for room in expected["rooms"]
            )
        )
        self.assertNotIn("sharedArchitecture", expected)
        self.assertNotIn("fog", generated["project"])
        self.assertNotIn("frontier", generated["project"])
        self.assertEqual(1, sum(relation["from"] == "@origin" for relation in expected["relations"]))
        self.assertEqual(
            {"refines", "led-to", "requires"},
            {relation["kind"] for relation in expected["relations"]},
        )
        self.assertTrue(all(relation["sourceRefs"] for relation in expected["relations"]))
        self.assertEqual(
            set().union(*source_ids_by_room.values()),
            set(expected["sourceRefs"]),
        )

    def test_current_wayfinder_docs_define_paper_rooms_without_a_convergence_node(self) -> None:
        current_contracts = [
            WAYFINDER_ROOT / "README.md",
            WAYFINDER_ROOT / "00-map.md",
            WAYFINDER_ROOT / "01-alignment-decision-packet.md",
            WAYFINDER_ROOT / "02-implementation-plan.md",
            WAYFINDER_ROOT / "rooms/project-field.md",
            ROOT / "design-system/rag-ime-control-center/pages/project-field.md",
        ]
        current_text = "\n".join(path.read_text(encoding="utf-8") for path in current_contracts)
        derived_text = re.sub(
            r"<!-- user-source:start -->.*?<!-- user-source:end -->",
            "",
            current_text,
            flags=re.DOTALL,
        )

        self.assertIn("汇聚是路径关系，不是独立节点", derived_text)
        for stale_term in ("汇聚门", "Room 汇聚", "不规则双层岸线", "Fog", "Frontier", "当前前沿"):
            with self.subTest(stale_term=stale_term):
                self.assertNotIn(stale_term, derived_text)

    def test_manifest_uses_a_history_derived_dag_layout(self) -> None:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        positions = {
            room["id"]: (room["x"], room["y"])
            for room in manifest["project"]["rooms"]
        }

        self.assertEqual(
            {
                "input-experience": (500, 260),
                "governed-memory": (900, 520),
                "unified-workbench": (900, 200),
                "room-delivery": (1300, 520),
                "agent-continuity": (1300, 200),
                "workflow-system": (1700, 520),
                "project-field": (2100, 260),
                "release-journey": (1250, 800),
            },
            positions,
        )

    def test_wayfinder_schema_fails_closed_for_every_authoritative_dimension(self) -> None:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        rooms = manifest["project"]["rooms"]
        room_boundaries = {room["id"]: room["title"] for room in rooms}
        source_ids_by_room = {
            room["id"]: {source["id"] for source in room["sources"]}
            for room in rooms
        }
        valid = build_wayfinder_projection(
            WAYFINDER_ROOT,
            expected_project_id=manifest["project"]["id"],
            expected_current_room_id=manifest["project"]["defaultRoomId"],
            room_boundaries=room_boundaries,
            available_source_ids_by_room=source_ids_by_room,
        )
        mutations = {
            "Initial vision": lambda value: value["initialVision"].__setitem__("statement", ""),
            "Destination": lambda value: value["destination"].__setitem__("state", "reached"),
            "Room requirement": lambda value: value["rooms"][0].__setitem__("requirement", ""),
            "Room decisions": lambda value: value["rooms"][0].__setitem__("decisions", []),
            "Room acceptance": lambda value: value["rooms"][0].__setitem__("acceptanceObservations", []),
            "Room progress": lambda value: value["rooms"][0]["progress"].__setitem__("completed", 99),
            "Room epoch": lambda value: value["rooms"][0].__setitem__("epochId", "unknown"),
            "evolution direction": lambda value: value["evolution"].__setitem__("direction", "top-to-bottom"),
            "relation endpoint": lambda value: value["relations"][0].__setitem__("to", "@destination"),
            "relation receipt": lambda value: value["relations"][0].__setitem__("sourceRefs", []),
            "skill state": lambda value: value["rooms"][0].__setitem__("currentStage", "unknown"),
            "TDD parent": lambda value: value["deliveryEngine"]["innerMethod"].__setitem__("parentStage", "quality-gate"),
            "source ref": lambda value: value["documents"][0]["sourceRefs"].append("source-missing"),
        }

        for label, mutate in mutations.items():
            with self.subTest(label=label):
                candidate = deepcopy(valid)
                mutate(candidate)
                with self.assertRaises(ProjectionBuildError):
                    validate_wayfinder_projection(
                        candidate,
                        expected_project_id=manifest["project"]["id"],
                        expected_current_room_id=manifest["project"]["defaultRoomId"],
                        room_boundaries=room_boundaries,
                        available_source_ids_by_room=source_ids_by_room,
                    )

    def test_verified_receipts_can_rebuild_only_the_docs_projection(self) -> None:
        existing = json.loads(GENERATED_PATH.read_text(encoding="utf-8"))
        rebuilt, material = build_projection(
            MANIFEST_PATH,
            ROOT.parent / "personal-agent-workbench-main-release",
            ROOT,
            session_roots([]),
            reused_projection=existing,
        )

        self.assertEqual(existing, rebuilt)
        self.assertEqual({}, material)


if __name__ == "__main__":
    unittest.main()
