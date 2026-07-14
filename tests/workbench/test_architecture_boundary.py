from __future__ import annotations

import ast
import unittest
from pathlib import Path


class WorkbenchArchitectureBoundaryTests(unittest.TestCase):
    def test_workbench_has_no_pipeline_mutation_or_cogito_imports(self) -> None:
        package = Path(__file__).parents[2] / "phase_tracker" / "workbench"
        forbidden_modules = {
            "archive",
            "archive_policy",
            "state_store",
            "workflow",
            "workflow_alignment",
        }
        forbidden_calls = {
            "advance",
            "align_position",
            "ArchiveService",
            "record_alignment",
        }
        violations: list[str] = []

        for source_path in sorted(package.glob("*.py")):
            tree = ast.parse(source_path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    module = (node.module or "").split(".")[-1]
                    if module in forbidden_modules or "cogito" in module.lower():
                        violations.append(f"{source_path.name}: import {node.module}")
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        module = alias.name.split(".")[-1]
                        if module in forbidden_modules or "cogito" in alias.name.lower():
                            violations.append(f"{source_path.name}: import {alias.name}")
                elif isinstance(node, ast.Call):
                    name = self._call_name(node.func)
                    if name in forbidden_calls:
                        violations.append(f"{source_path.name}: call {name}")

        self.assertEqual(violations, [])

    @staticmethod
    def _call_name(node: ast.expr) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return ""


if __name__ == "__main__":
    unittest.main()
