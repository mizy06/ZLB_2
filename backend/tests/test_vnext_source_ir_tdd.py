from __future__ import annotations

import unittest

from pydantic import ValidationError

from backend.vnext.contracts.source import (
    ChemicalReactionIR,
    FormulaIR,
    ReactionCondition,
    ReactionParticipant,
    TableCellIR,
    TableIR,
)

from backend.tests.vnext_test_support import (
    courseware_evidence,
    source_id,
)


class VNextSourceObjectContractTests(unittest.TestCase):
    def test_table_cells_preserve_header_dependencies(self):
        header = TableCellIR(
            cell_id=source_id("cell", "1"),
            row_index=0,
            column_index=0,
            text="Reagent",
            is_header=True,
            evidence_refs=(courseware_evidence("1", kind="cell"),),
        )
        value = TableCellIR(
            cell_id=source_id("cell", "2"),
            row_index=1,
            column_index=0,
            text="NaBH4",
            header_cell_refs=(header.cell_id,),
            evidence_refs=(courseware_evidence("2", kind="cell"),),
        )

        table = TableIR(
            row_count=2,
            column_count=1,
            cells=(header, value),
        )

        self.assertEqual(
            table.cells[1].header_cell_refs,
            (header.cell_id,),
        )

    def test_table_rejects_overlapping_spans_and_unknown_headers(self):
        spanning = TableCellIR(
            cell_id=source_id("cell", "3"),
            row_index=0,
            column_index=0,
            row_span=2,
            text="Header",
            evidence_refs=(courseware_evidence("3", kind="cell"),),
        )
        overlap = TableCellIR(
            cell_id=source_id("cell", "4"),
            row_index=1,
            column_index=0,
            text="Overlap",
            evidence_refs=(courseware_evidence("4", kind="cell"),),
        )
        with self.assertRaisesRegex(ValidationError, "overlap"):
            TableIR(
                row_count=2,
                column_count=1,
                cells=(spanning, overlap),
            )

        unknown_header = overlap.model_copy(
            update={
                "row_index": 0,
                "header_cell_refs": (source_id("cell", "f"),),
            }
        )
        with self.assertRaisesRegex(ValidationError, "unknown headers"):
            TableIR(
                row_count=1,
                column_count=1,
                cells=(unknown_header,),
            )

    def test_parsed_reaction_requires_field_level_provenance(self):
        reactant = ReactionParticipant(
            label="aldehyde",
            evidence_refs=(courseware_evidence("5"),),
        )
        product = ReactionParticipant(
            label="alcohol",
            evidence_refs=(courseware_evidence("6"),),
        )

        with self.assertRaisesRegex(ValidationError, "arrow"):
            ChemicalReactionIR(
                reactants=(reactant,),
                products=(product,),
                conditions=(
                    ReactionCondition(
                        text="NaBH4",
                        evidence_refs=(courseware_evidence("7"),),
                    ),
                ),
                parse_status="parsed",
            )

        reaction = ChemicalReactionIR(
            reactants=(reactant,),
            products=(product,),
            conditions=(
                ReactionCondition(
                    text="NaBH4",
                    evidence_refs=(courseware_evidence("7"),),
                ),
            ),
            arrow_evidence_refs=(courseware_evidence("8"),),
            direction="forward",
            direction_evidence_refs=(courseware_evidence("8"),),
            parse_status="parsed",
        )

        self.assertEqual(reaction.direction, "forward")

    def test_formula_contract_requires_original_render_reference(self):
        with self.assertRaises(ValidationError):
            FormulaIR(
                display_text="RCHO + H2 -> RCH2OH",
                parse_status="parsed",
            )


if __name__ == "__main__":
    unittest.main()
