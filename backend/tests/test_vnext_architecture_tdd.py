from __future__ import annotations

import ast
import unittest
from pathlib import Path

from backend.vnext.contracts.common import ArtifactType, RuntimeRole
from backend.vnext.orchestration.permissions import WRITE_PERMISSIONS


PROJECT_ROOT = Path(__file__).resolve().parents[2]
VNEXT_ROOT = PROJECT_ROOT / "backend" / "vnext"
LEGACY_ROOT = PROJECT_ROOT / "backend" / "app"

FORBIDDEN_LEGACY_PREFIXES = (
    "backend.app.agents",
    "backend.app.cplus_pipeline",
    "backend.app.architecture_schemas",
    "backend.app.mindmap_engine.normalize",
    "backend.app.mindmap_engine.topology",
    "backend.app.review_service",
    "backend.app.visual_analysis",
    "backend.app.pdf_page_knowledge",
    "backend.app.blackboard",
    "backend.app.schemas",
    "backend.app.mindmap_engine.schemas",
)


def _imports(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return tuple(imports)


class VNextArchitectureBoundaryTests(unittest.TestCase):
    def test_clean_room_never_imports_legacy_semantic_modules(self):
        violations: list[str] = []
        for path in VNEXT_ROOT.rglob("*.py"):
            relative = path.relative_to(PROJECT_ROOT)
            for imported in _imports(path):
                allowed_legacy_adapter = (
                    "adapters" in relative.parts
                    and path.name == "legacy_result.py"
                    and imported == "backend.app.architecture_schemas"
                )
                if allowed_legacy_adapter:
                    continue
                if imported.startswith(FORBIDDEN_LEGACY_PREFIXES):
                    violations.append(f"{relative}: {imported}")
                if (
                    imported.startswith("backend.app")
                    and "adapters" not in relative.parts
                ):
                    violations.append(f"{relative}: {imported}")
                if (
                    imported.startswith("backend.app")
                    and "adapters" in relative.parts
                ):
                    violations.append(f"{relative}: {imported}")

        self.assertEqual(violations, [])

    def test_legacy_runtime_does_not_import_vnext_during_s0(self):
        violations = [
            f"{path.relative_to(PROJECT_ROOT)}: {imported}"
            for path in LEGACY_ROOT.rglob("*.py")
            for imported in _imports(path)
            if imported.startswith("backend.vnext")
        ]

        self.assertEqual(violations, [])

    def test_region_plan_has_only_top_down_writers(self):
        writers = {
            role
            for role, artifact_types in WRITE_PERMISSIONS.items()
            if ArtifactType.REGION_PLAN in artifact_types
        }

        self.assertEqual(
            writers,
            {
                RuntimeRole.GLOBAL_STRUCTURE_PLANNER,
                RuntimeRole.RECURSIVE_REGION_PLANNER,
            },
        )

    def test_bottom_up_role_can_only_write_replan_request(self):
        self.assertEqual(
            WRITE_PERMISSIONS[RuntimeRole.BOTTOM_UP_REGION_AUDITOR],
            frozenset({ArtifactType.REPLAN_REQUEST}),
        )

    def test_clean_room_package_boundary_exists(self):
        expected = {
            "adapters",
            "artifacts",
            "canonical_graph",
            "claims",
            "contracts",
            "orchestration",
            "projection",
            "regions",
            "source_inventory",
            "source_ir",
        }
        observed = {
            path.name
            for path in VNEXT_ROOT.iterdir()
            if path.is_dir() and not path.name.startswith("__")
        }

        self.assertTrue(expected <= observed)


if __name__ == "__main__":
    unittest.main()
