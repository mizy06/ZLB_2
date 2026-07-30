from __future__ import annotations

import json
import unittest
from pathlib import Path

from backend.app.architecture_schemas import (
    HistoryItem,
    JobView,
    MindMapResult,
    ReviewResolutionRequest,
    ReviewResolutionResponse,
)
from backend.app.main import app
from backend.app.mindmap_engine.schemas import (
    EngineQualityReport,
    NormalizedGraph,
    RenderResponse,
    SolveResponse,
)
from backend.vnext.artifacts.canonical import payload_digest


SNAPSHOT_PATH = (
    Path(__file__).with_name("fixtures")
    / "vnext"
    / "legacy_public_contract_snapshot.json"
)
PUBLIC_MODELS = (
    HistoryItem,
    JobView,
    MindMapResult,
    ReviewResolutionRequest,
    ReviewResolutionResponse,
    EngineQualityReport,
    NormalizedGraph,
    RenderResponse,
    SolveResponse,
)


class VNextLegacyContractSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = json.loads(
            SNAPSHOT_PATH.read_text(encoding="ascii")
        )

    def test_legacy_openapi_contract_is_unchanged(self):
        openapi = app.openapi()

        self.assertEqual(
            payload_digest(openapi),
            self.snapshot["openapi_digest"],
        )
        self.assertEqual(
            len(openapi["paths"]),
            self.snapshot["openapi_path_count"],
        )
        self.assertEqual(
            len(openapi["components"]["schemas"]),
            self.snapshot["openapi_schema_count"],
        )
        self.assertFalse(
            any(
                name.startswith(
                    (
                        "SourceObservationIR",
                        "SourceInventory",
                        "RegionPlan",
                        "ClaimLedger",
                        "CanonicalExplicitGraph",
                        "DiagnosticProjection",
                    )
                )
                for name in openapi["components"]["schemas"]
            )
        )

    def test_legacy_public_model_schemas_are_unchanged(self):
        model_schemas = {
            model.__name__: model.model_json_schema()
            for model in PUBLIC_MODELS
        }

        self.assertEqual(
            tuple(model_schemas),
            tuple(self.snapshot["model_names"]),
        )
        self.assertEqual(
            payload_digest(model_schemas),
            self.snapshot["model_schema_digest"],
        )


if __name__ == "__main__":
    unittest.main()
