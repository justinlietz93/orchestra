import tempfile
import unittest
from pathlib import Path

from phase_tracker.domain import Agent, Coordinate, WorkflowState
from phase_tracker.state_store import StateStore
from phase_tracker.workflow_alignment import record_alignment


class WorkflowAlignmentTests(unittest.TestCase):
    def test_auditor_alignment_persists_state_and_event(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = WorkflowState(
                last_coordinate=Coordinate(5, 3, 10, "p5")
            )

            receipt = record_alignment(root, original, "Auditor")

            self.assertEqual(receipt.state.active_agent, Agent.AUDITOR)
            self.assertIsNone(receipt.warning)
            self.assertEqual(StateStore(root).load().active_agent, Agent.AUDITOR)
            event = StateStore(root).read_events(limit=1)[0]
            self.assertEqual(event["event_type"], "manual_workflow_alignment")
            self.assertEqual(event["previous_position"], "Operator")
            self.assertEqual(event["next_position"], "Auditor")
            self.assertEqual(event["path"], "p5/p5-b3/p5-b3-v10")


if __name__ == "__main__":
    unittest.main()

