from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from phase_tracker.workbench import ResearchWorkbenchService


class ResearchInputRestrictionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.version = self.root / "p5" / "p5-b3" / "p5-b3-v12"
        self.version.mkdir(parents=True)
        self.proof = self.version / "proof.md"
        self.proof.write_text("explicit evidence", encoding="utf-8")
        self.service = ResearchWorkbenchService(self.root)

    def test_rejects_symlinks_control_files_and_external_files(self) -> None:
        symlink = self.version / "proof-link.md"
        symlink.symlink_to(self.proof)
        with self.assertRaisesRegex(ValueError, "Symlinked research paths"):
            self._run(symlink)

        control = self.root / ".project-handoff" / "private.txt"
        control.write_text("internal", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "control files"):
            self._run(control)

        outside = self.root.parent / f"{self.root.name}-outside.txt"
        outside.write_text("external", encoding="utf-8")
        self.addCleanup(outside.unlink, missing_ok=True)
        with self.assertRaisesRegex(ValueError, "inside the project root"):
            self._run(outside)

    def _run(self, path: Path):
        return self.service.create_campaign_run(
            "Accept explicit evidence only.",
            path.name,
            (path,),
        )


if __name__ == "__main__":
    unittest.main()
