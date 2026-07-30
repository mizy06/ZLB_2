from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from backend.vnext.oracles import (
    evaluate_aldehydes_ketones,
    run_adversarial_oracle,
)


FIXTURE_ROOT = Path(__file__).with_name("fixtures") / "vnext"


class VNextOracleTests(unittest.TestCase):
    def test_aldehydes_ketones_contract_candidate_passes(self):
        oracle = json.loads(
            (FIXTURE_ROOT / "aldehydes_ketones_oracle.json").read_text(
                encoding="utf-8"
            )
        )
        candidate = json.loads(
            (
                FIXTURE_ROOT
                / "aldehydes_ketones_contract_candidate.json"
            ).read_text(encoding="utf-8")
        )

        self.assertEqual(
            evaluate_aldehydes_ketones(candidate, oracle),
            (),
        )

    def test_incident_oracle_detects_historical_failure_modes(self):
        oracle = json.loads(
            (FIXTURE_ROOT / "aldehydes_ketones_oracle.json").read_text(
                encoding="utf-8"
            )
        )
        candidate = json.loads(
            (
                FIXTURE_ROOT
                / "aldehydes_ketones_contract_candidate.json"
            ).read_text(encoding="utf-8")
        )
        broken = copy.deepcopy(candidate)
        broken["outline_labels"] = []
        broken["top_level_labels"].append("well-established")
        broken["claims"][0]["claim_type"] = "property"
        broken["claims"][0]["publication_status"] = "core"
        broken["vetoed_parent_reintroduced"] = True
        broken["parentless_claim_disposition"] = "root"
        broken["reaction_regions"][0]["preserved_fields"].remove("arrow")

        codes = {
            finding.code
            for finding in evaluate_aldehydes_ketones(broken, oracle)
        }

        self.assertTrue(
            {
                "missing_outline",
                "fragmentary_top_level_label",
                "instruction_promoted_to_fact",
                "veto_reintroduced",
                "parentless_claim_forced",
                "reaction_provenance_incomplete",
            }
            <= codes
        )

    def test_all_p0_adversarial_contract_cases_have_expected_outcome(self):
        mismatches = run_adversarial_oracle(
            FIXTURE_ROOT / "p0_adversarial_contract_cases.json"
        )

        self.assertEqual(mismatches, ())


if __name__ == "__main__":
    unittest.main()
