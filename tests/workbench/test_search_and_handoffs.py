from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from phase_tracker.search_engine import ProjectSearchIndex
from phase_tracker.workbench import (
    HandoffPackageExclusionPolicy,
    ResearchWorkbenchService,
    WorkbenchAttachmentService,
    WorkflowReference,
)
from phase_tracker.workbench.store import WorkbenchStore


class ResearchSearchAndHandoffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.version = self.root / "p2" / "p2-b4" / "p2-b4-v7"
        self.version.mkdir(parents=True)
        self.source = self.version / "source.md"
        self.source.write_text(
            "A cobalt lemniscate identifies the internal research finding.\n",
            encoding="utf-8",
        )
        run = ResearchWorkbenchService(self.root).create_campaign_run(
            "Trace the cobalt lemniscate.",
            "p2/p2-b4/p2-b4-v7/source.md",
            (self.source,),
        )
        self.attachment = WorkbenchAttachmentService(self.root).attach(
            run,
            WorkflowReference(2, 4, 7, "p2"),
        )

    def test_search_badges_do_not_create_exposure(self) -> None:
        store = WorkbenchStore(self.root)
        self.assertEqual(store.exposure_event_count(), 0)
        index = ProjectSearchIndex(self.root)
        index.rebuild()
        self.assertEqual(store.exposure_event_count(), 0)

        results = index.search("User Research Workbench Summary")
        attached = [
            result
            for result in results
            if result.path.endswith("/summary.md")
            and "user-research" in Path(result.path).parts
        ]
        self.assertTrue(attached)
        for result in attached:
            self.assertEqual(
                result.badges,
                ("USER RESEARCH", "ATTACHED", "NOT PROVIDED"),
            )
        self.assertEqual(store.exposure_event_count(), 0)

    def test_lookalike_folder_does_not_infer_attachment_state(self) -> None:
        lookalike = self.version / "user-research" / "manual-folder"
        lookalike.mkdir(parents=True)
        (lookalike / "summary.md").write_text(
            "unregistered turquoise counterfeit",
            encoding="utf-8",
        )
        index = ProjectSearchIndex(self.root)
        index.rebuild()
        results = index.search("turquoise counterfeit")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].badges, ())

    def test_all_default_agent_handoffs_exclude_user_research(self) -> None:
        policy = HandoffPackageExclusionPolicy(self.root)
        normal = self.version / "operator-package.zip"
        normal.write_bytes(b"normal handoff")
        summary = self.attachment.destination / "summary.md"
        candidates = (normal, summary)

        for role in ("operator", "guardian", "auditor"):
            with self.subTest(role=role):
                self.assertEqual(policy.filter_default(candidates, role), (normal,))
                self.assertFalse(policy.is_default_included(summary, role))
                relative_summary = summary.relative_to(self.root)
                self.assertFalse(
                    policy.is_default_included(relative_summary, role)
                )

    def test_handoff_policy_rejects_escape_and_unknown_roles(self) -> None:
        policy = HandoffPackageExclusionPolicy(self.root)
        with self.assertRaises(ValueError):
            policy.filter_default((Path("../outside.txt"),), "operator")
        with self.assertRaises(ValueError):
            policy.filter_default((self.source,), "publisher")


if __name__ == "__main__":
    unittest.main()
