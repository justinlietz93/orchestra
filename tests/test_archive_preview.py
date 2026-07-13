import tempfile
import unittest
from pathlib import Path

from phase_tracker.archive_preview import build_previews
from phase_tracker.discovery import scan_project
from phase_tracker.domain import Agent, ArchiveAction, Coordinate, WorkflowState


class ArchivePreviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "p5" / "p5-b3" / "p5-b3-v10").mkdir(parents=True)
        self.index = scan_project(self.root)
        self.current = Coordinate(5, 3, 10, "p5")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_operator_can_only_record_in_current_version(self) -> None:
        previews = build_previews(
            self.root,
            self.index,
            self.current,
            WorkflowState(active_agent=Agent.OPERATOR),
            "Package produced",
        )
        self.assertTrue(previews[ArchiveAction.CONTINUE].enabled)
        self.assertIn("RECORD IN CURRENT VERSION", previews[ArchiveAction.CONTINUE].text)
        self.assertFalse(previews[ArchiveAction.NEW_BRANCH].enabled)
        self.assertFalse(previews[ArchiveAction.NEW_PHASE].enabled)

    def test_guardian_failure_previews_review_subject_folder(self) -> None:
        previews = build_previews(
            self.root,
            self.index,
            self.current,
            WorkflowState(
                active_agent=Agent.GUARDIAN,
                guardian_subject=Agent.AUDITOR,
            ),
            "Fail",
        )
        self.assertTrue(previews[ArchiveAction.CONTINUE].enabled)
        self.assertTrue(
            previews[ArchiveAction.CONTINUE].text.endswith("p5/p5-b3/p5-b3-v10/audit-fails")
        )

    def test_auditor_result_enables_coordinate_actions(self) -> None:
        previews = build_previews(
            self.root,
            self.index,
            self.current,
            WorkflowState(active_agent=Agent.AUDITOR),
            "Pass",
        )
        self.assertIn("p5-b3-v11", previews[ArchiveAction.CONTINUE].text)
        self.assertTrue(previews[ArchiveAction.NEW_BRANCH].enabled)
        self.assertTrue(previews[ArchiveAction.NEW_PHASE].enabled)


if __name__ == "__main__":
    unittest.main()

