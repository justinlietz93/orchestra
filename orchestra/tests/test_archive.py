import json
import tempfile
import unittest
from pathlib import Path

from phase_tracker.archive import ArchiveError, ArchiveService, sha256_file
from phase_tracker.domain import Agent, ArchiveAction, Coordinate, WorkflowState
from phase_tracker.state_store import StateStore


class ArchiveTests(unittest.TestCase):
    def test_archives_artifacts_response_manifest_and_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "project"
            source_dir = base / "source"
            root.mkdir()
            source_dir.mkdir()
            package = source_dir / "operator-package.zip"
            package.write_bytes(b"package bytes")

            receipt = ArchiveService().record(
                project_root=root,
                action=ArchiveAction.CONTINUE,
                current=None,
                state=WorkflowState(),
                result="Package produced",
                artifacts=[package],
                response="# Operator response\n\nComplete.",
                note="Initial run",
            )

            destination = root / "p1" / "p1-b1" / "p1-b1-v1"
            self.assertEqual(receipt.destination, destination)
            self.assertEqual((destination / package.name).read_bytes(), b"package bytes")
            self.assertTrue((destination / "p1-b1-v1-operator-response.md").exists())

            manifest_path = destination / "p1-b1-v1-archive.json"
            manifest = json.loads(manifest_path.read_text())
            package_row = next(row for row in manifest["files"] if row["path"] == package.name)
            self.assertEqual(package_row["sha256"], sha256_file(package))
            self.assertEqual(manifest["source_agent"], "Operator")
            self.assertEqual(manifest["next_agent"], "Guardian")
            self.assertEqual(manifest["operator_note"], "Initial run")

            state = StateStore(root).load()
            self.assertEqual(state.active_agent, Agent.GUARDIAN)
            self.assertEqual(state.guardian_subject, Agent.OPERATOR)
            self.assertEqual(state.last_coordinate, receipt.coordinate)

    def test_new_branch_and_new_phase_use_max_existing_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "p3" / "p3-b4" / "p3-b4-v7").mkdir(parents=True)
            service = ArchiveService()
            auditor_state = WorkflowState(active_agent=Agent.AUDITOR)

            branch_receipt = service.record(
                root,
                ArchiveAction.NEW_BRANCH,
                None,
                auditor_state,
                "Pass",
                [],
                "Guardian pass",
            )
            self.assertEqual(
                branch_receipt.coordinate.relative_path(),
                Path("p3/p3-b5/p3-b5-v1"),
            )

            phase_receipt = service.record(
                root,
                ArchiveAction.NEW_PHASE,
                branch_receipt.coordinate,
                WorkflowState(active_agent=Agent.AUDITOR),
                "Fail",
                [],
                "Auditor pass",
            )
            self.assertEqual(
                phase_receipt.coordinate.relative_path(),
                Path("p4/p4-b1/p4-b1-v1"),
            )

    def test_only_auditor_result_can_change_branch_or_phase(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "p2" / "p2-b3" / "p2-b3-v4").mkdir(parents=True)
            for agent, result in (
                (Agent.OPERATOR, "Package produced"),
                (Agent.GUARDIAN, "Pass"),
            ):
                state = WorkflowState(
                    active_agent=agent,
                    guardian_subject=(
                        Agent.OPERATOR if agent == Agent.GUARDIAN else None
                    ),
                )
                with self.subTest(agent=agent):
                    with self.assertRaisesRegex(ArchiveError, "Only an Auditor"):
                        ArchiveService().record(
                            root,
                            ArchiveAction.NEW_BRANCH,
                            None,
                            state,
                            result,
                            [],
                            "return",
                        )
            self.assertFalse((root / "p2" / "p2-b4").exists())

    def test_auditor_revision_stays_in_first_advanced_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "project"
            root.mkdir()
            ratification = base / "AUDIT_RATIFICATION.md"
            ratification.write_text("Guardian ratification")

            operator = ArchiveService().record(
                root,
                ArchiveAction.CONTINUE,
                None,
                WorkflowState(),
                "Package produced",
                [],
                "Operator package response",
            )
            v1 = root / "p1" / "p1-b1" / "p1-b1-v1"
            self.assertTrue(operator.created_coordinate)
            self.assertEqual(operator.destination, v1)

            guardian_pass = ArchiveService().record(
                root,
                ArchiveAction.CONTINUE,
                operator.coordinate,
                operator.next_state,
                "Pass",
                [ratification],
                "Operator submission ratified",
            )
            self.assertFalse(guardian_pass.created_coordinate)
            self.assertEqual(guardian_pass.destination, v1)
            self.assertTrue((v1 / "AUDIT_RATIFICATION.md").exists())
            self.assertFalse((root / "p1" / "p1-b1" / "p1-b1-v2").exists())

            auditor = ArchiveService().record(
                root,
                ArchiveAction.CONTINUE,
                guardian_pass.coordinate,
                guardian_pass.next_state,
                "Pass",
                [],
                "Auditor pass response",
            )
            v2 = root / "p1" / "p1-b1" / "p1-b1-v2"
            self.assertTrue(auditor.created_coordinate)
            self.assertEqual(auditor.destination, v2)
            self.assertTrue((v2 / "p1-b1-v2-auditor-response.md").exists())

            guardian_fail = ArchiveService().record(
                root,
                ArchiveAction.CONTINUE,
                auditor.coordinate,
                auditor.next_state,
                "Fail",
                [],
                "Auditor failure notice",
            )
            self.assertFalse(guardian_fail.created_coordinate)
            self.assertEqual(guardian_fail.destination, v2 / "audit-fails")
            self.assertTrue(
                (v2 / "audit-fails" / "p1-b1-v2-guardian-response.md").exists()
            )
            self.assertFalse((root / "p1" / "p1-b1" / "p1-b1-v3").exists())
            stored = StateStore(root).load()
            self.assertIsNotNone(stored.last_manifest)
            append_manifest_path = root / str(stored.last_manifest)
            append_manifest = json.loads(append_manifest_path.read_text())
            self.assertEqual(append_manifest["event_type"], "current_version_append")
            self.assertEqual(append_manifest["placement"], "audit-fails")

            store = StateStore(root)
            store.state_path.unlink()
            store.prepare(stored)
            recovered = store.load()
            self.assertEqual(recovered.active_agent, Agent.AUDITOR)
            self.assertTrue(recovered.auditor_revision)
            self.assertEqual(recovered.last_manifest, stored.last_manifest)

            revised_auditor = ArchiveService().record(
                root,
                ArchiveAction.CONTINUE,
                guardian_fail.coordinate,
                guardian_fail.next_state,
                "Pass",
                [],
                "Auditor corrected the rejected phrasing",
            )
            self.assertFalse(revised_auditor.created_coordinate)
            self.assertEqual(revised_auditor.destination, v2)
            self.assertEqual(
                revised_auditor.next_state.guardian_subject, Agent.AUDITOR
            )
            self.assertTrue(revised_auditor.next_state.auditor_revision)
            self.assertTrue(
                (v2 / "p1-b1-v2-auditor-response-2.md").exists()
            )
            self.assertFalse((root / "p1" / "p1-b1" / "p1-b1-v3").exists())

            guardian_accepts_revision = ArchiveService().record(
                root,
                ArchiveAction.CONTINUE,
                revised_auditor.coordinate,
                revised_auditor.next_state,
                "Pass",
                [],
                "Auditor correction ratified",
            )
            self.assertEqual(guardian_accepts_revision.destination, v2)
            self.assertEqual(
                guardian_accepts_revision.next_state.active_agent,
                Agent.OPERATOR,
            )
            self.assertFalse(
                guardian_accepts_revision.next_state.auditor_revision
            )
            self.assertFalse((root / "p1" / "p1-b1" / "p1-b1-v3").exists())

    def test_guardian_operator_failure_uses_operator_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            version = root / "p5" / "p5-b3" / "p5-b3-v10"
            version.mkdir(parents=True)
            state = WorkflowState(
                active_agent=Agent.GUARDIAN,
                guardian_subject=Agent.OPERATOR,
                last_coordinate=Coordinate(5, 3, 10, "p5"),
            )

            receipt = ArchiveService().record(
                root,
                ArchiveAction.CONTINUE,
                state.last_coordinate,
                state,
                "Fail",
                [],
                "Operator score failed",
            )

            self.assertEqual(receipt.destination, version / "operator-fails")
            self.assertEqual(receipt.next_state.active_agent, Agent.OPERATOR)
            self.assertFalse((root / "p5" / "p5-b3" / "p5-b3-v11").exists())

    def test_same_named_artifacts_are_preserved_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "project"
            root.mkdir()
            (base / "a").mkdir()
            (base / "b").mkdir()
            (base / "a" / "result.txt").write_text("first")
            (base / "b" / "result.txt").write_text("second")

            receipt = ArchiveService().record(
                root,
                ArchiveAction.CONTINUE,
                None,
                WorkflowState(),
                "Not produced",
                [base / "a" / "result.txt", base / "b" / "result.txt"],
                "",
            )
            self.assertEqual((receipt.destination / "result.txt").read_text(), "first")
            self.assertEqual((receipt.destination / "result-2.txt").read_text(), "second")

    def test_project_root_cannot_be_archived_into_itself(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(ArchiveError):
                ArchiveService().record(
                    root,
                    ArchiveAction.CONTINUE,
                    None,
                    WorkflowState(),
                    "Package produced",
                    [root],
                    "response",
                )
            self.assertFalse((root / "p1").exists())

    def test_branch_cannot_be_archived_into_its_new_child_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            branch = root / "p1" / "p1-b1"
            (branch / "p1-b1-v1").mkdir(parents=True)
            with self.assertRaisesRegex(ArchiveError, "own descendant"):
                ArchiveService().record(
                    root,
                    ArchiveAction.CONTINUE,
                    None,
                    WorkflowState(),
                    "Package produced",
                    [branch],
                    "response",
                )
            self.assertFalse((branch / "p1-b1-v2").exists())

    def test_pending_state_recovers_only_from_matching_committed_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / "p2" / "p2-b1" / "p2-b1-v3"
            destination.mkdir(parents=True)
            coordinate = Coordinate(2, 1, 3, "p2")
            state = WorkflowState(
                active_agent=Agent.AUDITOR,
                last_coordinate=coordinate,
                last_event_id="event-123",
            )
            manifest = destination / "p2-b1-v3-archive.json"
            manifest.write_text(json.dumps({"event_id": "event-123"}))

            store = StateStore(root)
            store.prepare(state)
            recovered = store.load()

            self.assertEqual(recovered.active_agent, Agent.AUDITOR)
            self.assertEqual(recovered.last_event_id, "event-123")
            self.assertTrue(store.state_path.exists())
            self.assertFalse(store.pending_state_path.exists())

    def test_legacy_guardian_auditor_fail_resumes_as_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            version = root / "p2" / "p2-b1" / "p2-b1-v3"
            fail_dir = version / "audit-fails"
            fail_dir.mkdir(parents=True)
            manifest = fail_dir / "legacy-fail-archive.json"
            manifest.write_text(json.dumps({
                "source_agent": "Guardian",
                "guardian_subject": "Auditor",
                "result": "Fail",
            }))
            store = StateStore(root)
            store.tracker_dir.mkdir(parents=True)
            legacy_state = {
                "active_agent": "Auditor",
                "guardian_subject": None,
                "status": "in_progress",
                "last_coordinate": {
                    "phase": 2,
                    "branch": 1,
                    "version": 3,
                    "phase_dir": "p2",
                },
                "last_event_id": "legacy-event",
                "last_manifest": manifest.relative_to(root).as_posix(),
            }
            store.state_path.write_text(json.dumps(legacy_state))

            recovered = store.load()

            self.assertEqual(recovered.active_agent, Agent.AUDITOR)
            self.assertTrue(recovered.auditor_revision)


if __name__ == "__main__":
    unittest.main()
