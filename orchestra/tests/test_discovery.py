import tempfile
import unittest
from pathlib import Path

from phase_tracker.discovery import compute_target, scan_project
from phase_tracker.domain import ArchiveAction, Coordinate


class DiscoveryTests(unittest.TestCase):
    def test_scans_descriptive_phase_and_computes_all_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            phase = root / "Phase-5_Prime_QBL"
            (phase / "p5-b1" / "p5-b1-v1").mkdir(parents=True)
            (phase / "p5-b1" / "p5-b1-v2").mkdir()
            (phase / "p5-b3" / "p5-b3-v10").mkdir(parents=True)

            index = scan_project(root)
            current = Coordinate(5, 3, 10, "Phase-5_Prime_QBL")

            continued = compute_target(index, ArchiveAction.CONTINUE, current)
            new_branch = compute_target(index, ArchiveAction.NEW_BRANCH, current)
            new_phase = compute_target(index, ArchiveAction.NEW_PHASE, current)

            self.assertEqual(
                continued.coordinate.relative_path(),
                Path("Phase-5_Prime_QBL/p5-b3/p5-b3-v11"),
            )
            self.assertEqual(
                new_branch.coordinate.relative_path(),
                Path("Phase-5_Prime_QBL/p5-b4/p5-b4-v1"),
            )
            self.assertEqual(
                new_phase.coordinate.relative_path(),
                Path("p6/p6-b1/p6-b1-v1"),
            )

    def test_empty_project_starts_at_p1_b1_v1(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = compute_target(scan_project(root), ArchiveAction.CONTINUE, None)
            self.assertEqual(target.coordinate.relative_path(), Path("p1/p1-b1/p1-b1-v1"))

    def test_duplicate_phase_numbers_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "p5").mkdir()
            (root / "Phase-5_Prime_QBL").mkdir()
            with self.assertRaisesRegex(ValueError, "Ambiguous phase directories"):
                compute_target(scan_project(root), ArchiveAction.NEW_PHASE, None)


if __name__ == "__main__":
    unittest.main()

